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

ADMIN_ID = 7714575966

CHANNEL_ID = -1002358647162

PORT = int(os.getenv("PORT", "10000"))

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://rauda-ilm-books-bot.onrender.com"
)

WEBHOOK_PATH = "/telegram/webhook"

WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH

DB_FILE = "books.db"


if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден в Environment Variables"
    )


# ============================================================
# BOT
# ============================================================

bot = Bot(TOKEN)

dp = Dispatcher(
    storage=MemoryStorage()
)


# ============================================================
# DATABASE
# ============================================================

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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            file_id TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# BOOKS
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


def delete_book(book_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM favorites
        WHERE book_id = ?
        """,
        (book_id,)
    )

    conn.execute(
        """
        DELETE FROM books
        WHERE id = ?
        """,
        (book_id,)
    )

    conn.commit()
    conn.close()


# ============================================================
# FAVORITES
# ============================================================

def add_favorite(user_id, book_id):

    conn = get_db()

    conn.execute(
        """
        INSERT OR IGNORE INTO favorites
        (user_id, book_id)
        VALUES (?, ?)
        """,
        (user_id, book_id)
    )

    conn.commit()
    conn.close()


def remove_favorite(user_id, book_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM favorites
        WHERE user_id = ?
        AND book_id = ?
        """,
        (user_id, book_id)
    )

    conn.commit()
    conn.close()


def is_favorite(user_id, book_id):

    conn = get_db()

    result = conn.execute(
        """
        SELECT 1
        FROM favorites
        WHERE user_id = ?
        AND book_id = ?
        LIMIT 1
        """,
        (user_id, book_id)
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
# PENDING BOOKS
# ============================================================

def add_pending(
    user_id,
    username,
    file_id,
    file_name
):

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO pending_books
        (
            user_id,
            username,
            file_id,
            file_name
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            file_id,
            file_name
        )
    )

    pending_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return pending_id


def get_pending(pending_id):

    conn = get_db()

    result = conn.execute(
        """
        SELECT
            id,
            user_id,
            username,
            file_id,
            file_name
        FROM pending_books
        WHERE id = ?
        """,
        (pending_id,)
    ).fetchone()

    conn.close()

    return result


