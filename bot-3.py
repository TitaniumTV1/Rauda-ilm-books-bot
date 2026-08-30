import os
import sqlite3
import asyncio
import hashlib
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

PORT = int(os.getenv("PORT", "10000"))

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://rauda-ilm-books-bot.onrender.com",
)

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH

# Если на Render подключён Persistent Disk с /var/data,
# база автоматически будет храниться там. Локально остаётся books.db.
DEFAULT_DB_FILE = (
    "/var/data/books.db"
    if os.path.isdir("/var/data")
    else "books.db"
)
DB_FILE = os.getenv("DB_FILE", DEFAULT_DB_FILE)

# Telegram ограничивает inline-клавиатуры и текст сообщений.
BOOKS_PER_PAGE = 10
MAX_TITLE_LENGTH = 300
MAX_AUTHOR_LENGTH = 200
MAX_CATEGORY_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 3000
MAX_FILENAME_LENGTH = 500

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Environment Variables")


# ============================================================
# BOT
# ============================================================

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())
BOOK_INGEST_LOCK = asyncio.Lock()
SEARCH_CACHE = {}


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
# HELPERS
# ============================================================

def clean_text(value, max_length, default=""):
    value = (value or "").strip()
    return value[:max_length]


def safe_title(value):
    value = clean_text(value, MAX_TITLE_LENGTH)
    return value or "Без названия"


def safe_author(value):
    value = clean_text(value, MAX_AUTHOR_LENGTH)
    return value or "Не указан"


def safe_category(value):
    value = clean_text(value, MAX_CATEGORY_LENGTH)
    for category in CATEGORIES:
        if value.casefold() == category.casefold():
            return category
    return "Разное"


def safe_description(value):
    return clean_text(value, MAX_DESCRIPTION_LENGTH)


def safe_filename(value):
    return clean_text(value, MAX_FILENAME_LENGTH, "book.pdf") or "book.pdf"


def is_admin(user_id):
    return user_id == ADMIN_ID


def category_index(value):
    for index, category in enumerate(CATEGORIES):
        if category.casefold() == value.casefold():
            return index
    return len(CATEGORIES) - 1


def page_slice(items, page):
    total_pages = max(1, (len(items) + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * BOOKS_PER_PAGE
    return items[start:start + BOOKS_PER_PAGE], page, total_pages


def navigation_row(prefix, page, total_pages, extra_back=None):
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="Предыдущая", callback_data=f"{prefix}:{page - 1}"))
    if page + 1 < total_pages:
        row.append(InlineKeyboardButton(text="Следующая", callback_data=f"{prefix}:{page + 1}"))
    rows = [row] if row else []
    if extra_back:
        rows.append(extra_back)
    return rows


def book_rows(books):
    rows = []
    for book_id, title, author, category in books:
        rows.append([
            InlineKeyboardButton(
                text=clean_text(title, 50) or "Без названия",
                callback_data=f"book:{book_id}",
            )
        ])
    return rows


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Каталог", callback_data="catalog:0"),
                InlineKeyboardButton(text="Поиск", callback_data="search"),
            ],
            [
                InlineKeyboardButton(text="Новинки", callback_data="new:0"),
                InlineKeyboardButton(text="Категории", callback_data="categories"),
            ],
            [
                InlineKeyboardButton(text="Избранное", callback_data="favorites:0"),
                InlineKeyboardButton(text="Предложить книгу", callback_data="suggest"),
            ],
            [InlineKeyboardButton(text="О библиотеке", callback_data="about")],
        ]
    )


def back_home():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="home")]
        ]
    )


