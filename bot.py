import os
import sqlite3
import asyncio
from contextlib import suppress
from html import escape

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

PORT = int(
    os.getenv("PORT", "10000")
)

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://rauda-ilm-books-bot.onrender.com"
)

WEBHOOK_PATH = "/telegram/webhook"

WEBHOOK_URL = (
    RENDER_URL.rstrip("/")
    + WEBHOOK_PATH
)

DB_FILE = os.getenv(
    "DB_FILE",
    "books.db"
)


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
# CATEGORIES
# ============================================================

CATEGORIES = [
    "Акыда",
    "Фикх",
    "Хадисы",
    "Тафсир",
    "Сира",
    "Арабский язык",
    "Семья",
    "Дети",
    "Разное",
]


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE
    )

    return conn


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            file_id TEXT NOT NULL,
            file_unique_id TEXT,
            channel_message_id INTEGER,
            deleted INTEGER DEFAULT 0,
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
            file_unique_id TEXT,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # МИГРАЦИЯ BOOKS
    # --------------------------------------------------------

    columns = [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(books)"
        ).fetchall()
    ]

    if "channel_message_id" not in columns:

        conn.execute("""
            ALTER TABLE books
            ADD COLUMN channel_message_id INTEGER
        """)

    if "deleted" not in columns:

        conn.execute("""
            ALTER TABLE books
            ADD COLUMN deleted INTEGER DEFAULT 0
        """)

    if "file_unique_id" not in columns:

        conn.execute("""
            ALTER TABLE books
            ADD COLUMN file_unique_id TEXT
        """)

    # --------------------------------------------------------
    # МИГРАЦИЯ PENDING
    # --------------------------------------------------------

    pending_columns = [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(pending_books)"
        ).fetchall()
    ]

    if "file_unique_id" not in pending_columns:

        conn.execute("""
            ALTER TABLE pending_books
            ADD COLUMN file_unique_id TEXT
        """)

    # --------------------------------------------------------
    # ИНДЕКСЫ ДЛЯ ЗАЩИТЫ ОТ ДУБЛЕЙ
    # --------------------------------------------------------

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_books_file_unique_id
        ON books(file_unique_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_books_channel_message_id
        ON books(channel_message_id)
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
    file_id,
    file_unique_id=None,
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
            file_unique_id,
            channel_message_id,
            deleted
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            title,
            author,
            category,
            description,
            file_id,
            file_unique_id,
            channel_message_id
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
            file_id,
            file_unique_id,
            channel_message_id,
            deleted
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
        WHERE deleted = 0
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
        AND deleted = 0
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
        WHERE deleted = 0
        AND (
            title LIKE ?
            OR author LIKE ?
            OR category LIKE ?
        )
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


def update_book(
    book_id,
    title,
    author,
    category,
    description
):

    conn = get_db()

    conn.execute(
        """
        UPDATE books
        SET
            title = ?,
            author = ?,
            category = ?,
            description = ?
        WHERE id = ?
        """,
        (
            title,
            author,
            category,
            description,
            book_id
        )
    )

    conn.commit()
    conn.close()


# ============================================================
# DELETE
# ============================================================

def delete_book(book_id):

    conn = get_db()

    # Не удаляем запись физически.
    # Это позволяет потом восстановить книгу.

    conn.execute(
        """
        UPDATE books
        SET deleted = 1
        WHERE id = ?
        """,
        (book_id,)
    )

    conn.commit()
    conn.close()


# ============================================================
# DUPLICATE SEARCH
# ============================================================

def book_by_channel_message(
    message_id
):

    conn = get_db()

    result = conn.execute(
        """
        SELECT
            id
        FROM books
        WHERE channel_message_id = ?
        LIMIT 1
        """,
        (message_id,)
    ).fetchone()

    conn.close()

    return result


def book_by_file_unique_id(
    file_unique_id
):

    if not file_unique_id:
        return None

    conn = get_db()

    result = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category,
            description,
            file_id,
            file_unique_id,
            channel_message_id,
            deleted
        FROM books
        WHERE file_unique_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (file_unique_id,)
    ).fetchone()

    conn.close()

    return result


