
import asyncio
import logging
import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from html import escape
from html.parser import HTMLParser

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = Path(__file__).with_name(
    os.getenv("DATABASE_PATH", "orders.db")
)

if not TOKEN or not ADMIN_ID:
    raise RuntimeError("Заполни BOT_TOKEN и ADMIN_ID в .env")

dp = Dispatcher()
logging.basicConfig(level=logging.INFO)


async def safe_edit_text(message: Message, *args, **kwargs):
    """Repeated navigation may request the same text and keyboard."""
    try:
        return await message.edit_text(*args, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise
        return None


def database():
    return sqlite3.connect(DB_PATH)


def init_db():
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                product TEXT,
                description TEXT,
                dimensions TEXT,
                color TEXT,
                quantity INTEGER,
                painting TEXT,
                deadline TEXT,
                attachments TEXT,
                status TEXT DEFAULT 'Принят',
                created_at TEXT
            )
        """)
        # Additive migration: keep every existing order and all original fields.
        columns = {row[1] for row in db.execute("PRAGMA table_info(orders)")}
        if "source" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN source TEXT")


class Order(StatesGroup):
    product = State()
    description = State()
    dimensions = State()
    color = State()
    quantity = State()
    painting = State()
    deadline = State()
    attachments = State()
    confirmation = State()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🌸 Оформить заказ", callback_data="new_order"
        )],
        [InlineKeyboardButton(
            text="📦 Мои заказы", callback_data="my_orders"
        )],
        [InlineKeyboardButton(
            text="❓ Помощь", callback_data="help"
        )],
    ])


def product_menu():
    products = [
        ("🐈 Фигурка", "Фигурка"),
        ("🎁 Сувенир", "Сувенир"),
        ("🌸 Декор", "Декор"),
        ("🖨 Печать своей модели", "Своя модель"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=label, callback_data=f"product:{value}"
        )]
        for label, value in products
    ])


def choice_menu(prefix, values):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=value, callback_data=f"{prefix}:{value}"
        )]
        for value in values
    ])


def order_text(data):
    def safe(key):
        return escape(str(data[key]))

    return (
        "🛒 <b>Заказ SORA LAB</b>\n\n"
        f"Изделие: {safe('product')}\n"
        f"Описание: {safe('description')}\n"
        f"Размер: {safe('dimensions')}\n"
        f"Цвет: {safe('color')}\n"
        f"Количество: {safe('quantity')}\n"
        f"Покраска: {safe('painting')}\n"
        f"Срок: {safe('deadline')}\n"
        f"Вложений: {len(data.get('attachments', []))}"
    )

ORDER_SOURCES = {
    "site": "Сайт soralab.ru",
    "channel": "Telegram-канал @soralab3d",
    "direct": "Прямой вход в бота",
}


def order_source_label(source):
    return ORDER_SOURCES.get(source, "Не указан")


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject):
    await state.clear()
    source = command.args if command.args in {"site", "channel"} else "direct"
    await state.update_data(source=source)
    if source in {"site", "channel"}:
        await state.set_state(Order.product)
        await message.answer(
            "🌸 Добро пожаловать в SORA LAB!\nЧто хотите заказать?",
            reply_markup=product_menu(),
        )
        return
    await message.answer(
        "🐈 <b>Добро пожаловать в SORA LAB!</b> 🌸\n\n"
        "Здесь можно заказать фигурку, сувенир, декор "
        "или 3D-печать по своей модели.\n\n"
        "Выбери действие:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "🌸 <b>Помощь SORA LAB</b>\n\n"
        "/start — главное меню\n"
        "/order — оформить заказ\n"
        "/status — мои заказы\n"
        "/cancel — отменить заполнение\n\n"
        "Стоимость рассчитывается мастером после "
        "проверки заявки.",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "help")
async def help_button(call: CallbackQuery):
    await call.answer()
    await help_command(call.message)


@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Оформление отменено.",
        reply_markup=main_menu()
    )


@dp.message(Command("order"))
async def order_command(message: Message, state: FSMContext):
    source = (await state.get_data()).get("source", "direct")
    await state.clear()
    await state.update_data(source=source)
    await state.set_state(Order.product)
    await message.answer(
        "🌸 Что хотите заказать?",
        reply_markup=product_menu()
    )


@dp.callback_query(F.data == "new_order")
async def new_order(call: CallbackQuery, state: FSMContext):
    await call.answer()
    source = (await state.get_data()).get("source", "direct")
    await state.clear()
    await state.update_data(source=source)
    await state.set_state(Order.product)
    await call.message.answer(
        "🌸 Что хотите заказать?",
        reply_markup=product_menu()
    )


@dp.callback_query(Order.product, F.data.startswith("product:"))
async def select_product(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(product=call.data.split(":", 1)[1])
    await state.set_state(Order.description)
    await call.message.answer(
        "✏️ Опишите изделие.\n"
        "Например: фигурка кота с сакурой на подставке."
    )


@dp.message(Order.description, F.text)
async def description(message: Message, state: FSMContext):
    await state.update_data(description=message.text[:2000])
    await state.set_state(Order.dimensions)
    await message.answer(
        "📏 Укажите размеры в сантиметрах.\n"
        "Например: высота 15 см."
    )


@dp.message(Order.dimensions, F.text)
async def dimensions(message: Message, state: FSMContext):
    await state.update_data(dimensions=message.text[:200])
    await state.set_state(Order.color)
    await message.answer(
        "🎨 Какой цвет нужен?\n"
        "Можно указать несколько цветов."
    )


@dp.message(Order.color, F.text)
async def color(message: Message, state: FSMContext):
    await state.update_data(color=message.text[:200])
    await state.set_state(Order.quantity)
    await message.answer("🔢 Сколько экземпляров нужно?")


@dp.message(Order.quantity, F.text)
async def quantity(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if not 1 <= count <= 1000:
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 1 до 1000.")
        return

    await state.update_data(quantity=count)
    await state.set_state(Order.painting)
    await message.answer(
        "🖌 Нужна ли ручная покраска?",
        reply_markup=choice_menu("paint", ["Да", "Нет", "Обсудить"])
    )


@dp.callback_query(Order.painting, F.data.startswith("paint:"))
async def painting(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(painting=call.data.split(":", 1)[1])
    await state.set_state(Order.deadline)
    await call.message.answer(
        "📅 К какому сроку нужно изделие?\n"
        "Если не срочно, напишите «Не срочно»."
    )


@dp.message(Order.deadline, F.text)
async def deadline(message: Message, state: FSMContext):
    await state.update_data(
        deadline=message.text[:200],
        attachments=[]
    )
    await state.set_state(Order.attachments)
    await message.answer(
        "📸 Пришлите фотографии, референсы или файлы "
        "STL/3MF по одному.\n\n"
        "Когда закончите, нажмите кнопку.",
        reply_markup=choice_menu("files", ["Готово"])
    )


@dp.message(Order.attachments, F.photo | F.document)
async def receive_attachment(message: Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])

    if len(attachments) >= 10:
        await message.answer("Максимум 10 вложений.")
        return

    if message.photo:
        attachments.append({
            "type": "photo",
            "file_id": message.photo[-1].file_id
        })
    elif message.document:
        name = message.document.file_name or ""
        allowed = (".stl", ".3mf", ".png", ".jpg", ".jpeg", ".webp")
        if not name.lower().endswith(allowed):
            await message.answer(
                "Поддерживаются STL, 3MF, JPG, PNG и WEBP."
            )
            return
        attachments.append({
            "type": "document",
            "file_id": message.document.file_id
        })

    await state.update_data(attachments=attachments)
    await message.answer(
        f"✅ Файл добавлен ({len(attachments)}/10).\n"
        "Отправьте следующий или нажмите «Готово».",
        reply_markup=choice_menu("files", ["Готово"])
    )


@dp.callback_query(Order.attachments, F.data == "files:Готово")
async def finish_files(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    await state.set_state(Order.confirmation)
    await call.message.answer(
        order_text(data) + "\n\nВсё правильно?",
        parse_mode="HTML",
        reply_markup=choice_menu(
            "confirm", ["Подтвердить", "Отменить"]
        )
    )


@dp.callback_query(Order.confirmation, F.data.startswith("confirm:"))
async def confirm_order(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()

    if call.data == "confirm:Отменить":
        await state.clear()
        await call.message.answer(
            "Заказ отменён.", reply_markup=main_menu()
        )
        return

    data = await state.get_data()
    user = call.from_user

    with database() as db:
        cursor = db.execute("""
            INSERT INTO orders (
                user_id, username, product, description,
                dimensions, color, quantity, painting,
                deadline, attachments, created_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user.id, user.username, data["product"],
            data["description"], data["dimensions"],
            data["color"], data["quantity"],
            data["painting"], data["deadline"],
            json.dumps(data.get("attachments", [])),
            datetime.now().isoformat(timespec="seconds"),
            data.get("source", "direct")
        ))
        order_id = cursor.lastrowid

    await state.clear()
    await call.message.answer(
        f"🌸 <b>Заказ №{order_id} принят!</b>\n\n"
        "Мастер проверит заявку и свяжется с вами "
        "для согласования стоимости и сроков.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔔 <b>Новый заказ №{order_id}</b>\n"
            f"Клиент: @{user.username or 'без username'}\n"
            f"Telegram ID: <code>{user.id}</code>\n\n"
            f"Источник: {escape(order_source_label(data.get('source', 'direct')))}\n\n"
            + order_text(data),
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(order_id)
        )
        for attachment in data.get("attachments", []):
            if attachment["type"] == "photo":
                await bot.send_photo(
                    ADMIN_ID, attachment["file_id"]
                )
            else:
                await bot.send_document(
                    ADMIN_ID, attachment["file_id"]
                )
    except Exception:
        logging.exception(
            "Не удалось отправить уведомление о заказе %s",
            order_id
        )


