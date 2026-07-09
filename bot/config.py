from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str
    ADMIN_CHAT_ID: int

    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "hrbot"
    POSTGRES_USER: str = "hrbot"
    POSTGRES_PASSWORD: str

    TZ: str = "Europe/Moscow"
    ASK_METRO: bool = True
    INTERVIEW_ADDRESS: str = "Мичуринский проспект, Олимпийская деревня 4к3"
    INTERVIEW_DIRECTIONS: str = (
        "Для ориентира вбейте в навигаторе Ресторан «Берикони». "
        "Если смотреть на вход ресторана, слева в десяти метрах будет дверь на ступеньках. "
        "Позвоните, когда будете возле неё, я вас встречу."
    )
    INTERVIEW_CONTACT: str = "+7 905 530-11-91 Анна"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
