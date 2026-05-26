from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Candidate, CandidateStatus, Slot

router = Router()

MSK = ZoneInfo("Europe/Moscow")


def _workdays(n: int) -> list[datetime]:
    days = []
    d = datetime.now(MSK).date() + timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _slots_for_day(day) -> list[datetime]:
    slots = []
    t = datetime(day.year, day.month, day.day, 12, 0)  # naive MSK
    end = datetime(day.year, day.month, day.day, 18, 1)
    while t < end:
        slots.append(t)
        t += timedelta(minutes=30)
    return slots


async def _ensure_slots(days: list) -> None:
    async with SessionLocal() as session:
        for day in days:
            for dt in _slots_for_day(day):
                exists = await session.execute(select(Slot).where(Slot.dt == dt))
                if not exists.scalar_one_or_none():
                    session.add(Slot(dt=dt))
        await session.commit()


WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _day_label(d) -> str:
    return f"{WEEKDAYS_RU[d.weekday()]}, {d.day} {MONTHS_RU[d.month - 1]}"


def _day_keyboard(days: list, candidate_id: int) -> InlineKeyboardMarkup:
    rows = []
    for d in days:
        rows.append([InlineKeyboardButton(
            text=_day_label(d),
            callback_data=f"slot_day:{candidate_id}:{d.isoformat()}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _time_keyboard(slots: list[Slot], candidate_id: int, day_iso: str) -> InlineKeyboardMarkup:
    row = []
    rows = []
    for slot in slots:
        row.append(InlineKeyboardButton(
            text=slot.dt.strftime("%H:%M"),
            callback_data=f"slot_pick:{candidate_id}:{slot.id}"
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"slot_back:{candidate_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- Пригласить ---
@router.callback_query(F.data.startswith("admin_invite:"))
async def admin_invite(callback: CallbackQuery):
    candidate_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        candidate = await session.get(Candidate, candidate_id)
        if not candidate:
            await callback.answer("Кандидат не найден.", show_alert=True)
            return
        if candidate.status == CandidateStatus.rejected:
            await callback.answer("Кандидат уже отклонён.", show_alert=True)
            return
        candidate.status = CandidateStatus.invited
        await session.commit()
        tg_id = candidate.tg_id

    days = _workdays(5)
    await _ensure_slots(days)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Кандидат #{candidate_id} приглашён. Отправляю слоты.",
    )
    await callback.bot.send_message(
        tg_id,
        "🎉 Поздравляем! Вас приглашают на собеседование.\n\nВыберите удобный день:",
        reply_markup=_day_keyboard(days, candidate_id),
    )


# --- Позвать позже ---
@router.callback_query(F.data.startswith("admin_later:"))
async def admin_later(callback: CallbackQuery):
    candidate_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        candidate = await session.get(Candidate, candidate_id)
        if candidate:
            candidate.status = CandidateStatus.postponed
            await session.commit()
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Пригласить", callback_data=f"admin_invite:{candidate_id}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"admin_reject:{candidate_id}")],
    ]))
    await callback.answer("Отмечено: позвать позже.")


# --- Отказать ---
@router.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject(callback: CallbackQuery):
    candidate_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        candidate = await session.get(Candidate, candidate_id)
        if not candidate:
            await callback.answer("Кандидат не найден.", show_alert=True)
            return
        candidate.status = CandidateStatus.rejected
        await session.commit()
        tg_id = candidate.tg_id

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Кандидат #{candidate_id} отклонён.")
    await callback.bot.send_message(
        tg_id,
        "К сожалению, мы не можем пригласить вас на собеседование.\n"
        "Спасибо за интерес к нашей компании."
    )


# --- Выбор дня ---
@router.callback_query(F.data.startswith("slot_day:"))
async def slot_day(callback: CallbackQuery):
    _, candidate_id, day_iso = callback.data.split(":")
    candidate_id = int(candidate_id)
    from datetime import date
    day = date.fromisoformat(day_iso)

    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= datetime(day.year, day.month, day.day, 0, 0),
                Slot.dt < datetime(day.year, day.month, day.day, 23, 59),
                Slot.candidate_id.is_(None),
                Slot.is_blocked.is_(False),
            ).order_by(Slot.dt)
        )
        slots = result.scalars().all()

    if not slots:
        await callback.answer("На этот день нет свободных слотов.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Выберите удобное время на {day.day} {MONTHS_RU[day.month - 1]}:",
        reply_markup=_time_keyboard(slots, candidate_id, day_iso),
    )


# --- Назад к выбору дня ---
@router.callback_query(F.data.startswith("slot_back:"))
async def slot_back(callback: CallbackQuery):
    candidate_id = int(callback.data.split(":")[1])
    days = _workdays(5)
    await callback.message.edit_text(
        "Выберите удобный день:",
        reply_markup=_day_keyboard(days, candidate_id),
    )


# --- Выбор времени ---
@router.callback_query(F.data.startswith("slot_pick:"))
async def slot_pick(callback: CallbackQuery):
    _, candidate_id, slot_id = callback.data.split(":")
    candidate_id = int(candidate_id)
    slot_id = int(slot_id)

    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if not slot or slot.candidate_id or slot.is_blocked:
            await callback.answer("Этот слот уже занят. Выберите другой.", show_alert=True)
            return
        candidate = await session.get(Candidate, candidate_id)
        slot.candidate_id = candidate_id
        candidate.status = CandidateStatus.scheduled
        await session.commit()
        dt = slot.dt
        dt_str = f"{dt.day} {MONTHS_RU[dt.month - 1]} в {dt.strftime('%H:%M')}"
        tg_id = candidate.tg_id
    await callback.message.edit_text(f"✅ Вы записаны на собеседование {dt_str}.")
    await callback.bot.send_message(
        settings.ADMIN_CHAT_ID,
        f"📅 Кандидат #{candidate_id} записался на собеседование: <b>{dt_str}</b>",
    )


# --- Ответ на напоминание: Да ---
@router.callback_query(F.data.startswith("remind_yes:"))
async def remind_yes(callback: CallbackQuery):
    slot_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if slot:
            slot.confirmed = True
            await session.commit()
    await callback.message.edit_text("✅ Отлично! Ждём вас на собеседовании.")


# --- Ответ на напоминание: Нет ---
@router.callback_query(F.data.startswith("remind_no:"))
async def remind_no(callback: CallbackQuery):
    slot_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if not slot:
            await callback.answer()
            return
        candidate_id = slot.candidate_id
        slot.candidate_id = None
        slot.confirmed = None
        slot.reminder_sent = False
        candidate = await session.get(Candidate, candidate_id)
        if candidate:
            from bot.db.models import CandidateStatus
            candidate.status = CandidateStatus.new
        await session.commit()

    await callback.message.edit_text(
        "Понятно, слот освобождён. Если захотите перезаписаться — обратитесь к нам."
    )
    await callback.bot.send_message(
        settings.ADMIN_CHAT_ID,
        f"⚠️ Кандидат #{candidate_id} отказался от собеседования. Слот освобождён.",
    )