async def show_orders(message: Message, user_id: int):
    with database() as db:
        rows = db.execute("""
            SELECT id, product, status
            FROM orders WHERE user_id = ?
            ORDER BY id DESC LIMIT 10
        """, (user_id,)).fetchall()

    if not rows:
        await message.answer("📦 У вас пока нет заказов.")
        return

    text = "📦 <b>Ваши заказы:</b>\n\n"
    for order_id, product, status in rows:
        text += f"№{order_id} — {product} — {status}\n"

    await message.answer(text, parse_mode="HTML")


@dp.message(Command("status"))
async def status_command(message: Message):
    await show_orders(message, message.from_user.id)


@dp.callback_query(F.data == "my_orders")
async def my_orders(call: CallbackQuery):
    await call.answer()
    await show_orders(call.message, call.from_user.id)


@dp.message(Command("orders"))
async def admin_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    with database() as db:
        rows = db.execute("""
            SELECT id, user_id, product, status
            FROM orders ORDER BY id DESC LIMIT 20
        """).fetchall()

    if not rows:
        await message.answer("Заявок пока нет.")
        return

    lines = ["📋 Последние заявки:\n"]
    for order_id, user_id, product, status in rows:
        lines.append(
            f"№{order_id} | {product} | {status} | ID {user_id}"
        )

    await message.answer("\n".join(lines))


