from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, Enum, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.database import Base


class CandidateStatus(PyEnum):
    new = "new"
    invited = "invited"
    postponed = "postponed"
    rejected = "rejected"
    scheduled = "scheduled"


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus), default=CandidateStatus.new
    )
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    questionnaire: Mapped["Questionnaire | None"] = relationship(
        back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )
    slots: Mapped[list["Slot"]] = relationship(back_populates="candidate")


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)

    full_name: Mapped[str] = mapped_column(String(256))
    phone: Mapped[str] = mapped_column(String(32))
    age: Mapped[int] = mapped_column(Integer)
    has_sales_experience: Mapped[bool] = mapped_column(Boolean)
    sales_experience_details: Mapped[str | None] = mapped_column(Text)
    last_job: Mapped[str] = mapped_column(Text)
    schedule: Mapped[str] = mapped_column(String(16))  # day / night / any
    nearest_metro: Mapped[str] = mapped_column(String(128))
    motivation: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="questionnaire")


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dt: Mapped[datetime] = mapped_column(DateTime, unique=True, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"), nullable=True
    )
    day_before_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    candidate: Mapped["Candidate | None"] = relationship(back_populates="slots")
