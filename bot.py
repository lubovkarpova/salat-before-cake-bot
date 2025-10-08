import logging
import os
import re
import asyncio
from datetime import datetime, date
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from openai import OpenAI
from database import Database

load_dotenv()

# Режим работы: 'test' или 'production'
BOT_MODE = os.getenv('BOT_MODE', 'production')

if BOT_MODE == 'test':
    API_TOKEN = os.getenv('TEST_TELEGRAM_BOT_TOKEN')
    OPENAI_API_KEY = os.getenv('TEST_OPENAI_API_KEY')
    DB_PATH = "test_nutrition_bot.db"
    print("🧪 ТЕСТОВЫЙ РЕЖИМ АКТИВЕН")
else:
    API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    DB_PATH = "nutrition_bot.db"
    print("🚀 ПРОДАКШН РЕЖИМ АКТИВЕН")

if not API_TOKEN or not OPENAI_API_KEY:
    print("Ошибка: не найдены токены в переменных окружения")
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Инициализируем базу данных с правильным путем
db = Database(DB_PATH)

class ProfileStates(StatesGroup):
    waiting_for_gender = State()
    waiting_for_age = State()
    waiting_for_height = State()
    waiting_for_weight = State()
    waiting_for_activity = State()
    waiting_for_goal = State()
    waiting_for_target_confirmation = State()
    waiting_for_goal_correction = State()

class FoodStates(StatesGroup):
    waiting_for_food_description = State()
    waiting_for_clarification = State()
    waiting_for_review = State()  # Ожидание подтверждения после ревью
    waiting_for_correction = State()  # Ожидание уточнения после проблем с валидацией

def analyze_food_with_gpt5(food_description: str) -> dict:
    """Анализирует еду с помощью GPT-5 с использованием custom tool и JSON grammar"""
    print(f"DEBUG: Анализируем еду через GPT-5: '{food_description}'")
    
    try:
        # Определяем custom tool с JSON grammar для КБЖУ
        kbju_tool = {
            "type": "custom",
            "name": "analyze_nutrition",
            "description": "Анализирует пищевую ценность продукта и возвращает КБЖУ в JSON",
            "grammar": """
                ?start: nutrition_data
                
                nutrition_data: "{" 
                    "\\"calories\\":" INT "," 
                    "\\"proteins\\":" INT "," 
                    "\\"fats\\":" INT "," 
                    "\\"carbs\\":" INT "," 
                    "\\"portion_clear\\":" BOOL 
                "}"
                
                BOOL: "true" | "false"
                INT: /[0-9]+/
                
                %import common.WS
                %ignore WS
            """
        }
        
        # Формируем запрос
        input_text = f"""Проанализируй пищевую ценность и рассчитай КБЖУ для:

{food_description}

Рассчитай:
- calories: общие калории в ккал (суммируй все продукты если их несколько)
- proteins: общие белки в граммах
- fats: общие жиры в граммах
- carbs: общие углеводы в граммах
- portion_clear: true/false

КРИТЕРИИ portion_clear:
- true если: указаны граммы/мл/штуки (например "200г", "1 блин", "25гр сыра")
- true если: детальное описание с количествами
- true если: стандартная порция явно определена (например "1 яблоко среднее")
- false ТОЛЬКО если: совсем нет информации о количестве (например просто "курица")

ВАЖНО: Если в описании несколько продуктов - суммируй все вместе!"""

        response = client.responses.create(
            model="gpt-5",
            input=input_text,
            reasoning={"effort": "minimal"},
            text={"verbosity": "low"},
            tools=[kbju_tool]
        )
        
        # Получаем результат из tool call
        import json
        
        if hasattr(response, 'tool_calls') and response.tool_calls:
            # Берем результат из tool call
            tool_result = response.tool_calls[0].get('arguments', '{}')
            kbju_data = json.loads(tool_result)
        else:
            # Fallback - парсим из текста
            response_text = response.output_text if hasattr(response, 'output_text') else str(response)
            print(f"DEBUG: Ответ GPT-5: {response_text}")
            
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            kbju_data = json.loads(response_text)
        
        print(f"DEBUG: Извлеченные значения - калории: {kbju_data.get('calories', 0)}, белки: {kbju_data.get('proteins', 0)}, жиры: {kbju_data.get('fats', 0)}, углеводы: {kbju_data.get('carbs', 0)}")
        
        return {
            'calories': int(kbju_data.get('calories', 0)),
            'proteins': int(kbju_data.get('proteins', 0)),
            'fats': int(kbju_data.get('fats', 0)),
            'carbs': int(kbju_data.get('carbs', 0)),
            'portion_clear': kbju_data.get('portion_clear', True)
        }
        
    except Exception as e:
        print(f"DEBUG: Ошибка при анализе через GPT-5: {e}")
        # Fallback - возвращаем нули
        return {
            'calories': 0,
            'proteins': 0,
            'fats': 0,
            'carbs': 0,
            'portion_clear': False
        }

