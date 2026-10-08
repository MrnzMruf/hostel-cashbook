import calendar
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.auth import authenticate, create_token, current_user, require_manager
from app.config import settings
from app.db import get_db
from app.models import (
    CashCount, DayClose, Entry, Expense, Handover, PaymentMethod, Rate, Role, User,
)
from app.services import ledger

router = APIRouter(prefix="/api")


def _rate_or_400(db: Session, currency: str) -> Decimal:
    try:
        return ledger.rate_for(db, currency)
    except LookupError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {obj_id} not found.")
    return obj


# ---------------- auth & meta ----------------
@router.post("/auth/token", response_model=schemas.Token, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate(db, form.username, form.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password.")
    return schemas.Token(access_token=create_token(user))


@router.get("/auth/me", response_model=schemas.UserOut, tags=["auth"])
def me(user: User = Depends(current_user)):
    return user


@router.get("/meta", response_model=schemas.Meta, tags=["meta"])
def meta():
    return schemas.Meta(
        channels=settings.channels, currencies=settings.currencies,
        base_currency=settings.base_currency, methods=list(PaymentMethod),
    )


# ---------------- rates ----------------
@router.get("/rates", response_model=list[schemas.RateOut], tags=["rates"])
def list_rates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Rate).order_by(Rate.currency)).all()


@router.put("/rates", response_model=list[schemas.RateOut], tags=["rates"])
def set_rates(body: list[schemas.RateIn], db: Session = Depends(get_db), _: User = Depends(require_manager)):
    for r in body:
        if r.currency == settings.base_currency:
            continue
        row = db.get(Rate, r.currency)
        if row:
            row.base_per_unit = r.base_per_unit
        else:
            db.add(Rate(currency=r.currency, base_per_unit=r.base_per_unit))
    db.commit()
    return db.scalars(select(Rate).order_by(Rate.currency)).all()


