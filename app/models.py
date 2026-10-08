"""Database tables.

Money is stored as Numeric(12, 2) in the original currency, plus the
exchange rate captured at entry time and the converted base-currency
amount. Changing today's rate never rewrites yesterday's books.
"""
import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(12, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    staff = "staff"      # reception: records income, expenses, handovers, closes the day
    manager = "manager"  # reads everything, confirms cash handovers, manages rates


class PaymentMethod(str, enum.Enum):
    cash = "cash"   # goes into the drawer
    card = "card"   # POS terminal, checked against the Z-report
    ota = "ota"     # prepaid to the booking site, paid out later
    bank = "bank"   # bank transfer / Idram, never touches the drawer


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.staff)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rate(Base):
    __tablename__ = "rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    base_per_unit: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    guest: Mapped[str] = mapped_column(String(128), default="")
    channel: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, native_enum=False))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    base_amount: Mapped[Decimal] = mapped_column(Money)
    booking_ref: Mapped[str] = mapped_column(String(64), default="")
    in_pms: Mapped[bool] = mapped_column(Boolean, default=False)  # entered in Airtable / PMS
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    created_by: Mapped[User | None] = relationship()


class Handover(Base):
    """Cash taken out of the drawer by the manager."""
    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    time: Mapped[str] = mapped_column(String(5), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    confirmed_by: Mapped[User | None] = relationship(foreign_keys=[confirmed_by_id])

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DayClose(Base):
    __tablename__ = "day_closes"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    terminal_total: Mapped[Decimal | None] = mapped_column(Money)  # POS Z-report, base currency
    pms_total: Mapped[Decimal | None] = mapped_column(Money)       # total entered in Airtable / PMS
    note: Mapped[str] = mapped_column(Text, default="")
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CashCount(Base):
    """Opening float and end-of-day count, one row per day and currency."""
    __tablename__ = "cash_counts"
    __table_args__ = (UniqueConstraint("day", "currency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    opening: Mapped[Decimal | None] = mapped_column(Money)
    counted: Mapped[Decimal | None] = mapped_column(Money)
