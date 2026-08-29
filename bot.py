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
        "BOT_TOKEN не найден в Environment Variables Render"
    )


# ============================================================
# BOT
# ============================================================

bot = Bot(token=TOKEN)

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
            channel_message_id INTEGER,
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
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            description TEXT,
            file_id TEXT NOT NULL,
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
    file_id,
    channel_message_id=None
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
            file_id,
            channel_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            author,
            category,
            description,
            file_id,
            channel_message_id
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
        SELECT id, title, author, category
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
            file_id,
            channel_message_id
        FROM books
        WHERE id = ?
        """,
        (book_id,)
    ).fetchone()

    conn.close()

    return book


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


def category_books(category):

    conn = get_db()

    books = conn.execute(
        """
        SELECT id, title, author, category
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
        SELECT id, title, author, category
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


# ============================================================
# PENDING
# ============================================================

def add_pending(
    user_id,
    username,
    title,
    author,
    description,
    file_id
):

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO pending_books
        (
            user_id,
            username,
            title,
            author,
            description,
            file_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            title,
            author,
            description,
            file_id
        )
    )

    pending_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return pending_id


def get_pending(pending_id):

    conn = get_db()

    item = conn.execute(
        """
        SELECT
            id,
            user_id,
            username,
            title,
            author,
            description,
            file_id
        FROM pending_books
        WHERE id = ?
        """,
        (pending_id,)
    ).fetchone()

    conn.close()

    return item


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
# FSM
# ============================================================

class UploadState(StatesGroup):

    waiting_title = State()
    waiting_author = State()
    waiting_description = State()


class SearchState(StatesGroup):

    waiting = State()


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
                callback_data="upload"
            )
        ],

        [
            InlineKeyboardButton(
                text="ℹ️ О библиотеке",
                callback_data="about"
            )
        ]
    ]

    # Только для владельца
    if False:
        buttons.append([])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
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
# CATEGORIES
# ============================================================

CATEGORIES = [
    "📖 Акыда",
    "⚖️ Фикх",
    "📜 Хадисы",
    "📚 Тафсир",
    "🕌 Сира",
    "🌙 Исламская история",
    "🗣 Арабский язык",
    "👨‍👩‍👧 Семья и воспитание",
    "📕 Общие исламские книги",
    "📂 Другое",
]


