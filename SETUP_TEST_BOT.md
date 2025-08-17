# 🧪 Настройка тестового бота

## ✅ Токен получен:
```
8267210378:AAE6Esz6tJFPe5wI5wbtwgL1asqEztsqVnw
```

## 📝 Настройка переменных окружения:

### 1. Откройте файл `.env` и добавьте:
```bash
# Тестовый бот
TEST_TELEGRAM_BOT_TOKEN=8267210378:AAE6Esz6tJFPe5wI5wbtwgL1asqEztsqVnw

# Режим работы (test/production)
BOT_MODE=test
```

### 2. Или установите переменные в терминале:
```bash
export TEST_TELEGRAM_BOT_TOKEN=8267210378:AAE6Esz6tJFPe5wI5wbtwgL1asqEztsqVnw
export BOT_MODE=test
```

## 🚀 Запуск тестового бота:

### Локально:
```bash
python3 test_bot.py
```

### В Railway (отдельный проект):
1. Создайте новый проект в Railway
2. Подключите репозиторий
3. Настройте переменные окружения:
   - `TEST_TELEGRAM_BOT_TOKEN=8267210378:AAE6Esz6tJFPe5wI5wbtwgL1asqEztsqVnw`
   - `OPENAI_API_KEY=ваш_openai_ключ`
   - `BOT_MODE=test`

## 🧪 Тестовые команды:

После запуска тестового бота используйте:
- `/start` - приветствие с префиксом "🧪 ТЕСТ:"
- `/test` - список тестовых команд
- `/test_profile` - быстрая настройка профиля
- `/clear_data` - очистка тестовых данных
- `/status` - статус бота

## 🔄 Workflow разработки:

1. **Разработка** → ветка `develop`
2. **Тестирование** → тестовый бот
3. **Релиз** → ветка `main` → продакшн бот

## 📱 Найти тестового бота:
Поищите в Telegram по username, который вы указали при создании бота. 