def validate_kbju_with_gpt5(food_description: str, kbju_data: dict) -> dict:
    """Валидирует КБЖУ через GPT-5 для проверки адекватности оценки"""
    print(f"DEBUG: Валидируем КБЖУ через GPT-5: {food_description} = {kbju_data}")
    
    try:
        # Custom tool для валидации
        validation_tool = {
            "type": "custom",
            "name": "validate_nutrition",
            "description": "Проверяет адекватность оценки КБЖУ для продукта",
            "grammar": """
                ?start: validation_result
                
                validation_result: "{" 
                    "\\"is_valid\\":" BOOL "," 
                    "\\"confidence\\":" INT "," 
                    "\\"issues\\":" array "," 
                    "\\"suggestion\\":" STRING 
                "}"
                
                array: "[" (STRING ("," STRING)*)? "]"
                BOOL: "true" | "false"
                INT: /[0-9]+/
                STRING: /\\"[^\\"]*\\"/
                
                %import common.WS
                %ignore WS
            """
        }
        
        input_text = f"""Ты эксперт-нутрициолог. Проверь адекватность оценки КБЖУ.

ПРОДУКТ: {food_description}

ОЦЕНКА КБЖУ:
- Калории: {kbju_data['calories']} ккал
- Белки: {kbju_data['proteins']} г
- Жиры: {kbju_data['fats']} г
- Углеводы: {kbju_data['carbs']} г

ЗАДАЧА:
Оцени, насколько адекватны эти значения для данного продукта.

Проверь:
1. Калории соответствуют БЖУ (белки и углеводы = 4 ккал/г, жиры = 9 ккал/г)?
2. Значения реалистичны для этого продукта и указанной порции?
3. Нет явно завышенных/заниженных значений?
4. Пропорции БЖУ типичны для этого продукта?
5. Достаточно ли информации в описании для точной оценки?

КРИТЕРИИ:
- Если в описании указаны граммы/мл/штуки конкретно → это ДОСТАТОЧНО информации
- Если описание детальное (например "1 блин с 25гр сыра") → это ХОРОШО
- Проблемы только если значения явно неадекватны

Верни:
- is_valid: true если данные адекватны (даже если не идеально точно)
- confidence: уверенность в оценке 0-100% (80%+ = хорошо)
- issues: список РЕАЛЬНЫХ проблем (пустой если всё ок)
- suggestion: только если есть явная ошибка, иначе пустая строка"""

        response = client.responses.create(
            model="gpt-5",
            input=input_text,
            reasoning={"effort": "medium"},  # Средний effort для проверки
            text={"verbosity": "low"},
            tools=[validation_tool]
        )
        
        # Получаем результат
        import json
        
        if hasattr(response, 'tool_calls') and response.tool_calls:
            validation_result = json.loads(response.tool_calls[0].get('arguments', '{}'))
        else:
            response_text = response.output_text if hasattr(response, 'output_text') else str(response)
            
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            validation_result = json.loads(response_text)
        
        print(f"DEBUG: Валидация - valid={validation_result.get('is_valid')}, confidence={validation_result.get('confidence')}%, issues={validation_result.get('issues')}")
        
        return {
            'is_valid': validation_result.get('is_valid', True),
            'confidence': validation_result.get('confidence', 100),
            'issues': validation_result.get('issues', []),
            'suggestion': validation_result.get('suggestion', '')
        }
        
    except Exception as e:
        print(f"DEBUG: Ошибка валидации через GPT-5: {e}")
        # При ошибке валидации считаем данные валидными
        return {
            'is_valid': True,
            'confidence': 100,
            'issues': [],
            'suggestion': ''
        }

def save_food_to_daily(user_id: int, food_description: str, kbju_data: dict):
    """Сохраняет еду в дневной учет"""
    print(f"DEBUG: Сохраняем приём пищи: user_id={user_id}, description='{food_description}', kbju={kbju_data}")
    
    success = db.save_meal(user_id, food_description, kbju_data)
    if success:
        print("DEBUG: Приём пищи сохранён в таблицу meals")
    else:
        print("DEBUG: Ошибка сохранения приёма пищи")
    
    return success

def get_daily_summary(user_id: int) -> dict:
    """Получает дневную сводку"""
    today = date.today().strftime('%Y-%m-%d')
    print(f"DEBUG: Получаем дневные итоги: user_id={user_id}, date={today}")
    
    summary = db.get_daily_summary(user_id, today)
    print(f"DEBUG: Результат запроса: {summary}")
    
    if summary:
        print(f"DEBUG: Возвращаем итоги из daily_summaries: {summary}")
        return summary
    else:
        print("DEBUG: Данных нет, возвращаем нули")
        return {'calories': 0, 'proteins': 0, 'fats': 0, 'carbs': 0, 'meals': 0}

@router.message(Command("start", "help"))
async def send_welcome(message: Message):
    mode_prefix = "🧪 ТЕСТ: " if BOT_MODE == 'test' else ""
    await message.answer(
        f"{mode_prefix}Привет! Я бот, который не учит, а просто считает КБЖУ.\n\n"
        "📍 Напиши, что ты ел(а) — я разберу по БЖУ\n"
        "⚙️ Хочешь точности — настрой профиль: /profile\n"
        "📊 Посмотреть цели: /target\n"
        "📅 Отчёт за день: /day\n\n"
        "Всё просто. Без диет и занудства."
    )

@router.message(Command("test"))
async def test_command(message: Message):
    if BOT_MODE == 'test':
        await message.answer(
            "🧪 ТЕСТОВЫЕ КОМАНДЫ:\n\n"
            "/test_profile - быстрая настройка профиля\n"
            "/clear_data - очистить все данные\n"
            "/status - статус бота\n\n"
            "💡 Просто пиши название еды - запустится автоматический флоу:\n"
            "   1️⃣ GPT-5 анализ КБЖУ\n"
            "   2️⃣ GPT-5 валидация\n"
            "   3️⃣ Ревью и подтверждение"
        )
    else:
        await message.answer("Эта команда доступна только в тестовом режиме")

@router.message(Command("test_profile"))
async def test_profile_setup(message: Message):
    if BOT_MODE != 'test':
        return
    
    # Быстрая настройка тестового профиля
    test_data = {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'похудеть и белок'
    }
    
    success = db.save_user_profile(message.from_user.id, test_data)
    if success:
        await message.answer(
            "🧪 Тестовый профиль создан:\n"
            "👤 Женский, 25 лет\n"
            "📏 165 см, 60 кг\n"
            "🏃‍♀️ Средняя активность\n"
            "🎯 Цель: похудеть и белок\n\n"
            "Теперь просто пиши еду - запустится автоматический флоу!"
        )
    else:
        await message.answer("❌ Ошибка создания тестового профиля")

