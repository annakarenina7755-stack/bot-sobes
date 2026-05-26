from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove

from bot.config import settings
from bot.db.database import SessionLocal
from bot.db.models import Candidate, Questionnaire, CandidateStatus
from bot.keyboards import (
    CONSENT_KB, PHONE_KB, SALES_EXP_KB, SCHEDULE_KB
)
from bot.states import ConsentState, QuestionnaireState
from sqlalchemy import select, delete

router = Router()

CONSENT_TEXT = (
    "👋 Добро пожаловать!\n\n"
    "Перед началом анкетирования нам необходимо получить ваше согласие "
    "на обработку персональных данных.\n\n"
    "Ваши данные будут использованы исключительно для рассмотрения вашей "
    "кандидатуры на вакансию и не будут переданы третьим лицам.\n\n"
    "Вы соглашаетесь на обработку ваших персональных данных?"
)


async def get_or_create_candidate(tg_id: int, username: str | None) -> Candidate:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate).where(Candidate.tg_id == tg_id)
        )
        candidate = result.scalar_one_or_none()
        if not candidate:
            candidate = Candidate(tg_id=tg_id, username=username)
            session.add(candidate)
            await session.commit()
            await session.refresh(candidate)
        return candidate


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_candidate(message.from_user.id, message.from_user.username)
    await message.answer(CONSENT_TEXT, reply_markup=CONSENT_KB)
    await state.set_state(ConsentState.waiting)


@router.callback_query(ConsentState.waiting, F.data == "consent_no")
async def consent_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Вы отказались от обработки персональных данных.\n"
        "Без согласия мы не можем рассмотреть вашу кандидатуру.\n\n"
        "Если передумаете — нажмите /start."
    )
    await state.clear()


@router.callback_query(ConsentState.waiting, F.data == "consent_yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate).where(Candidate.tg_id == callback.from_user.id)
        )
        candidate = result.scalar_one()
        candidate.consent_given = True
        await session.commit()

    await callback.message.edit_text("✅ Спасибо! Начинаем анкету.")
    await callback.message.answer(
        "📝 <b>Вопрос 1 из 8</b>\n\nВведите вашу фамилию и имя:",
        parse_mode="HTML"
    )
    await state.set_state(QuestionnaireState.full_name)


