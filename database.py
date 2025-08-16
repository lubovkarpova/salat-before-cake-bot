import sqlite3
import os
from datetime import datetime, date
from typing import Dict, List, Optional

class Database:
    def __init__(self, db_path: str = "nutrition_bot.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных и создание таблиц"""
        print(f"DEBUG: Инициализация БД: {self.db_path}")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Таблица пользователей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        gender TEXT,
                        age INTEGER,
                        height INTEGER,
                        weight INTEGER,
                        activity TEXT,
                        goal TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                print("DEBUG: Таблица users создана/проверена")
                
                # Таблица приёмов пищи
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS meals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        description TEXT,
                        calories INTEGER,
                        proteins INTEGER,
                        fats INTEGER,
                        carbs INTEGER,
                        date TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                print("DEBUG: Таблица meals создана/проверена")
                
                # Таблица дневных сводок
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS daily_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        date TEXT,
                        total_calories INTEGER,
                        total_proteins INTEGER,
                        total_fats INTEGER,
                        total_carbs INTEGER,
                        meals_count INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id),
                        UNIQUE(user_id, date)
                    )
                ''')
                print("DEBUG: Таблица daily_summaries создана/проверена")
                
                conn.commit()
                print("DEBUG: База данных инициализирована успешно")
                
        except Exception as e:
            print(f"DEBUG: Ошибка инициализации БД: {e}")

    def save_user_profile(self, user_id: int, profile_data: Dict) -> bool:
        """Сохранение профиля пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO users 
                    (user_id, gender, age, height, weight, activity, goal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    profile_data.get('gender'),
                    profile_data.get('age'),
                    profile_data.get('height'),
                    profile_data.get('weight'),
                    profile_data.get('activity'),
                    profile_data.get('goal')
                ))
                
                conn.commit()
                print(f"DEBUG: Профиль пользователя {user_id} сохранён")
                return True
                
        except Exception as e:
            print(f"DEBUG: Ошибка сохранения профиля: {e}")
            return False

    def get_user_profile(self, user_id: int) -> Optional[Dict]:
        """Получение профиля пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT gender, age, height, weight, activity, goal
                    FROM users WHERE user_id = ?
                ''', (user_id,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'gender': row[0],
                        'age': row[1],
                        'height': row[2],
                        'weight': row[3],
                        'activity': row[4],
                        'goal': row[5]
                    }
                return None
                
        except Exception as e:
            print(f"DEBUG: Ошибка получения профиля: {e}")
            return None

    def user_profile_exists(self, user_id: int) -> bool:
        """Проверка существования профиля пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
                return cursor.fetchone() is not None
                
        except Exception as e:
            print(f"DEBUG: Ошибка проверки профиля: {e}")
            return False

    def save_meal(self, user_id: int, description: str, kbju_data: Dict) -> bool:
        """Сохранение приёма пищи"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                today = date.today().strftime('%Y-%m-%d')
                
                cursor.execute('''
                    INSERT INTO meals 
                    (user_id, description, calories, proteins, fats, carbs, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    description,
                    kbju_data.get('calories', 0),
                    kbju_data.get('proteins', 0),
                    kbju_data.get('fats', 0),
                    kbju_data.get('carbs', 0),
                    today
                ))
                
                conn.commit()
                print("DEBUG: Приём пищи сохранён в таблицу meals")
                
                # Обновляем дневную сводку
                self._update_daily_summary(user_id, today, kbju_data)
                
                return True
                
        except Exception as e:
            print(f"DEBUG: Ошибка сохранения приёма пищи: {e}")
            return False

    def _update_daily_summary(self, user_id: int, date_str: str, new_meal_kbju: Dict):
        """Обновление дневной сводки"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Получаем текущие итоги
                cursor.execute('''
                    SELECT total_calories, total_proteins, total_fats, total_carbs, meals_count
                    FROM daily_summaries 
                    WHERE user_id = ? AND date = ?
                ''', (user_id, date_str))
                
                row = cursor.fetchone()
                
                if row:
                    # Обновляем существующую запись
                    current_calories = row[0] or 0
                    current_proteins = row[1] or 0
                    current_fats = row[2] or 0
                    current_carbs = row[3] or 0
                    current_meals = row[4] or 0
                    
                    new_calories = current_calories + new_meal_kbju.get('calories', 0)
                    new_proteins = current_proteins + new_meal_kbju.get('proteins', 0)
                    new_fats = current_fats + new_meal_kbju.get('fats', 0)
                    new_carbs = current_carbs + new_meal_kbju.get('carbs', 0)
                    new_meals = current_meals + 1
                    
                    cursor.execute('''
                        UPDATE daily_summaries 
                        SET total_calories = ?, total_proteins = ?, total_fats = ?, 
                            total_carbs = ?, meals_count = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND date = ?
                    ''', (new_calories, new_proteins, new_fats, new_carbs, new_meals, user_id, date_str))
                    
                else:
                    # Создаём новую запись
                    cursor.execute('''
                        INSERT INTO daily_summaries 
                        (user_id, date, total_calories, total_proteins, total_fats, total_carbs, meals_count)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                    ''', (
                        user_id, date_str,
                        new_meal_kbju.get('calories', 0),
                        new_meal_kbju.get('proteins', 0),
                        new_meal_kbju.get('fats', 0),
                        new_meal_kbju.get('carbs', 0)
                    ))
                
                conn.commit()
                print("DEBUG: Дневные итоги обновлены")
                print("DEBUG: Транзакция зафиксирована")
                
        except Exception as e:
            print(f"Ошибка обновления дневных итогов: {e}")

    def get_daily_summary(self, user_id: int, date_str: str = None) -> Dict:
        """Получение дневной сводки"""
        if date_str is None:
            date_str = date.today().strftime('%Y-%m-%d')
        
        print(f"DEBUG: Получаем дневные итоги: user_id={user_id}, date={date_str}")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT total_calories, total_proteins, total_fats, total_carbs, meals_count
                    FROM daily_summaries 
                    WHERE user_id = ? AND date = ?
                ''', (user_id, date_str))
                
                row = cursor.fetchone()
                print(f"DEBUG: Результат запроса из daily_summaries: {row}")
                
                if row:
                    result = {
                        'calories': row[0] or 0,
                        'proteins': row[1] or 0,
                        'fats': row[2] or 0,
                        'carbs': row[3] or 0,
                        'meals': row[4] or 0
                    }
                    print(f"DEBUG: Возвращаем итоги из daily_summaries: {result}")
                    return result
                
                # Если нет данных в daily_summaries, считаем из meals
                cursor.execute('''
                    SELECT SUM(calories), SUM(proteins), SUM(fats), SUM(carbs), COUNT(*)
                    FROM meals 
                    WHERE user_id = ? AND date = ?
                ''', (user_id, date_str))
                
                row = cursor.fetchone()
                print(f"DEBUG: Результат запроса из meals: {row}")
                
                if row and row[0] is not None:
                    result = {
                        'calories': row[0],
                        'proteins': row[1] or 0,
                        'fats': row[2] or 0,
                        'carbs': row[3] or 0,
                        'meals': row[4] or 0
                    }
                    print(f"DEBUG: Возвращаем итоги из meals: {result}")
                    return result
                
                print("DEBUG: Данных нет, возвращаем нули")
                return {'calories': 0, 'proteins': 0, 'fats': 0, 'carbs': 0, 'meals': 0}
                
        except Exception as e:
            print(f"DEBUG: Ошибка получения дневной сводки: {e}")
            return {'calories': 0, 'proteins': 0, 'fats': 0, 'carbs': 0, 'meals': 0}

    def get_meals_for_day(self, user_id: int, date_str: str = None) -> List[Dict]:
        """Получение всех приёмов пищи за день"""
        if date_str is None:
            date_str = date.today().strftime('%Y-%m-%d')
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT description, calories, proteins, fats, carbs
                    FROM meals 
                    WHERE user_id = ? AND date = ?
                    ORDER BY created_at
                ''', (user_id, date_str))
                
                rows = cursor.fetchall()
                meals = []
                
                for row in rows:
                    meals.append({
                        'description': row[0],
                        'calories': row[1],
                        'proteins': row[2],
                        'fats': row[3],
                        'carbs': row[4]
                    })
                
                return meals
                
        except Exception as e:
            print(f"DEBUG: Ошибка получения приёмов пищи: {e}")
            return []

    def calculate_bmr(self, user_id: int) -> int:
        """Расчёт базового обмена веществ (BMR) по формуле Миффлина-Сан Жеора"""
        profile = self.get_user_profile(user_id)
        if not profile:
            return 0
        
        gender = profile.get('gender', '').lower()
        age = profile.get('age', 0)
        height = profile.get('height', 0)
        weight = profile.get('weight', 0)
        
        if gender == 'мужской':
            bmr = 10 * weight + 6.25 * height - 5 * age + 5
        else:
            bmr = 10 * weight + 6.25 * height - 5 * age - 161
        
        return int(bmr)

    def calculate_target_calories(self, user_id: int) -> Dict:
        """Расчёт целевых калорий и макросов с учётом цели пользователя и пояснением"""
        bmr = self.calculate_bmr(user_id)
        if bmr == 0:
            return {'calories': 0, 'proteins': 0, 'fats': 0, 'carbs': 0, 'explanation': 'Нет профиля'}
        
        profile = self.get_user_profile(user_id)
        activity = profile.get('activity', 'Средний').lower()
        goal = profile.get('goal', '').lower()
        weight = profile.get('weight', 0)
        explanation = []
        
        # Коэффициенты активности
        activity_multipliers = {
            'низкий': 1.2,      # Сидячий образ жизни
            'средний': 1.55,    # Умеренная активность
            'высокий': 1.725    # Высокая активность
        }
        tdee = bmr * activity_multipliers.get(activity, 1.55)
        explanation.append(f"TDEE рассчитан с коэффициентом активности '{activity}': {activity_multipliers.get(activity, 1.55)}")
        
        # Базовые значения
        target_calories = int(tdee)
        target_proteins = int(weight * 1.2)
        target_fats = int(weight * 1)
        target_carbs = int((target_calories - target_proteins * 4 - target_fats * 9) / 4)
        
        # Корректировка по целям
        if any(word in goal for word in ['похудение', 'похудеть', 'сбросить вес']):
            target_calories = int(tdee * 0.85)
            target_proteins = int(weight * 1.6)
            target_fats = int(weight * 0.8)
            target_carbs = int((target_calories - target_proteins * 4 - target_fats * 9) / 4)
            explanation.append("Цель — похудение: калорийность снижена на 15%, белок повышен до 1.6 г/кг, жиры снижены до 0.8 г/кг")
        elif any(word in goal for word in ['набор массы', 'набрать вес', 'нарастить мышцы']):
            target_calories = int(tdee * 1.15)
            target_proteins = int(weight * 1.6)
            target_fats = int(weight * 1)
            target_carbs = int((target_calories - target_proteins * 4 - target_fats * 9) / 4)
            explanation.append("Цель — набор массы: калорийность увеличена на 15%, белок 1.6 г/кг, жиры 1 г/кг")
        elif 'белок' in goal or 'протеин' in goal:
            target_proteins = int(weight * 2)
            target_fats = int(weight * 1)
            target_carbs = int((target_calories - target_proteins * 4 - target_fats * 9) / 4)
            explanation.append("Цель — повысить белок: белок 2 г/кг, жиры 1 г/кг, калории по TDEE")
        elif 'холестерин' in goal or 'жиры' in goal:
            target_fats = int(weight * 0.7)
            target_carbs = int((target_calories - target_proteins * 4 - target_fats * 9) / 4)
            explanation.append("Цель — снизить жиры/холестерин: жиры 0.7 г/кг, калории по TDEE")
        elif 'поддержание' in goal or 'поддерживать вес' in goal:
            explanation.append("Цель — поддержание: калории по TDEE, белок 1.2 г/кг, жиры 1 г/кг")
        else:
            explanation.append("Стандартные значения: калории по TDEE, белок 1.2 г/кг, жиры 1 г/кг")
        
        return {
            'calories': target_calories,
            'proteins': target_proteins,
            'fats': target_fats,
            'carbs': target_carbs,
            'bmr': bmr,
            'tdee': int(tdee),
            'explanation': '; '.join(explanation)
        }

# Создаём глобальный экземпляр базы данных
db = Database() 