def delete_pending(pending_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM pending_books
        WHERE id = ?
        """,
        (pending_id,)
    )

    conn.commit()
    conn.close()


# ============================================================
# CATEGORIES
# ============================================================

CATEGORIES = [
    "📖 Акыда",
    "🕌 Фикх",
    "📚 Хадисы",
    "📜 Тафсир",
    "🌙 Сирa",
    "🗣 Арабский язык",
    "👨‍👩‍👧 Семья",
    "👶 Дети",
    "📕 Разное",
]


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():

    buttons = [
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
                text="📤 Предложить книгу",
                callback_data="suggest"
            )
        ],
        [
            InlineKeyboardButton(
                text="ℹ️ О библиотеке",
                callback_data="about"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def home_button():

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


def book_menu(book_id, user_id):

    buttons = [
        [
            InlineKeyboardButton(
                text="📥 Скачать PDF",
                callback_data=f"download:{book_id}"
            )
        ]
    ]

    if is_favorite(user_id, book_id):

        buttons.append([
            InlineKeyboardButton(
                text="❌ Убрать из избранного",
                callback_data=f"unfavorite:{book_id}"
            )
        ])

    else:

        buttons.append([
            InlineKeyboardButton(
                text="⭐ В избранное",
                callback_data=f"favorite:{book_id}"
            )
        ])

    if user_id == ADMIN_ID:

        buttons.append([
            InlineKeyboardButton(
                text="🗑 Удалить книгу",
                callback_data=f"delete:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Каталог",
            callback_data="catalog"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# HOME
# ============================================================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):

    await callback.message.edit_text(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer()


# ============================================================
# SUGGEST BOOK
# ============================================================

class SuggestState(StatesGroup):
    waiting_file = State()


@dp.callback_query(F.data == "suggest")
async def suggest_book(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.set_state(
        SuggestState.waiting_file
    )

    await callback.message.edit_text(
        "📤 <b>Предложить книгу</b>\n\n"
        "Отправьте мне PDF-файл книги.\n\n"
        "После этого книга попадёт "
        "на модерацию.\n\n"
        "❗ Отправляйте именно файл PDF.",
        parse_mode="HTML",
        reply_markup=home_button()
    )

    await callback.answer()


@dp.message(SuggestState.waiting_file)
async def receive_suggested_book(
    message: Message,
    state: FSMContext
):

    if not message.document:

        await message.answer(
            "❗ Пожалуйста, отправьте книгу именно "
            "как PDF-файл.",
            reply_markup=home_button()
        )

        return

    document = message.document

    file_name = document.file_name or "book.pdf"

    if not file_name.lower().endswith(".pdf"):

        await message.answer(
            "❌ Это не PDF.\n\n"
            "Пожалуйста, отправьте файл с расширением .pdf."
        )

        return

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    pending_id = add_pending(
        user_id=message.from_user.id,
        username=username,
        file_id=document.file_id,
        file_name=file_name
    )

    await state.clear()

    await message.answer(
        "✅ <b>Книга отправлена на модерацию!</b>\n\n"
        "После проверки администратора она "
        "может появиться в каталоге.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    # Отправляем книгу админу
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"approve:{pending_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{pending_id}"
                )
            ]
        ]
    )

    await bot.send_document(
        ADMIN_ID,
        document=document.file_id,
        caption=(
            "📥 <b>Новая книга на модерации</b>\n\n"
            f"🆔 Заявка: {pending_id}\n"
            f"👤 Отправитель: {username}\n"
            f"📄 Файл: {file_name}"
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# ADMIN APPROVE
# ============================================================

@dp.callback_query(
    F.data.startswith("approve:")
)
async def approve_book(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    pending_id = int(
        callback.data.split(":")[1]
    )

    pending = get_pending(pending_id)

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=category,
                    callback_data=f"setcat:{pending_id}:{i}"
                )
            ]
            for i, category in enumerate(CATEGORIES)
        ]
    )

    await callback.message.answer(
        "📂 <b>Выберите раздел для книги:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


# ============================================================
# SET CATEGORY
# ============================================================

@dp.callback_query(
    F.data.startswith("setcat:")
)
async def set_category(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    _, pending_id, category_index = callback.data.split(":")

    pending_id = int(pending_id)
    category_index = int(category_index)

    pending = get_pending(pending_id)

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    category = CATEGORIES[category_index]

    file_name = pending[4]

    title = os.path.splitext(file_name)[0]

    author = "Не указан"

    description = ""

    # Добавляем книгу
    book_id = add_book(
        title=title,
        author=author,
        category=category,
        description=description,
        file_id=pending[3]
    )

    user_id = pending[1]

    delete_pending(pending_id)

    # Уведомляем пользователя
    try:

        await bot.send_message(
            user_id,
            "🎉 <b>Ваша книга одобрена!</b>\n\n"
            f"📖 <b>{title}</b>\n"
            f"📂 {category}\n\n"
            "Теперь она доступна в каталоге Rauda Ilm.",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "USER NOTIFICATION ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "✅ <b>Книга добавлена!</b>\n\n"
        f"📖 {title}\n"
        f"📂 {category}\n"
        f"🆔 ID: {book_id}",
        parse_mode="HTML"
    )

    await callback.answer(
        "Книга добавлена."
    )


# ============================================================
# REJECT
# ============================================================

@dp.callback_query(
    F.data.startswith("reject:")
)
async def reject_book(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    pending_id = int(
        callback.data.split(":")[1]
    )

    pending = get_pending(pending_id)

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    user_id = pending[1]

    file_name = pending[4]

    delete_pending(pending_id)

    try:

        await bot.send_message(
            user_id,
            "❌ <b>Книга отклонена.</b>\n\n"
            f"📄 {file_name}",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "REJECT NOTIFICATION ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "❌ <b>Книга отклонена.</b>\n\n"
        f"📄 {file_name}",
        parse_mode="HTML"
    )

    await callback.answer(
        "Отклонено."
    )


# ============================================================
# CHANNEL PDF
# ============================================================

@dp.channel_post()
async def channel_pdf(
    message: Message
):

    if message.chat.id != CHANNEL_ID:
        return

    if not message.document:
        return

    document = message.document

    file_name = document.file_name or ""

    if not file_name.lower().endswith(".pdf"):

        return

    caption = message.caption or ""

    title = os.path.splitext(file_name)[0]

    author = "Не указан"

    category = "📕 Разное"

    description = ""

    for line in caption.splitlines():

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
        file_id=document.file_id
    )

    print(
        f"CHANNEL BOOK ADDED: {book_id} | {title}"
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
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=home_button()
        )

        await callback.answer()

        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {title}",
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="home"
        )
    ])

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
# DOWNLOAD
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

    book = get_book(book_id)

    if not book:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )

        return

    await callback.message.answer_document(
        document=book[5],
        caption=(
            f"📖 <b>{book[1]}</b>\n"
            f"✍️ {book[2]}"
        ),
        parse_mode="HTML"
    )

    await callback.answer()


# ============================================================
# FAVORITE
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

    if not get_book(book_id):

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
        "⭐ Добавлено!"
    )


# ============================================================
# UNFAVORITE
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
# FAVORITES
# ============================================================

@dp.callback_query(
    F.data == "favorites"
)
async def favorites(
    callback: CallbackQuery
):

    books = get_favorites(
        callback.from_user.id
    )

    if not books:

        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "У вас пока нет сохранённых книг.",
            parse_mode="HTML",
            reply_markup=home_button()
        )

        await callback.answer()

        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {title}",
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "⭐ <b>Избранное</b>\n\n"
        "Ваши книги:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# ============================================================
# CATEGORIES
# ============================================================

@dp.callback_query(
    F.data == "categories"
)
async def categories(
    callback: CallbackQuery
):

    buttons = []

    for i, category in enumerate(CATEGORIES):

        buttons.append([
            InlineKeyboardButton(
                text=category,
                callback_data=f"cat:{i}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "📂 <b>Категории</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("cat:")
)
async def category(
    callback: CallbackQuery
):

    index = int(
        callback.data.split(":")[1]
    )

    category_name = CATEGORIES[index]

    books = category_books(
        category_name
    )

    if not books:

        await callback.message.edit_text(
            f"📂 <b>{category_name}</b>\n\n"
            "В этом разделе пока нет книг.",
            parse_mode="HTML",
            reply_markup=home_button()
        )

        await callback.answer()

        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {title}",
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Категории",
            callback_data="categories"
        )
    ])

    await callback.message.edit_text(
        f"📂 <b>{category_name}</b>\n\n"
        "Книги:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# ============================================================
# DELETE
# ============================================================

@dp.callback_query(
    F.data.startswith("delete:")
)
async def delete_callback(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(book_id)

    if not book:

        await callback.answer(
            "Книга уже удалена.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"confirm_delete:{book_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"cancel_delete:{book_id}"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "⚠️ <b>Удалить книгу?</b>\n\n"
        f"📖 {book[1]}\n\n"
        "Она будет удалена из каталога "
        "и избранного.\n\n"
        "PDF в канале останется.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("confirm_delete:")
)
async def confirm_delete(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    book_id = int(
        callback.data.split(":")[1]
    )

    book = get_book(book_id)

    if not book:

        await callback.answer(
            "Книга уже удалена.",
            show_alert=True
        )

        return

    title = book[1]

    delete_book(book_id)

    await callback.message.edit_text(
        "✅ <b>Книга удалена.</b>\n\n"
        f"📖 {title}\n\n"
        "PDF в канале не удалён.",
        parse_mode="HTML",
        reply_markup=home_button()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("cancel_delete:")
)
async def cancel_delete(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

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

    await callback.message.edit_text(
        f"📖 <b>{book[1]}</b>\n\n"
        "Удаление отменено.",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )

    await callback.answer()


# ============================================================
# ABOUT
# ============================================================

@dp.callback_query(
    F.data == "about"
)
async def about(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "ℹ️ <b>О библиотеке Rauda Ilm</b>\n\n"
        "Rauda Ilm — электронная библиотека "
        "исламских книг.\n\n"
        "📚 Книги распределяются по разделам.\n"
        "📤 Пользователи могут предлагать книги "
        "на модерацию.\n"
        "⭐ Понравившиеся книги можно сохранять "
        "в избранное.",
        parse_mode="HTML",
        reply_markup=home_button()
    )

    await callback.answer()


# ============================================================
# SEARCH
# ============================================================

class SearchState(StatesGroup):
    waiting = State()


@dp.callback_query(
    F.data == "search"
)
async def search_start(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.set_state(
        SearchState.waiting
    )

    await callback.message.edit_text(
        "🔎 <b>Поиск</b>\n\n"
        "Напишите название книги, автора "
        "или категорию.",
        parse_mode="HTML",
        reply_markup=home_button()
    )

    await callback.answer()


@dp.message(SearchState.waiting)
async def search_result(
    message: Message,
    state: FSMContext
):

    text = message.text.strip()

    books = search_books(text)

    await state.clear()

    if not books:

        await message.answer(
            "🔎 Ничего не найдено.",
            reply_markup=main_menu()
        )

        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {title}",
                callback_data=f"book:{book_id}"
            )
        ])

    await message.answer(
        f"🔎 <b>Результаты поиска:</b> {len(books)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# ============================================================
# NEW BOOKS
# ============================================================

@dp.callback_query(
    F.data == "new"
)
async def new_books(
    callback: CallbackQuery
):

    books = get_books()[:10]

    if not books:

        await callback.message.edit_text(
            "🆕 Новинок пока нет.",
            reply_markup=home_button()
        )

        await callback.answer()

        return

    buttons = []

    for book_id, title, author, category in books:

        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {title}",
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "🆕 <b>Новые книги</b>\n\n"
        "Последние добавленные книги:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# ============================================================
# RENDER HTTP SERVER
# ============================================================

async def health(request):

    return web.Response(
        text="OK"
    )


async def webhook_handler(request):

    try:

        data = await request.json()

        update = Update.model_validate(data)

        await dp.feed_update(
            bot,
            update
        )

        return web.Response(
            text="OK"
        )

    except Exception as e:

        print(
            "WEBHOOK ERROR:",
            repr(e)
        )

        return web.Response(
            status=500,
            text="ERROR"
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    init_db()

    # Удаляем старый webhook,
    # чтобы не оставался старый адрес
    await bot.delete_webhook(
        drop_pending_updates=False
    )

    # Устанавливаем новый webhook
    await bot.set_webhook(
        WEBHOOK_URL
    )

    print(
        "Rauda Ilm bot started!"
    )

    print(
        "Webhook:",
        WEBHOOK_URL
    )

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/healthz",
        health
    )

    app.router.add_post(
        WEBHOOK_PATH,
        webhook_handler
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    print(
        f"HTTP server started on port {PORT}"
    )

    try:

        while True:

            await asyncio.sleep(3600)

    finally:

        await bot.delete_webhook()

        await runner.cleanup()


if __name__ == "__main__":

    asyncio.run(main())