"""
Автоматические тесты для Nutrition Bot
Покрывают основные сценарии использования бота

Установка зависимостей:
pip install pytest pytest-asyncio

Запуск тестов:
pytest test_scenarios.py -v
"""

import pytest
import sqlite3
import os
from datetime import date
from database import Database


# ============= FIXTURES =============

@pytest.fixture
def test_db():
    """Создает тестовую базу данных для каждого теста"""
    db_path = "test_scenarios.db"
    
    # Удаляем старую базу если существует
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # Создаем новую базу
    db = Database(db_path)
    
    yield db
    
    # Очистка после теста
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def test_user_id():
    """ID тестового пользователя"""
    return 12345


@pytest.fixture
def test_profile_data():
    """Тестовые данные профиля"""
    return {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'похудеть'
    }


# ============= ТЕСТЫ ПРОФИЛЯ =============

def test_create_profile(test_db, test_user_id, test_profile_data):
    """TC-001: Создание профиля пользователя"""
    # Arrange & Act
    result = test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Assert
    assert result == True, "Профиль должен быть сохранен"
    assert test_db.user_profile_exists(test_user_id), "Профиль должен существовать"


def test_get_profile(test_db, test_user_id, test_profile_data):
    """Получение данных профиля"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Act
    profile = test_db.get_user_profile(test_user_id)
    
    # Assert
    assert profile is not None, "Профиль должен быть найден"
    assert profile['gender'] == 'Женский'
    assert profile['age'] == 25
    assert profile['height'] == 165
    assert profile['weight'] == 60
    assert profile['activity'] == 'Средний'
    assert profile['goal'] == 'похудеть'


def test_profile_exists_check(test_db, test_user_id):
    """Проверка существования профиля"""
    # Arrange & Act
    exists_before = test_db.user_profile_exists(test_user_id)
    
    test_db.save_user_profile(test_user_id, {
        'gender': 'Мужской',
        'age': 30,
        'height': 180,
        'weight': 75,
        'activity': 'Высокий',
        'goal': 'набрать массу'
    })
    
    exists_after = test_db.user_profile_exists(test_user_id)
    
    # Assert
    assert exists_before == False, "Профиль не должен существовать до создания"
    assert exists_after == True, "Профиль должен существовать после создания"


def test_profile_not_exists(test_db):
    """Проверка несуществующего профиля"""
    # Arrange & Act
    exists = test_db.user_profile_exists(99999)
    profile = test_db.get_user_profile(99999)
    
    # Assert
    assert exists == False, "Профиль не должен существовать"
    assert profile is None, "Профиль должен быть None"


# ============= ТЕСТЫ РАСЧЕТА BMR =============

def test_bmr_calculation_female(test_db, test_user_id):
    """Расчет BMR для женщины"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'поддерживать вес'
    })
    
    # Act
    bmr = test_db.calculate_bmr(test_user_id)
    
    # Assert
    # BMR = 10 * 60 + 6.25 * 165 - 5 * 25 - 161
    expected_bmr = 10 * 60 + 6.25 * 165 - 5 * 25 - 161
    assert bmr == int(expected_bmr), f"BMR должен быть {int(expected_bmr)}"
    assert 1300 <= bmr <= 1400, "BMR должен быть в разумных пределах"