def book_by_file_id(
    file_id
):

    if not file_id:
        return None

    conn = get_db()

    result = conn.execute(
        """
        SELECT
            id,
            title,
            author,
            category,
            description,
            file_id,
            file_unique_id,
            channel_message_id,
            deleted
        FROM books
        WHERE file_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (file_id,)
    ).fetchone()

    conn.close()

    return result


def restore_book(
    book_id,
    file_id=None,
    file_unique_id=None,
    channel_message_id=None
):

    conn = get_db()

    conn.execute(
        """
        UPDATE books
        SET
            file_id = COALESCE(?, file_id),
            file_unique_id = COALESCE(?, file_unique_id),
            channel_message_id =
                COALESCE(?, channel_message_id),
            deleted = 0
        WHERE id = ?
        """,
        (
            file_id,
            file_unique_id,
            channel_message_id,
            book_id
        )
    )

    conn.commit()
    conn.close()


def restore_book_from_channel(
    book_id,
    title,
    author,
    category,
    description,
    file_id,
    file_unique_id,
    channel_message_id
):

    conn = get_db()

    conn.execute(
        """
        UPDATE books
        SET
            title = ?,
            author = ?,
            category = ?,
            description = ?,
            file_id = ?,
            file_unique_id = ?,
            channel_message_id = ?,
            deleted = 0
        WHERE id = ?
        """,
        (
            title,
            author,
            category,
            description,
            file_id,
            file_unique_id,
            channel_message_id,
            book_id
        )
    )

    conn.commit()
    conn.close()


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


def get_favorites(
    user_id
):

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
        AND books.deleted = 0
        ORDER BY books.id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return books


# ============================================================
# PENDING
# ============================================================

def add_pending(
    user_id,
    username,
    file_id,
    file_unique_id,
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
            file_unique_id,
            file_name
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            file_id,
            file_unique_id,
            file_name
        )
    )

    pending_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return pending_id


def get_pending(
    pending_id
):

    conn = get_db()

    result = conn.execute(
        """
        SELECT
            id,
            user_id,
            username,
            file_id,
            file_unique_id,
            file_name
        FROM pending_books
        WHERE id = ?
        """,
        (pending_id,)
    ).fetchone()

    conn.close()

    return result


def delete_pending(
    pending_id
):

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
# KEYBOARDS
# ============================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Каталог",
                    callback_data="catalog"
                ),
                InlineKeyboardButton(
                    text="Поиск",
                    callback_data="search"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Новинки",
                    callback_data="new"
                ),
                InlineKeyboardButton(
                    text="Категории",
                    callback_data="categories"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Избранное",
                    callback_data="favorites"
                ),
                InlineKeyboardButton(
                    text="Предложить книгу",
                    callback_data="suggest"
                )
            ],
            [
                InlineKeyboardButton(
                    text="О библиотеке",
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
                    text="Отмена",
                    callback_data="home"
                )
            ]
        ]
    )


def book_menu(
    book_id,
    user_id
):

    buttons = [
        [
            InlineKeyboardButton(
                text="Скачать PDF",
                callback_data=f"download:{book_id}"
            )
        ]
    ]

    if is_favorite(
        user_id,
        book_id
    ):

        buttons.append([
            InlineKeyboardButton(
                text="Убрать из избранного",
                callback_data=f"unfavorite:{book_id}"
            )
        ])

    else:

        buttons.append([
            InlineKeyboardButton(
                text="В избранное",
                callback_data=f"favorite:{book_id}"
            )
        ])

    if user_id == ADMIN_ID:

        buttons.append([
            InlineKeyboardButton(
                text="Редактировать",
                callback_data=f"edit:{book_id}"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="Удалить",
                callback_data=f"delete:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="catalog"
        ),
        InlineKeyboardButton(
            text="Меню",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def category_keyboard(
    prefix
):

    rows = []

    for i, category_name in enumerate(
        CATEGORIES
    ):

        rows.append([
            InlineKeyboardButton(
                text=category_name,
                callback_data=f"{prefix}:{i}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="Отмена",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


# ============================================================
# STATES
# ============================================================

class SuggestState(
    StatesGroup
):

    waiting_file = State()


class SearchState(
    StatesGroup
):

    waiting = State()


class EditBookState(
    StatesGroup
):

    waiting_title = State()
    waiting_author = State()
    waiting_category = State()
    waiting_description = State()


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "<b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


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
        "<b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую "
        "электронную библиотеку.",
        parse_mode="HTML",
        reply_markup=main_menu()
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
        "<b>Rauda Ilm</b>\n\n"
        "Электронная библиотека "
        "исламских книг.\n\n"
        "Каталог\n"
        "Поиск\n"
        "Избранное\n"
        "Предложение книг\n"
        "Редактирование\n"
        "Модерация",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


# ============================================================
# SUGGEST
# ============================================================

@dp.callback_query(
    F.data == "suggest"
)
async def suggest(
    callback: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await state.set_state(
        SuggestState.waiting_file
    )

    await callback.message.edit_text(
        "<b>Предложить книгу</b>\n\n"
        "Отправьте PDF-файл книги.\n\n"
        "После отправки файл попадёт "
        "администратору на модерацию.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


@dp.message(
    SuggestState.waiting_file
)
async def receive_suggested(
    message: Message,
    state: FSMContext
):

    if not message.document:

        await message.answer(
            "Отправьте именно PDF-файл.",
            reply_markup=back_home()
        )

        return

    document = message.document

    file_name = (
        document.file_name
        or "book.pdf"
    )

    if not file_name.lower().endswith(
        ".pdf"
    ):

        await message.answer(
            "Принимаются только PDF-файлы.",
            reply_markup=back_home()
        )

        return

    # --------------------------------------------------------
    # ПРОВЕРКА ДУБЛИКАТА ЕЩЁ ДО МОДЕРАЦИИ
    # --------------------------------------------------------

    existing = book_by_file_unique_id(
        document.file_unique_id
    )

    if existing:

        if existing[8] == 1:

            restore_book(
                book_id=existing[0],
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=existing[7]
            )

            await state.clear()

            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

        else:

            await state.clear()

            await message.answer(
                "<b>Эта книга уже есть "
                "в каталоге.</b>\n\n"
                f"{escape(existing[1])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
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
        file_unique_id=document.file_unique_id,
        file_name=file_name
    )

    await state.clear()

    await message.answer(
        "<b>Книга отправлена.</b>\n\n"
        "Администратор проверит файл.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Одобрить",
                    callback_data=f"approve:{pending_id}"
                ),
                InlineKeyboardButton(
                    text="Отклонить",
                    callback_data=f"reject:{pending_id}"
                )
            ]
        ]
    )

    try:

        await bot.send_document(
            ADMIN_ID,
            document=document.file_id,
            caption=(
                "<b>Новая книга на модерации</b>\n\n"
                f"Заявка: {pending_id}\n"
                f"Пользователь: {escape(username)}\n"
                f"Файл: {escape(file_name)}"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:

        print(
            "MODERATION SEND ERROR:",
            repr(e)
        )


# ============================================================
# APPROVE
# ============================================================

@dp.callback_query(
    F.data.startswith("approve:")
)
async def approve(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        pending_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная заявка.",
            show_alert=True
        )

        return

    pending = get_pending(
        pending_id
    )

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    await callback.message.answer(
        "<b>Выберите категорию:</b>",
        parse_mode="HTML",
        reply_markup=category_keyboard(
            f"setcat:{pending_id}"
        )
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
            "Нет доступа.",
            show_alert=True
        )

        return

    parts = callback.data.split(":")

    if len(parts) != 3:

        await callback.answer(
            "Некорректные данные.",
            show_alert=True
        )

        return

    try:

        pending_id = int(parts[1])
        index = int(parts[2])

    except ValueError:

        await callback.answer(
            "Некорректные данные.",
            show_alert=True
        )

        return

    if index < 0 or index >= len(
        CATEGORIES
    ):

        await callback.answer(
            "Категория не найдена.",
            show_alert=True
        )

        return

    pending = get_pending(
        pending_id
    )

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    category = CATEGORIES[index]

    title = os.path.splitext(
        pending[5]
    )[0]

    # --------------------------------------------------------
    # ПРОВЕРКА ДУБЛИКАТА
    # --------------------------------------------------------

    existing = book_by_file_unique_id(
        pending[4]
    )

    if existing:

        if existing[8] == 1:

            restore_book_from_channel(
                book_id=existing[0],
                title=existing[1],
                author=existing[2],
                category=existing[3],
                description=existing[4],
                file_id=pending[3],
                file_unique_id=pending[4],
                channel_message_id=existing[7]
            )

            delete_pending(
                pending_id
            )

            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"Название: {escape(existing[1])}\n"
                f"Категория: {escape(existing[3])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

            await callback.answer(
                "Книга восстановлена."
            )

            return

        delete_pending(
            pending_id
        )

        await callback.message.edit_text(
            "<b>Такая книга уже есть "
            "в каталоге.</b>\n\n"
            f"{escape(existing[1])}\n"
            f"ID: {existing[0]}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        await callback.answer(
            "Дубликат не добавлен."
        )

        return

    # --------------------------------------------------------
    # ПРОВЕРКА ПО СТАРОМУ FILE_ID
    # --------------------------------------------------------

    existing_old = book_by_file_id(
        pending[3]
    )

    if existing_old:

        if existing_old[8] == 1:

            restore_book_from_channel(
                book_id=existing_old[0],
                title=existing_old[1],
                author=existing_old[2],
                category=existing_old[3],
                description=existing_old[4],
                file_id=pending[3],
                file_unique_id=pending[4],
                channel_message_id=existing_old[7]
            )

            delete_pending(
                pending_id
            )

            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing_old[1])}\n"
                f"ID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

            await callback.answer(
                "Восстановлено."
            )

            return

        delete_pending(
            pending_id
        )

        await callback.message.edit_text(
            "<b>Этот PDF уже есть "
            "в каталоге.</b>\n\n"
            f"{escape(existing_old[1])}\n"
            f"ID: {existing_old[0]}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        await callback.answer(
            "Дубликат не добавлен."
        )

        return

    # --------------------------------------------------------
    # СОХРАНЯЕМ PDF В КАНАЛ
    # --------------------------------------------------------

    try:

        channel_message = await bot.send_document(
            CHANNEL_ID,
            document=pending[3],
            caption=(
                f"Название: {escape(title)}\n"
                "Автор: Не указан\n"
                f"Категория: {escape(category)}"
            ),
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "CHANNEL UPLOAD ERROR:",
            repr(e)
        )

        await callback.answer(
            "Не удалось сохранить PDF в канал.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # СОХРАНЯЕМ КНИГУ
    # --------------------------------------------------------

    book_id = add_book(
        title=title,
        author="Не указан",
        category=category,
        description="",
        file_id=pending[3],
        file_unique_id=pending[4],
        channel_message_id=channel_message.message_id
    )

    user_id = pending[1]

    delete_pending(
        pending_id
    )

    try:

        await bot.send_message(
            user_id,
            "<b>Ваша книга одобрена.</b>\n\n"
            f"Название: {escape(title)}\n"
            f"Категория: {escape(category)}\n\n"
            "Она добавлена в каталог.",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "USER NOTIFICATION ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "<b>Книга добавлена.</b>\n\n"
        f"Название: {escape(title)}\n"
        f"Категория: {escape(category)}\n"
        f"ID: {book_id}",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )

    await callback.answer(
        "Добавлено."
    )


# ============================================================
# REJECT
# ============================================================

@dp.callback_query(
    F.data.startswith("reject:")
)
async def reject(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        pending_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная заявка.",
            show_alert=True
        )

        return

    pending = get_pending(
        pending_id
    )

    if not pending:

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True
        )

        return

    user_id = pending[1]

    file_name = pending[5]

    delete_pending(
        pending_id
    )

    try:

        await bot.send_message(
            user_id,
            "<b>Книга отклонена.</b>\n\n"
            f"Файл: {escape(file_name)}",
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "REJECT NOTIFICATION ERROR:",
            repr(e)
        )

    await callback.message.edit_text(
        "<b>Книга отклонена.</b>\n\n"
        f"Файл: {escape(file_name)}",
        parse_mode="HTML",
        reply_markup=main_menu()
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

    file_name = (
        document.file_name
        or ""
    )

    if not file_name.lower().endswith(
        ".pdf"
    ):

        return

    # --------------------------------------------------------
    # ПРОВЕРКА ПО MESSAGE ID
    # --------------------------------------------------------

    existing_message = book_by_channel_message(
        message.message_id
    )

    if existing_message:

        print(
            "CHANNEL MESSAGE ALREADY EXISTS:",
            message.message_id
        )

        return

    # --------------------------------------------------------
    # ЧИТАЕМ ПОДПИСЬ
    # --------------------------------------------------------

    caption = (
        message.caption
        or ""
    )

    title = os.path.splitext(
        file_name
    )[0]

    author = "Не указан"

    category = "Разное"

    description = ""

    for line in caption.splitlines():

        if ":" not in line:

            continue

        key, value = line.split(
            ":",
            1
        )

        key = key.strip().lower()

        value = value.strip()

        if key in (
            "название",
            "название книги"
        ):

            if value:
                title = value

        elif key == "автор":

            if value:
                author = value

        elif key in (
            "категория",
            "раздел"
        ):

            if value:
                category = value

        elif key == "описание":

            description = value

    # --------------------------------------------------------
    # НОРМАЛИЗАЦИЯ КАТЕГОРИИ
    # --------------------------------------------------------

    matched_category = None

    for cat in CATEGORIES:

        if category.lower() == cat.lower():

            matched_category = cat

            break

    if matched_category:

        category = matched_category

    else:

        category = "Разное"

    # --------------------------------------------------------
    # ПОИСК ПО FILE UNIQUE ID
    # --------------------------------------------------------

    existing = book_by_file_unique_id(
        document.file_unique_id
    )

    if existing:

        # ----------------------------------------------------
        # УДАЛЁННАЯ КНИГА
        # ----------------------------------------------------

        if existing[8] == 1:

            restore_book_from_channel(
                book_id=existing[0],
                title=title,
                author=author,
                category=category,
                description=description,
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=message.message_id
            )

            print(
                "BOOK RESTORED FROM CHANNEL:",
                existing[0],
                title
            )

            return

        # ----------------------------------------------------
        # АКТИВНАЯ КНИГА
        # ----------------------------------------------------

        print(
            "DUPLICATE PDF SKIPPED:",
            existing[0],
            title
        )

        return

    # --------------------------------------------------------
    # ПОИСК ПО СТАРОМУ FILE ID
    # --------------------------------------------------------

    existing_old = book_by_file_id(
        document.file_id
    )

    if existing_old:

        if existing_old[8] == 1:

            restore_book_from_channel(
                book_id=existing_old[0],
                title=title,
                author=author,
                category=category,
                description=description,
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=message.message_id
            )

            print(
                "OLD BOOK RESTORED:",
                existing_old[0],
                title
            )

            return

        print(
            "OLD FILE ID DUPLICATE SKIPPED:",
            existing_old[0]
        )

        return

    # --------------------------------------------------------
    # НОВАЯ КНИГА
    # --------------------------------------------------------

    book_id = add_book(
        title=title,
        author=author,
        category=category,
        description=description,
        file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        channel_message_id=message.message_id
    )

    print(
        "CHANNEL BOOK ADDED:",
        book_id,
        title,
        category
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
            "<b>Каталог</b>\n\n"
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=back_home()
        )

        await callback.answer()

        return

    buttons = []

    for (
        book_id,
        title,
        author,
        category
    ) in books:

        buttons.append([
            InlineKeyboardButton(
                text=title[:50],
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "<b>Каталог</b>\n\n"
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

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book or book[8] == 1:

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
        file_unique_id,
        channel_message_id,
        deleted
    ) = book

    text = (
        f"<b>{escape(title)}</b>\n\n"
        f"Автор: {escape(author)}\n"
        f"Категория: {escape(category)}"
    )

    if description:

        text += (
            f"\n\n{escape(description)}"
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

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book or book[8] == 1:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )

        return

    try:

        await callback.message.answer_document(
            document=book[5],
            caption=(
                f"<b>{escape(book[1])}</b>\n"
                f"{escape(book[2])}"
            ),
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:

        print(
            "DOWNLOAD ERROR:",
            repr(e)
        )

        await callback.answer(
            "Не удалось отправить PDF.",
            show_alert=True
        )


# ============================================================
# FAVORITE
# ============================================================

@dp.callback_query(
    F.data.startswith("favorite:")
)
async def favorite(
    callback: CallbackQuery
):

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book or book[8] == 1:

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
        "Добавлено."
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

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

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
        "Убрано."
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
            "<b>Избранное</b>\n\n"
            "У вас пока нет избранных книг.",
            parse_mode="HTML",
            reply_markup=back_home()
        )

        await callback.answer()

        return

    buttons = []

    for (
        book_id,
        title,
        author,
        category
    ) in books:

        buttons.append([
            InlineKeyboardButton(
                text=title[:50],
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Меню",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "<b>Избранное</b>\n\n"
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

    rows = []

    for i, category_name in enumerate(
        CATEGORIES
    ):

        rows.append([
            InlineKeyboardButton(
                text=category_name,
                callback_data=f"category:{i}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "<b>Категории</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("category:")
)
async def category(
    callback: CallbackQuery
):

    try:

        index = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная категория.",
            show_alert=True
        )

        return

    if index < 0 or index >= len(
        CATEGORIES
    ):

        await callback.answer(
            "Категория не найдена.",
            show_alert=True
        )

        return

    category_name = CATEGORIES[index]

    books = category_books(
        category_name
    )

    if not books:

        await callback.message.edit_text(
            f"<b>{escape(category_name)}</b>\n\n"
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Категории",
                            callback_data="categories"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Меню",
                            callback_data="home"
                        )
                    ]
                ]
            )
        )

        await callback.answer()

        return

    buttons = []

    for (
        book_id,
        title,
        author,
        cat
    ) in books:

        buttons.append([
            InlineKeyboardButton(
                text=title[:50],
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Категории",
            callback_data="categories"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="Меню",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        f"<b>{escape(category_name)}</b>\n\n"
        "Книги:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


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
            "<b>Новинки</b>\n\n"
            "Книг пока нет.",
            parse_mode="HTML",
            reply_markup=back_home()
        )

        await callback.answer()

        return

    buttons = []

    for (
        book_id,
        title,
        author,
        category
    ) in books:

        buttons.append([
            InlineKeyboardButton(
                text=title[:50],
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "<b>Последние книги</b>\n\n"
        "Новые поступления:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
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

    await state.clear()

    await state.set_state(
        SearchState.waiting
    )

    await callback.message.edit_text(
        "<b>Поиск</b>\n\n"
        "Введите название книги, автора "
        "или категорию:",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


@dp.message(
    SearchState.waiting
)
async def search_result(
    message: Message,
    state: FSMContext
):

    text = (
        message.text
        or ""
    ).strip()

    if not text:

        await message.answer(
            "Введите текст для поиска.",
            reply_markup=back_home()
        )

        return

    books = search_books(
        text
    )

    await state.clear()

    if not books:

        await message.answer(
            "Ничего не найдено.",
            reply_markup=main_menu()
        )

        return

    buttons = []

    for (
        book_id,
        title,
        author,
        category
    ) in books:

        buttons.append([
            InlineKeyboardButton(
                text=title[:50],
                callback_data=f"book:{book_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="home"
        )
    ])

    await message.answer(
        f"<b>Результаты:</b> {escape(text)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# ============================================================
# DELETE START
# ============================================================

@dp.callback_query(
    F.data.startswith("delete:")
)
async def delete_start(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book or book[8] == 1:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"confirm_delete:{book_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"cancel_delete:{book_id}"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "<b>Удалить книгу?</b>\n\n"
        f"<b>{escape(book[1])}</b>\n"
        f"Категория: {escape(book[3])}\n\n"
        "Книга исчезнет из каталога.\n"
        "PDF в канале останется.",
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

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )

        return

    title = book[1]

    delete_book(
        book_id
    )

    await callback.message.edit_text(
        "<b>Книга удалена из каталога.</b>\n\n"
        f"{escape(title)}\n\n"
        "PDF в канале сохранён.\n"
        "Если тот же PDF снова будет "
        "обработан ботом, книга восстановится.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer(
        "Удалено."
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

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

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
        f"<b>{escape(book[1])}</b>\n\n"
        "Удаление отменено.",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )

    await callback.answer(
        "Отменено."
    )


# ============================================================
# EDIT START
# ============================================================

@dp.callback_query(
    F.data.startswith("edit:")
)
async def edit_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная книга.",
            show_alert=True
        )

        return

    book = get_book(
        book_id
    )

    if not book or book[8] == 1:

        await callback.answer(
            "Книга не найдена.",
            show_alert=True
        )

        return

    await state.clear()

    await state.update_data(
        book_id=book_id,
        old_title=book[1],
        old_author=book[2],
        old_category=book[3],
        old_description=book[4]
    )

    await state.set_state(
        EditBookState.waiting_title
    )

    await callback.message.edit_text(
        "<b>Редактирование</b>\n\n"
        "Текущее название:\n"
        f"<b>{escape(book[1])}</b>\n\n"
        "Отправьте новое название.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отмена",
                        callback_data=f"editcancel:{book_id}"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# ============================================================
# EDIT CANCEL
# ============================================================

@dp.callback_query(
    F.data.startswith("editcancel:")
)
async def edit_cancel(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        return

    try:

        book_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer()

        return

    await state.clear()

    book = get_book(
        book_id
    )

    if not book:

        await callback.message.edit_text(
            "Книга не найдена.",
            reply_markup=main_menu()
        )

        await callback.answer()

        return

    await callback.message.edit_text(
        f"<b>{escape(book[1])}</b>\n\n"
        "Редактирование отменено.",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )

    await callback.answer(
        "Отменено."
    )


# ============================================================
# EDIT TITLE
# ============================================================

@dp.message(
    EditBookState.waiting_title
)
async def edit_title(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:

        return

    title = (
        message.text
        or ""
    ).strip()

    if not title:

        await message.answer(
            "Название не может быть пустым.",
            reply_markup=back_home()
        )

        return

    await state.update_data(
        title=title
    )

    data = await state.get_data()

    await state.set_state(
        EditBookState.waiting_author
    )

    await message.answer(
        "<b>Автор</b>\n\n"
        f"Сейчас: <b>{escape(data['old_author'])}</b>\n\n"
        "Отправьте нового автора.\n"
        "Если автора нет — напишите «нет».",
        parse_mode="HTML",
        reply_markup=back_home()
    )


# ============================================================
# EDIT AUTHOR
# ============================================================

@dp.message(
    EditBookState.waiting_author
)
async def edit_author(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:

        return

    author = (
        message.text
        or ""
    ).strip()

    if author.lower() == "нет" or not author:

        author = "Не указан"

    await state.update_data(
        author=author
    )

    await state.set_state(
        EditBookState.waiting_category
    )

    await message.answer(
        "<b>Выберите новую категорию:</b>",
        parse_mode="HTML",
        reply_markup=category_keyboard(
            "editcat"
        )
    )


# ============================================================
# EDIT CATEGORY
# ============================================================

@dp.callback_query(
    EditBookState.waiting_category,
    F.data.startswith("editcat:")
)
async def edit_category(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        return

    try:

        index = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Некорректная категория.",
            show_alert=True
        )

        return

    if index < 0 or index >= len(
        CATEGORIES
    ):

        await callback.answer(
            "Категория не найдена.",
            show_alert=True
        )

        return

    category_name = CATEGORIES[index]

    await state.update_data(
        category=category_name
    )

    await state.set_state(
        EditBookState.waiting_description
    )

    await callback.message.edit_text(
        "<b>Описание</b>\n\n"
        "Отправьте новое описание.\n\n"
        "Если описание не нужно — "
        "напишите <code>нет</code>.",
        parse_mode="HTML",
        reply_markup=back_home()
    )

    await callback.answer()


# ============================================================
# EDIT DESCRIPTION
# ============================================================

@dp.message(
    EditBookState.waiting_description
)
async def edit_description(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:

        return

    description = (
        message.text
        or ""
    ).strip()

    if description.lower() == "нет":

        description = ""

    data = await state.get_data()

    book_id = data["book_id"]

    update_book(
        book_id=book_id,
        title=data["title"],
        author=data["author"],
        category=data["category"],
        description=description
    )

    await state.clear()

    book = get_book(
        book_id
    )

    if not book:

        await message.answer(
            "Книга не найдена.",
            reply_markup=main_menu()
        )

        return

    text = (
        "<b>Книга изменена.</b>\n\n"
        f"<b>{escape(book[1])}</b>\n"
        f"Автор: {escape(book[2])}\n"
        f"Категория: {escape(book[3])}"
    )

    if book[4]:

        text += (
            f"\n\n{escape(book[4])}"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )


# ============================================================
# ADMIN DIRECT PDF
# ============================================================

@dp.message(
    F.document,
    F.from_user.id == ADMIN_ID
)
async def admin_direct_pdf(
    message: Message
):

    document = message.document

    file_name = (
        document.file_name
        or ""
    )

    if not file_name.lower().endswith(
        ".pdf"
    ):

        await message.answer(
            "Принимаются только PDF-файлы.",
            reply_markup=main_menu()
        )

        return

    # --------------------------------------------------------
    # ДУБЛИКАТ ПО FILE UNIQUE ID
    # --------------------------------------------------------

    existing = book_by_file_unique_id(
        document.file_unique_id
    )

    if existing:

        if existing[8] == 1:

            restore_book(
                book_id=existing[0],
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=existing[7]
            )

            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

        else:

            await message.answer(
                "<b>Этот PDF уже есть "
                "в каталоге.</b>\n\n"
                f"{escape(existing[1])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

        return

    # --------------------------------------------------------
    # ДУБЛИКАТ ПО СТАРОМУ FILE ID
    # --------------------------------------------------------

    existing_old = book_by_file_id(
        document.file_id
    )

    if existing_old:

        if existing_old[8] == 1:

            restore_book(
                book_id=existing_old[0],
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=existing_old[7]
            )

            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing_old[1])}\n"
                f"ID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

        else:

            await message.answer(
                "<b>Этот PDF уже есть "
                "в каталоге.</b>\n\n"
                f"{escape(existing_old[1])}\n"
                f"ID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

        return

    # --------------------------------------------------------
    # НОВЫЙ PDF
    # --------------------------------------------------------

    pending_id = add_pending(
        user_id=ADMIN_ID,
        username="ADMIN",
        file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        file_name=file_name
    )

    await message.answer(
        "<b>PDF получен.</b>\n\n"
        "Выберите категорию:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=category_name,
                        callback_data=(
                            f"directcat:"
                            f"{pending_id}:"
                            f"{i}"
                        )
                    )
                ]
                for i, category_name
                in enumerate(CATEGORIES)
            ] + [
                [
                    InlineKeyboardButton(
                        text="Отмена",
                        callback_data=(
                            f"directcancel:"
                            f"{pending_id}"
                        )
                    )
                ]
            ]
        )
    )


# ============================================================
# DIRECT CATEGORY
# ============================================================

@dp.callback_query(
    F.data.startswith("directcat:")
)
async def direct_category(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    parts = callback.data.split(":")

    if len(parts) != 3:

        await callback.answer(
            "Некорректные данные.",
            show_alert=True
        )

        return

    try:

        pending_id = int(parts[1])
        category_index = int(parts[2])

    except ValueError:

        await callback.answer(
            "Некорректные данные.",
            show_alert=True
        )

        return

    if category_index < 0 or category_index >= len(
        CATEGORIES
    ):

        await callback.answer(
            "Категория не найдена.",
            show_alert=True
        )

        return

    pending = get_pending(
        pending_id
    )

    if not pending:

        await callback.answer(
            "Файл уже обработан.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # ДУБЛИКАТ ПО FILE UNIQUE ID
    # --------------------------------------------------------

    existing = book_by_file_unique_id(
        pending[4]
    )

    if existing:

        if existing[8] == 1:

            restore_book(
                book_id=existing[0],
                file_id=pending[3],
                file_unique_id=pending[4],
                channel_message_id=existing[7]
            )

            delete_pending(
                pending_id
            )

            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\n"
                f"ID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

            await callback.answer(
                "Восстановлено."
            )

            return

        delete_pending(
            pending_id
        )

        await callback.message.edit_text(
            "<b>Этот PDF уже есть "
            "в каталоге.</b>\n\n"
            f"{escape(existing[1])}\n"
            f"ID: {existing[0]}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        await callback.answer(
            "Дубликат не добавлен."
        )

        return

    # --------------------------------------------------------
    # ДУБЛИКАТ ПО FILE ID
    # --------------------------------------------------------

    existing_old = book_by_file_id(
        pending[3]
    )

    if existing_old:

        if existing_old[8] == 1:

            restore_book(
                book_id=existing_old[0],
                file_id=pending[3],
                file_unique_id=pending[4],
                channel_message_id=existing_old[7]
            )

            delete_pending(
                pending_id
            )

            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing_old[1])}\n"
                f"ID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

            await callback.answer(
                "Восстановлено."
            )

            return

        delete_pending(
            pending_id
        )

        await callback.message.edit_text(
            "<b>Этот PDF уже есть "
            "в каталоге.</b>\n\n"
            f"{escape(existing_old[1])}\n"
            f"ID: {existing_old[0]}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        await callback.answer(
            "Дубликат не добавлен."
        )

        return

    category_name = CATEGORIES[
        category_index
    ]

    title = os.path.splitext(
        pending[5]
    )[0]

    # --------------------------------------------------------
    # СОХРАНЯЕМ PDF В КАНАЛ
    # --------------------------------------------------------

    try:

        channel_message = await bot.send_document(
            CHANNEL_ID,
            document=pending[3],
            caption=(
                f"Название: {escape(title)}\n"
                "Автор: Не указан\n"
                f"Категория: {escape(category_name)}"
            ),
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            "DIRECT CHANNEL UPLOAD ERROR:",
            repr(e)
        )

        await callback.answer(
            "Не удалось сохранить PDF в канал.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # СОХРАНЯЕМ В БАЗУ
    # --------------------------------------------------------

    book_id = add_book(
        title=title,
        author="Не указан",
        category=category_name,
        description="",
        file_id=pending[3],
        file_unique_id=pending[4],
        channel_message_id=channel_message.message_id
    )

    delete_pending(
        pending_id
    )

    await callback.message.edit_text(
        "<b>Книга добавлена.</b>\n\n"
        f"{escape(title)}\n"
        f"Категория: {escape(category_name)}\n"
        f"ID: {book_id}",
        parse_mode="HTML",
        reply_markup=book_menu(
            book_id,
            ADMIN_ID
        )
    )

    await callback.answer(
        "Добавлено."
    )


# ============================================================
# DIRECT CANCEL
# ============================================================

@dp.callback_query(
    F.data.startswith("directcancel:")
)
async def direct_cancel(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        return

    try:

        pending_id = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer()

        return

    delete_pending(
        pending_id
    )

    await callback.message.edit_text(
        "<b>Добавление отменено.</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    await callback.answer(
        "Отменено."
    )


# ============================================================
# HEALTH
# ============================================================

async def health(
    request
):

    return web.Response(
        text="OK"
    )


# ============================================================
# WEBHOOK
# ============================================================

async def telegram_webhook(
    request
):

    try:

        data = await request.json()

        update = Update.model_validate(
            data,
            context={
                "bot": bot
            }
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
            text="ERROR",
            status=500
        )


# ============================================================
# WEB SERVER
# ============================================================

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

    app.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
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

    return runner


# ============================================================
# MAIN
# ============================================================

async def main():

    init_db()

    print(
        "===================================="
    )

    print(
        "Rauda Ilm bot starting..."
    )

    print(
        "Database:",
        DB_FILE
    )

    print(
        "Channel:",
        CHANNEL_ID
    )

    print(
        "Admin:",
        ADMIN_ID
    )

    print(
        "Webhook:",
        WEBHOOK_URL
    )

    print(
        "Duplicate protection: ON"
    )

    print(
        "Deleted book recovery: ON"
    )

    print(
        "===================================="
    )

    # --------------------------------------------------------
    # WEB SERVER ЗАПУСКАЕМ ДО WEBHOOK
    # --------------------------------------------------------

    runner = await start_web_server()

    try:

        # ----------------------------------------------------
        # УДАЛЯЕМ СТАРЫЙ WEBHOOK
        # ----------------------------------------------------

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        # ----------------------------------------------------
        # УСТАНАВЛИВАЕМ WEBHOOK
        # ----------------------------------------------------

        allowed_updates = (
            dp.resolve_used_update_types()
        )

        await bot.set_webhook(
            WEBHOOK_URL,
            allowed_updates=allowed_updates
        )

        print(
            "Webhook successfully configured."
        )

        print(
            "Allowed updates:",
            allowed_updates
        )

        # ----------------------------------------------------
        # ДЕРЖИМ PROCESS ЗАПУЩЕННЫМ
        # ----------------------------------------------------

        while True:

            await asyncio.sleep(
                3600
            )

    finally:

        try:

            await bot.delete_webhook()

        except Exception as e:

            print(
                "WEBHOOK DELETE ERROR:",
                repr(e)
            )

        await runner.cleanup()

        await bot.session.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    with suppress(
        KeyboardInterrupt
    ):

        asyncio.run(
            main()
        )
