from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Slot, Candidate

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def _check_reminders(bot: Bot):
    now = datetime.now()
    window_start = now + timedelta(hours=3)
    window_end = window_start + timedelta(minutes=1)

    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= window_start,
                Slot.dt < window_end,
                Slot.candidate_id.isnot(None),
                Slot.reminder_sent.is_(False),
                Slot.is_blocked.is_(False),
            )
        )
        slots = result.scalars().all()

        for slot in slots:
            candidate = await session.get(Candidate, slot.candidate_id)
            if not candidate:
                continue

            from bot.db.models import CandidateStatus
            if candidate.status != CandidateStatus.scheduled:
                continue

            dt = slot.dt
            from bot.handlers.admin import MONTHS_RU
            dt_str = f"{dt.day} {MONTHS_RU[dt.month - 1]} в {dt.strftime('%H:%M')}"

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, буду", callback_data=f"remind_yes:{slot.id}"),
                    InlineKeyboardButton(text="❌ Нет, не смогу", callback_data=f"remind_no:{slot.id}"),
                ]
            ])

            try:
                await bot.send_message(
                    candidate.tg_id,
                    f"⏰ Напоминание!\n\nВаше собеседование — <b>{dt_str}</b>.\n\nВы придёте?",
                    reply_markup=kb,
                )
                slot.reminder_sent = True
            except Exception:
                pass

        await session.commit()


async def _check_unanswered(bot: Bot):
    """Уведомляем админа если кандидат не ответил на напоминание (проверяем слоты через 30 мин после собеседования)."""
    now = datetime.now()
    window_start = now - timedelta(minutes=31)
    window_end = now - timedelta(minutes=29)

    async with SessionLocal() as session:
        result = await session.execute(
            select(Slot).where(
                Slot.dt >= window_start,
                Slot.dt < window_end,
                Slot.candidate_id.isnot(None),
                Slot.reminder_sent.is_(True),
                Slot.confirmed.is_(None),
            )
        )
        slots = result.scalars().all()

        for slot in slots:
            candidate = await session.get(Candidate, slot.candidate_id)
            if not candidate:
                continue
            dt = slot.dt
            from bot.handlers.admin import MONTHS_RU
            dt_str = f"{dt.day} {MONTHS_RU[dt.month - 1]} в {dt.strftime('%H:%M')}"
            try:
                await bot.send_message(
                    settings.ADMIN_CHAT_ID,
                    f"⚠️ Кандидат #{candidate.id} не ответил на напоминание о собеседовании {dt_str}.",
                )
            except Exception:
                pass


def start_scheduler(bot: Bot):
    scheduler.add_job(
        _check_reminders,
        trigger=IntervalTrigger(minutes=1),
        args=[bot],
        id="reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_unanswered,
        trigger=IntervalTrigger(minutes=1),
        args=[bot],
        id="unanswered",
        replace_existing=True,
    )
    scheduler.start()