@router.message(Command("clear_data"))
async def clear_test_data(message: Message):
    if BOT_MODE != 'test':
        return
    
    # Очистка тестовых данных
    try:
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id = ?", (message.from_user.id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (message.from_user.id,))
            cursor.execute("DELETE FROM daily_summaries WHERE user_id = ?", (message.from_user.id,))
            conn.commit()
        
        await message.answer("🧪 Все тестовые данные очищены")
    except Exception as e:
        await message.answer(f"❌ Ошибка очистки данных: {e}")

@router.message(Command("status"))
async def bot_status(message: Message):
    if BOT_MODE != 'test':
        return
    
    status = f"🧪 СТАТУС БОТА:\n\n"
    status += f"Режим: {'ТЕСТОВЫЙ' if BOT_MODE == 'test' else 'ПРОДАКШН'}\n"
    status += f"База данных: {DB_PATH}\n"
    status += f"OpenAI API: {'✅' if OPENAI_API_KEY else '❌'}\n"
    status += f"Telegram Bot: {'✅' if API_TOKEN else '❌'}\n"
    
    await message.answer(status)

# ============= HELPER FUNCTIONS =============

def calculate_targets_with_gpt5(profile_data: dict, bmr: int, tdee: int, goal: str) -> dict:
    """Расчёт таргетов с помощью GPT-5 для более гибкой интерпретации цели"""
    print(f"DEBUG: Используем GPT-5 для расчёта таргетов")
    
    try:
        # Определяем custom tool с JSON grammar для таргетов
        targets_tool = {
            "type": "custom",
            "name": "calculate_nutrition_targets",
            "description": "Рассчитывает персонализированные целевые показатели КБЖУ",
            "grammar": """
                ?start: targets_data
                
                targets_data: "{" 
                    "\\"calories\\":" INT "," 
                    "\\"proteins\\":" INT "," 
                    "\\"fats\\":" INT "," 
                    "\\"carbs\\":" INT "," 
                    "\\"explanation\\":" STRING 
                "}"
                
                INT: /[0-9]+/
                STRING: /\\"[^\\"]*\\"/
                
                %import common.WS
                %ignore WS
            """
        }
        
        input_text = f"""Ты эксперт по питанию и фитнесу. Рассчитай персонализированные целевые показатели КБЖУ.

ДАННЫЕ ПОЛЬЗОВАТЕЛЯ:
- Пол: {profile_data.get('gender')}
- Возраст: {profile_data.get('age')} лет
- Рост: {profile_data.get('height')} см
- Вес: {profile_data.get('weight')} кг
- Уровень активности: {profile_data.get('activity')}
- Базовый обмен веществ (BMR): {bmr} ккал
- Общий расход энергии (TDEE): {tdee} ккал

ЦЕЛЬ: "{goal}"

ЗАДАЧА:
Проанализируй цель и рассчитай:
- calories: целевые калории (учитывай нюансы: "чуть-чуть похудеть" = -10%, "быстро" = -20%, "набрать" = +10-15%)
- proteins: белки в граммах (похудение/набор = 1.6-2.0 г/кг, поддержание = 1.2 г/кг)
- fats: жиры в граммах (минимум 0.8 г/кг веса, но не меньше 25% калорий)
- carbs: углеводы в граммах (остаток калорий)
- explanation: краткое пояснение (2-3 предложения)

ОГРАНИЧЕНИЯ:
- Калории: не меньше {bmr-200} и не больше {tdee+500}
- Белки: минимум {int(profile_data.get('weight', 60) * 1.2)} г
- Учитывай ключевые слова: "белок", "похудеть", "набрать", "здоровье", "чуть-чуть", "быстро"
"""

        response = client.responses.create(
            model="gpt-5",
            input=input_text,
            reasoning={"effort": "high"},  # Высокий effort для сложных расчетов
            text={"verbosity": "medium"},
            tools=[targets_tool]
        )
        
        # Получаем результат
        import json
        
        if hasattr(response, 'tool_calls') and response.tool_calls:
            tool_result = response.tool_calls[0].get('arguments', '{}')
            target_data = json.loads(tool_result)
        else:
            response_text = response.output_text if hasattr(response, 'output_text') else str(response)
            print(f"DEBUG: GPT-5 ответ: {response_text}")
            
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            target_data = json.loads(response_text)
        
        # Добавляем BMR и TDEE
        target_data['bmr'] = bmr
        target_data['tdee'] = tdee
        
        print(f"DEBUG: GPT-5 таргеты: калории={target_data['calories']}, белки={target_data['proteins']}, жиры={target_data['fats']}, углеводы={target_data['carbs']}")
        
        return target_data
        
    except Exception as e:
        print(f"DEBUG: Ошибка GPT-5 расчёта таргетов: {e}")
        # Fallback на формульный расчёт
        print("DEBUG: Используем формульный расчёт как fallback")
        return None

# ============= PROD HANDLERS (SYNCHRONIZED) =============

@router.message(Command("profile"))
async def profile_start(message: Message, state: FSMContext):
    mode_prefix = "🧪 " if BOT_MODE == 'test' else ""
    if db.user_profile_exists(message.from_user.id):
        await message.answer(f"{mode_prefix}У тебя уже есть профиль! Используй /target чтобы посмотреть целевые калории.")
        return
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        f"{mode_prefix}Начнём с профиля — так расчёт КБЖУ будет точнее.\n\n"
        "Сначала — пол. Он влияет на обмен веществ.",
        reply_markup=keyboard
    )
    await state.set_state(ProfileStates.waiting_for_gender)