# ---------------- entries ----------------
@router.post("/entries", response_model=schemas.EntryOut, status_code=201, tags=["entries"])
def create_entry(body: schemas.EntryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rate = _rate_or_400(db, body.currency)
    entry = Entry(**body.model_dump(), rate=rate, base_amount=ledger.to_base(body.amount, rate), created_by_id=user.id)
    db.add(entry)
    db.commit()
    return entry


@router.patch("/entries/{entry_id}", response_model=schemas.EntryOut, tags=["entries"])
def update_entry(entry_id: int, body: schemas.EntryPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    entry = _get_or_404(db, Entry, entry_id)
    changes = body.model_dump(exclude_unset=True)
    money_changed = "amount" in changes or "currency" in changes
    for k, v in changes.items():
        if v is not None:
            setattr(entry, k, v)
    if "currency" in changes:
        entry.rate = _rate_or_400(db, entry.currency)  # a new currency needs its current rate
    if money_changed:
        entry.base_amount = ledger.to_base(entry.amount, entry.rate)
    db.commit()
    return entry


@router.delete("/entries/{entry_id}", status_code=204, tags=["entries"])
def delete_entry(entry_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(_get_or_404(db, Entry, entry_id))
    db.commit()
    return Response(status_code=204)


# ---------------- handovers ----------------
@router.post("/handovers", response_model=schemas.HandoverOut, status_code=201, tags=["handovers"])
def create_handover(body: schemas.HandoverIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    h = Handover(**body.model_dump(), created_by_id=user.id)
    db.add(h)
    db.commit()
    return h


@router.post("/handovers/{handover_id}/confirm", response_model=schemas.HandoverOut, tags=["handovers"])
def confirm_handover(handover_id: int, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    """The manager confirms they actually received the cash."""
    h = _get_or_404(db, Handover, handover_id)
    if h.confirmed_at is None:
        h.confirmed_at = datetime.now(timezone.utc)
        h.confirmed_by_id = user.id
        db.commit()
    return h


@router.delete("/handovers/{handover_id}", status_code=204, tags=["handovers"])
def delete_handover(handover_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    h = _get_or_404(db, Handover, handover_id)
    if h.confirmed_at is not None and user.role != Role.manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This handover was confirmed by the manager; only a manager can delete it.")
    db.delete(h)
    db.commit()
    return Response(status_code=204)


# ---------------- expenses ----------------
@router.post("/expenses", response_model=schemas.ExpenseOut, status_code=201, tags=["expenses"])
def create_expense(body: schemas.ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = Expense(**body.model_dump(), created_by_id=user.id)
    db.add(x)
    db.commit()
    return x


@router.delete("/expenses/{expense_id}", status_code=204, tags=["expenses"])
def delete_expense(expense_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(_get_or_404(db, Expense, expense_id))
    db.commit()
    return Response(status_code=204)


# ---------------- days ----------------
def _day_out(db: Session, day: date) -> schemas.DayOut:
    entries, handovers, expenses, counts, close, rec = ledger.load_day(db, day)
    return schemas.DayOut(
        day=day,
        entries=[schemas.EntryOut.model_validate(e) for e in entries],
        handovers=[schemas.HandoverOut.model_validate(h) for h in handovers],
        expenses=[schemas.ExpenseOut.model_validate(x) for x in expenses],
        close_note=close.note if close else "",
        suggested_opening=ledger.suggested_opening(db, day),
        reconciliation=schemas.ReconciliationOut.model_validate(rec, from_attributes=True),
    )


@router.get("/days/{day}", response_model=schemas.DayOut, tags=["days"])
def get_day(day: date, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _day_out(db, day)


@router.put("/days/{day}/close", response_model=schemas.DayOut, tags=["days"])
def close_day(day: date, body: schemas.DayCloseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    close = db.get(DayClose, day) or DayClose(day=day)
    close.terminal_total = body.terminal_total
    close.pms_total = body.pms_total
    close.note = body.note
    close.updated_by_id = user.id
    db.add(close)

    existing = {c.currency: c for c in db.scalars(select(CashCount).where(CashCount.day == day))}
    for c in body.cash:
        row = existing.get(c.currency) or CashCount(day=day, currency=c.currency)
        row.opening, row.counted = c.opening, c.counted
        db.add(row)
    db.commit()
    return _day_out(db, day)


# ---------------- reports ----------------
def _month_bounds(month: str) -> tuple[date, date]:
    try:
        y, m = (int(p) for p in month.split("-"))
        return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must look like 2026-10")


MonthParam = Query(..., pattern=r"^\d{4}-\d{2}$", examples=["2026-10"])


@router.get("/reports/monthly", response_model=schemas.MonthlyReport, tags=["reports"])
def monthly(month: str = MonthParam, db: Session = Depends(get_db), _: User = Depends(current_user)):
    start, end = _month_bounds(month)
    rows = ledger.load_range(db, start, end)
    total, n = Decimal("0"), 0
    by_channel: dict[str, Decimal] = {}
    by_method: dict[str, Decimal] = {}
    hand_list, hand_sum = [], {}
    days = []
    for d, entries, handovers, _x, rec in rows:
        total += rec.total_base
        n += len(entries)
        for k, v in rec.by_channel.items():
            by_channel[k] = by_channel.get(k, Decimal("0")) + v
        for k, v in rec.by_method.items():
            by_method[k] = by_method.get(k, Decimal("0")) + v
        for h in handovers:
            hand_list.append(schemas.HandoverOut.model_validate(h))
            hand_sum[h.currency] = hand_sum.get(h.currency, Decimal("0")) + h.amount
        days.append(schemas.DaySummary(day=d, entries=len(entries), total_base=rec.total_base, status=rec.status, issues=rec.issues))
    return schemas.MonthlyReport(
        month=month, total_base=total, entries=n, by_channel=by_channel, by_method=by_method,
        handovers=hand_list, handovers_by_currency=hand_sum, days=days,
    )


@router.get("/reports/monthly.csv", tags=["reports"])
def monthly_csv(month: str = MonthParam, db: Session = Depends(get_db), _: User = Depends(current_user)):
    start, end = _month_bounds(month)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "type", "guest_or_description", "channel", "method", "amount", "currency",
                "rate", f"amount_{settings.base_currency.lower()}", "booking_ref", "in_pms", "note"])
    for d, entries, handovers, expenses, _rec in ledger.load_range(db, start, end):
        for e in entries:
            w.writerow([d, "income", e.guest, e.channel, e.method.value, e.amount, e.currency, e.rate,
                        e.base_amount, e.booking_ref, "yes" if e.in_pms else "no", e.note])
        for h in handovers:
            w.writerow([d, "handover", "", "", "cash", h.amount, h.currency, "", "", "",
                        "", f"{h.time} {'confirmed' if h.confirmed else 'unconfirmed'} {h.note}".strip()])
        for x in expenses:
            w.writerow([d, "expense", x.description, "", "cash", x.amount, x.currency, "", "", "", "", ""])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cashbook-{month}.csv"'},
    )
