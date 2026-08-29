import os
import asyncio
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage


TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 7714575966
CHANNEL_ID = -1002358647162

if not TOKEN:
    raise RuntimeError("BOT_TOKEN not found")


bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_FILE = "books.db"


# =====================================================
# DATABASE
# =====================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            file_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            book_id INTEGER,
            UNIQUE(user_id, book_id)
        )
    """)

    conn.commit()
    conn.close()


def add_book(title, author, category, description, file_id):
    conn = db()

    cur = conn.execute(
        """
        INSERT INTO books
        (title, author, category, description, file_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            author,
            category,
            description,
            file_id,
        ),
    )

    book_id = cur.lastrowid

    conn.commit()
    conn.close()

    return book_id


def get_books():
    conn = db()

    rows = conn.execute(
        """
        SELECT id, title, author, category
        FROM books
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return rows


def get_book(book_id):
    conn = db()

    row = conn.execute(
        """
        SELECT id, title, author, category, description, file_id
        FROM books
        WHERE id = ?
        """,
        (book_id,),
    ).fetchone()

    conn.close()

    return row


def search_books(text):
    conn = db()

    rows = conn.execute(
        """
        SELECT id, title, author, category
        FROM books
        WHERE title LIKE ?
        OR author LIKE ?
        ORDER BY id DESC
        """,
        (
            f"%{text}%",
            f"%{text}%",
        ),
    ).fetchall()

    conn.close()

    return rows


def category_books(category):
    conn = db()

    rows = conn.execute(
        """
        SELECT id, title, author, category
        FROM books
        WHERE category = ?
        ORDER BY id DESC
        """,
        (category,),
    ).fetchall()

    conn.close()

    return rows


def add_favorite(user_id, book_id):
    conn = db()

    conn.execute(
        """
        INSERT OR IGNORE INTO favorites
        (user_id, book_id)
        VALUES (?, ?)
        """,
        (user_id, book_id),
    )

    conn.commit()
    conn.close()


def get_favorites(user_id):
    conn = db()

    rows = conn.execute(
        """
        SELECT books.id, books.title,
               books.author, books.category
        FROM books
        JOIN favorites
        ON books.id = favorites.book_id
        WHERE favorites.user_id = ?
        ORDER BY books.id DESC
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    return rows


# =====================================================
# STATES
# =====================================================

class SearchState(StatesGroup):
    waiting = State()


# =====================================================
# MENUS
# =====================================================

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📚 Каталог",
                    callback_data="catalog"
                ),
                InlineKeyboardButton(
                    text="🔎 Поиск",
                    callback_data="search"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🆕 Новинки",
                    callback_data="new"
                ),
                InlineKeyboardButton(
                    text="📂 Категории",
                    callback_data="categories"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Избранное",
                    callback_data="favorites"
                ),
                InlineKeyboardButton(
                    text="ℹ️ О библиотеке",
                    callback_data="about"
                ),
            ],
        ]
    )


def back_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="home"
                )
            ]
        ]
    )


def categories_menu():
    names = [
        "Акыда",
        "Фикх",
        "Хадисы",
        "Тафсир",
        "Сира",
        "Манхадж",
        "Арабский язык",
    ]

    buttons = []

    for name in names:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📂 {name}",
                    callback_data=f"category:{name}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="home"
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def book_menu(book_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Скачать PDF",
                    callback_data=f"download:{book_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ В избранное",
                    callback_data=f"favorite:{book_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Каталог",
                    callback_data="catalog"
                )
            ],
        ]
    )


# =====================================================
# START
# =====================================================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую библиотеку!\n\n"
        "Выберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =====================================================
# ADMIN
# =====================================================

@dp.message(Command("admin"))
async def admin(message: Message):

    if message.from_user.id != ADMIN_ID:
        await message.answer(
            "⛔ Доступ запрещён."
        )
        return

    await message.answer(
        "👑 Панель администратора\n\n"
        "Книги добавляются автоматически "
        "через твой частный канал."
    )


# =====================================================
# CHANNEL
# =====================================================

@dp.channel_post()
async def channel_post(message: Message):

    if message.chat.id != CHANNEL_ID:
        return

    # PDF должен быть документом
    if not message.document:
        return

    file_name = message.document.file_name or ""

    if not file_name.lower().endswith(".pdf"):
        return

    # Текст подписи
    text = message.caption or ""

    title = "Без названия"
    author = "Не указан"
    category = "Без категории"
    description = ""

    lines = text.splitlines()

    for line in lines:

        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip().lower()
        value = value.strip()

        if key == "название":
            title = value

        elif key == "автор":
            author = value

        elif key == "категория":
            category = value

        elif key == "описание":
            description = value

    book_id = add_book(
        title=title,
        author=author,
        category=category,
        description=description,
        file_id=message.document.file_id
    )

    print(
        f"NEW BOOK: {book_id} | {title}"
    )


# =====================================================
# CATALOG
# =====================================================

