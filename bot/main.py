import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import settings
from bot.db.database import engine, Base

logging.basicConfig(level=logging.INFO)


async def main():
    from bot.handlers import candidate, admin, slots, menu
    from bot.scheduler import start_scheduler

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(menu.router)
    dp.include_router(candidate.router)
    dp.include_router(admin.router)
    dp.include_router(slots.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать анкету"),
        BotCommand(command="menu", description="Меню администратора"),
        BotCommand(command="bookings", description="Записи по дням"),
    ])

    start_scheduler(bot)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
