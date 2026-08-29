import os
import sqlite3
import asyncio

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage


# ============================================================
# НАСТРОЙКИ
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

# ТВОЙ Telegram ID
ADMIN_ID = 7714575966

# ID частного канала
CHANNEL_ID = -1002358647162

# Порт Render
PORT = int(os.getenv("PORT", "10000"))

# Адрес Render
RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://rauda-ilm-books-bot.onrender.com"
)

# Webhook
WEBHOOK_PATH = "/telegram/webhook"

WEBHOOK_URL = (
    RENDER_URL.rstrip("/")
    + WEBHOOK_PATH
)


if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден в Render Environment Variables"
    )


# ============================================================
# BOT
# ============================================================

bot = Bot(
    token=TOKEN
)

dp = Dispatcher(
    storage=MemoryStorage()
)


# ============================================================
# DATABASE
# ============================================================

DB_FILE = "books.db"


def get_db():
    return sqlite3.connect(DB_FILE)


def init_db():

    conn = get_db()

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
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            UNIQUE(user_id, book_id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# BOOK FUNCTIONS
# ============================================================

def add_book(
    title,
    author,
    category,
    description,
    file_id
):

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO books
        (
            title,
            author,
            category,
            description,
            file_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            author,
            category,
            description,
            file_id
        )
    )

    book_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return book_id


def get_books():

    conn = get_db()

    books = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category
        FROM books
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return books


def get_book(book_id):

    conn = get_db()

    book = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category,
            description,
            file_id
        FROM books
        WHERE id = ?
        """,
        (book_id,)
    ).fetchone()

    conn.close()

    return book


def delete_book(book_id):

    conn = get_db()

    # Сначала удаляем из избранного
    conn.execute(
        """
        DELETE FROM favorites
        WHERE book_id = ?
        """,
        (book_id,)
    )

    # Затем удаляем книгу
    conn.execute(
        """
        DELETE FROM books
        WHERE id = ?
        """,
        (book_id,)
    )

    conn.commit()
    conn.close()


def search_books(text):

    conn = get_db()

    books = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category
        FROM books
        WHERE title LIKE ?
           OR author LIKE ?
           OR category LIKE ?
        ORDER BY id DESC
        """,
        (
            f"%{text}%",
            f"%{text}%",
            f"%{text}%"
        )
    ).fetchall()

    conn.close()

    return books


def category_books(category):

    conn = get_db()

    books = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category
        FROM books
        WHERE category = ?
        ORDER BY id DESC
        """,
        (category,)
    ).fetchall()

    conn.close()

    return books


# ============================================================
# FAVORITES
# ============================================================

def add_favorite(
    user_id,
    book_id
):

    conn = get_db()

    conn.execute(
        """
        INSERT OR IGNORE INTO favorites
        (
            user_id,
            book_id
        )
        VALUES (?, ?)
        """,
        (
            user_id,
            book_id
        )
    )

    conn.commit()
    conn.close()


def remove_favorite(
    user_id,
    book_id
):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM favorites
        WHERE user_id = ?
          AND book_id = ?
        """,
        (
            user_id,
            book_id
        )
    )

    conn.commit()
    conn.close()


def is_favorite(
    user_id,
    book_id
):

    conn = get_db()

    result = conn.execute(
        """
        SELECT 1
        FROM favorites
        WHERE user_id = ?
          AND book_id = ?
        LIMIT 1
        """,
        (
            user_id,
            book_id
        )
    ).fetchone()

    conn.close()

    return result is not None


