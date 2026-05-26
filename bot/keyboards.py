from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

CONSENT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Согласен(а)", callback_data="consent_yes")],
    [InlineKeyboardButton(text="❌ Не согласен(а)", callback_data="consent_no")],
])

PHONE_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
    resize_keyboard=True, one_time_keyboard=True,
)

SALES_EXP_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Да", callback_data="sales_yes")],
    [InlineKeyboardButton(text="Нет", callback_data="sales_no")],
])

SCHEDULE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="☀️ Дневная (9:00–21:00)", callback_data="schedule_day")],
    [InlineKeyboardButton(text="🌙 Ночная (21:00–9:00)", callback_data="schedule_night")],
    [InlineKeyboardButton(text="🔄 Любая", callback_data="schedule_any")],
])

REMOVE_KB = ReplyKeyboardMarkup(keyboard=[[]], resize_keyboard=True)