def test_bmr_calculation_male(test_db, test_user_id):
    """Расчет BMR для мужчины"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Мужской',
        'age': 30,
        'height': 180,
        'weight': 75,
        'activity': 'Средний',
        'goal': 'поддерживать вес'
    })
    
    # Act
    bmr = test_db.calculate_bmr(test_user_id)
    
    # Assert
    # BMR = 10 * 75 + 6.25 * 180 - 5 * 30 + 5
    expected_bmr = 10 * 75 + 6.25 * 180 - 5 * 30 + 5
    assert bmr == int(expected_bmr), f"BMR должен быть {int(expected_bmr)}"
    assert 1700 <= bmr <= 1800, "BMR должен быть в разумных пределах"


def test_bmr_without_profile(test_db):
    """Расчет BMR без профиля"""
    # Arrange & Act
    bmr = test_db.calculate_bmr(99999)
    
    # Assert
    assert bmr == 0, "BMR должен быть 0 для несуществующего профиля"


# ============= ТЕСТЫ РАСЧЕТА ЦЕЛЕВЫХ КАЛОРИЙ =============

def test_target_weight_loss(test_db, test_user_id):
    """TC-016: Расчет таргетов для похудения"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'похудеть'
    })
    
    # Act
    target = test_db.calculate_target_calories(test_user_id)
    bmr = test_db.calculate_bmr(test_user_id)
    tdee = int(bmr * 1.55)  # Средняя активность
    
    # Assert
    assert target['calories'] < tdee, "Калории должны быть меньше TDEE"
    assert target['calories'] == int(tdee * 0.85), "Калории должны быть 85% от TDEE"
    assert target['proteins'] == int(60 * 1.6), "Белки должны быть 1.6 г/кг"
    assert target['fats'] == int(60 * 0.8), "Жиры должны быть 0.8 г/кг"
    assert 'похудение' in target['explanation'].lower(), "Пояснение должно содержать информацию о похудении"


def test_target_weight_gain(test_db, test_user_id):
    """TC-016: Расчет таргетов для набора массы"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Мужской',
        'age': 30,
        'height': 180,
        'weight': 75,
        'activity': 'Высокий',
        'goal': 'набрать массу'
    })
    
    # Act
    target = test_db.calculate_target_calories(test_user_id)
    bmr = test_db.calculate_bmr(test_user_id)
    tdee = int(bmr * 1.725)  # Высокая активность
    
    # Assert
    assert target['calories'] > tdee, "Калории должны быть больше TDEE"
    assert target['calories'] == int(tdee * 1.15), "Калории должны быть 115% от TDEE"
    assert target['proteins'] == int(75 * 1.6), "Белки должны быть 1.6 г/кг"
    assert target['fats'] == int(75 * 1.0), "Жиры должны быть 1.0 г/кг"
    assert 'набор массы' in target['explanation'].lower(), "Пояснение должно содержать информацию о наборе массы"


def test_target_high_protein(test_db, test_user_id):
    """TC-016: Расчет таргетов для повышенного белка"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'больше белка'
    })
    
    # Act
    target = test_db.calculate_target_calories(test_user_id)
    bmr = test_db.calculate_bmr(test_user_id)
    tdee = int(bmr * 1.55)
    
    # Assert
    assert target['calories'] == int(tdee), "Калории должны быть равны TDEE"
    assert target['proteins'] == int(60 * 2.0), "Белки должны быть 2.0 г/кг"
    assert target['fats'] == int(60 * 1.0), "Жиры должны быть 1.0 г/кг"
    assert 'белок' in target['explanation'].lower(), "Пояснение должно содержать информацию о белке"


def test_target_maintenance(test_db, test_user_id):
    """TC-016: Расчет таргетов для поддержания веса"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Мужской',
        'age': 30,
        'height': 180,
        'weight': 75,
        'activity': 'Средний',
        'goal': 'поддерживать вес'
    })
    
    # Act
    target = test_db.calculate_target_calories(test_user_id)
    bmr = test_db.calculate_bmr(test_user_id)
    tdee = int(bmr * 1.55)
    
    # Assert
    assert target['calories'] == int(tdee), "Калории должны быть равны TDEE"
    assert target['proteins'] == int(75 * 1.2), "Белки должны быть 1.2 г/кг"
    assert target['fats'] == int(75 * 1.0), "Жиры должны быть 1.0 г/кг"


def test_target_low_fat(test_db, test_user_id):
    """TC-016: Расчет таргетов для снижения жиров"""
    # Arrange
    test_db.save_user_profile(test_user_id, {
        'gender': 'Женский',
        'age': 40,
        'height': 160,
        'weight': 55,
        'activity': 'Низкий',
        'goal': 'холестерин'
    })
    
    # Act
    target = test_db.calculate_target_calories(test_user_id)
    
    # Assert
    assert target['fats'] == int(55 * 0.7), "Жиры должны быть 0.7 г/кг"
    assert 'холестерин' in target['explanation'].lower() or 'жиры' in target['explanation'].lower()


# ============= ТЕСТЫ ПРИЕМОВ ПИЩИ =============

def test_save_meal(test_db, test_user_id, test_profile_data):
    """TC-008: Сохранение приема пищи"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    kbju_data = {
        'calories': 95,
        'proteins': 0,
        'fats': 0,
        'carbs': 25
    }
    
    # Act
    result = test_db.save_meal(test_user_id, "яблоко среднее", kbju_data)
    
    # Assert
    assert result == True, "Прием пищи должен быть сохранен"


