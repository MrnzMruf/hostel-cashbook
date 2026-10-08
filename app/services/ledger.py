"""Loads a day (or a range of days) from the database and reconciles it."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CashCount, DayClose, Entry, Expense, Handover, Rate
from app.services.reconcile import CashLine, Count, IncomeLine, Reconciliation, reconcile

TOL = Decimal(settings.tolerance)


def rate_for(db: Session, currency: str) -> Decimal:
    if currency == settings.base_currency:
        return Decimal("1")
    rate = db.get(Rate, currency)
    if rate is None:
        raise LookupError(f"No exchange rate set for {currency}. A manager can add it under Rates.")
    return rate.base_per_unit


def to_base(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate).quantize(Decimal("1"))


def _reconcile(entries, handovers, expenses, counts, close) -> Reconciliation:
    return reconcile(
        income=[IncomeLine(e.method.value, e.channel, e.amount, e.currency, e.base_amount, e.in_pms) for e in entries],
        handovers=[CashLine(h.amount, h.currency) for h in handovers],
        expenses=[CashLine(x.amount, x.currency) for x in expenses],
        counts=[Count(c.currency, c.opening, c.counted) for c in counts],
        terminal_total=close.terminal_total if close else None,
        pms_total=close.pms_total if close else None,
        base_currency=settings.base_currency,
        tolerance=TOL,
    )


def load_day(db: Session, day: date):
    entries = db.scalars(select(Entry).where(Entry.day == day).order_by(Entry.created_at, Entry.id)).all()
    handovers = db.scalars(select(Handover).where(Handover.day == day).order_by(Handover.id)).all()
    expenses = db.scalars(select(Expense).where(Expense.day == day).order_by(Expense.id)).all()
    counts = db.scalars(select(CashCount).where(CashCount.day == day)).all()
    close = db.get(DayClose, day)
    return entries, handovers, expenses, counts, close, _reconcile(entries, handovers, expenses, counts, close)


def suggested_opening(db: Session, day: date) -> dict[str, Decimal]:
    """Yesterday's counted cash is today's opening float."""
    last_day = db.scalar(
        select(CashCount.day).where(CashCount.day < day, CashCount.counted.is_not(None))
        .order_by(CashCount.day.desc()).limit(1)
    )
    if last_day is None:
        return {}
    rows = db.scalars(select(CashCount).where(CashCount.day == last_day, CashCount.counted.is_not(None))).all()
    return {r.currency: r.counted for r in rows}


def load_range(db: Session, start: date, end: date):
    """Everything between start and end (inclusive), grouped by day, with a reconciliation per day."""
    def grouped(model):
        out = defaultdict(list)
        for row in db.scalars(select(model).where(model.day >= start, model.day <= end).order_by(model.id)):
            out[row.day].append(row)
        return out

    entries, handovers, expenses, counts = grouped(Entry), grouped(Handover), grouped(Expense), grouped(CashCount)
    closes = {c.day: c for c in db.scalars(select(DayClose).where(DayClose.day >= start, DayClose.day <= end))}
    days = sorted(set(entries) | set(handovers) | set(expenses) | set(counts) | set(closes))
    result = []
    for d in days:
        rec = _reconcile(entries[d], handovers[d], expenses[d], counts[d], closes.get(d))
        result.append((d, entries[d], handovers[d], expenses[d], rec))
    return result
