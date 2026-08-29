import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "📚 Добро пожаловать в библиотеку Rauda Ilm!\n\n"
        "Здесь будут собраны книги.\n\n"
        "📚 Каталог — скоро\n"
        "🔎 Поиск — скоро\n"
        "🆕 Новинки — скоро"
    )


@dp.message()
async def message_handler(message: types.Message):
    await message.answer(
        "📚 Я получил твоё сообщение.\n"
        "Библиотека Rauda Ilm скоро будет готова!"
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
