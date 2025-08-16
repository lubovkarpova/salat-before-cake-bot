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
import openai
from database import db

load_dotenv()

API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not API_TOKEN or not OPENAI_API_KEY:
    print("Ошибка: не найдены TELEGRAM_BOT_TOKEN или OPENAI_API_KEY в переменных окружения")
    exit(1)

openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

class ProfileStates(StatesGroup):
    waiting_for_gender = State()
    waiting_for_age = State()
    waiting_for_height = State()
    waiting_for_weight = State()
    waiting_for_activity = State()
    waiting_for_goal = State()

class FoodStates(StatesGroup):
    waiting_for_food_description = State()
    waiting_for_clarification = State()

def parse_kbju_from_gpt(gpt_response: str) -> dict:
    """Извлекает КБЖУ из ответа GPT"""
    print(f"DEBUG: Парсим ответ GPT: {gpt_response}")
    
    # Ищем калории
    calories_match = re.search(r'калори[йи].*?(\d+(?:-\d+)?)', gpt_response, re.IGNORECASE)
    if calories_match:
        calories_str = calories_match.group(1)
        if '-' in calories_str:
            # Если диапазон, берем верхнее значение
            calories = int(calories_str.split('-')[1])
        else:
            calories = int(calories_str)
    else:
        calories = 0
    
    # Ищем белки
    proteins_match = re.search(r'белк[аи].*?(\d+(?:\.\d+)?)', gpt_response, re.IGNORECASE)
    proteins = int(float(proteins_match.group(1))) if proteins_match else 0
    
    # Ищем жиры
    fats_match = re.search(r'жир[аи].*?(\d+(?:\.\d+)?)', gpt_response, re.IGNORECASE)
    fats = int(float(fats_match.group(1))) if fats_match else 0
    
    # Ищем углеводы
    carbs_match = re.search(r'углевод[аи].*?(\d+(?:\.\d+)?)', gpt_response, re.IGNORECASE)
    carbs = int(float(carbs_match.group(1))) if carbs_match else 0
    
    print(f"DEBUG: Извлеченные значения - калории: {calories}, белки: {proteins}, жиры: {fats}, углеводы: {carbs}")
    
    return {
        'calories': calories,
        'proteins': proteins,
        'fats': fats,
        'carbs': carbs
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
    await message.answer(
        "Привет! Я бот для учёта КБЖУ и советов по питанию.\n\n"
        "📋 Доступные команды:\n"
        "/profile - настроить профиль\n"
        "/target - показать целевые калории\n"
        "/day - показать дневную сводку\n"
        "/meals - показать все приёмы пищи за день\n\n"
        "🍽 Просто напиши, что ты ел(а), и я посчитаю КБЖУ!"
    )

@router.message(Command("profile"))
async def profile_start(message: Message, state: FSMContext):
    if db.user_profile_exists(message.from_user.id):
        await message.answer("У тебя уже есть профиль! Используй /target чтобы посмотреть целевые калории.")
        return
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
        ],
        resize_keyboard=True
    )
    
    await message.answer("Привет! Давай настроим твой профиль для расчёта КБЖУ.\n\nКакой у тебя пол?", reply_markup=keyboard)
    await state.set_state(ProfileStates.waiting_for_gender)

@router.message(ProfileStates.waiting_for_gender)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.strip()
    if gender not in ["Мужской", "Женский"]:
        await message.answer("Пожалуйста, выбери 'Мужской' или 'Женский'")
        return
    
    await state.update_data(gender=gender)
    
    # Убираем кнопки
    await message.answer("Сколько тебе лет? (введите число)", reply_markup=ReplyKeyboardRemove())
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
    
    await message.answer("Какой у тебя рост в см? (например: 170)")
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
    
    await message.answer("Какой у тебя вес в кг? (например: 65)")
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
        "Какой у тебя уровень активности?\n\n"
        "🏃‍♀️ Низкий - сидячий образ жизни, мало движения\n"
        "🏃‍♀️ Средний - умеренная активность, спорт 2-3 раза в неделю\n"
        "🏃‍♀️ Высокий - активный образ жизни, спорт 4+ раз в неделю",
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
        "Какова твоя цель? Напиши своими словами, например:\n\n"
        "🎯 Похудение: похудеть, сбросить вес\n"
        "💪 Набор массы: набрать вес, нарастить мышцы\n"
        "⚖️ Поддержание: поддерживать форму, сохранить вес\n"
        "🥩 Белок: следить за белком, повысить протеин\n"
        "🩸 Здоровье: снизить холестерин, контролировать сахар\n"
        "🥗 Разнообразие: разнообразить рацион, попробовать новое\n\n"
        "Или опиши свою цель своими словами!",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ProfileStates.waiting_for_goal)