@router.message(ProfileStates.waiting_for_gender)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.strip()
    if gender not in ["Мужской", "Женский"]:
        await message.answer("Пожалуйста, выбери 'Мужской' или 'Женский'")
        return
    
    await state.update_data(gender=gender)
    
    # Убираем кнопки
    await message.answer("Сколько тебе лет?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ProfileStates.waiting_for_age)

@router.message(ProfileStates.waiting_for_age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 10 or age > 100:
            await message.answer("Пожалуйста, введите реальный возраст (10-100 лет)")
            return
    except ValueError:
        await message.answer("Пожалуйста, введите число")
        return
    
    await state.update_data(age=age)
    
    await message.answer("Рост в см? Например: 170")
    await state.set_state(ProfileStates.waiting_for_height)

@router.message(ProfileStates.waiting_for_height)
async def process_height(message: Message, state: FSMContext):
    try:
        height = int(message.text.strip())
        if height < 100 or height > 250:
            await message.answer("Пожалуйста, введите реальный рост (100-250 см)")
            return
    except ValueError:
        await message.answer("Пожалуйста, введите число")
        return
    
    await state.update_data(height=height)
    
    await message.answer("Вес в кг? Например: 65")
    await state.set_state(ProfileStates.waiting_for_weight)

@router.message(ProfileStates.waiting_for_weight)
async def process_weight(message: Message, state: FSMContext):
    try:
        weight = int(message.text.strip())
        if weight < 30 or weight > 300:
            await message.answer("Пожалуйста, введите реальный вес (30-300 кг)")
            return
    except ValueError:
        await message.answer("Пожалуйста, введите число")
        return
    
    await state.update_data(weight=weight)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Низкий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "Выбери уровень активности:\n\n"
        "🏃‍♀️ Низкий — почти нет спорта\n"
        "🏃‍♀️ Средний — спорт 2–3 раза в неделю\n"
        "🏃‍♀️ Высокий — 4+ раз в неделю или физическая работа",
        reply_markup=keyboard
    )
    await state.set_state(ProfileStates.waiting_for_activity)

@router.message(ProfileStates.waiting_for_activity)
async def process_activity(message: Message, state: FSMContext):
    activity = message.text.strip()
    if activity not in ["Низкий", "Средний", "Высокий"]:
        await message.answer("Пожалуйста, выбери один из вариантов: Низкий, Средний, Высокий")
        return
    
    await state.update_data(activity=activity)
    
    # Убираем кнопки и добавляем примеры целей
    await message.answer(
        "Какая у тебя цель? Вот примеры:\n\n"
        "🎯 Похудеть\n"
        "💪 Набрать массу\n"
        "⚖️ Поддерживать вес\n"
        "💪 Следить за белком\n"
        "🩸 Для здоровья\n"
        "🥗 Больше разнообразия\n\n"
        "Или просто напиши, чего хочешь 🙂",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ProfileStates.waiting_for_goal)

@router.message(ProfileStates.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    goal = message.text.strip()
    if len(goal) < 3:
        await message.answer("Напиши цель чуть подробнее 🙂")
        return
    
    # Проверяем, не ввел ли пользователь число (калории)
    if goal.isdigit():
        calories = int(goal)
        if 800 <= calories <= 5000:  # разумный диапазон калорий
            # Пользователь ввел целевые калории
            await message.answer(
                f"Понял! Устанавливаю {calories} ккал как цель.\n\n"
                "Теперь напиши цель словами (например: похудеть, набрать массу, поддерживать вес):",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.update_data(target_calories=calories)
            return
        else:
            await message.answer("Это слишком много или мало калорий. Напиши цель словами 🙂")
            return
    
    # Ищем числа в тексте (например: "например 1700", "калории 1800", "хочу 1500")
    numbers = re.findall(r'\d+', goal)
    if numbers:
        calories = int(numbers[0])
        if 800 <= calories <= 5000:  # разумный диапазон калорий
            # Пользователь ввел калории в тексте
            await message.answer(
                f"Понял! Устанавливаю {calories} ккал как цель.\n\n"
                "Теперь напиши цель словами (например: похудеть, набрать массу, поддерживать вес):",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.update_data(target_calories=calories)
            return
    
    await state.update_data(goal=goal)
    
    # Получаем все данные профиля
    data = await state.get_data()
    
    # Рассчитываем целевые калории
    user_id = message.from_user.id
    
    # Временно сохраняем профиль для расчёта таргета
    temp_success = db.save_user_profile(user_id, data)
    if not temp_success:
        await message.answer("Ошибка сохранения профиля. Попробуй ещё раз.")
        await state.clear()
        return
    
    # Используем GPT-5 для расчёта таргетов (если калории не указаны вручную)
    if 'target_calories' not in data:
        mode_indicator = "🧪 " if BOT_MODE == 'test' else ""
        await message.answer(f"{mode_indicator}Анализирую твою цель с помощью AI... ⏳")
        
        # Получаем BMR и TDEE для передачи в GPT-5
        bmr = db.calculate_bmr(user_id)
        profile = db.get_user_profile(user_id)
        activity = profile.get('activity', 'Средний').lower()
        activity_multipliers = {'низкий': 1.2, 'средний': 1.55, 'высокий': 1.725}
        tdee = int(bmr * activity_multipliers.get(activity, 1.55))
        
        # Пробуем GPT-5 расчёт
        target = calculate_targets_with_gpt5(data, bmr, tdee, goal)
        
        # Если GPT-5 не сработал, используем формулы как fallback
        if target is None:
            target = db.calculate_target_calories(user_id)
    else:
        # Если калории указаны вручную - используем формулы
        target = db.calculate_target_calories(user_id)
    
    # Если пользователь указал конкретные калории, используем их
    if 'target_calories' in data:
        target['calories'] = data['target_calories']
        # Пересчитываем макросы под новые калории
        weight = data.get('weight', 70)
        
        # Определяем приоритеты макросов на основе цели
        goal_text = data.get('goal', '').lower()
        
        if 'белок' in goal_text or 'протеин' in goal_text:
            # Приоритет белку
            target['proteins'] = int(weight * 2.0)  # 2 г/кг
            target['fats'] = int(weight * 0.8)  # 0.8 г/кг
        elif 'похуд' in goal_text:
            # Приоритет белку при похудении
            target['proteins'] = int(weight * 1.6)  # 1.6 г/кг
            target['fats'] = int(weight * 0.8)  # 0.8 г/кг
        else:
            # Стандартные значения
            target['proteins'] = int(weight * 1.2)  # 1.2 г/кг
            target['fats'] = int(weight * 1.0)  # 1.0 г/кг
        
        # Рассчитываем углеводы как остаток
        protein_calories = target['proteins'] * 4
        fat_calories = target['fats'] * 9
        remaining_calories = target['calories'] - protein_calories - fat_calories
        target['carbs'] = max(0, int(remaining_calories / 4))  # 4 ккал на грамм углеводов
        
        target['explanation'] = f"Целевые калории установлены пользователем: {data['target_calories']} ккал"
    
    # Проверяем, это новая цель или корректировка
    is_correction = await state.get_state() == ProfileStates.waiting_for_goal and 'goal' in data
    
    mode_prefix = "🧪 " if BOT_MODE == 'test' else ""
    
    # Формируем сообщение с профилем и таргетом
    profile_text = f"{mode_prefix}📋 Твой профиль:\n\n"
    profile_text += f"👤 Пол: {data['gender']}\n"
    profile_text += f"📅 Возраст: {data['age']} лет\n"
    profile_text += f"📏 Рост: {data['height']} см\n"
    profile_text += f"⚖️ Вес: {data['weight']} кг\n"
    profile_text += f"🏃‍♀️ Активность: {data['activity']}\n"
    profile_text += f"🎯 Цель: {data['goal']}\n\n"
    
    target_text = f"🎯 Рассчитанные целевые показатели:\n\n"
    target_text += f"📊 Базовый обмен веществ (BMR): {target['bmr']} ккал\n"
    target_text += f"🔥 Общий расход энергии (TDEE): {target['tdee']} ккал\n"
    target_text += f"🎯 Целевые калории: {target['calories']} ккал\n\n"
    target_text += f"💪 Белки: {target['proteins']} г\n"
    target_text += f"🥑 Жиры: {target['fats']} г\n"
    target_text += f"🍞 Углеводы: {target['carbs']} г\n\n"
    target_text += f"ℹ️ {target.get('explanation', '')}\n\n"
    
    # Кнопки для подтверждения
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Принять таргет"), KeyboardButton(text="✏️ Изменить профиль")]
        ],
        resize_keyboard=True
    )
    
    if is_correction:
        # Если это корректировка цели, показываем специальное сообщение
        await message.answer(
            f"Цель обновлена: {goal}\n" + target_text + 
            "Всё ок? Можешь подтвердить или подправить.",
            reply_markup=keyboard
        )
    else:
        # Если это новая цель, показываем полный профиль
        await message.answer(
            profile_text + target_text + 
            "Всё верно? Можно подтвердить или изменить.",
            reply_markup=keyboard
        )
    
    # Сохраняем данные для возможного редактирования
    await state.update_data(target=target)
    await state.set_state(ProfileStates.waiting_for_target_confirmation)

@router.message(ProfileStates.waiting_for_target_confirmation)
async def process_target_confirmation(message: Message, state: FSMContext):
    choice = message.text.strip()
    
    if choice == "✅ Принять таргет":
        # Сохраняем профиль с таргетами
        data = await state.get_data()
        user_id = message.from_user.id
        
        # Сохраняем профиль с принятыми таргетами
        success = db.save_user_profile(user_id, data)
        if success:
            print(f"DEBUG: Профиль с таргетами сохранен для user_id={user_id}")
        
        await message.answer(
            "Готово! Всё на месте.\n\n"
            "Что дальше:\n"
            "• Присылай еду — посчитаю КБЖУ\n"
            "• /target — цели\n"
            "• /day — сводка дня",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()
        
    elif choice == "✏️ Изменить профиль":
        # Спрашиваем, что именно нужно изменить
        await message.answer(
            "Что поменяем? Напиши, что хочешь поправить 🙂",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(ProfileStates.waiting_for_goal_correction)
        
    else:
        await message.answer(
            "Выбери: ✅ Принять или ✏️ Изменить профиль"
        )

@router.message(ProfileStates.waiting_for_goal_correction)
async def process_goal_correction(message: Message, state: FSMContext):
    user_feedback = message.text.strip().lower()
    
    # Получаем текущие данные профиля
    data = await state.get_data()
    current_goal = data.get('goal', '')
    
    # Анализируем обратную связь пользователя
    new_goal = current_goal  # по умолчанию оставляем как есть
    
    if any(word in user_feedback for word in ['цель', 'задача', 'хочу', 'нужно']):
        # Пользователь хочет изменить цель
        await message.answer(
            "Понял! Напиши новую цель своими словами:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(ProfileStates.waiting_for_goal)
        return
    
    elif any(word in user_feedback for word in ['возраст', 'лет', 'года']):
        # Пользователь хочет изменить возраст
        await message.answer("Сколько тебе лет?")
        await state.set_state(ProfileStates.waiting_for_age)
        return
    
    elif any(word in user_feedback for word in ['рост', 'высота', 'см']):
        # Пользователь хочет изменить рост
        await message.answer("Рост в см? Например: 170")
        await state.set_state(ProfileStates.waiting_for_height)
        return
    
    elif any(word in user_feedback for word in ['вес', 'масса', 'кг']):
        # Пользователь хочет изменить вес
        await message.answer("Вес в кг? Например: 65")
        await state.set_state(ProfileStates.waiting_for_weight)
        return
    
    elif any(word in user_feedback for word in ['активность', 'спорт', 'движение']):
        # Пользователь хочет изменить активность
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Низкий"), KeyboardButton(text="Средний"), KeyboardButton(text="Высокий")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "Выбери уровень активности:\n\n"
            "🏃‍♀️ Низкий — почти нет спорта\n"
            "🏃‍♀️ Средний — спорт 2–3 раза в неделю\n"
            "🏃‍♀️ Высокий — 4+ раз в неделю или физическая работа",
            reply_markup=keyboard
        )
        await state.set_state(ProfileStates.waiting_for_activity)
        return
    
    elif any(word in user_feedback for word in ['пол', 'мужской', 'женский']):
        # Пользователь хочет изменить пол
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "Укажи биологический пол — он влияет на расчёт калорий.",
            reply_markup=keyboard
        )
        await state.set_state(ProfileStates.waiting_for_gender)
        return
    
    else:
        # Если не поняли, что хочет изменить, предлагаем изменить цель
        await message.answer(
            "Понял! Напиши новую цель своими словами:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(ProfileStates.waiting_for_goal)

@router.message(lambda message: not message.text.startswith('/'))
async def auto_food_analysis(message: Message, state: FSMContext):
    # Проверяем, не находимся ли мы в другом диалоге
    current_state = await state.get_state()
    if current_state:
        return
    
    user_food = message.text.strip()
    
    # Игнорируем очень короткие сообщения
    if len(user_food) < 2:
        return
    
    print(f"DEBUG: Анализируем еду: '{user_food}'")
    
    # Проверяем, есть ли профиль
    if not db.user_profile_exists(message.from_user.id):
        await message.answer("Сначала нужно настроить профиль! Используй команду /profile")
        return
    
    await message.answer("🍽 Анализирую твою еду... ⏳")
    
    try:
        # Шаг 1: Анализируем еду через GPT-5 с JSON grammar
        kbju_data = analyze_food_with_gpt5(user_food)
        
        # Если не удалось извлечь калории (полный провал анализа)
        if kbju_data['calories'] == 0:
            clarification_prompt = f"Не смог распознать продукт: {user_food}\n\nПожалуйста, опиши подробнее:\n• Что это за продукт?\n• Сколько граммов/миллилитров?\n• Как приготовлено?"
            await message.answer(clarification_prompt)
            await state.update_data(original_food=user_food)
            await state.set_state(FoodStates.waiting_for_clarification)
            return
        
        # Шаг 2: Валидируем КБЖУ через GPT-5
        # Валидация сама проверит, достаточно ли информации
        validation = validate_kbju_with_gpt5(user_food, kbju_data)
        
        # Формируем ответ на ревью
        response_text = f"📊 Результат анализа для: {user_food}\n\n"
        response_text += f"🔥 Калории: {kbju_data['calories']} ккал\n"
        response_text += f"🥩 Белки: {kbju_data['proteins']} г\n"
        response_text += f"🥑 Жиры: {kbju_data['fats']} г\n"
        response_text += f"🍞 Углеводы: {kbju_data['carbs']} г\n"
        
        # Добавляем информацию о валидации
        if validation['confidence'] < 100:
            response_text += f"\n🎯 Уверенность: {validation['confidence']}%\n"
        
        # Если есть проблемы с валидацией
        has_issues = not validation['is_valid'] or validation['issues']
        if has_issues:
            response_text += f"\n⚠️ Обнаружены проблемы:\n"
            for issue in validation['issues']:
                response_text += f"  • {issue}\n"
            if validation['suggestion']:
                response_text += f"\n💡 Рекомендация: {validation['suggestion']}\n"
        
        # Сохраняем данные в state для возможного сохранения
        await state.update_data(
            food_description=user_food,
            kbju_data=kbju_data,
            validation=validation
        )
        
        # Создаем кнопки для подтверждения
        if has_issues:
            # Если есть проблемы - даем выбор сохранить или уточнить
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="✏️ Уточнить")]
                ],
                resize_keyboard=True
            )
            response_text += "\n\nДанные выглядят подозрительно. Что делать?"
        else:
            # Если всё ок - просто подтверждение
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="✏️ Уточнить")]
                ],
                resize_keyboard=True
            )
            response_text += "\n\nВсё верно?"
        
        await message.answer(response_text, reply_markup=keyboard)
        await state.set_state(FoodStates.waiting_for_review)
        
    except Exception as e:
        print(f"DEBUG: Ошибка при анализе еды: {e}")
        await message.answer("Извини, произошла ошибка при анализе еды. Попробуй ещё раз.")