# --- Вопрос 1: ФИО ---
@router.message(QuestionnaireState.full_name)
async def q_full_name(message: Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("Пожалуйста, введите корректное имя.")
        return
    await state.update_data(full_name=message.text.strip()[:256])
    await message.answer(
        "📝 <b>Вопрос 2 из 8</b>\n\nВведите ваш номер телефона или нажмите кнопку ниже:",
        parse_mode="HTML",
        reply_markup=PHONE_KB,
    )
    await state.set_state(QuestionnaireState.phone)


# --- Вопрос 2: Телефон ---
@router.message(QuestionnaireState.phone, F.contact)
async def q_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await _ask_age(message, state)


@router.message(QuestionnaireState.phone, F.text)
async def q_phone_text(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 7:
        await message.answer("Пожалуйста, введите корректный номер телефона.")
        return
    await state.update_data(phone=phone[:32])
    await _ask_age(message, state)


async def _ask_age(message: Message, state: FSMContext):
    await message.answer(
        "📝 <b>Вопрос 3 из 8</b>\n\nСколько вам лет?",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(QuestionnaireState.age)


# --- Вопрос 3: Возраст ---
@router.message(QuestionnaireState.age)
async def q_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите возраст цифрами.")
        return
    if age < 18:
        await message.answer(
            "К сожалению, мы рассматриваем кандидатов от 18 лет.\n"
            "Если вы допустили ошибку — введите возраст ещё раз."
        )
        return
    if age > 100:
        await message.answer("Пожалуйста, введите корректный возраст.")
        return
    await state.update_data(age=age)
    await message.answer(
        "📝 <b>Вопрос 4 из 8</b>\n\nЕсть ли у вас опыт в продажах?",
        parse_mode="HTML",
        reply_markup=SALES_EXP_KB,
    )
    await state.set_state(QuestionnaireState.has_sales_exp)


# --- Вопрос 4: Опыт в продажах ---
@router.callback_query(QuestionnaireState.has_sales_exp, F.data == "sales_no")
async def q_sales_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(has_sales_experience=False, sales_experience_details=None)
    await callback.message.edit_text("📝 <b>Вопрос 4 из 8</b>\n\nОпыт в продажах: Нет", parse_mode="HTML")
    await _ask_last_job(callback.message, state)


@router.callback_query(QuestionnaireState.has_sales_exp, F.data == "sales_yes")
async def q_sales_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(has_sales_experience=True)
    await callback.message.edit_text("📝 <b>Вопрос 4 из 8</b>\n\nОпыт в продажах: Да", parse_mode="HTML")
    await callback.message.answer("Расскажите кратко о вашем опыте в продажах:")
    await state.set_state(QuestionnaireState.sales_exp_details)


@router.message(QuestionnaireState.sales_exp_details)
async def q_sales_details(message: Message, state: FSMContext):
    await state.update_data(sales_experience_details=message.text.strip()[:500])
    await _ask_last_job(message, state)


async def _ask_last_job(message: Message, state: FSMContext):
    await message.answer(
        "📝 <b>Вопрос 5 из 8</b>\n\nГде вы работали последний раз? "
        "Кратко опишите должность и обязанности:",
        parse_mode="HTML",
    )
    await state.set_state(QuestionnaireState.last_job)


# --- Вопрос 5: Последнее место работы ---
@router.message(QuestionnaireState.last_job)
async def q_last_job(message: Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("Пожалуйста, введите информацию о последнем месте работы.")
        return
    await state.update_data(last_job=message.text.strip()[:500])
    await message.answer(
        "📝 <b>Вопрос 6 из 8</b>\n\nКакой график вам подходит?",
        parse_mode="HTML",
        reply_markup=SCHEDULE_KB,
    )
    await state.set_state(QuestionnaireState.schedule)


# --- Вопрос 6: График ---
SCHEDULE_LABELS = {
    "schedule_day": "day",
    "schedule_night": "night",
    "schedule_any": "any",
}
SCHEDULE_DISPLAY = {
    "day": "Дневная (9:00–21:00)",
    "night": "Ночная (21:00–9:00)",
    "any": "Любая",
}

@router.callback_query(QuestionnaireState.schedule, F.data.in_(SCHEDULE_LABELS))
async def q_schedule(callback: CallbackQuery, state: FSMContext):
    value = SCHEDULE_LABELS[callback.data]
    await state.update_data(schedule=value)
    await callback.message.edit_text(
        f"📝 <b>Вопрос 6 из 8</b>\n\nГрафик: {SCHEDULE_DISPLAY[value]}",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "📝 <b>Вопрос 7 из 8</b>\n\nКакое ближайшее метро к вашему дому?",
        parse_mode="HTML",
    )
    await state.set_state(QuestionnaireState.metro)


# --- Вопрос 7: Метро ---
@router.message(QuestionnaireState.metro)
async def q_metro(message: Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("Пожалуйста, введите название станции метро.")
        return
    await state.update_data(nearest_metro=message.text.strip()[:128])
    await message.answer(
        "📝 <b>Вопрос 8 из 8</b>\n\nПочему вы хотите работать именно в табачном магазине?",
        parse_mode="HTML",
    )
    await state.set_state(QuestionnaireState.motivation)


# --- Вопрос 8: Мотивация ---
@router.message(QuestionnaireState.motivation)
async def q_motivation(message: Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("Пожалуйста, напишите ответ.")
        return
    data = await state.update_data(motivation=message.text.strip()[:500])
    await state.clear()
    await _save_questionnaire(message, data)


async def _save_questionnaire(message: Message, data: dict):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Candidate).where(Candidate.tg_id == message.from_user.id)
        )
        candidate = result.scalar_one()

        # удаляем старую анкету если есть
        await session.execute(
            delete(Questionnaire).where(Questionnaire.candidate_id == candidate.id)
        )

        q = Questionnaire(
            candidate_id=candidate.id,
            full_name=data["full_name"],
            phone=data["phone"],
            age=data["age"],
            has_sales_experience=data["has_sales_experience"],
            sales_experience_details=data.get("sales_experience_details"),
            last_job=data["last_job"],
            schedule=data["schedule"],
            nearest_metro=data["nearest_metro"],
            motivation=data["motivation"],
        )
        session.add(q)
        candidate.status = CandidateStatus.new
        await session.commit()
        candidate_id = candidate.id
        username = candidate.username

    await message.answer(
        "✅ Спасибо! Ваша анкета принята.\n"
        "Мы рассмотрим её и свяжемся с вами в ближайшее время."
    )

    await _notify_admin(message.bot, candidate_id, data, message.from_user.id, username)


async def _notify_admin(bot, candidate_id: int, data: dict, tg_id: int, username: str | None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    sales_info = "Нет"
    if data.get("has_sales_experience"):
        sales_info = f"Да — {data.get('sales_experience_details', '')}"

    schedule_display = SCHEDULE_DISPLAY.get(data.get("schedule", ""), data.get("schedule", ""))

    tg_link = f"@{username}" if username else f"tg://user?id={tg_id}"

    text = (
        f"📋 <b>Новая анкета #{candidate_id}</b>\n\n"
        f"👤 <b>ФИО:</b> {data['full_name']}\n"
        f"📞 <b>Телефон:</b> {data['phone']}\n"
        f"🎂 <b>Возраст:</b> {data['age']}\n"
        f"💼 <b>Опыт в продажах:</b> {sales_info}\n"
        f"🏢 <b>Последнее место работы:</b> {data['last_job']}\n"
        f"🕐 <b>График:</b> {schedule_display}\n"
        f"🚇 <b>Метро:</b> {data['nearest_metro']}\n"
        f"💬 <b>Мотивация:</b> {data['motivation']}\n\n"
        f"✈️ <b>Telegram:</b> {tg_link}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Пригласить", callback_data=f"admin_invite:{candidate_id}"),
            InlineKeyboardButton(text="⏳ Позвать позже", callback_data=f"admin_later:{candidate_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"admin_reject:{candidate_id}"),
            InlineKeyboardButton(text="💬 Связаться", url=f"tg://user?id={tg_id}"),
        ],
    ])

    await bot.send_message(settings.ADMIN_CHAT_ID, text, parse_mode="HTML", reply_markup=kb)