@dp.callback_query(F.data == "catalog")
async def catalog(callback: CallbackQuery):

    books = get_books()

    if not books:

        await callback.message.edit_text(
            "📚 <b>Каталог</b>\n\n"
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=back_menu()
        )

        await callback.answer()
        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📖 {title}",
                    callback_data=f"book:{book_id}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="home"
            )
        ]
    )

    await callback.message.edit_text(
        "📚 <b>Каталог</b>\n\n"
        "Выберите книгу:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =====================================================
# BOOK
# =====================================================

@dp.callback_query(F.data.startswith("book:"))
async def show_book(callback: CallbackQuery):

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(book_id)

    if not book:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )
        return

    (
        book_id,
        title,
        author,
        category,
        description,
        file_id
    ) = book

    text = (
        f"📖 <b>{title}</b>\n\n"
        f"✍️ Автор: {author}\n"
        f"📂 Категория: {category}\n"
    )

    if description:
        text += f"\n📝 {description}"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=book_menu(book_id)
    )

    await callback.answer()


# =====================================================
# DOWNLOAD
# =====================================================

@dp.callback_query(F.data.startswith("download:"))
async def download(callback: CallbackQuery):

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(book_id)

    if not book:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )
        return

    file_id = book[5]

    await callback.message.answer_document(
        document=file_id,
        caption=(
            f"📖 {book[1]}\n"
            f"✍️ {book[2]}"
        )
    )

    await callback.answer()


# =====================================================
# FAVORITE
# =====================================================

@dp.callback_query(F.data.startswith("favorite:"))
async def favorite(callback: CallbackQuery):

    book_id = int(
        callback.data.split(":")[1]
    )

    add_favorite(
        callback.from_user.id,
        book_id
    )

    await callback.answer(
        "⭐ Добавлено в избранное!"
    )


# =====================================================
# SEARCH
# =====================================================

@dp.callback_query(F.data == "search")
async def search_start(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.set_state(
        SearchState.waiting
    )

    await callback.message.answer(
        "🔎 Напиши название книги "
        "или имя автора:"
    )

    await callback.answer()


@dp.message(SearchState.waiting)
async def search_result(
    message: Message,
    state: FSMContext
):

    results = search_books(
        message.text
    )

    await state.clear()

    if not results:

        await message.answer(
            "❌ Ничего не найдено.",
            reply_markup=main_menu()
        )

        return

    buttons = []

    for book_id, title, author, category in results:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📖 {title}",
                    callback_data=f"book:{book_id}"
                )
            ]
        )

    await message.answer(
        "🔎 <b>Результаты поиска:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =====================================================
# CATEGORIES
# =====================================================

@dp.callback_query(F.data == "categories")
async def categories(callback: CallbackQuery):

    await callback.message.edit_text(
        "📂 <b>Категории</b>\n\n"
        "Выберите категорию:",
        parse_mode="HTML",
        reply_markup=categories_menu()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("category:"))
async def category(callback: CallbackQuery):

    category_name = callback.data.split(
        ":", 1
    )[1]

    books = category_books(
        category_name
    )

    if not books:

        await callback.message.edit_text(
            f"📂 <b>{category_name}</b>\n\n"
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=categories_menu()
        )

        await callback.answer()
        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📖 {title}",
                    callback_data=f"book:{book_id}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Категории",
                callback_data="categories"
            )
        ]
    )

    await callback.message.edit_text(
        f"📂 <b>{category_name}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =====================================================
# NEW BOOKS
# =====================================================

@dp.callback_query(F.data == "new")
async def new_books(callback: CallbackQuery):

    books = get_books()[:10]

    if not books:

        await callback.message.edit_text(
            "🆕 Новинок пока нет.",
            reply_markup=back_menu()
        )

        await callback.answer()
        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📖 {title}",
                    callback_data=f"book:{book_id}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="home"
            )
        ]
    )

    await callback.message.edit_text(
        "🆕 <b>Последние книги</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =====================================================
# FAVORITES
# =====================================================

@dp.callback_query(F.data == "favorites")
async def favorites(callback: CallbackQuery):

    books = get_favorites(
        callback.from_user.id
    )

    if not books:

        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "Здесь пока ничего нет.",
            parse_mode="HTML",
            reply_markup=back_menu()
        )

        await callback.answer()
        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📖 {title}",
                    callback_data=f"book:{book_id}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="home"
            )
        ]
    )

    await callback.message.edit_text(
        "⭐ <b>Избранное</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =====================================================
# ABOUT
# =====================================================

@dp.callback_query(F.data == "about")
async def about(callback: CallbackQuery):

    await callback.message.edit_text(
        "ℹ️ <b>Rauda Ilm</b>\n\n"
        "Электронная библиотека исламских книг.\n\n"
        "📚 Каталог\n"
        "🔎 Поиск\n"
        "📂 Категории\n"
        "⭐ Избранное",
        parse_mode="HTML",
        reply_markup=back_menu()
    )

    await callback.answer()


# =====================================================
# HOME
# =====================================================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):

    await callback.message.edit_text(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer()


# =====================================================
# RENDER HTTP SERVER
# =====================================================

async def health(request):
    return web.Response(text="OK")


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/healthz",
        health
    )

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        f"HTTP server started on port {port}"
    )


# =====================================================
# START
# =====================================================

async def main():

    init_db()

    await start_web_server()

    print(
        "Rauda Ilm bot started!"
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