def get_favorites(user_id):

    conn = get_db()

    books = conn.execute(
        """
        SELECT
            books.id,
            books.title,
            books.author,
            books.category
        FROM books
        INNER JOIN favorites
            ON books.id = favorites.book_id
        WHERE favorites.user_id = ?
        ORDER BY books.id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return books


# ============================================================
# SEARCH STATE
# ============================================================

class SearchState(StatesGroup):

    waiting = State()


# ============================================================
# MAIN MENU
# ============================================================

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
                )
            ],

            [
                InlineKeyboardButton(
                    text="🆕 Новинки",
                    callback_data="new"
                ),

                InlineKeyboardButton(
                    text="📂 Категории",
                    callback_data="categories"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⭐ Избранное",
                    callback_data="favorites"
                ),

                InlineKeyboardButton(
                    text="ℹ️ О библиотеке",
                    callback_data="about"
                )
            ]

        ]
    )


def back_home():

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


# ============================================================
# BOOK MENU
# ============================================================

def book_menu(
    book_id,
    user_id
):

    buttons = [

        [
            InlineKeyboardButton(
                text="📥 Скачать PDF",
                callback_data=f"download:{book_id}"
            )
        ]

    ]

    # Избранное
    if is_favorite(
        user_id,
        book_id
    ):

        buttons.append(

            [
                InlineKeyboardButton(
                    text="❌ Убрать из избранного",
                    callback_data=f"unfavorite:{book_id}"
                )
            ]

        )

    else:

        buttons.append(

            [
                InlineKeyboardButton(
                    text="⭐ В избранное",
                    callback_data=f"favorite:{book_id}"
                )
            ]

        )

    # Кнопка удаления только для владельца
    if user_id == ADMIN_ID:

        buttons.append(

            [
                InlineKeyboardButton(
                    text="🗑 Удалить книгу",
                    callback_data=f"delete:{book_id}"
                )
            ]

        )

    buttons.append(

        [
            InlineKeyboardButton(
                text="⬅️ Каталог",
                callback_data="catalog"
            )
        ]

    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(
    message: Message
):

    await message.answer(

        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.\n\n"
        "Выберите нужный раздел:",

        parse_mode="HTML",

        reply_markup=main_menu()
    )


# ============================================================
# PDF FROM PRIVATE CHANNEL
# ============================================================

@dp.channel_post()
async def channel_pdf(
    message: Message
):

    # Проверяем канал
    if message.chat.id != CHANNEL_ID:
        return

    # Проверяем наличие документа
    if not message.document:
        return

    document = message.document

    file_name = (
        document.file_name or ""
    )

    # Только PDF
    if not file_name.lower().endswith(
        ".pdf"
    ):

        print(
            "Получен документ, но это не PDF:",
            file_name
        )

        return

    caption = (
        message.caption or ""
    )

    # Значения по умолчанию
    title = file_name.rsplit(
        ".",
        1
    )[0]

    author = "Не указан"

    category = "Без категории"

    description = ""

    # Читаем подпись
    for line in caption.splitlines():

        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1
        )

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

    # Добавляем книгу
    book_id = add_book(

        title=title,

        author=author,

        category=category,

        description=description,

        file_id=document.file_id

    )

    print(
        f"BOOK ADDED: {book_id} | {title}"
    )


# ============================================================
# CATALOG
# ============================================================

@dp.callback_query(
    F.data == "catalog"
)
async def catalog(
    callback: CallbackQuery
):

    books = get_books()

    if not books:

        await callback.message.edit_text(

            "📚 <b>Каталог</b>\n\n"
            "Книг пока нет.\n\n"
            "Добавьте PDF в частный канал.",

            parse_mode="HTML",

            reply_markup=back_home()
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


# ============================================================
# SHOW BOOK
# ============================================================

@dp.callback_query(
    F.data.startswith("book:")
)
async def show_book(
    callback: CallbackQuery
):

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

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

        f"📂 Категория: {category}"

    )

    if description:

        text += (
            f"\n\n📝 {description}"
        )

    await callback.message.edit_text(

        text,

        parse_mode="HTML",

        reply_markup=book_menu(

            book_id,

            callback.from_user.id

        )

    )

    await callback.answer()


# ============================================================
# DOWNLOAD PDF
# ============================================================

@dp.callback_query(
    F.data.startswith("download:")
)
async def download(
    callback: CallbackQuery
):

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(

            "Книга не найдена.",

            show_alert=True

        )

        return

    file_id = book[5]

    try:

        await callback.message.answer_document(

            document=file_id,

            caption=(

                f"📖 <b>{book[1]}</b>\n"
                f"✍️ {book[2]}"

            ),

            parse_mode="HTML"

        )

        await callback.answer()

    except Exception as e:

        print(
            "PDF SEND ERROR:",
            repr(e)
        )

        await callback.answer(

            "❌ Не удалось отправить PDF.",

            show_alert=True

        )


# ============================================================
# ADD FAVORITE
# ============================================================

@dp.callback_query(
    F.data.startswith("favorite:")
)
async def favorite(
    callback: CallbackQuery
):

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(

            "Книга не найдена.",

            show_alert=True

        )

        return

    add_favorite(

        callback.from_user.id,

        book_id

    )

    await callback.message.edit_reply_markup(

        reply_markup=book_menu(

            book_id,

            callback.from_user.id

        )

    )

    await callback.answer(
        "⭐ Добавлено в избранное!"
    )


# ============================================================
# REMOVE FAVORITE
# ============================================================

@dp.callback_query(
    F.data.startswith("unfavorite:")
)
async def unfavorite(
    callback: CallbackQuery
):

    book_id = int(
        callback.data.split(":")[1]
    )

    remove_favorite(

        callback.from_user.id,

        book_id

    )

    await callback.message.edit_reply_markup(

        reply_markup=book_menu(

            book_id,

            callback.from_user.id

        )

    )

    await callback.answer(
        "❌ Убрано из избранного."
    )


# ============================================================
# DELETE — CONFIRMATION
# ============================================================

@dp.callback_query(
    F.data.startswith("delete:")
)
async def delete_book_callback(
    callback: CallbackQuery
):

    # Только владелец
    if callback.from_user.id != ADMIN_ID:

        await callback.answer(

            "⛔ У вас нет доступа.",

            show_alert=True

        )

        return

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(

            "Книга уже удалена.",

            show_alert=True

        )

        return

    title = book[1]

    keyboard = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="✅ Да, удалить",

                    callback_data=(
                        f"confirm_delete:{book_id}"
                    )

                )

            ],

            [

                InlineKeyboardButton(

                    text="❌ Отмена",

                    callback_data=(
                        f"cancel_delete:{book_id}"
                    )

                )

            ]

        ]

    )

    await callback.message.edit_text(

        "⚠️ <b>Удалить книгу?</b>\n\n"

        f"📖 <b>{title}</b>\n\n"

        "Книга будет удалена из каталога "
        "и из избранного пользователей.\n\n"

        "📌 Сам PDF в частном канале "
        "останется.",

        parse_mode="HTML",

        reply_markup=keyboard

    )

    await callback.answer()


# ============================================================
# CONFIRM DELETE
# ============================================================

@dp.callback_query(
    F.data.startswith("confirm_delete:")
)
async def confirm_delete(
    callback: CallbackQuery
):

    # Только владелец
    if callback.from_user.id != ADMIN_ID:

        await callback.answer(

            "⛔ У вас нет доступа.",

            show_alert=True

        )

        return

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(

            "Книга уже удалена.",

            show_alert=True

        )

        return

    title = book[1]

    delete_book(
        book_id
    )

    await callback.message.edit_text(

        "✅ <b>Книга удалена</b>\n\n"

        f"📖 {title}\n\n"

        "Книга удалена из каталога "
        "и из избранного пользователей.\n\n"

        "📌 PDF в частном канале "
        "не удалён.",

        parse_mode="HTML",

        reply_markup=back_home()

    )

    await callback.answer(
        "Книга удалена."
    )


# ============================================================
# CANCEL DELETE
# ============================================================

@dp.callback_query(
    F.data.startswith("cancel_delete:")
)
async def cancel_delete(
    callback: CallbackQuery
):

    # Только владелец
    if callback.from_user.id != ADMIN_ID:

        await callback.answer(

            "⛔ У вас нет доступа.",

            show_alert=True

        )

        return

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(
        book_id
    )

    if not book:

        await callback.message.edit_text(

            "❌ Книга не найдена.",

            reply_markup=back_home()

        )

        await callback.answer()

        return

    await callback.message.edit_text(

        f"📖 <b>{book[1]}</b>\n\n"
        "Удаление отменено.",

        parse_mode="HTML",

        reply_markup=book_menu(

            book_id,

            callback.from_user.id

        )

    )

    await callback.answer(
        "Удаление отменено."
    )


# ====