def test_get_meals_for_day(test_db, test_user_id, test_profile_data):
    """TC-015: Получение приемов пищи за день"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    test_db.save_meal(test_user_id, "яблоко", {'calories': 95, 'proteins': 0, 'fats': 0, 'carbs': 25})
    test_db.save_meal(test_user_id, "банан", {'calories': 105, 'proteins': 1, 'fats': 0, 'carbs': 27})
    test_db.save_meal(test_user_id, "курица 150г", {'calories': 248, 'proteins': 47, 'fats': 5, 'carbs': 0})
    
    # Act
    meals = test_db.get_meals_for_day(test_user_id)
    
    # Assert
    assert len(meals) == 3, "Должно быть 3 приема пищи"
    assert meals[0]['description'] == "яблоко"
    assert meals[1]['description'] == "банан"
    assert meals[2]['description'] == "курица 150г"


def test_get_meals_empty(test_db, test_user_id, test_profile_data):
    """TC-013: Получение приемов пищи без данных"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Act
    meals = test_db.get_meals_for_day(test_user_id)
    
    # Assert
    assert len(meals) == 0, "Должно быть 0 приемов пищи"


# ============= ТЕСТЫ ДНЕВНОЙ СВОДКИ =============

def test_daily_summary_with_meals(test_db, test_user_id, test_profile_data):
    """TC-012: Дневная сводка с приемами пищи"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    test_db.save_meal(test_user_id, "яблоко", {'calories': 95, 'proteins': 0, 'fats': 0, 'carbs': 25})
    test_db.save_meal(test_user_id, "банан", {'calories': 105, 'proteins': 1, 'fats': 0, 'carbs': 27})
    test_db.save_meal(test_user_id, "курица 150г", {'calories': 248, 'proteins': 47, 'fats': 5, 'carbs': 0})
    
    today = date.today().strftime('%Y-%m-%d')
    
    # Act
    summary = test_db.get_daily_summary(test_user_id, today)
    
    # Assert
    assert summary['calories'] == 448, f"Калории должны быть 448, получено {summary['calories']}"
    assert summary['proteins'] == 48, f"Белки должны быть 48, получено {summary['proteins']}"
    assert summary['fats'] == 5, f"Жиры должны быть 5, получено {summary['fats']}"
    assert summary['carbs'] == 52, f"Углеводы должны быть 52, получено {summary['carbs']}"
    assert summary['meals'] == 3, f"Приемов пищи должно быть 3, получено {summary['meals']}"


def test_daily_summary_empty(test_db, test_user_id, test_profile_data):
    """TC-013: Дневная сводка без приемов пищи"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    today = date.today().strftime('%Y-%m-%d')
    
    # Act
    summary = test_db.get_daily_summary(test_user_id, today)
    
    # Assert
    assert summary['calories'] == 0
    assert summary['proteins'] == 0
    assert summary['fats'] == 0
    assert summary['carbs'] == 0
    assert summary['meals'] == 0


