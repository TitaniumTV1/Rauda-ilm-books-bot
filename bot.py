import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7714575966

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Каталог", callback_data="catalog"),
                InlineKeyboardButton(text="🔎 Поиск", callback_data="search"),
            ],
            [
                InlineKeyboardButton(text="🆕 Новинки", callback_data="new"),
                InlineKeyboardButton(text="📂 Категории", callback_data="categories"),
            ],
            [
                InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites"),
                InlineKeyboardButton(text="ℹ️ О библиотеке", callback_data="about"),
            ],
        ]
    )


def back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить книгу", callback_data="add_book")],
            [InlineKeyboardButton(text="📚 Все книги", callback_data="admin_books")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="home")],
        ]
    )


@dp.message(CommandStart())
async def start(message):
    await message.answer(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую библиотеку!\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=menu()
    )


@dp.message(Command("admin"))
async def admin(message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "👑 <b>Панель администратора</b>",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


@dp.callback_query(F.data == "home")
async def home(callback):
    await callback.message.edit_text(
        "📚 <b>Rauda Ilm</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "catalog")
async def catalog(callback):
    await callback.message.edit_text(
        "📚 <b>Каталог</b>\n\n"
        "Библиотека пока пуста.\n"
        "Скоро здесь появятся книги.",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "search")
async def search(callback):
    await callback.message.edit_text(
        "🔎 <b>Поиск</b>\n\n"
        "Поиск книг подключим следующим этапом.",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "new")
async def new_books(callback):
    await callback.message.edit_text(
        "🆕 <b>Новинки</b>\n\n"
        "Новых книг пока нет.",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "categories")
async def categories(callback):
    await callback.message.edit_text(
        "📂 <b>Категории</b>\n\n"
        "🕌 Акыда\n"
        "📖 Тафсир\n"
        "📜 Хадисы\n"
        "⚖️ Фикх\n"
        "👤 Сира\n"
        "📚 Манхадж\n"
        "🗣 Арабский язык",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "favorites")
async def favorites(callback):
    await callback.message.edit_text(
        "⭐ <b>Избранное</b>\n\n"
        "Раздел пока пуст.",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "about")
async def about(callback):
    await callback.message.edit_text(
        "ℹ️ <b>О библиотеке</b>\n\n"
        "Rauda Ilm — электронная библиотека исламских книг.",
        parse_mode="HTML",
        reply_markup=back_button()
    )
    await callback.answer()


@dp.callback_query(F.data == "add_book")
async def add_book(callback):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.message.answer(
        "➕ Добавление книг подключим следующим этапом."
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_books")
async def admin_books(callback):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.message.answer("📚 Книг пока нет.")
    await callback.answer()


@dp.callback_query(F.data == "stats