@router.message(ProfileStates.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    goal = message.text.strip()
    if len(goal) < 3:
        await message.answer("Пожалуйста, опиши цель подробнее")
        return
    
    await state.update_data(goal=goal)
    
    # Получаем все данные профиля
    data = await state.get_data()
    
    # Сохраняем профиль в базу данных
    success = db.save_user_profile(message.from_user.id, data)
    
    if success:
        await message.answer(
            f"Отлично! Твой профиль сохранён:\n\n"
            f"👤 Пол: {data['gender']}\n"
            f"📅 Возраст: {data['age']} лет\n"
            f"📏 Рост: {data['height']} см\n"
            f"⚖️ Вес: {data['weight']} кг\n"
            f"🏃‍♀️ Активность: {data['activity']}\n"
            f"🎯 Цель: {data['goal']}\n\n"
            f"Теперь можешь:\n"
            f"• Написать, что ты ел(а) - я посчитаю КБЖУ\n"
            f"• Использовать /target - посмотреть целевые калории\n"
            f"• Использовать /day - посмотреть дневную сводку"
        )
    else:
        await message.answer("Ошибка сохранения профиля. Попробуй ещё раз.")
    
    await state.clear()

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
        # Отправляем запрос к GPT
        prompt = f"Оцени КБЖУ {user_food}"
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты эксперт по питанию. Оценивай КБЖУ продуктов на основе описания пользователя."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200
        )
        
        gpt_response = response.choices[0].message.content
        print(f"DEBUG: Ответ GPT: {gpt_response}")
        
        # Парсим КБЖУ из ответа
        kbju_data = parse_kbju_from_gpt(gpt_response)
        
        # Если не удалось извлечь калории, просим уточнить
        if kbju_data['calories'] == 0:
            clarification_prompt = f"Для оценки КБЖУ {user_food} нужно больше информации о размере порции. Пожалуйста, уточните количество."
            await message.answer(clarification_prompt)
            await state.update_data(original_food=user_food)
            await state.set_state(FoodStates.waiting_for_clarification)
            return
        
        # Сохраняем еду в дневной учет
        save_food_to_daily(message.from_user.id, user_food, kbju_data)
        
        # Получаем дневную сводку
        daily_summary = get_daily_summary(message.from_user.id)
        
        # Формируем ответ
        response_text = f"🍽 Анализирую твою еду... ⏳\n\n"
        response_text += f"Для {user_food}:\n"
        response_text += f"🔥 Калории: {kbju_data['calories']} ккал\n"
        response_text += f"🥩 Белки: {kbju_data['proteins']} г\n"
        response_text += f"🥑 Жиры: {kbju_data['fats']} г\n"
        response_text += f"🍞 Углеводы: {kbju_data['carbs']} г\n\n"
        
        # Добавляем дневную сводку
        response_text += f"📊 Итого за день ({daily_summary['meals']} приёмов пищи):\n"
        response_text += f"🔥 Калории: {daily_summary['calories']} ккал\n"
        response_text += f"🥩 Белки: {daily_summary['proteins']} г\n"
        response_text += f"🥑 Жиры: {daily_summary['fats']} г\n"
        response_text += f"🍞 Углеводы: {daily_summary['carbs']} г"
        
        # Добавляем прогресс к цели
        target = db.calculate_target_calories(message.from_user.id)
        if target['calories'] > 0:
            progress = (daily_summary['calories'] / target['calories']) * 100
            response_text += f"\n\n🎯 Прогресс к цели: {progress:.1f}%"
        
        await message.answer(response_text)
        
    except Exception as e:
        print(f"DEBUG: Ошибка при анализе еды: {e}")
        await message.answer("Извини, произошла ошибка при анализе еды. Попробуй ещё раз.")