STATUSES = {
    "accepted": "Принят",
    "discussion": "Согласование",
    "printing": "В печати",
    "ready": "Готов",
    "completed": "Выдан",
    "cancelled": "Отменён",
}


@dp.message(Command("setstatus"))
async def set_status(message: Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return

    args = (message.text or "").split()
    if len(args) != 3 or not args[1].isdigit() or args[2] not in STATUSES:
        await message.answer(
            "Формат: /setstatus НОМЕР СТАТУС\n\n"
            "Статусы: accepted, discussion, printing, "
            "ready, completed, cancelled\n\n"
            "Пример: /setstatus 1 printing"
        )
        return

    order_id = int(args[1])
    new_status = STATUSES[args[2]]

    with database() as db:
        row = db.execute(
            "SELECT user_id FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()
        if row:
            db.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (new_status, order_id)
            )

    if not row:
        await message.answer("Заказ не найден.")
        return

    await message.answer(
        f"✅ Статус заказа №{order_id}: {new_status}"
    )
    try:
        await bot.send_message(
            row[0],
            f"🌸 SORA LAB\n"
            f"Статус заказа №{order_id} изменён: {new_status}"
        )
    except Exception:
        logging.exception("Не удалось уведомить клиента")


# ── Админ-панель SORA LAB ───────────────────────────────────────
ADMIN_PAGE_SIZE = 8


def admin_home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Открыть список заказов", callback_data="adm:list:0")],
    ])