@router.message(FoodStates.waiting_for_review)
async def food_review(message: Message, state: FSMContext):
    """Обработка ревью КБЖУ - пользователь подтверждает или уточняет"""
    choice = message.text.strip()
    data = await state.get_data()
    
    if choice == "✅ Сохранить":
        # Пользователь подтвердил - сохраняем в БД
        food_description = data.get('food_description', '')
        kbju_data = data.get('kbju_data', {})
        
        # Сохраняем
        save_food_to_daily(message.from_user.id, food_description, kbju_data)
        
        # Получаем дневную сводку
        daily_summary = get_daily_summary(message.from_user.id)
        
        # Формируем ответ
        response_text = f"✅ Сохранено!\n\n"
        response_text += f"📊 Итого за день ({daily_summary['meals']} приёмов пищи):\n"
        response_text += f"🔥 Калории: {daily_summary['calories']} ккал\n"
        response_text += f"🥩 Белки: {daily_summary['proteins']} г\n"
        response_text += f"🥑 Жиры: {daily_summary['fats']} г\n"
        response_text += f"🍞 Углеводы: {daily_summary['carbs']} г"
        
        # Добавляем прогресс к цели
        target = db.get_saved_targets(message.from_user.id)
        if target is None:
            target = db.calculate_target_calories(message.from_user.id)
        
        if target and target['calories'] > 0:
            progress = (daily_summary['calories'] / target['calories']) * 100
            response_text += f"\n\n🎯 Прогресс к цели: {progress:.1f}%"
        
        await message.answer(response_text, reply_markup=ReplyKeyboardRemove())
        await state.clear()
        
    elif choice == "✏️ Уточнить" or choice == "✏️ Уточнить еще раз":
        # Пользователь хочет уточнить
        await message.answer(
            "Хорошо! Уточни описание продукта.\n\n"
            "Например:\n"
            "• Укажи граммы: '200 грамм'\n"
            "• Уточни размер: 'большое яблоко'\n"
            "• Добавь деталей: 'жареная на масле'\n"
            "• Или опиши заново полностью",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(FoodStates.waiting_for_correction)
        
    else:
        # Неправильный выбор
        await message.answer("Пожалуйста, выбери: ✅ Сохранить или ✏️ Уточнить")

@router.message(FoodStates.waiting_for_correction)
async def food_correction(message: Message, state: FSMContext):
    """Обработка уточнения - пользователь дает новое/уточненное описание"""
    data = await state.get_data()
    original_food = data.get('food_description', '')
    correction = message.text.strip()
    
    # Объединяем или заменяем в зависимости от ввода
    if len(correction.split()) <= 3:  # Короткое уточнение (например "200 грамм")
        corrected_food = f"{original_food} {correction}"
    else:  # Полное новое описание
        corrected_food = correction
    
    await message.answer("🔄 Пересчитываю с уточнением... ⏳")
    
    try:
        # Шаг 1: Анализируем уточненное описание
        kbju_data = analyze_food_with_gpt5(corrected_food)
        
        # Шаг 2: Валидируем
        validation = validate_kbju_with_gpt5(corrected_food, kbju_data)
        
        # Формируем ответ на ревью
        response_text = f"📊 Пересчет для: {corrected_food}\n\n"
        response_text += f"🔥 Калории: {kbju_data['calories']} ккал\n"
        response_text += f"🥩 Белки: {kbju_data['proteins']} г\n"
        response_text += f"🥑 Жиры: {kbju_data['fats']} г\n"
        response_text += f"🍞 Углеводы: {kbju_data['carbs']} г\n"
        
        # Добавляем информацию о валидации
        if validation['confidence'] < 100:
            response_text += f"\n🎯 Уверенность: {validation['confidence']}%\n"
        
        # Если есть проблемы
        has_issues = not validation['is_valid'] or validation['issues']
        if has_issues:
            response_text += f"\n⚠️ Обнаружены проблемы:\n"
            for issue in validation['issues']:
                response_text += f"  • {issue}\n"
            if validation['suggestion']:
                response_text += f"\n💡 Рекомендация: {validation['suggestion']}\n"
        
        # Обновляем данные в state
        await state.update_data(
            food_description=corrected_food,
            kbju_data=kbju_data,
            validation=validation
        )
        
        # Создаем кнопки
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="✏️ Уточнить еще раз")]
            ],
            resize_keyboard=True
        )
        
        if has_issues:
            response_text += "\n\nПроблемы остались. Сохранить или уточнить еще раз?"
        else:
            response_text += "\n\nТеперь всё верно?"
        
        await message.answer(response_text, reply_markup=keyboard)
        await state.set_state(FoodStates.waiting_for_review)
        
    except Exception as e:
        print(f"DEBUG: Ошибка при уточнении: {e}")
        await message.answer("Извини, произошла ошибка. Попробуй еще раз.")
        await state.clear()