def book_menu(book_id, user_id):
    buttons = [
        [InlineKeyboardButton(text="Скачать PDF", callback_data=f"download:{book_id}")]
    ]

    if is_favorite(user_id, book_id):
        buttons.append([
            InlineKeyboardButton(text="Убрать из избранного", callback_data=f"unfavorite:{book_id}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="В избранное", callback_data=f"favorite:{book_id}")
        ])

    if is_admin(user_id):
        buttons.extend([
            [InlineKeyboardButton(text="Редактировать", callback_data=f"edit:{book_id}")],
            [InlineKeyboardButton(text="Удалить", callback_data=f"delete:{book_id}")],
        ])

    buttons.append([
        InlineKeyboardButton(text="Назад", callback_data="catalog:0"),
        InlineKeyboardButton(text="Меню", callback_data="home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def category_keyboard(prefix):
    rows = []
    for i, category_name in enumerate(CATEGORIES):
        rows.append([
            InlineKeyboardButton(
                text=category_name,
                callback_data=f"{prefix}:{i}",
            )
        ])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_category_keyboard():
    rows = []
    for i, category_name in enumerate(CATEGORIES):
        rows.append([
            InlineKeyboardButton(
                text=category_name,
                callback_data=f"editcat:{i}",
            )
        ])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    directory = os.path.dirname(os.path.abspath(DB_FILE))
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_db()
    try:
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

        # Совместимость со старой базой.
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(books)").fetchall()
        }
        if "channel_message_id" not in columns:
            conn.execute("ALTER TABLE books ADD COLUMN channel_message_id INTEGER")
        if "deleted" not in columns:
            conn.execute("ALTER TABLE books ADD COLUMN deleted INTEGER DEFAULT 0")
        if "file_unique_id" not in columns:
            conn.execute("ALTER TABLE books ADD COLUMN file_unique_id TEXT")

        pending_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pending_books)").fetchall()
        }
        if "file_unique_id" not in pending_columns:
            conn.execute("ALTER TABLE pending_books ADD COLUMN file_unique_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_file_unique_id ON books(file_unique_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_channel_message_id ON books(channel_message_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_deleted ON books(deleted)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_category ON books(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_books(user_id)")

        conn.commit()
    finally:
        conn.close()


# ============================================================
# BOOK FUNCTIONS
# ============================================================

def add_book(title, author, category, description, file_id, file_unique_id=None, channel_message_id=None):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO books
                (title, author, category, description, file_id,
                 file_unique_id, channel_message_id, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                safe_title(title),
                safe_author(author),
                safe_category(category),
                safe_description(description),
                file_id,
                file_unique_id,
                channel_message_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_book(book_id):
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, title, author, category, description, file_id,
                   file_unique_id, channel_message_id, deleted
            FROM books WHERE id = ?
            """,
            (book_id,),
        ).fetchone()
    finally:
        conn.close()


def get_books():
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, title, author, category
            FROM books
            WHERE deleted = 0
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()


def category_books(category):
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, title, author, category
            FROM books
            WHERE category = ? AND deleted = 0
            ORDER BY id DESC
            """,
            (category,),
        ).fetchall()
    finally:
        conn.close()


def search_books(text):
    text = clean_text(text, 100)
    conn = get_db()
    try:
        pattern = f"%{text}%"
        return conn.execute(
            """
            SELECT id, title, author, category
            FROM books
            WHERE deleted = 0
              AND (title LIKE ? OR author LIKE ? OR category LIKE ?)
            ORDER BY id DESC
            """,
            (pattern, pattern, pattern),
        ).fetchall()
    finally:
        conn.close()


def update_book(book_id, title, author, category, description):
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE books
            SET title = ?, author = ?, category = ?, description = ?
            WHERE id = ?
            """,
            (
                safe_title(title),
                safe_author(author),
                safe_category(category),
                safe_description(description),
                book_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_book(book_id):
    conn = get_db()
    try:
        conn.execute("UPDATE books SET deleted = 1 WHERE id = ?", (book_id,))
        conn.commit()
    finally:
        conn.close()


def book_by_channel_message(message_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id FROM books WHERE channel_message_id = ? LIMIT 1",
            (message_id,),
        ).fetchone()
    finally:
        conn.close()


def book_by_file_unique_id(file_unique_id):
    if not file_unique_id:
        return None
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, title, author, category, description, file_id,
                   file_unique_id, channel_message_id, deleted
            FROM books
            WHERE file_unique_id = ?
            ORDER BY id ASC LIMIT 1
            """,
            (file_unique_id,),
        ).fetchone()
    finally:
        conn.close()


def book_by_file_id(file_id):
    if not file_id:
        return None
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, title, author, category, description, file_id,
                   file_unique_id, channel_message_id, deleted
            FROM books
            WHERE file_id = ?
            ORDER BY id ASC LIMIT 1
            """,
            (file_id,),
        ).fetchone()
    finally:
        conn.close()


def restore_book(book_id, file_id=None, file_unique_id=None, channel_message_id=None):
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE books
            SET file_id = COALESCE(?, file_id),
                file_unique_id = COALESCE(?, file_unique_id),
                channel_message_id = COALESCE(?, channel_message_id),
                deleted = 0
            WHERE id = ?
            """,
            (file_id, file_unique_id, channel_message_id, book_id),
        )
        conn.commit()
    finally:
        conn.close()


