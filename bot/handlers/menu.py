from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from sqlalchemy import select, func
from datetime import date, datetime, timedelta

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Candidate, Questionnaire, CandidateStatus, Slot

router = Router()


class AdminState(StatesGroup):
    waiting_contact_id = State()

ADMIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Кандидаты"), KeyboardButton(text="📅 Слоты")],
        [KeyboardButton(text="👤 Связаться"), KeyboardButton(text="📤 Экспорт")],
        [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📆 Записи")],
    ],
    resize_keyboard=True,
)

STATUS_LABELS = {
    CandidateStatus.new: "🆕 Новые",
    CandidateStatus.postponed: "⏳ Отложенные",
    CandidateStatus.invited: "✅ Приглашённые",
    CandidateStatus.scheduled: "📅 Записанные",
    CandidateStatus.rejected: "❌ Отказ",
}


def _is_admin(user_id: int) -> bool:
    return user_id == settings.ADMIN_CHAT_ID


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return (
        datetime(day.year, day.month, day.day, 0, 0),
        datetime(day.year, day.month, day.day, 0, 0) + timedelta(days=1),
    )


async def _bookings_for_day(day: date):
    start, end = _day_bounds(day)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot, Candidate, Questionnaire)
            .join(Candidate, Candidate.id == Slot.candidate_id)
            .outerjoin(Questionnaire, Questionnaire.candidate_id == Candidate.id)
            .where(
                Slot.dt >= start,
                Slot.dt < end,
                Slot.candidate_id.isnot(None),
            )
            .order_by(Slot.dt)
        )
        return result.all()


async def _booking_counts(days: list[date]) -> dict[date, int]:
    if not days:
        return {}

    start, _ = _day_bounds(days[0])
    _, end = _day_bounds(days[-1])
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.date(Slot.dt), func.count(Slot.id))
            .where(
                Slot.dt >= start,
                Slot.dt < end,
                Slot.candidate_id.isnot(None),
            )
            .group_by(func.date(Slot.dt))
        )
        rows = result.all()

    return {
        datetime.strptime(str(day), "%Y-%m-%d").date(): count
        for day, count in rows
    }


async def _bookings_calendar_keyboard(offset: int = 0) -> InlineKeyboardMarkup:
    offset = max(offset, 0)
    days = [date.today() + timedelta(days=offset + i) for i in range(14)]
    counts = await _booking_counts(days)

    rows = []
    row = []
    for day in days:
        count = counts.get(day, 0)
        row.append(InlineKeyboardButton(
            text=f"{day.strftime('%d.%m')} ({count})",
            callback_data=f"bookings_day:{day.isoformat()}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if offset:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"bookings_page:{max(offset - 14, 0)}"))
    nav.append(InlineKeyboardButton(text="Дальше ▶️", callback_data=f"bookings_page:{offset + 14}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bookings_calendar_text(offset: int = 0) -> str:
    start = date.today() + timedelta(days=max(offset, 0))
    end = start + timedelta(days=13)
    return f"📆 Выберите день для просмотра записей.\n\nПериод: {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"


async def _bookings_text(day: date) -> str:
    from bot.handlers.admin import MONTHS_RU, WEEKDAYS_RU

    rows = await _bookings_for_day(day)
    header = f"<b>📆 {WEEKDAYS_RU[day.weekday()]}, {day.day} {MONTHS_RU[day.month - 1]}</b>"
    if not rows:
        return f"{header}\n\nЗаписей на собеседования нет."

    lines = [header]
    for slot, candidate, questionnaire in rows:
        time_str = slot.dt.strftime("%H:%M")
        confirmed = "✅" if slot.confirmed else ("❌" if slot.confirmed is False else "❓")
        name = questionnaire.full_name if questionnaire else "—"
        phone = questionnaire.phone if questionnaire else "—"
        username = f"@{candidate.username}" if candidate.username else f"tg://user?id={candidate.tg_id}"
        lines.append(f"{time_str} {confirmed} #{candidate.id} {name}\n📞 {phone}\n{username}")
    return "\n\n".join(lines)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Меню администратора:", reply_markup=ADMIN_KB)


# --- Кандидаты ---
@router.message(F.text == "📋 Кандидаты")
async def menu_candidates(message: Message):
    if not _is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"clist:{status.value}")]
        for status, label in STATUS_LABELS.items()
    ])
    await message.answer("Выберите категорию:", reply_markup=kb)


