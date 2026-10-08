from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.config import settings
from app.models import PaymentMethod, Role

# Decimals in, JSON numbers out (Pydantic would otherwise emit strings).
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
OptMoney = Annotated[Decimal | None, PlainSerializer(lambda v: None if v is None else float(v), when_used="json")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


def _check_currency(v: str) -> str:
    v = v.upper()
    if v not in settings.currencies:
        raise ValueError(f"currency must be one of {settings.currencies}")
    return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str
    role: Role


class Meta(BaseModel):
    channels: list[str]
    currencies: list[str]
    base_currency: str
    methods: list[PaymentMethod]


# ---- rates ----
class RateIn(BaseModel):
    currency: str
    base_per_unit: Annotated[Decimal, Field(gt=0)]
    _c = field_validator("currency")(_check_currency)


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    currency: str
    base_per_unit: Money
    updated_at: datetime


# ---- entries ----
class EntryIn(BaseModel):
    day: date
    guest: str = Field("", max_length=128)
    channel: str
    method: PaymentMethod
    amount: PositiveMoney
    currency: str = settings.base_currency
    booking_ref: str = Field("", max_length=64)
    in_pms: bool = False
    note: str = Field("", max_length=255)

    _c = field_validator("currency")(_check_currency)

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        if v not in settings.channels:
            raise ValueError(f"channel must be one of {settings.channels}")
        return v


class EntryPatch(BaseModel):
    guest: str | None = Field(None, max_length=128)
    channel: str | None = None
    method: PaymentMethod | None = None
    amount: PositiveMoney | None = None
    currency: str | None = None
    booking_ref: str | None = Field(None, max_length=64)
    in_pms: bool | None = None
    note: str | None = Field(None, max_length=255)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        return None if v is None else _check_currency(v)

    @field_validator("channel")
    @classmethod
    def _channel(cls, v):
        if v is not None and v not in settings.channels:
            raise ValueError(f"channel must be one of {settings.channels}")
        return v


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    day: date
    guest: str
    channel: str
    method: PaymentMethod
    amount: Money
    currency: str
    rate: Money
    base_amount: Money
    booking_ref: str
    in_pms: bool
    note: str
    created_at: datetime


# ---- handovers & expenses ----
class HandoverIn(BaseModel):
    day: date
    amount: PositiveMoney
    currency: str = settings.base_currency
    time: str = Field("", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    note: str = Field("", max_length=255)
    _c = field_validator("currency")(_check_currency)


class HandoverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    day: date
    amount: Money
    currency: str
    time: str
    note: str
    confirmed: bool
    confirmed_at: datetime | None


class ExpenseIn(BaseModel):
    day: date
    description: str = Field("", max_length=255)
    amount: PositiveMoney
    currency: str = settings.base_currency
    _c = field_validator("currency")(_check_currency)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    day: date
    description: str
    amount: Money
    currency: str


# ---- day close & reconciliation ----
class CashCountIn(BaseModel):
    currency: str
    opening: Annotated[Decimal | None, Field(ge=0)] = None
    counted: Annotated[Decimal | None, Field(ge=0)] = None
    _c = field_validator("currency")(_check_currency)


class DayCloseIn(BaseModel):
    terminal_total: Annotated[Decimal | None, Field(ge=0)] = None
    pms_total: Annotated[Decimal | None, Field(ge=0)] = None
    note: str = ""
    cash: list[CashCountIn] = []


class CashResultOut(BaseModel):
    currency: str
    opening: Money
    cash_in: Money
    handed_over: Money
    expenses: Money
    expected: Money
    counted: OptMoney
    difference: OptMoney


class ReconciliationOut(BaseModel):
    total_base: Money
    by_method: dict[str, Money]
    by_channel: dict[str, Money]
    cash: list[CashResultOut]
    card_recorded: Money
    card_terminal: OptMoney
    card_difference: OptMoney
    pms_total: OptMoney
    pms_difference: OptMoney
    missing_in_pms: int
    status: str
    issues: list[str]


class DayOut(BaseModel):
    day: date
    entries: list[EntryOut]
    handovers: list[HandoverOut]
    expenses: list[ExpenseOut]
    close_note: str
    suggested_opening: dict[str, Money]
    reconciliation: ReconciliationOut


class DaySummary(BaseModel):
    day: date
    entries: int
    total_base: Money
    status: str
    issues: list[str]


class MonthlyReport(BaseModel):
    month: str
    total_base: Money
    entries: int
    by_channel: dict[str, Money]
    by_method: dict[str, Money]
    handovers: list[HandoverOut]
    handovers_by_currency: dict[str, Money]
    days: list[DaySummary]