@router.message(FoodStates.waiting_for_clarification)
async def food_clarification(message: Message, state: FSMContext):
    """Обработка уточнения когда порция была неясна (portion_clear=false)"""
    data = await state.get_data()
    original_food = data.get('original_food', '')
    clarification = message.text.strip()
    
    combined_food = f"{original_food} {clarification}"
    
    await message.answer("🔄 Пересчитываю с уточнением... ⏳")
    
    try:
        # Шаг 1: Анализируем уточненное описание
        kbju_data = analyze_food_with_gpt5(combined_food)
        
        # Шаг 2: Валидируем результат
        validation = validate_kbju_with_gpt5(combined_food, kbju_data)
        
        # Формируем ответ на ревью
        response_text = f"📊 Пересчет для: {combined_food}\n\n"
        response_text += f"🔥 Калории: {kbju_data['calories']} ккал\n"
        response_text += f"🥩 Белки: {kbju_data['proteins']} г\n"
        response_text += f"🥑 Жиры: {kbju_data['fats']} г\n"
        response_text += f"🍞 Углеводы: {kbju_data['carbs']} г\n"
        
        # Добавляем информацию о валидации
        if validation['confidence'] < 100:
            response_text += f"\n🎯 Уверенность: {validation['confidence']}%\n"
        
        # Если есть проблемы
        has_issues = not validation['is_valid'] or validation['issues']
        if has_issues:
            response_text += f"\n⚠️ Обнаружены проблемы:\n"
            for issue in validation['issues']:
                response_text += f"  • {issue}\n"
            if validation['suggestion']:
                response_text += f"\n💡 Рекомендация: {validation['suggestion']}\n"
        
        # Сохраняем данные в state
        await state.update_data(
            food_description=combined_food,
            kbju_data=kbju_data,
            validation=validation
        )
        
        # Создаем кнопки для подтверждения
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="✏️ Уточнить")]
            ],
            resize_keyboard=True
        )
        
        if has_issues:
            response_text += "\n\nДанные выглядят подозрительно. Что делать?"
        else:
            response_text += "\n\nТеперь всё верно?"
        
        await message.answer(response_text, reply_markup=keyboard)
        await state.set_state(FoodStates.waiting_for_review)
        
    except Exception as e:
        print(f"DEBUG: Ошибка при уточнении: {e}")
        await message.answer("Извини, произошла ошибка. Попробуй еще раз.")
        await state.clear()

