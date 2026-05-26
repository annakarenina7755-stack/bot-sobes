from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from datetime import datetime, timedelta
import io

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Slot, Candidate, Questionnaire, CandidateStatus
from bot.handlers.admin import MONTHS_RU, _workdays, _ensure_slots

router = Router()


def _admin_only(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id != settings.ADMIN_CHAT_ID:
            return
        return await func(message, *args, **kwargs)
    return wrapper


def _slot_label(slot: Slot) -> str:
    dt = slot.dt
    from bot.handlers.admin import WEEKDAYS_RU
    day = f"{WEEKDAYS_RU[dt.weekday()]}, {dt.day} {MONTHS_RU[dt.month - 1]} {dt.strftime('%H:%M')}"
    if slot.is_blocked:
        return f"{day} — 🔒 заблокирован"
    if slot.candidate_id:
        return f"{day} — 👤 занят (#{slot.candidate_id})"
    return f"{day} — ✅ свободен"


def _slots_keyboard(slots: list[Slot]) -> InlineKeyboardMarkup:
    rows = []
    for slot in slots:
        dt = slot.dt
        time_str = dt.strftime("%H:%M")
        if slot.is_blocked:
            action_text = "🔓 Разблокировать"
            action_cb = f"slot_unblock:{slot.id}"
        elif slot.candidate_id:
            action_text = "🗑 Освободить"
            action_cb = f"slot_free:{slot.id}"
        else:
            action_text = "🔒 Заблокировать"
            action_cb = f"slot_block:{slot.id}"

        rows.append([
            InlineKeyboardButton(text=time_str, callback_data="noop"),
            InlineKeyboardButton(text=action_text, callback_data=action_cb),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("slots"))
@_admin_only
async def cmd_slots(message: Message):
    days = _workdays(3)
    await _ensure_slots(days)

    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= datetime.now(),
                Slot.dt <= datetime.now() + timedelta(days=7),
            ).order_by(Slot.dt)
        )
        slots = result.scalars().all()

    if not slots:
        await message.answer("Нет слотов на ближайшие 7 дней.")
        return

    # группируем по дням
    from itertools import groupby
    from datetime import date
    for day, group in groupby(slots, key=lambda s: s.dt.date()):
        day_slots = list(group)
        from bot.handlers.admin import WEEKDAYS_RU
        header = f"📅 {WEEKDAYS_RU[day.weekday()]}, {day.day} {MONTHS_RU[day.month - 1]}"
        day_iso = day.isoformat()
        all_blocked = all(s.is_blocked for s in day_slots)
        day_btn = InlineKeyboardButton(
            text="🔓 Разблокировать день" if all_blocked else "🔒 Заблокировать день",
            callback_data=f"day_unblock:{day_iso}" if all_blocked else f"day_block:{day_iso}",
        )
        kb = _slots_keyboard(day_slots)
        kb.inline_keyboard.insert(0, [day_btn])
        await message.answer(header, reply_markup=kb)


@router.callback_query(F.data.startswith("day_block:"))
async def day_block(callback: CallbackQuery):
    from datetime import date
    day = date.fromisoformat(callback.data.split(":")[1])
    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= datetime(day.year, day.month, day.day, 0, 0),
                Slot.dt < datetime(day.year, day.month, day.day, 23, 59),
                Slot.candidate_id.is_(None),
            )
        )
        slots = result.scalars().all()
        for slot in slots:
            slot.is_blocked = True
        await session.commit()
    await callback.answer(f"День заблокирован ({len(slots)} слотов).")
    await callback.message.delete()


@router.callback_query(F.data.startswith("day_unblock:"))
async def day_unblock(callback: CallbackQuery):
    from datetime import date
    day = date.fromisoformat(callback.data.split(":")[1])
    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= datetime(day.year, day.month, day.day, 0, 0),
                Slot.dt < datetime(day.year, day.month, day.day, 23, 59),
            )
        )
        slots = result.scalars().all()
        for slot in slots:
            slot.is_blocked = False
        await session.commit()
    await callback.answer(f"День разблокирован ({len(slots)} слотов).")
    await callback.message.delete()


@router.callback_query(F.data.startswith("slot_block:"))
async def slot_block(callback: CallbackQuery):
    slot_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if slot:
            slot.is_blocked = True
            await session.commit()
    await callback.answer("Слот заблокирован.")
    await callback.message.delete()


@router.callback_query(F.data.startswith("slot_unblock:"))
async def slot_unblock(callback: CallbackQuery):
    slot_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if slot:
            slot.is_blocked = False
            await session.commit()
    await callback.answer("Слот разблокирован.")
    await callback.message.delete()


@router.callback_query(F.data.startswith("slot_free:"))
async def slot_free(callback: CallbackQuery):
    slot_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        slot = await session.get(Slot, slot_id)
        if not slot:
            await callback.answer()
            return
        candidate_id = slot.candidate_id
        slot.candidate_id = None
        slot.reminder_sent = False
        slot.confirmed = None
        if candidate_id:
            candidate = await session.get(Candidate, candidate_id)
            if candidate:
                candidate.status = CandidateStatus.invited
                try:
                    await callback.bot.send_message(
                        candidate.tg_id,
                        "ℹ️ Ваше собеседование было отменено администратором. "
                        "Пожалуйста, выберите новый слот или свяжитесь с нами."
                    )
                except Exception:
                    pass
        await session.commit()
    await callback.answer("Слот освобождён.")
    await callback.message.delete()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@router.message(Command("export"))
@_admin_only
async def cmd_export(message: Message):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate, Questionnaire, Slot)
            .join(Questionnaire, Questionnaire.candidate_id == Candidate.id)
            .outerjoin(Slot, Slot.candidate_id == Candidate.id)
            .where(Candidate.status.in_([
                CandidateStatus.invited,
                CandidateStatus.scheduled,
            ]))
            .order_by(Candidate.id)
        )
        rows = result.all()

    if not rows:
        await message.answer("Нет приглашённых кандидатов.")
        return

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Кандидаты"
    ws.append([
        "ID", "ФИО", "Телефон", "Возраст", "Опыт продаж", "Детали опыта",
        "Последнее место работы", "График", "Метро", "Мотивация",
        "Статус", "Слот собеседования",
    ])

    SCHEDULE_DISPLAY = {"day": "Дневная", "night": "Ночная", "any": "Любая"}
    STATUS_DISPLAY = {
        CandidateStatus.invited: "Приглашён",
        CandidateStatus.scheduled: "Записан",
    }

    for candidate, q, slot in rows:
        slot_str = ""
        if slot:
            dt = slot.dt
            slot_str = f"{dt.day} {MONTHS_RU[dt.month - 1]} {dt.strftime('%H:%M')}"
        ws.append([
            candidate.id,
            q.full_name,
            q.phone,
            q.age,
            "Да" if q.has_sales_experience else "Нет",
            q.sales_experience_details or "",
            q.last_job,
            SCHEDULE_DISPLAY.get(q.schedule, q.schedule),
            q.nearest_metro,
            q.motivation,
            STATUS_DISPLAY.get(candidate.status, str(candidate.status)),
            slot_str,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from aiogram.types import BufferedInputFile
    await message.answer_document(
        BufferedInputFile(buf.read(), filename="candidates.xlsx"),
        caption="📊 Приглашённые кандидаты"
    )
