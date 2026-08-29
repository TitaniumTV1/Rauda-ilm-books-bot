import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Environment Variables")

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "📚 Добро пожаловать в библиотеку Rauda Ilm!\n\n"
        "Здесь будет собрана библиотека исламских книг."
    )


@dp.message()
async def message_handler(message: types.Message):
    await message.answer(
        "📚 Библиотека Rauda Ilm\n\n"
        "Функции библиотеки скоро будут доступны."
    )


async def health(request):
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"HTTP server started on port {port}")


async def main():
    await start_web_server()

    print("Telegram bot started!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