@router.callback_query(F.data.startswith("clist:"))
async def candidates_list(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    status_val = callback.data.split(":")[1]
    status = CandidateStatus(status_val)

    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate, Questionnaire)
            .outerjoin(Questionnaire, Questionnaire.candidate_id == Candidate.id)
            .where(Candidate.status == status)
            .order_by(Candidate.id.desc())
            .limit(20)
        )
        rows = result.all()

    if not rows:
        await callback.answer("Кандидатов в этой категории нет.", show_alert=True)
        return

    lines = [f"<b>{STATUS_LABELS[status]}</b>\n"]
    for c, q in rows:
        name = q.full_name if q else "—"
        phone = q.phone if q else "—"
        username = f"@{c.username}" if c.username else f"tg://user?id={c.tg_id}"
        lines.append(f"#{c.id} {name} | {phone} | {username}")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


# --- Сегодня ---
@router.message(F.text == "📊 Сегодня")
async def menu_today(message: Message):
    if not _is_admin(message.from_user.id):
        return
    from bot.handlers.admin import MONTHS_RU, WEEKDAYS_RU

    today = datetime.now().date()
    rows = await _bookings_for_day(today)

    if not rows:
        await message.answer("На сегодня собеседований нет.")
        return

    lines = [f"<b>📊 Сегодня, {today.day} {MONTHS_RU[today.month - 1]}</b>\n"]
    for slot, c, q in rows:
        name = q.full_name if q else "—"
        time_str = slot.dt.strftime("%H:%M")
        confirmed = "✅" if slot.confirmed else ("❌" if slot.confirmed is False else "❓")
        lines.append(f"{time_str} {confirmed} #{c.id} {name}")

    await message.answer("\n".join(lines))


@router.message(Command("bookings"))
@router.message(F.text == "📆 Записи")
async def menu_bookings(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        _bookings_calendar_text(),
        reply_markup=await _bookings_calendar_keyboard(),
    )


@router.callback_query(F.data.startswith("bookings_page:"))
async def bookings_page(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    offset = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        _bookings_calendar_text(offset),
        reply_markup=await _bookings_calendar_keyboard(offset),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bookings_day:"))
async def bookings_day(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    day = date.fromisoformat(callback.data.split(":")[1])
    await callback.message.answer(await _bookings_text(day))
    await callback.answer()


# --- Связаться ---
@router.message(F.text == "👤 Связаться")
async def menu_contact(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Введите ID кандидата (число из карточки):")
    await state.set_state(AdminState.waiting_contact_id)


@router.message(AdminState.waiting_contact_id)
async def contact_by_id(message: Message, state: FSMContext):
    await state.clear()
    if not message.text or not message.text.isdigit():
        await message.answer("Введите корректный числовой ID.")
        return
    candidate_id = int(message.text)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate, Questionnaire)
            .outerjoin(Questionnaire, Questionnaire.candidate_id == Candidate.id)
            .where(Candidate.id == candidate_id)
        )
        row = result.one_or_none()

    if not row:
        await message.answer(f"Кандидат #{candidate_id} не найден.")
        return

    c, q = row
    name = q.full_name if q else "—"
    phone = q.phone if q else "—"

    buttons = []
    if c.username:
        buttons.append([InlineKeyboardButton(text="✈️ Написать в Telegram", url=f"https://t.me/{c.username}")])
    buttons.append([InlineKeyboardButton(text="📞 Позвонить", url=f"tel:{phone}")])

    await message.answer(
        f"👤 <b>#{c.id} {name}</b>\n📞 {phone}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# --- Слоты и экспорт — перенаправляем на команды ---
@router.message(F.text == "📅 Слоты")
async def menu_slots(message: Message):
    if not _is_admin(message.from_user.id):
        return
    from bot.handlers.slots import cmd_slots
    await cmd_slots(message)


@router.message(F.text == "📤 Экспорт")
async def menu_export(message: Message):
    if not _is_admin(message.from_user.id):
        return
    from bot.handlers.slots import cmd_export
    await cmd_export(message)