@router.message(Command("day"))
async def show_daily_summary(message: Message):
    user_id = message.from_user.id
    
    print(f"DEBUG: /day вызван для user_id={user_id}")
    
    if not db.user_profile_exists(user_id):
        await message.answer("Сначала нужно настроить профиль! Используй команду /profile")
        return
    
    # Получаем дневную сводку
    daily_summary = get_daily_summary(user_id)
    
    # Сначала пробуем получить сохраненные таргеты
    target = db.get_saved_targets(user_id)
    
    # Если нет сохраненных, рассчитываем через GPT-5
    if target is None:
        profile = db.get_user_profile(user_id)
        bmr = db.calculate_bmr(user_id)
        activity = profile.get('activity', 'Средний').lower()
        activity_multipliers = {'низкий': 1.2, 'средний': 1.55, 'высокий': 1.725}
        tdee = int(bmr * activity_multipliers.get(activity, 1.55))
        goal = profile.get('goal', '')
        
        # Пробуем GPT-5 расчёт
        target = calculate_targets_with_gpt5(profile, bmr, tdee, goal)
        
        # Если GPT-5 не сработал, используем формулы как fallback
        if target is None:
            target = db.calculate_target_calories(user_id)
    
    if target['calories'] == 0:
        await message.answer("Ошибка расчёта целевых калорий. Проверь свой профиль.")
        return
    
    # Рассчитываем прогресс
    calories_progress = (daily_summary['calories'] / target['calories']) * 100 if target['calories'] > 0 else 0
    proteins_progress = (daily_summary['proteins'] / target['proteins']) * 100 if target['proteins'] > 0 else 0
    fats_progress = (daily_summary['fats'] / target['fats']) * 100 if target['fats'] > 0 else 0
    carbs_progress = (daily_summary['carbs'] / target['carbs']) * 100 if target['carbs'] > 0 else 0
    
    mode_prefix = "🧪 " if BOT_MODE == 'test' else ""
    text = f"{mode_prefix}📊 Дневная сводка ({daily_summary['meals']} приёмов пищи):\n\n"
    text += f"🔥 Калории: {daily_summary['calories']} / {target['calories']} ккал ({calories_progress:.1f}%)\n"
    text += f"🥩 Белки: {daily_summary['proteins']} / {target['proteins']} г ({proteins_progress:.1f}%)\n"
    text += f"🥑 Жиры: {daily_summary['fats']} / {target['fats']} г ({fats_progress:.1f}%)\n"
    text += f"🍞 Углеводы: {daily_summary['carbs']} / {target['carbs']} г ({carbs_progress:.1f}%)\n\n"
    
    # Добавляем простой совет
    if daily_summary['meals'] == 0:
        text += "Сегодня ты ещё ничего не ел(а). Добавь еду!"
    elif calories_progress < 50:
        text += "💡 Совет: Попробуй добавить ещё один приём пищи для достижения цели."
    elif calories_progress > 120:
        text += "💡 Совет: Возможно, стоит немного снизить калорийность следующих приёмов пищи."
    else:
        text += "💡 Отличная работа! Ты на правильном пути к своей цели."
    
    await message.answer(text)