def admin_order_keyboard(order_id: int, page: int = 0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Подробнее", callback_data=f"adm:view:{order_id}:{page}")],
        [InlineKeyboardButton(text="📎 Вложения", callback_data=f"adm:files:{order_id}:{page}")],
        [InlineKeyboardButton(text="🔄 Изменить статус", callback_data=f"adm:statuses:{order_id}:{page}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data=f"adm:list:{page}")],
    ])


def admin_status_keyboard(order_id: int, page: int):
    rows = [
        [InlineKeyboardButton(text=f"{'✅' if code == 'ready' else '🔹'} {name}",
                              callback_data=f"adm:set:{order_id}:{code}:{page}")]
        for code, name in STATUSES.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад к заказу", callback_data=f"adm:view:{order_id}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_order(order_id: int):
    with database() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


def admin_order_text(order):
    def val(key):
        return escape(str(order.get(key) if order.get(key) is not None else "—"))

    try:
        attachments = json.loads(order.get("attachments") or "[]")
        if not isinstance(attachments, list):
            attachments = []
    except (ValueError, TypeError):
        attachments = []

    username = order.get("username")
    user_label = "@" + escape(username) if username else "Без username"
    return (
        f"📦 <b>Заказ №{val('id')}</b>\n\n"
        f"👤 Клиент: {user_label}\n"
        f"🆔 Telegram ID: <code>{val('user_id')}</code>\n"
        f"🔗 Источник: {escape(order_source_label(order.get('source')))}\n"
        f"🧸 Изделие: {val('product')}\n"
        f"📝 Описание: {val('description')}\n"
        f"📏 Размеры: {val('dimensions')}\n"
        f"🎨 Цвет: {val('color')}\n"
        f"🔢 Количество: {val('quantity')}\n"
        f"🖌 Покраска: {val('painting')}\n"
        f"📅 Срок: {val('deadline')}\n"
        f"📎 Вложений: {len(attachments)}\n"
        f"📋 Статус: <b>{val('status')}</b>\n"
        f"🕒 Создан: {val('created_at')}"
    )


async def send_admin_order(bot: Bot, chat_id: int, order, page: int):
    """Send the complete saved order as new messages, including on repeat clicks."""
    class PlainText(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = PlainText()
    parser.feed(admin_order_text(order))
    parser.close()
    text = "".join(parser.parts)
    # Count UTF-16 units conservatively, including emoji. Escape AFTER splitting
    # so HTML entities and tags can never be cut between messages.
    chunks = []
    current = []
    units = 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > 3500:
            chunks.append("".join(current))
            current = []
            units = 0
        current.append(char)
        units += size
    if current:
        chunks.append("".join(current))
    for index, chunk in enumerate(chunks):
        await bot.send_message(
            chat_id=chat_id,
            text=escape(chunk),
            parse_mode="HTML",
            reply_markup=(admin_order_keyboard(order["id"], page)
                          if index == len(chunks) - 1 else None),
        )


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ только для администратора.")
        return
    await message.answer("🌸 <b>SORA LAB — админ-панель</b>\nВыбери действие:",
                         parse_mode="HTML", reply_markup=admin_home_keyboard())


@dp.callback_query(F.data.startswith("adm:"))
async def admin_callbacks(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа", show_alert=True)
        return

    parts = (call.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        if action == "list":
            page = max(0, int(parts[2]))
            with database() as db:
                total = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
                max_page = max(0, (total - 1) // ADMIN_PAGE_SIZE)
                page = min(page, max_page)
                rows = db.execute(
                    "SELECT id, product, status FROM orders ORDER BY id DESC LIMIT ? OFFSET ?",
                    (ADMIN_PAGE_SIZE, page * ADMIN_PAGE_SIZE)
                ).fetchall()
            buttons = [[InlineKeyboardButton(
                text=f"№{order_id} · {str(product or 'Изделие')[:24]} · {str(status or '—')[:20]}",
                callback_data=f"adm:view:{order_id}:{page}")]
                for order_id, product, status in rows]
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm:list:{page - 1}"))
            if page < max_page:
                nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"adm:list:{page + 1}"))
            if nav:
                buttons.append(nav)
            await safe_edit_text(call.message, 
                f"📋 <b>Заказы SORA LAB</b> — {total} шт.\nСтраница {page + 1}/{max_page + 1}"
                if total else "📋 Пока нет заказов.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
            )
        elif action in {"view", "files", "statuses", "set"}:
            order_id = int(parts[2])
            page = max(0, int(parts[4] if action == "set" else parts[3]))
            order = get_admin_order(order_id)
            if not order:
                await call.answer("Заказ не найден", show_alert=True)
                return
            if action == "view":
                # Acknowledge before sending; never edit the source message.
                await call.answer()
                chat_id = call.message.chat.id if call.message else call.from_user.id
                await send_admin_order(bot, chat_id, order, page)
                return
            elif action == "statuses":
                await safe_edit_text(call.message, 
                    f"🔄 <b>Заказ №{order_id}</b>\nТекущий статус: {escape(str(order.get('status') or '—'))}\nВыбери новый статус:",
                    parse_mode="HTML", reply_markup=admin_status_keyboard(order_id, page))
            elif action == "files":
                try:
                    attachments = json.loads(order.get("attachments") or "[]")
                    if not isinstance(attachments, list):
                        attachments = []
                except (ValueError, TypeError):
                    attachments = []
                if not attachments:
                    await call.answer("У этого заказа нет вложений", show_alert=True)
                    return
                sent = 0
                for item in attachments[:10]:
                    if not isinstance(item, dict) or not item.get("file_id"):
                        continue
                    try:
                        if item.get("type") == "photo":
                            await bot.send_photo(call.from_user.id, item["file_id"],
                                                 caption=f"📎 Заказ №{order_id}")
                        elif item.get("type") == "document":
                            await bot.send_document(call.from_user.id, item["file_id"],
                                                    caption=f"📎 Заказ №{order_id}")
                        else:
                            continue
                        sent += 1
                    except Exception:
                        logging.exception("Не удалось отправить вложение заказа %s", order_id)
                await call.answer(f"Отправлено файлов: {sent}", show_alert=(sent == 0))
                return
            elif action == "set":
                code = parts[3]
                if code not in STATUSES:
                    await call.answer("Неизвестный статус", show_alert=True)
                    return
                new_status = STATUSES[code]
                with database() as db:
                    db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
                order["status"] = new_status
                await safe_edit_text(call.message, admin_order_text(order), parse_mode="HTML",
                                             reply_markup=admin_order_keyboard(order_id, page))
                try:
                    await bot.send_message(order["user_id"],
                                           f"🌸 SORA LAB\nСтатус заказа №{order_id} изменён: {new_status}")
                except Exception:
                    logging.exception("Не удалось уведомить клиента о заказе %s", order_id)
                    await call.answer("Статус сохранён, но уведомление клиенту не доставлено", show_alert=True)
                    return
        else:
            await call.answer("Неизвестное действие", show_alert=True)
            return
        await call.answer()
    except (ValueError, IndexError):
        await call.answer("Некорректная кнопка", show_alert=True)
    except Exception:
        logging.exception("Ошибка админ-панели")
        await call.answer("Произошла ошибка. Подробности в консоли.", show_alert=True)


@dp.message()
async def fallback(message: Message):
    await message.answer(
        "Используйте /start для главного меню.\n"
        "Если оформляете заказ, отвечайте на вопрос бота."
    )


async def main():
    init_db()
    bot = Bot(token=TOKEN)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