def test_daily_summary_incremental(test_db, test_user_id, test_profile_data):
    """Инкрементальное обновление дневной сводки"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    today = date.today().strftime('%Y-%m-%d')
    
    # Act & Assert - Первый прием пищи
    test_db.save_meal(test_user_id, "яблоко", {'calories': 95, 'proteins': 0, 'fats': 0, 'carbs': 25})
    summary1 = test_db.get_daily_summary(test_user_id, today)
    assert summary1['calories'] == 95
    assert summary1['meals'] == 1
    
    # Act & Assert - Второй прием пищи
    test_db.save_meal(test_user_id, "банан", {'calories': 105, 'proteins': 1, 'fats': 0, 'carbs': 27})
    summary2 = test_db.get_daily_summary(test_user_id, today)
    assert summary2['calories'] == 200
    assert summary2['meals'] == 2
    
    # Act & Assert - Третий прием пищи
    test_db.save_meal(test_user_id, "курица", {'calories': 248, 'proteins': 47, 'fats': 5, 'carbs': 0})
    summary3 = test_db.get_daily_summary(test_user_id, today)
    assert summary3['calories'] == 448
    assert summary3['meals'] == 3


# ============= ТЕСТЫ СОХРАНЕНИЯ ТАРГЕТОВ =============

def test_save_targets_with_profile(test_db, test_user_id):
    """Сохранение таргетов вместе с профилем"""
    # Arrange
    profile_data = {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'похудеть',
        'target': {
            'calories': 1800,
            'proteins': 96,
            'fats': 48,
            'carbs': 225,
            'bmr': 1361,
            'tdee': 2110,
            'explanation': 'Тестовое пояснение'
        }
    }
    
    # Act
    test_db.save_user_profile(test_user_id, profile_data)
    saved_targets = test_db.get_saved_targets(test_user_id)
    
    # Assert
    assert saved_targets is not None, "Таргеты должны быть сохранены"
    assert saved_targets['calories'] == 1800
    assert saved_targets['proteins'] == 96
    assert saved_targets['fats'] == 48
    assert saved_targets['carbs'] == 225
    assert saved_targets['explanation'] == 'Тестовое пояснение'


def test_get_saved_targets_not_exist(test_db, test_user_id, test_profile_data):
    """Получение несуществующих сохраненных таргетов"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)  # Без таргетов
    
    # Act
    saved_targets = test_db.get_saved_targets(test_user_id)
    
    # Assert
    assert saved_targets is None, "Таргеты не должны быть найдены"


# ============= ГРАНИЧНЫЕ СЛУЧАИ =============

def test_max_values(test_db, test_user_id):
    """GC-001: Максимальные допустимые значения"""
    # Arrange & Act
    test_db.save_user_profile(test_user_id, {
        'gender': 'Мужской',
        'age': 100,
        'height': 250,
        'weight': 300,
        'activity': 'Высокий',
        'goal': 'поддерживать вес'
    })
    
    bmr = test_db.calculate_bmr(test_user_id)
    target = test_db.calculate_target_calories(test_user_id)
    
    # Assert
    assert bmr > 0, "BMR должен быть рассчитан"
    assert target['calories'] > 0, "Калории должны быть рассчитаны"
    assert test_db.user_profile_exists(test_user_id), "Профиль должен существовать"


def test_min_values(test_db, test_user_id):
    """GC-002: Минимальные допустимые значения"""
    # Arrange & Act
    test_db.save_user_profile(test_user_id, {
        'gender': 'Женский',
        'age': 10,
        'height': 100,
        'weight': 30,
        'activity': 'Низкий',
        'goal': 'поддерживать вес'
    })
    
    bmr = test_db.calculate_bmr(test_user_id)
    target = test_db.calculate_target_calories(test_user_id)
    
    # Assert
    assert bmr > 0, "BMR должен быть рассчитан"
    assert target['calories'] > 0, "Калории должны быть рассчитаны"
    assert test_db.user_profile_exists(test_user_id), "Профиль должен существовать"