def restore_book_from_channel(book_id, title, author, category, description,
                              file_id, file_unique_id, channel_message_id):
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE books
            SET title = ?, author = ?, category = ?, description = ?,
                file_id = ?, file_unique_id = ?, channel_message_id = ?,
                deleted = 0
            WHERE id = ?
            """,
            (
                safe_title(title),
                safe_author(author),
                safe_category(category),
                safe_description(description),
                file_id,
                file_unique_id,
                channel_message_id,
                book_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# FAVORITES
# ============================================================

def add_favorite(user_id, book_id):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO favorites(user_id, book_id) VALUES (?, ?)",
            (user_id, book_id),
        )
        conn.commit()
    finally:
        conn.close()


def remove_favorite(user_id, book_id):
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND book_id = ?",
            (user_id, book_id),
        )
        conn.commit()
    finally:
        conn.close()


def is_favorite(user_id, book_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND book_id = ? LIMIT 1",
            (user_id, book_id),
        ).fetchone() is not None
    finally:
        conn.close()


def get_favorites(user_id):
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT books.id, books.title, books.author, books.category
            FROM books
            INNER JOIN favorites ON books.id = favorites.book_id
            WHERE favorites.user_id = ? AND books.deleted = 0
            ORDER BY books.id DESC
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


# ============================================================
# PENDING
# ============================================================

def add_pending(user_id, username, file_id, file_unique_id, file_name):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO pending_books
                (user_id, username, file_id, file_unique_id, file_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                clean_text(username, 300),
                file_id,
                file_unique_id,
                safe_filename(file_name),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_pending(pending_id):
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT id, user_id, username, file_id, file_unique_id, file_name
            FROM pending_books WHERE id = ?
            """,
            (pending_id,),
        ).fetchone()
    finally:
        conn.close()


