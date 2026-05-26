from aiogram.fsm.state import State, StatesGroup


class ConsentState(StatesGroup):
    waiting = State()


class QuestionnaireState(StatesGroup):
    full_name = State()
    phone = State()
    age = State()
    has_sales_exp = State()
    sales_exp_details = State()
    last_job = State()
    schedule = State()
    metro = State()
    motivation = State()