@router.message(Command("target"))
async def show_target_calories(message: Message):
    user_id = message.from_user.id
    
    print(f"DEBUG: /target вызван для user_id={user_id}")
    if not db.user_profile_exists(user_id):
        print("DEBUG: Профиль не найден")
        await message.answer(
            "Сначала нужно настроить профиль! Используй команду /profile"
        )
        return
    
    profile = db.get_user_profile(user_id)
    print(f"DEBUG: Профиль пользователя: {profile}")
    
    # Сначала пробуем получить сохраненные таргеты
    target = db.get_saved_targets(user_id)
    
    # Если нет сохраненных, рассчитываем через GPT-5
    if target is None:
        bmr = db.calculate_bmr(user_id)
        activity = profile.get('activity', 'Средний').lower()
        activity_multipliers = {'низкий': 1.2, 'средний': 1.55, 'высокий': 1.725}
        tdee = int(bmr * activity_multipliers.get(activity, 1.55))
        goal = profile.get('goal', '')
        
        # Пробуем GPT-5 расчёт
        target = calculate_targets_with_gpt5(profile, bmr, tdee, goal)
        
        # Если GPT-5 не сработал, используем формулы как fallback
        if target is None:
            target = db.calculate_target_calories(user_id)
    
    print(f"DEBUG: Целевые калории: {target}")
    
    if target['calories'] == 0:
        await message.answer("Ошибка расчёта целевых калорий. Проверь свой профиль.")
        return
    
    mode_prefix = "🧪 " if BOT_MODE == 'test' else ""
    text = f"{mode_prefix}🎯 Целевые калории для {profile.get('gender', 'пользователя')}:\n\n"
    text += f"📊 Базовый обмен веществ (BMR): {target['bmr']} ккал\n"
    text += f"🔥 Общий расход энергии (TDEE): {target['tdee']} ккал\n"
    text += f"🎯 Целевые калории: {target['calories']} ккал\n\n"
    text += f"🥩 Белки: {target['proteins']} г\n"
    text += f"🥑 Жиры: {target['fats']} г\n"
    text += f"🍞 Углеводы: {target['carbs']} г\n\n"
    text += f"💡 Цель: {profile.get('goal', 'Не указана')}\n"
    text += f"🏃 Активность: {profile.get('activity', 'Не указана')}\n\n"
    text += f"ℹ️ {target.get('explanation', '')}"
    
    await message.answer(text)

@router.message(Command("meals"))
async def show_meals(message: Message):
    user_id = message.from_user.id
    
    if not db.user_profile_exists(user_id):
        await message.answer("Сначала нужно настроить профиль! Используй команду /profile")
        return
    
    meals = db.get_meals_for_day(user_id)
    
    if not meals:
        await message.answer("Сегодня ты ещё ничего не ел(а). Добавь еду!")
        return
    
    mode_prefix = "🧪 " if BOT_MODE == 'test' else ""
    text = f"{mode_prefix}🍽 Приёмы пищи за сегодня ({len(meals)}):\n\n"
    
    for i, meal in enumerate(meals, 1):
        text += f"{i}. {meal['description']}\n"
        text += f"   🔥 {meal['calories']} ккал | 🥩 {meal['proteins']}г | 🥑 {meal['fats']}г | 🍞 {meal['carbs']}г\n\n"
    
    await message.answer(text)

dp.include_router(router)

async def main():
    print(f"🤖 Бот запущен в режиме: {BOT_MODE}")
    print(f"🧠 Используется модель: GPT-5 (reasoning + custom tools)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())