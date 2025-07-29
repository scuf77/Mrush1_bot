import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram import F
from webserver import app
from threading import Thread

TOKEN = "твой_токен"

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer("Привет!")

@dp.message(F.text)
async def handle_text(message: Message):
    await message.answer("Ты написал: " + message.text)

def run_web():
    app.run(host="0.0.0.0", port=10000)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем фейковый веб-сервер параллельно с ботом
    Thread(target=run_web).start()
    asyncio.run(main())
