import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7714575966

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu():
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


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить книгу", callback_data="add_book")
            ],
            [
                InlineKeyboardButton(text="📚 Все книги", callback_data="admin_books"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Главное меню", callback_data="home")
            ],
        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: types.Message):
    text = (
        "📚 <b>Rauda Ilm</b>\n"
        "Исламская библиотека\n\n"
        "Добро пожаловать!\n"
        "Выберите нужный раздел:"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================

@dp.callback_query(F.data == "home")
async def home(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 <b>Rauda Ilm</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    await callback.answer()


# =========================
# КАТАЛОГ
# =========================

@dp.callback_query(F.data == "catalog")
async def catalog(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 <b>Каталог</b>\n\n"
        "Пока библиотека пуста.\n\n"
        "Скоро здесь появятся книги.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# ПОИСК
# =========================

@dp.callback_query(F.data == "search")
async def search(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔎 <b>Поиск книг</b>\n\n"
        "Функция поиска будет подключена следующим этапом.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# НОВИНКИ
# =========================

@dp.callback_query(F.data == "new")
async def new_books(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🆕 <b>Новые книги</b>\n\n"
        "Пока новых книг нет.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# КАТЕГОРИИ
# =========================

@dp.callback_query(F.data == "categories")
async def categories(callback: types.CallbackQuery):
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# ИЗБРАННОЕ
# =========================

@dp.callback_query(F.data == "favorites")
async def favorites(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⭐ <b>Избранное</b>\n\n"
        "Здесь будут сохранённые пользователем книги.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# О БИБЛИОТЕКЕ
# =========================

@dp.callback_query(F.data == "about")
async def about(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ <b>О библиотеке</b>\n\n"
        "Rauda Ilm — электронная библиотека исламских книг.\n\n"
        "📚 Книги\n"
        "🔎 Поиск\n"
        "📂 Категории\n"
        "⭐ Избранное",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# =========================
# АДМИН-ПАНЕЛЬ
# =========================

@dp.message(Command("admin"))
async def admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await