def category_keyboard(prefix="category"):

    buttons = []

    for i, category in enumerate(CATEGORIES):

        buttons.append(
            [
                InlineKeyboardButton(
                    text=category,
                    callback_data=f"{prefix}:{i}"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="home"
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# ============================================================
# BOOK MENU
# ============================================================

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
async def start(message: Message):

    await message.answer(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.\n\n"
        "Здесь можно читать и скачивать книги "
        "в формате PDF.\n\n"
        "Также вы можете предложить свою книгу "
        "для добавления в библиотеку.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# UPLOAD BOOK
# ============================================================

@dp.callback_query(F.data == "upload")
async def upload_start(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await state.set_state(
        UploadState.waiting_title
    )

    await callback.message.edit_text(
        "📤 <b>Предложить книгу</b>\n\n"
        "Отправьте название книги.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


@dp.message(UploadState.waiting_title)
async def upload_title(
    message: Message,
    state: FSMContext
):

    title = (message.text or "").strip()

    if not title:

        await message.answer(
            "❌ Напишите название книги."
        )

        return

    await state.update_data(
        title=title
    )

    await state.set_state(
        UploadState.waiting_author
    )

    await message.answer(
        "✍️ Теперь отправьте имя автора.\n\n"
        "Если автор неизвестен, напишите: <b>Не указан</b>",
        parse_mode="HTML"
    )


@dp.message(UploadState.waiting_author)
async def upload_author(
    message: Message,
    state: FSMContext
):

    author = (message.text or "").strip()

    if not author:

        await message.answer(
            "❌ Напишите автора."
        )

        return

    await state.update_data(
        author=author
    )

    await state.set_state(
        UploadState.waiting_description
    )

    await message.answer(
        "📝 Напишите краткое описание книги.\n\n"
        "Если описание не нужно, напишите: <b>нет</b>",
        parse_mode="HTML"
    )


@dp.message(UploadState.waiting_description)
async def upload_description(
    message: Message,
    state: FSMContext
):

    description = (message.text or "").strip()

    if description.lower() == "нет":
        description = ""

    await state.update_data(
        description=description
    )

    await state.clear()

    await message.answer(
        "📄 Теперь отправьте <b>PDF-файл книги</b>.",
        parse_mode="HTML"
    )


# ============================================================
# RECEIVE PDF
# ============================================================

@dp.message(F.document)
async def receive_pdf(message: Message):

    document = message.document

    file_name = document.file_name or ""

    if not file_name.lower().endswith(".pdf"):

        await message.answer(
            "❌ Можно отправлять только PDF-файлы."
        )

        return

    # Проверяем, есть ли данные незавершённой заявки
    # Для надёжности используем отдельное временное состояние.
    # Если пользователь прислал PDF сразу — предлагаем повторить процесс.

    await message.answer(
        "📄 PDF получен.\n\n"
        "Для отправки книги на модерацию нажмите "
        "«📤 Предложить книгу» и пройдите оформление заново.",
        reply_markup=main_menu()
    )


# ============================================================
# ВАЖНО:
# Храним временные данные загрузки в словаре.
# ============================================================

upload_sessions = {}


# Переопределяем начало загрузки с использованием словаря

@dp.callback_query(F.data == "upload")
async def upload_start_real(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    upload_sessions.pop(
        callback.from_user.id,
        None
    )

    await state.set_state(
        UploadState.waiting_title
    )

    await callback.message.edit_text(
        "📤 <b>Предложить книгу</b>\n\n"
        "Шаг 1/4\n"
        "Отправьте название книги.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


# ============================================================
# ЗАГРУЗКА: НАЗВАНИЕ
# ============================================================

@dp.message(UploadState.waiting_title)
async def upload_title_real(
    message: Message,
    state: FSMContext
):

    title = (message.text or "").strip()

    if not title:
        await message.answer(
            "❌ Напишите название книги."
        )
        return

    await state.update_data(title=title)

    await state.set_state(
        UploadState.waiting_author
    )

    await message.answer(
        "✍️ Шаг 2/4\n\n"
        "Напишите автора.\n"
        "Если автор неизвестен — напишите «Не указан»."
    )


# ============================================================
# ЗАГРУЗКА: АВТОР
# ============================================================

@dp.message(UploadState.waiting_author)
async def upload_author_real(
    message: Message,
    state: FSMContext
):

    author = (message.text or "").strip()

    if not author:
        await message.answer(
            "❌ Напишите автора."
        )
        return

    await state.update_data(author=author)

    await state.set_state(
        UploadState.waiting_description
    )

    await message.answer(
        "📝 Шаг 3/4\n\n"
        "Напишите краткое описание.\n"
        "Если описания нет — напишите «нет»."
    )


# ============================================================
# ЗАГРУЗКА: ОПИСАНИЕ
# ============================================================

@dp.message(UploadState.waiting_description)
async def upload_description_real(
    message: Message,
    state: FSMContext
):

    description = (message.text or "").strip()

    if description.lower() == "нет":
        description = ""

    data = await state.get_data()

    data["description"] = description

    await state.update_data(
        description=description
    )

    await state.set_state(
        "waiting_pdf"
    )

    await message.answer(
        "📄 Шаг 4/4\n\n"
        "Теперь отправьте PDF-файл книги."
    )


# ============================================================
# PDF
# ============================================================

@dp.message(F.document)
async def receive_pdf_real(
    message: Message,
    state: FSMContext
):

    current_state = await state.get_state()

    if current_state != "waiting_pdf":
        return

    document = message.document

    file_name = document.file_name or ""

    if not file_name.lower().endswith(".pdf"):

        await message.answer(
            "❌ Нужен именно PDF-файл."
        )

        return

    data = await state.get_data()

    title = data.get(
        "title",
        file_name.rsplit(".", 1)[0]
    )

    author = data.get(
        "author",
        "Не указан"
    )

    description = data.get(
        "description",
        ""
    )

    pending_id = add_pending(
        user_id=message.from_user.id,
        username=message.from_user.username,
        title=title,
        author=author,
        description=description,
        file_id=document.file_id
    )

    await state.clear()

    await message.answer(
        "✅ <b>Книга отправлена на модерацию!</b>\n\n"
        f"📖 {title}\n"
        f"✍️ {author}\n\n"
        "После проверки книга будет добавлена "
        "в библиотеку.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    # Сообщение владельцу
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "без username"
    )

    admin_text = (
        "📚 <b>НОВАЯ КНИГА НА МОДЕРАЦИИ</b>\n\n"
        f"🆔 Заявка: <code>{pending_id}</code>\n"
        f"👤 Пользователь: {username}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"📖 Название: <b>{title}</b>\n"
        f"✍️ Автор: {author}\n"
        f"📝 Описание: {description or 'нет'}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👀 Посмотреть PDF",
                    callback_data=f"pending_file:{pending_id}"
                )
            ],
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

    try:

        await bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:

        print(
            "ADMIN MESSAGE ERROR:",
            repr(e)
        )


# ============================================================
# ADMIN: PDF
# ============================================================

@dp.callback_query(
    F.data.startswith("pending_file:")
)
async def pending_file(
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

    item = get_pending(
        pending_id
    )

    if not item:

        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )

        return

    await callback.message.answer_document(
        item[6],
        caption=(
            f"📖 {item[3]}\n"
            f"✍️ {item[4]}"
        )
    )

    await callback.answer()


# ============================================================
# ADMIN: APPROVE
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

    item = get_pending(
        pending_id
    )

    if not item:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    await callback.message.edit_text(
        "📂 <b>Выберите категорию для книги:</b>\n\n"
        f"📖 {item[3]}\n"
        f"✍️ {item[4]}",
        parse_mode="HTML",
        reply_markup=category_keyboard(
            prefix=f"approve_category:{pending_id}"
        )
    )

    await callback.answer()


# ============================================================
# ADMIN: CATEGORY
# ============================================================

@dp.callback_query(
    F.data.startswith("approve_category:")
)
async def approve_category(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "⛔ Нет доступа.",
            show_alert=True
        )

        return

    parts = callback.data.split(":")

    pending_id = int(parts[1])
    category_index = int(parts[2])

    if category_index >= len(CATEGORIES):

        await callback.answer(
            "Ошибка категории.",
            show_alert=True
        )

        return

    category = CATEGORIES[
        category_index
    ]

    item = get_pending(
        pending_id
    )

    if not item:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    (
        pending_id,
        user_id,
        username,
        title,
        author,
        description,
        file_id
    ) = item

    # Публикуем PDF в приватный канал
    try:

        channel_message = await bot.send_document(
            chat_id=CHANNEL_ID,
            document=file_id,
            caption=(
                f"📖 <b>{title}</b>\n\n"
                f"✍️ Автор: {author}\n"
                f"📂 Категория: {category}\n\n"
                f"{description}"
            ),
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "CHANNEL SEND ERROR:",
            repr(e)
        )

        await callback.message.edit_text(
            "❌ Не удалось отправить PDF в канал.\n\n"
            "Проверьте, что бот является администратором "
            "частного канала и имеет право публиковать сообщения.",
            reply_markup=back_home()
        )

        await callback.answer()

        return

    book_id = add_book(
        title=title,
        author=author,
        category=category,
        description=description,
        file_id=file_id,
        channel_message_id=channel_message.message_id
    )

    delete_pending(
        pending_id
    )

    # Уведомляем пользователя
    try:

        await bot.send_message(
            user_id,
            "🎉 <b>Ваша книга одобрена!</b>\n\n"
            f"📖 {title}\n"
            f"📂 {category}\n\n"
            "Она уже добавлена в библиотеку.",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "USER APPROVAL MESSAGE ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "✅ <b>Книга опубликована!</b>\n\n"
        f"📖 {title}\n"
        f"✍️ {author}\n"
        f"📂 {category}\n\n"
        f"🆔 ID книги: <code>{book_id}</code>",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer(
        "Книга добавлена."
    )


# ============================================================
# ADMIN: REJECT
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

    item = get_pending(
        pending_id
    )

    if not item:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    title = item[3]
    user_id = item[1]

    delete_pending(
        pending_id
    )

    try:

        await bot.send_message(
            user_id,
            "❌ <b>Книга не прошла модерацию.</b>\n\n"
            f"📖 {title}",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "USER REJECT MESSAGE ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "❌ <b>Заявка отклонена.</b>\n\n"
        f"📖 {title}",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer(
        "Заявка отклонена."
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
                text="⬅️ Главное меню",
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
# NEW
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
        "🆕 <b>Последние книги</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# ============================================================
# CATEGORIES MENU
# ============================================================

@dp.callback_query(
    F.data == "categories"
)
async def categories(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "📂 <b>Категории</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=category_keyboard()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("category:")
)
async def show_category(
    callback: CallbackQuery
):

    index = int(
        callback.data.split(":")[1]
    )

    if index >= len(CATEGORIES):

        await callback.answer(
            "Ошибка.",
            show_alert=True
        )

        return

    category = CATEGORIES[index]

    books = category_books(
        category
    )

    if not books:

        await callback.message.edit_text(
            f"{category}\n\n"
            "В этом разделе пока нет книг.",
            reply_markup=back_home()
        )

        await callback.answer()

        return

    buttons = []

    for book_id, title, author, cat in books:

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
        f"{category}\n\n"
        "Выберите книгу:",
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
        file_id,
        channel_message_id
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

    book = get_book(
        book_id
    )

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
        "⭐ Добавлено в избранное!"
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
                text="⬅️ Главное меню",
                callback_data="home"
            )
        ]
    )

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
# DELETE BOOK
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

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(
            "Книга уже удалена.",
            show_alert=True
        )

        return

    await callback.message.edit_text(
        "⚠️ <b>Удалить книгу?</b>\n\n"
        f"📖 {book[1]}\n\n"
        "Книга будет удалена из каталога "
        "и из избранного.\n\n"
        "PDF в канале останется.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
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
        "Из каталога и избранного она удалена.\n"
        "PDF в канале не удалён.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("cancel_delete:")
)
async def cancel_delete(
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

    await callback.message.edit_text(
        f"📖 <b>{book[1]}</b>\n\n"
        "Удаление отменено.",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            callback.from_user.id
        )
    )

    await callback.answer()


# ============================================================
# SEARCH
# ============================================================

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
        "🔎 <b>Поиск книги</b>\n\n"
        "Введите название, автора или категорию.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


@dp.message(SearchState.waiting)
async def search_process(
    message: Message,
    state: FSMContext
):

    text = (message.text or "").strip()

    await state.clear()

    if not text:

        await message.answer(
            "❌ Введите поисковый запрос.",
            reply_markup=main_menu()
        )

        return

    books = search_books(
        text
    )

    if not books:

        await message.answer(
            "🔎 Ничего не найдено.",
            reply_markup=main_menu()
        )

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
                text="⬅️ Главное меню",
                callback_data="home"
            )
        ]
    )

    await message.answer(
        f"🔎 <b>Результаты поиска:</b> {text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


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
        "ℹ️ <b>Rauda Ilm</b>\n\n"
        "Исламская электронная библиотека.\n\n"
        "📚 Книги добавляются после проверки "
        "модератором.\n\n"
        "📤 Любой пользователь может предложить "
        "PDF-книгу для добавления.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


# ============================================================
# HOME
# ============================================================

@dp.callback_query(
    F.data == "home"
)
async def home(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await callback.message.edit_text(
        "📚 <b>Rauda Ilm</b>\n\n"
        "Выберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer()


# ============================================================
# HTTP SERVER FOR RENDER
# ============================================================

async def health(request):

    return web.Response(
        text="OK"
    )


async def webhook(request):

    try:

        data = await request.json()

        update = __import__(
            "aiogram.types",
            fromlist=["Update"]
        ).Update.model_validate(
            data
        )

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


async def on_startup():

    init_db()

    # Удаляем старые pending updates
    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await bot.set_webhook(
        url=WEBHOOK_URL
    )

    print(
        "Rauda Ilm bot started!"
    )

    print(
        "Webhook:",
        WEBHOOK_URL
    )


async def on_shutdown():

    try:

        await bot.delete_webhook()

    except Exception as e:

        print(
            "Webhook delete error:",
            repr(e)
        )

    await bot.session.close()


# ============================================================
# MAIN
# ============================================================

async def main():

    app = web.Application()

    app.router.add_get(
        "/healthz",
        health
    )

    app.router.add_post(
        WEBHOOK_PATH,
        webhook
    )

    app.on_startup.append(
        lambda app: on_startup()
    )

    app.on_cleanup.append(
        lambda app: on_shutdown()
    )

    runner = web.AppRunner(
        app
    )

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

    while True:

        await asyncio.sleep(3600)


if __name__ == "__main__":

    asyncio.run(
        main()
    )