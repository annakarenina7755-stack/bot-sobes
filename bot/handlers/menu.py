from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from sqlalchemy import select, func

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Candidate, Questionnaire, CandidateStatus

router = Router()

ADMIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Кандидаты"), KeyboardButton(text="📅 Слоты")],
        [KeyboardButton(text="👤 Связаться"), KeyboardButton(text="📤 Экспорт")],
        [KeyboardButton(text="📊 Сегодня")],
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
    from datetime import datetime
    from bot.db.models import Slot
    from bot.handlers.admin import MONTHS_RU, WEEKDAYS_RU

    today = datetime.now().date()
    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot, Candidate, Questionnaire)
            .join(Candidate, Candidate.id == Slot.candidate_id)
            .outerjoin(Questionnaire, Questionnaire.candidate_id == Candidate.id)
            .where(
                Slot.dt >= datetime(today.year, today.month, today.day, 0, 0),
                Slot.dt < datetime(today.year, today.month, today.day, 23, 59),
                Slot.candidate_id.isnot(None),
            )
            .order_by(Slot.dt)
        )
        rows = result.all()

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


# --- Связаться ---
@router.message(F.text == "👤 Связаться")
async def menu_contact(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Введите ID кандидата (число из карточки):")


@router.message(F.text.regexp(r"^\d+$"))
async def contact_by_id(message: Message):
    if not _is_admin(message.from_user.id):
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
