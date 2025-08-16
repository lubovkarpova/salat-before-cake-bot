import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

@router.message(Command("start", "help"))
async def send_welcome(message: Message):
    await message.answer("Привет! Я бот для учёта КБЖУ и советов по питанию. Напиши /profile чтобы начать!")

dp.include_router(router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())