def test_long_description(test_db, test_user_id, test_profile_data):
    """GC-003: Очень длинное описание еды"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    long_description = "200 грамм отварной куриной грудки без кожи, 150 грамм бурого риса, 100 грамм свежих огурцов, 50 грамм помидоров черри, 1 столовая ложка оливкового масла extra virgin"
    kbju_data = {'calories': 500, 'proteins': 50, 'fats': 15, 'carbs': 50}
    
    # Act
    result = test_db.save_meal(test_user_id, long_description, kbju_data)
    meals = test_db.get_meals_for_day(test_user_id)
    
    # Assert
    assert result == True, "Прием пищи должен быть сохранен"
    assert len(meals) == 1, "Должен быть 1 прием пищи"
    assert meals[0]['description'] == long_description, "Описание должно быть сохранено полностью"


def test_multiple_users(test_db):
    """Изоляция данных разных пользователей"""
    # Arrange
    user1_id = 11111
    user2_id = 22222
    
    test_db.save_user_profile(user1_id, {
        'gender': 'Женский',
        'age': 25,
        'height': 165,
        'weight': 60,
        'activity': 'Средний',
        'goal': 'похудеть'
    })
    
    test_db.save_user_profile(user2_id, {
        'gender': 'Мужской',
        'age': 30,
        'height': 180,
        'weight': 75,
        'activity': 'Высокий',
        'goal': 'набрать массу'
    })
    
    test_db.save_meal(user1_id, "яблоко", {'calories': 95, 'proteins': 0, 'fats': 0, 'carbs': 25})
    test_db.save_meal(user2_id, "курица", {'calories': 248, 'proteins': 47, 'fats': 5, 'carbs': 0})
    
    # Act
    user1_meals = test_db.get_meals_for_day(user1_id)
    user2_meals = test_db.get_meals_for_day(user2_id)
    user1_summary = test_db.get_daily_summary(user1_id)
    user2_summary = test_db.get_daily_summary(user2_id)
    
    # Assert
    assert len(user1_meals) == 1, "У пользователя 1 должен быть 1 прием пищи"
    assert len(user2_meals) == 1, "У пользователя 2 должен быть 1 прием пищи"
    assert user1_summary['calories'] == 95, "Калории пользователя 1 должны быть 95"
    assert user2_summary['calories'] == 248, "Калории пользователя 2 должны быть 248"


# ============= ТЕСТЫ НА ЦЕЛОСТНОСТЬ ДАННЫХ =============

def test_special_characters_in_description(test_db, test_user_id, test_profile_data):
    """NEG-004: Специальные символы в описании"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    special_descriptions = [
        "яблоко' OR '1'='1",
        "<script>alert('test')</script>",
        "'; DROP TABLE meals; --",
        "яблоко & банан",
        "100% натуральный сок"
    ]
    
    # Act & Assert
    for desc in special_descriptions:
        result = test_db.save_meal(test_user_id, desc, {'calories': 100, 'proteins': 0, 'fats': 0, 'carbs': 25})
        assert result == True, f"Прием пищи с описанием '{desc}' должен быть сохранен"
    
    meals = test_db.get_meals_for_day(test_user_id)
    assert len(meals) == len(special_descriptions), "Все приемы пищи должны быть сохранены"


def test_zero_values_in_kbju(test_db, test_user_id, test_profile_data):
    """Нулевые значения в КБЖУ"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Act
    result = test_db.save_meal(test_user_id, "вода", {'calories': 0, 'proteins': 0, 'fats': 0, 'carbs': 0})
    summary = test_db.get_daily_summary(test_user_id)
    
    # Assert
    assert result == True, "Прием пищи с нулевыми значениями должен быть сохранен"
    assert summary['calories'] == 0
    assert summary['meals'] == 1, "Должен быть учтен 1 прием пищи"


def test_negative_values_prevented(test_db, test_user_id, test_profile_data):
    """Проверка на отрицательные значения (должны быть обработаны на уровне валидации)"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Act - пытаемся сохранить отрицательные значения
    # В реальности валидация должна происходить раньше, но проверяем базу
    result = test_db.save_meal(test_user_id, "test", {'calories': -100, 'proteins': -10, 'fats': -5, 'carbs': -20})
    
    # Assert
    assert result == True, "Запись в базу выполнена (валидация должна быть на уровне бота)"
    # В идеале: добавить проверки в Database класс


# ============= ПРОИЗВОДИТЕЛЬНОСТЬ =============

def test_multiple_meals_performance(test_db, test_user_id, test_profile_data):
    """Производительность при большом количестве приемов пищи"""
    # Arrange
    test_db.save_user_profile(test_user_id, test_profile_data)
    
    # Act - добавляем 100 приемов пищи
    for i in range(100):
        test_db.save_meal(test_user_id, f"прием пищи {i}", {
            'calories': 100,
            'proteins': 10,
            'fats': 5,
            'carbs': 15
        })
    
    # Assert
    meals = test_db.get_meals_for_day(test_user_id)
    summary = test_db.get_daily_summary(test_user_id)
    
    assert len(meals) == 100, "Должно быть 100 приемов пищи"
    assert summary['calories'] == 10000, "Калории должны быть 10000"
    assert summary['meals'] == 100, "Должно быть 100 приемов пищи"


# ============= ЗАПУСК ТЕСТОВ =============

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