@router.message(FoodStates.waiting_for_clarification)
async def food_clarification(message: Message, state: FSMContext):
    data = await state.get_data()
    original_food = data.get('original_food', '')
    clarification = message.text.strip()
    
    combined_food = f"{original_food} {clarification}"
    
    await message.answer("🔄 Пересчитываю КБЖУ... ⏳")
    
    try:
        # Отправляем запрос к GPT с уточнением
        prompt = f"Оцени КБЖУ {combined_food}\n\nВключай в ответ саммари:\n🔥 Калории: 0 ккал\n🥩 Белки: 0 г\n🥑 Жиры: 0 г\n🍞 Углеводы: 0 г"
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты эксперт по питанию. Оценивай КБЖУ продуктов на основе описания пользователя."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200
        )
        
        gpt_response = response.choices[0].message.content
        print(f"DEBUG: Ответ GPT с уточнением: {gpt_response}")
        
        # Парсим КБЖУ из ответа
        kbju_data = parse_kbju_from_gpt(gpt_response)
        
        # Сохраняем еду в дневной учет
        save_food_to_daily(message.from_user.id, combined_food, kbju_data)
        
        # Получаем дневную сводку
        daily_summary = get_daily_summary(message.from_user.id)
        
        # Формируем ответ
        response_text = f"🔄 Пересчитываю КБЖУ... ⏳\n\n"
        response_text += f"Для {combined_food}:\n"
        response_text += f"🔥 Калории: {kbju_data['calories']} ккал\n"
        response_text += f"🥩 Белки: {kbju_data['proteins']} г\n"
        response_text += f"🥑 Жиры: {kbju_data['fats']} г\n"
        response_text += f"🍞 Углеводы: {kbju_data['carbs']} г\n\n"
        
        # Добавляем дневную сводку
        response_text += f"📊 Итого за день ({daily_summary['meals']} приёмов пищи):\n"
        response_text += f"🔥 Калории: {daily_summary['calories']} ккал\n"
        response_text += f"🥩 Белки: {daily_summary['proteins']} г\n"
        response_text += f"🥑 Жиры: {daily_summary['fats']} г\n"
        response_text += f"🍞 Углеводы: {daily_summary['carbs']} г"
        
        # Добавляем прогресс к цели
        target = db.calculate_target_calories(message.from_user.id)
        if target['calories'] > 0:
            progress = (daily_summary['calories'] / target['calories']) * 100
            response_text += f"\n\n🎯 Прогресс к цели: {progress:.1f}%"
        
        await message.answer(response_text)
        
    except Exception as e:
        print(f"DEBUG: Ошибка при уточнении еды: {e}")
        await message.answer("Извини, произошла ошибка при анализе еды. Попробуй ещё раз.")
    
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
    
    # Получаем целевые калории
    target = db.calculate_target_calories(user_id)
    
    if target['calories'] == 0:
        await message.answer("Ошибка расчёта целевых калорий. Проверь свой профиль.")
        return
    
    # Рассчитываем прогресс
    calories_progress = (daily_summary['calories'] / target['calories']) * 100 if target['calories'] > 0 else 0
    proteins_progress = (daily_summary['proteins'] / target['proteins']) * 100 if target['proteins'] > 0 else 0
    fats_progress = (daily_summary['fats'] / target['fats']) * 100 if target['fats'] > 0 else 0
    carbs_progress = (daily_summary['carbs'] / target['carbs']) * 100 if target['carbs'] > 0 else 0
    
    text = f"📊 Дневная сводка ({daily_summary['meals']} приёмов пищи):\n\n"
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
    target = db.calculate_target_calories(user_id)
    print(f"DEBUG: Целевые калории: {target}")
    
    if target['calories'] == 0:
        await message.answer("Ошибка расчёта целевых калорий. Проверь свой профиль.")
        return
    
    text = f"🎯 Целевые калории для {profile.get('gender', 'пользователя')}:\n\n"
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
    
    text = f"🍽 Приёмы пищи за сегодня ({len(meals)}):\n\n"
    
    for i, meal in enumerate(meals, 1):
        text += f"{i}. {meal['description']}\n"
        text += f"   🔥 {meal['calories']} ккал | 🥩 {meal['proteins']}г | 🥑 {meal['fats']}г | 🍞 {meal['carbs']}г\n\n"
    
    await message.answer(text)

dp.include_router(router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())