def delete_pending(pending_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM pending_books WHERE id = ?", (pending_id,))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# STATES
# ============================================================

class SuggestState(StatesGroup):
    waiting_file = State()


class SearchState(StatesGroup):
    waiting = State()


class EditBookState(StatesGroup):
    waiting_title = State()
    waiting_author = State()
    waiting_category = State()
    waiting_description = State()


# ============================================================
# START / HOME / ABOUT
# ============================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую электронную библиотеку.\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "<b>Rauda Ilm</b>\n\n"
        "Добро пожаловать в исламскую электронную библиотеку.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "about")
async def about(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>Rauda Ilm</b>\n\n"
        "Электронная библиотека исламских книг.\n\n"
        "Каталог\n"
        "Поиск\n"
        "Избранное\n"
        "Предложение книг\n"
        "Редактирование\n"
        "Модерация",
        parse_mode="HTML",
        reply_markup=back_home(),
    )
    await callback.answer()


# ============================================================
# SUGGEST BOOK
# ============================================================

@dp.callback_query(F.data == "suggest")
async def suggest(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SuggestState.waiting_file)
    await callback.message.edit_text(
        "<b>Предложить книгу</b>\n\n"
        "Отправьте PDF-файл книги.\n\n"
        "После отправки файл попадёт администратору на модерацию.",
        parse_mode="HTML",
        reply_markup=back_home(),
    )
    await callback.answer()


@dp.message(SuggestState.waiting_file)
async def receive_suggested(message: Message, state: FSMContext):
    if not message.document:
        await message.answer("Отправьте именно PDF-файл.", reply_markup=back_home())
        return

    document = message.document
    file_name = safe_filename(document.file_name)
    if not file_name.lower().endswith(".pdf"):
        await message.answer("Принимаются только PDF-файлы.", reply_markup=back_home())
        return

    existing = book_by_file_unique_id(document.file_unique_id)
    if existing:
        await state.clear()
        if existing[8] == 1:
            restore_book(
                existing[0],
                file_id=document.file_id,
                file_unique_id=document.file_unique_id,
                channel_message_id=existing[7],
            )
            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\nID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        else:
            await message.answer(
                "<b>Эта книга уже есть в каталоге.</b>\n\n"
                f"{escape(existing[1])}\nID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        return

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )
    pending_id = add_pending(
        message.from_user.id,
        username,
        document.file_id,
        document.file_unique_id,
        file_name,
    )
    await state.clear()

    await message.answer(
        "<b>Книга отправлена.</b>\n\nАдминистратор проверит файл.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Одобрить", callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"reject:{pending_id}"),
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
                f"Пользователь: {escape(clean_text(username, 300))}\n"
                f"Файл: {escape(file_name)}"
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as exc:
        print("MODERATION SEND ERROR:", repr(exc))
        # Заявка остаётся в БД, чтобы не потерять книгу.
        await message.answer(
            "Книга сохранена в очередь, но уведомление администратору не отправилось.",
            reply_markup=main_menu(),
        )


# ============================================================
# APPROVE / REJECT
# ============================================================

@dp.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    try:
        pending_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    pending = get_pending(pending_id)
    if not pending:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await callback.message.answer(
        "<b>Выберите категорию:</b>",
        parse_mode="HTML",
        reply_markup=category_keyboard(f"setcat:{pending_id}"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("setcat:"))
async def set_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    try:
        pending_id = int(parts[1])
        index = int(parts[2])
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    if not 0 <= index < len(CATEGORIES):
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    pending = get_pending(pending_id)
    if not pending:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await finalize_pending(callback, pending, CATEGORIES[index], notify_user=True)


@dp.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    try:
        pending_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    pending = get_pending(pending_id)
    if not pending:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    user_id = pending[1]
    file_name = pending[5]
    delete_pending(pending_id)

    try:
        await bot.send_message(
            user_id,
            "<b>Книга отклонена.</b>\n\n"
            f"Файл: {escape(file_name)}",
            parse_mode="HTML",
        )
    except Exception as exc:
        print("REJECT NOTIFICATION ERROR:", repr(exc))

    await callback.message.edit_text(
        "<b>Книга отклонена.</b>\n\n"
        f"Файл: {escape(file_name)}",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer("Отклонено.")


async def finalize_pending(callback, pending, category, notify_user=False):
    async with BOOK_INGEST_LOCK:
        await _finalize_pending_locked(callback, pending, category, notify_user)


async def _finalize_pending_locked(callback, pending, category, notify_user=False):
    pending_id = pending[0]
    user_id = pending[1]
    file_id = pending[3]
    file_unique_id = pending[4]
    file_name = pending[5]

    # Повторная проверка непосредственно перед сохранением.
    existing = book_by_file_unique_id(file_unique_id)
    if existing:
        if existing[8] == 1:
            restore_book(existing[0], file_id=file_id, file_unique_id=file_unique_id,
                         channel_message_id=existing[7])
            delete_pending(pending_id)
            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\nID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
            await callback.answer("Восстановлено.")
            return

        delete_pending(pending_id)
        await callback.message.edit_text(
            "<b>Этот PDF уже есть в каталоге.</b>\n\n"
            f"{escape(existing[1])}\nID: {existing[0]}",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await callback.answer("Дубликат не добавлен.")
        return

    existing_old = book_by_file_id(file_id)
    if existing_old:
        if existing_old[8] == 1:
            restore_book(existing_old[0], file_id=file_id, file_unique_id=file_unique_id,
                         channel_message_id=existing_old[7])
            delete_pending(pending_id)
            await callback.message.edit_text(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing_old[1])}\nID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
            await callback.answer("Восстановлено.")
            return

        delete_pending(pending_id)
        await callback.message.edit_text(
            "<b>Этот PDF уже есть в каталоге.</b>\n\n"
            f"{escape(existing_old[1])}\nID: {existing_old[0]}",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await callback.answer("Дубликат не добавлен.")
        return

    title = safe_title(os.path.splitext(file_name)[0])
    category = safe_category(category)

    try:
        channel_message = await bot.send_document(
            CHANNEL_ID,
            document=file_id,
            caption=(
                f"Название: {escape(title)}\n"
                "Автор: Не указан\n"
                f"Категория: {escape(category)}"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        print("CHANNEL UPLOAD ERROR:", repr(exc))
        await callback.answer("Не удалось сохранить PDF в канал.", show_alert=True)
        return

    try:
        book_id = add_book(
            title=title,
            author="Не указан",
            category=category,
            description="",
            file_id=file_id,
            file_unique_id=file_unique_id,
            channel_message_id=channel_message.message_id,
        )
    except Exception as exc:
        # Файл уже находится в канале; pending НЕ удаляем, чтобы можно было
        # повторить обработку после временной ошибки БД.
        print("BOOK INSERT ERROR:", repr(exc))
        await callback.answer("PDF сохранён в канал, но запись в БД не создана. Повторите действие.", show_alert=True)
        return

    delete_pending(pending_id)

    if notify_user:
        try:
            await bot.send_message(
                user_id,
                "<b>Ваша книга одобрена.</b>\n\n"
                f"Название: {escape(title)}\n"
                f"Категория: {escape(category)}\n\n"
                "Она добавлена в каталог.",
                parse_mode="HTML",
            )
        except Exception as exc:
            print("USER NOTIFICATION ERROR:", repr(exc))

    await callback.message.edit_text(
        "<b>Книга добавлена.</b>\n\n"
        f"{escape(title)}\n"
        f"Категория: {escape(category)}\n"
        f"ID: {book_id}",
        parse_mode="HTML",
        reply_markup=book_menu(book_id, ADMIN_ID),
    )
    await callback.answer("Добавлено.")


# ============================================================
# CHANNEL PDF INGESTION
# ============================================================

@dp.channel_post()
async def channel_pdf(message: Message):
    async with BOOK_INGEST_LOCK:
        await _channel_pdf_locked(message)


async def _channel_pdf_locked(message: Message):
    if message.chat.id != CHANNEL_ID or not message.document:
        return

    document = message.document
    file_name = safe_filename(document.file_name)
    if not file_name.lower().endswith(".pdf"):
        return

    if book_by_channel_message(message.message_id):
        return

    caption = message.caption or ""
    title = safe_title(os.path.splitext(file_name)[0])
    author = "Не указан"
    category = "Разное"
    description = ""

    for line in caption.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold()
        value = value.strip()
        if key in ("название", "название книги") and value:
            title = safe_title(value)
        elif key == "автор" and value:
            author = safe_author(value)
        elif key in ("категория", "раздел") and value:
            category = safe_category(value)
        elif key == "описание":
            description = safe_description(value)

    existing = book_by_file_unique_id(document.file_unique_id)
    if existing:
        if existing[8] == 1:
            restore_book_from_channel(
                existing[0], title, author, category, description,
                document.file_id, document.file_unique_id, message.message_id,
            )
            print("BOOK RESTORED FROM CHANNEL:", existing[0], title)
        else:
            print("DUPLICATE PDF SKIPPED:", existing[0], title)
        return

    existing_old = book_by_file_id(document.file_id)
    if existing_old:
        if existing_old[8] == 1:
            restore_book_from_channel(
                existing_old[0], title, author, category, description,
                document.file_id, document.file_unique_id, message.message_id,
            )
            print("OLD BOOK RESTORED:", existing_old[0], title)
        else:
            print("OLD FILE ID DUPLICATE SKIPPED:", existing_old[0])
        return

    try:
        book_id = add_book(
            title=title,
            author=author,
            category=category,
            description=description,
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            channel_message_id=message.message_id,
        )
        print("CHANNEL BOOK ADDED:", book_id, title, category)
    except Exception as exc:
        print("CHANNEL BOOK INSERT ERROR:", repr(exc))


# ============================================================
# CATALOG
# ============================================================

async def render_catalog(target, page=0, answer_callback=None):
    books = get_books()
    visible, page, total_pages = page_slice(books, page)
    rows = book_rows(visible)
    rows += navigation_row(
        "catalog",
        page,
        total_pages,
        [InlineKeyboardButton(text="Главное меню", callback_data="home")],
    )
    text = f"<b>Каталог</b>\n\nВыберите книгу:\nСтраница {page + 1} из {total_pages}"
    if not books:
        text = "<b>Каталог</b>\n\nКниг пока нет."
        rows = [[InlineKeyboardButton(text="Главное меню", callback_data="home")]]

    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        await target.answer()
    else:
        await target.edit_text(text, parse_mode="HTML", reply_markup=markup)


@dp.callback_query(F.data.regexp(r"^catalog(?::\d+)?$"))
async def catalog(callback: CallbackQuery):
    try:
        page = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    except ValueError:
        page = 0
    await render_catalog(callback, page)


# ============================================================
# SHOW / DOWNLOAD / FAVORITE
# ============================================================

@dp.callback_query(F.data.startswith("book:"))
async def show_book(callback: CallbackQuery):
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга не найдена.", show_alert=True)
        return

    text = (
        f"<b>{escape(book[1])}</b>\n\n"
        f"Автор: {escape(book[2])}\n"
        f"Категория: {escape(book[3])}"
    )
    if book[4]:
        text += f"\n\n{escape(book[4])}"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=book_menu(book_id, callback.from_user.id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("download:"))
async def download(callback: CallbackQuery):
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга не найдена.", show_alert=True)
        return

    try:
        await callback.message.answer_document(
            document=book[5],
            caption=f"<b>{escape(book[1])}</b>\n{escape(book[2])}",
            parse_mode="HTML",
        )
        await callback.answer()
    except Exception as exc:
        print("DOWNLOAD ERROR:", repr(exc))
        await callback.answer("Не удалось отправить PDF.", show_alert=True)


@dp.callback_query(F.data.startswith("favorite:"))
async def favorite(callback: CallbackQuery):
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return
    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга не найдена.", show_alert=True)
        return
    add_favorite(callback.from_user.id, book_id)
    await callback.message.edit_reply_markup(reply_markup=book_menu(book_id, callback.from_user.id))
    await callback.answer("Добавлено.")


@dp.callback_query(F.data.startswith("unfavorite:"))
async def unfavorite(callback: CallbackQuery):
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return
    remove_favorite(callback.from_user.id, book_id)
    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга больше недоступна.")
        return
    await callback.message.edit_reply_markup(reply_markup=book_menu(book_id, callback.from_user.id))
    await callback.answer("Убрано.")


# ============================================================
# FAVORITES
# ============================================================

@dp.callback_query(F.data.regexp(r"^favorites(?::\d+)?$"))
async def favorites(callback: CallbackQuery):
    try:
        page = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    except ValueError:
        page = 0

    books = get_favorites(callback.from_user.id)
    visible, page, total_pages = page_slice(books, page)
    rows = book_rows(visible)
    rows += navigation_row(
        "favorites",
        page,
        total_pages,
        [InlineKeyboardButton(text="Меню", callback_data="home")],
    )
    if not books:
        text = "<b>Избранное</b>\n\nУ вас пока нет избранных книг."
        rows = [[InlineKeyboardButton(text="Меню", callback_data="home")]]
    else:
        text = f"<b>Избранное</b>\n\nВаши книги:\nСтраница {page + 1} из {total_pages}"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ============================================================
# CATEGORIES
# ============================================================

@dp.callback_query(F.data == "categories")
async def categories(callback: CallbackQuery):
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"category:{i}:0")]
        for i, name in enumerate(CATEGORIES)
    ]
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="home")])
    await callback.message.edit_text(
        "<b>Категории</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@dp.callback_query(F.data.regexp(r"^category:\d+:\d+$"))
async def category(callback: CallbackQuery):
    parts = callback.data.split(":")
    try:
        index = int(parts[1])
        page = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("Некорректная категория.", show_alert=True)
        return

    if not 0 <= index < len(CATEGORIES):
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    category_name = CATEGORIES[index]
    books = category_books(category_name)
    visible, page, total_pages = page_slice(books, page)
    rows = book_rows(visible)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="Предыдущая", callback_data=f"category:{index}:{page - 1}"))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="Следующая", callback_data=f"category:{index}:{page + 1}"))
        if nav:
            rows.append(nav)
    rows.extend([
        [InlineKeyboardButton(text="Категории", callback_data="categories")],
        [InlineKeyboardButton(text="Меню", callback_data="home")],
    ])

    text = f"<b>{escape(category_name)}</b>\n\nКниги:"
    if books:
        text += f"\nСтраница {page + 1} из {total_pages}"
    else:
        text += "\nКниг пока нет."

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ============================================================
# NEW BOOKS
# ============================================================

@dp.callback_query(F.data.regexp(r"^new(?::\d+)?$"))
async def new_books(callback: CallbackQuery):
    try:
        page = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    except ValueError:
        page = 0

    books = get_books()
    visible, page, total_pages = page_slice(books, page)
    # Новинки показываем от самых новых, но не ограничиваем каталог десятью.
    rows = book_rows(visible)
    rows += navigation_row(
        "new",
        page,
        total_pages,
        [InlineKeyboardButton(text="Главное меню", callback_data="home")],
    )
    text = f"<b>Последние книги</b>\n\nНовые поступления:\nСтраница {page + 1} из {total_pages}"
    if not books:
        text = "<b>Новинки</b>\n\nКниг пока нет."
        rows = [[InlineKeyboardButton(text="Главное меню", callback_data="home")]]

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ============================================================
# SEARCH
# ============================================================

@dp.callback_query(F.data == "search")
async def search_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SearchState.waiting)
    await callback.message.edit_text(
        "<b>Поиск</b>\n\nВведите название книги, автора или категорию:",
        parse_mode="HTML",
        reply_markup=back_home(),
    )
    await callback.answer()


@dp.message(SearchState.waiting)
async def search_result(message: Message, state: FSMContext):
    text = clean_text(message.text, 100)
    if not text:
        await message.answer("Введите текст для поиска.", reply_markup=back_home())
        return

    books = search_books(text)
    await state.clear()
    visible, page, total_pages = page_slice(books, 0)
    rows = book_rows(visible)

    if books:
        if total_pages > 1:
            token = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
            SEARCH_CACHE[token] = text
            rows.append([
                InlineKeyboardButton(text="Следующая", callback_data=f"searchpage:{token}:1")
            ])
        rows.append([InlineKeyboardButton(text="Главное меню", callback_data="home")])
        await message.answer(
            f"<b>Результаты:</b> {escape(text)}\nСтраница 1 из {total_pages}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    else:
        await message.answer("Ничего не найдено.", reply_markup=main_menu())


@dp.callback_query(F.data.startswith("searchpage:"))
async def search_page(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Некорректный поиск.", show_alert=True)
        return
    token = parts[1]
    text = SEARCH_CACHE.get(token)
    if text is None:
        await callback.answer("Поиск устарел. Выполните поиск заново.", show_alert=True)
        return
    try:
        page = int(parts[2])
    except ValueError:
        page = 0

    books = search_books(text)
    visible, page, total_pages = page_slice(books, page)
    rows = book_rows(visible)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="Предыдущая", callback_data=f"searchpage:{token}:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="Следующая", callback_data=f"searchpage:{token}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="home")])

    await callback.message.edit_text(
        f"<b>Результаты:</b> {escape(text)}\nСтраница {page + 1} из {total_pages}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ============================================================
# DELETE
# ============================================================

@dp.callback_query(F.data.startswith("delete:"))
async def delete_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга не найдена.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"confirm_delete:{book_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"cancel_delete:{book_id}")],
        ]
    )
    await callback.message.edit_text(
        "<b>Удалить книгу?</b>\n\n"
        f"<b>{escape(book[1])}</b>\n"
        f"Категория: {escape(book[3])}\n\n"
        "Книга исчезнет из каталога.\n"
        "PDF в канале останется.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete:"))
async def confirm_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book:
        await callback.answer("Книга не найдена.", show_alert=True)
        return
    if book[8] == 1:
        await callback.answer("Книга уже удалена.", show_alert=True)
        return

    title = book[1]
    delete_book(book_id)
    await callback.message.edit_text(
        "<b>Книга удалена из каталога.</b>\n\n"
        f"{escape(title)}\n\n"
        "PDF в канале сохранён.\n"
        "Если тот же PDF снова будет обработан ботом, книга восстановится.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer("Удалено.")


@dp.callback_query(F.data.startswith("cancel_delete:"))
async def cancel_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.message.edit_text("Книга не найдена.", reply_markup=main_menu())
        await callback.answer()
        return

    await callback.message.edit_text(
        f"<b>{escape(book[1])}</b>\n\nУдаление отменено.",
        parse_mode="HTML",
        reply_markup=book_menu(book_id, ADMIN_ID),
    )
    await callback.answer("Отменено.")


# ============================================================
# EDIT
# ============================================================

@dp.callback_query(F.data.startswith("edit:"))
async def edit_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        book_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная книга.", show_alert=True)
        return

    book = get_book(book_id)
    if not book or book[8] == 1:
        await callback.answer("Книга не найдена.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        book_id=book_id,
        old_title=book[1],
        old_author=book[2],
        old_category=book[3],
        old_description=book[4],
    )
    await state.set_state(EditBookState.waiting_title)

    await callback.message.edit_text(
        "<b>Редактирование</b>\n\n"
        "Текущее название:\n"
        f"<b>{escape(book[1])}</b>\n\n"
        "Отправьте новое название.",
        parse_mode="HTML",
        reply_markup=back_home(),
    )
    await callback.answer()


@dp.message(EditBookState.waiting_title)
async def edit_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    title = clean_text(message.text, MAX_TITLE_LENGTH)
    if not title:
        await message.answer("Название не может быть пустым.", reply_markup=back_home())
        return
    await state.update_data(title=title)
    data = await state.get_data()
    await state.set_state(EditBookState.waiting_author)
    await message.answer(
        "<b>Автор</b>\n\n"
        f"Сейчас: <b>{escape(data['old_author'])}</b>\n\n"
        "Отправьте нового автора.\nЕсли автора нет — напишите «нет».",
        parse_mode="HTML",
        reply_markup=back_home(),
    )


@dp.message(EditBookState.waiting_author)
async def edit_author(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    author = clean_text(message.text, MAX_AUTHOR_LENGTH)
    if author.casefold() == "нет" or not author:
        author = "Не указан"
    await state.update_data(author=author)
    await state.set_state(EditBookState.waiting_category)
    await message.answer(
        "<b>Выберите новую категорию:</b>",
        parse_mode="HTML",
        reply_markup=edit_category_keyboard(),
    )


@dp.callback_query(EditBookState.waiting_category, F.data.startswith("editcat:"))
async def edit_category(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        index = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная категория.", show_alert=True)
        return
    if not 0 <= index < len(CATEGORIES):
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.update_data(category=CATEGORIES[index])
    await state.set_state(EditBookState.waiting_description)
    await callback.message.edit_text(
        "<b>Описание</b>\n\n"
        "Отправьте новое описание.\n\n"
        "Если описание не нужно — напишите <code>нет</code>.",
        parse_mode="HTML",
        reply_markup=back_home(),
    )
    await callback.answer()


@dp.message(EditBookState.waiting_description)
async def edit_description(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    description = clean_text(message.text, MAX_DESCRIPTION_LENGTH)
    if description.casefold() == "нет":
        description = ""

    data = await state.get_data()
    book_id = data.get("book_id")
    if not book_id:
        await state.clear()
        await message.answer("Сессия редактирования устарела.", reply_markup=main_menu())
        return

    update_book(book_id, data["title"], data["author"], data["category"], description)
    await state.clear()
    book = get_book(book_id)

    # Синхронизируем подпись PDF в постоянном канале.
    # Если сообщение в канале было удалено/недоступно, каталог всё равно обновляется.
    if book and book[7]:
        try:
            caption = (
                f"Название: {escape(book[1])}\n"
                f"Автор: {escape(book[2])}\n"
                f"Категория: {escape(book[3])}"
            )
            if book[4]:
                caption += f"\nОписание: {escape(book[4])}"
            await bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=book[7],
                caption=caption[:1024],
                parse_mode="HTML",
            )
        except Exception as exc:
            print("CHANNEL CAPTION UPDATE ERROR:", repr(exc))
    if not book or book[8] == 1:
        await message.answer("Книга не найдена.", reply_markup=main_menu())
        return

    text = (
        "<b>Книга изменена.</b>\n\n"
        f"<b>{escape(book[1])}</b>\n"
        f"Автор: {escape(book[2])}\n"
        f"Категория: {escape(book[3])}"
    )
    if book[4]:
        text += f"\n\n{escape(book[4])}"
    await message.answer(text, parse_mode="HTML", reply_markup=book_menu(book_id, ADMIN_ID))


# ============================================================
# ADMIN DIRECT PDF
# ============================================================

@dp.message(F.document, F.from_user.id == ADMIN_ID)
async def admin_direct_pdf(message: Message):
    document = message.document
    file_name = safe_filename(document.file_name)

    if not file_name.lower().endswith(".pdf"):
        await message.answer("Принимаются только PDF-файлы.", reply_markup=main_menu())
        return

    existing = book_by_file_unique_id(document.file_unique_id)
    if existing:
        if existing[8] == 1:
            restore_book(existing[0], file_id=document.file_id,
                         file_unique_id=document.file_unique_id,
                         channel_message_id=existing[7])
            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing[1])}\nID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        else:
            await message.answer(
                "<b>Этот PDF уже есть в каталоге.</b>\n\n"
                f"{escape(existing[1])}\nID: {existing[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        return

    existing_old = book_by_file_id(document.file_id)
    if existing_old:
        if existing_old[8] == 1:
            restore_book(existing_old[0], file_id=document.file_id,
                         file_unique_id=document.file_unique_id,
                         channel_message_id=existing_old[7])
            await message.answer(
                "<b>Книга восстановлена.</b>\n\n"
                f"{escape(existing_old[1])}\nID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        else:
            await message.answer(
                "<b>Этот PDF уже есть в каталоге.</b>\n\n"
                f"{escape(existing_old[1])}\nID: {existing_old[0]}",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
        return

    pending_id = add_pending(
        ADMIN_ID,
        "ADMIN",
        document.file_id,
        document.file_unique_id,
        file_name,
    )
    rows = [
        [
            InlineKeyboardButton(
                text=category_name,
                callback_data=f"directcat:{pending_id}:{i}",
            )
        ]
        for i, category_name in enumerate(CATEGORIES)
    ]
    rows.append([
        InlineKeyboardButton(text="Отмена", callback_data=f"directcancel:{pending_id}")
    ])
    await message.answer(
        "<b>PDF получен.</b>\n\nВыберите категорию:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("directcat:"))
async def direct_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    try:
        pending_id = int(parts[1])
        category_index_value = int(parts[2])
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    if not 0 <= category_index_value < len(CATEGORIES):
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    pending = get_pending(pending_id)
    if not pending:
        await callback.answer("Файл уже обработан.", show_alert=True)
        return

    await finalize_pending(callback, pending, CATEGORIES[category_index_value])


@dp.callback_query(F.data.startswith("directcancel:"))
async def direct_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        pending_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    pending = get_pending(pending_id)
    if pending:
        delete_pending(pending_id)
    await callback.message.edit_text(
        "<b>Добавление отменено.</b>",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer("Отменено.")


# ============================================================
# HEALTH / WEBHOOK
# ============================================================

async def health(request):
    return web.Response(text="OK")


async def telegram_webhook(request):
    if WEBHOOK_SECRET:
        received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if received_secret != WEBHOOK_SECRET:
            return web.Response(text="Forbidden", status=403)

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response(text="OK")
    except Exception as exc:
        print("WEBHOOK ERROR:", repr(exc))
        return web.Response(text="ERROR", status=500)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"HTTP server started on port {PORT}")
    return runner


# ============================================================
# MAIN
# ============================================================

async def main():
    init_db()

    print("====================================")
    print("Rauda Ilm bot starting...")
    print("Database:", DB_FILE)
    print("Channel:", CHANNEL_ID)
    print("Admin:", ADMIN_ID)
    print("Webhook:", WEBHOOK_URL)
    print("Webhook secret:", "ON" if WEBHOOK_SECRET else "OFF")
    print("Duplicate protection: ON")
    print("Deleted book recovery: ON")
    print("====================================")

    runner = await start_web_server()

    try:
        await bot.delete_webhook(drop_pending_updates=True)

        allowed_updates = dp.resolve_used_update_types()
        await bot.set_webhook(
            WEBHOOK_URL,
            allowed_updates=allowed_updates,
            **({"secret_token": WEBHOOK_SECRET} if WEBHOOK_SECRET else {}),
        )

        print("Webhook successfully configured.")
        print("Allowed updates:", allowed_updates)

        while True:
            await asyncio.sleep(3600)
    finally:
        with suppress(Exception):
            await bot.delete_webhook()
        with suppress(Exception):
            await runner.cleanup()
        with suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
