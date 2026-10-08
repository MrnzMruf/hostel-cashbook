"""Daily reconciliation, kept free of the database so it is easy to test.

For each day it answers three questions:

1. Cash drawer, per currency:
       expected = opening + cash income - handovers - cash expenses
       difference = counted - expected
2. Card: POS Z-report total minus the card income recorded here.
3. PMS: the total entered in Airtable / the PMS minus everything recorded here,
   plus how many entries are not yet marked as entered there.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Literal

ZERO = Decimal("0")


@dataclass(frozen=True)
class IncomeLine:
    method: str
    channel: str
    amount: Decimal
    currency: str
    base_amount: Decimal
    in_pms: bool


@dataclass(frozen=True)
class CashLine:
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Count:
    currency: str
    opening: Decimal | None
    counted: Decimal | None


@dataclass
class CashResult:
    currency: str
    opening: Decimal
    cash_in: Decimal
    handed_over: Decimal
    expenses: Decimal
    expected: Decimal
    counted: Decimal | None
    difference: Decimal | None


@dataclass
class Reconciliation:
    total_base: Decimal
    by_method: dict[str, Decimal]
    by_channel: dict[str, Decimal]
    cash: list[CashResult]
    card_recorded: Decimal
    card_terminal: Decimal | None
    card_difference: Decimal | None
    pms_total: Decimal | None
    pms_difference: Decimal | None
    missing_in_pms: int
    status: Literal["open", "balanced", "mismatch"]
    issues: list[str] = field(default_factory=list)


def _sum_by(lines: Iterable[CashLine]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for line in lines:
        out[line.currency] = out.get(line.currency, ZERO) + line.amount
    return out


def reconcile(
    income: list[IncomeLine],
    handovers: list[CashLine],
    expenses: list[CashLine],
    counts: list[Count],
    terminal_total: Decimal | None,
    pms_total: Decimal | None,
    base_currency: str = "AMD",
    tolerance: Decimal = Decimal("1"),
) -> Reconciliation:
    total = ZERO
    by_method: dict[str, Decimal] = {}
    by_channel: dict[str, Decimal] = {}
    card = ZERO
    missing = 0
    cash_in: dict[str, Decimal] = {}

    for line in income:
        total += line.base_amount
        by_method[line.method] = by_method.get(line.method, ZERO) + line.base_amount
        by_channel[line.channel] = by_channel.get(line.channel, ZERO) + line.base_amount
        if line.method == "cash":
            cash_in[line.currency] = cash_in.get(line.currency, ZERO) + line.amount
        elif line.method == "card":
            card += line.base_amount
        if not line.in_pms:
            missing += 1

    out_hand = _sum_by(handovers)
    out_exp = _sum_by(expenses)
    count_map = {c.currency: c for c in counts}

    currencies = [base_currency] + sorted(
        (set(cash_in) | set(out_hand) | set(out_exp) | set(count_map)) - {base_currency}
    )

    issues: list[str] = []
    any_closed = False
    cash_results: list[CashResult] = []
    for cur in currencies:
        c = count_map.get(cur)
        opening = (c.opening if c and c.opening is not None else ZERO)
        expected = opening + cash_in.get(cur, ZERO) - out_hand.get(cur, ZERO) - out_exp.get(cur, ZERO)
        counted = c.counted if c else None
        diff = None
        if counted is not None:
            any_closed = True
            diff = counted - expected
            if abs(diff) >= tolerance:
                issues.append(f"cash {cur} off by {diff:+}")
        cash_results.append(CashResult(
            currency=cur, opening=opening, cash_in=cash_in.get(cur, ZERO),
            handed_over=out_hand.get(cur, ZERO), expenses=out_exp.get(cur, ZERO),
            expected=expected, counted=counted, difference=diff,
        ))

    card_diff = None
    if terminal_total is not None:
        any_closed = True
        card_diff = terminal_total - card
        if abs(card_diff) >= tolerance:
            issues.append(f"card off by {card_diff:+}")

    pms_diff = None
    if pms_total is not None:
        any_closed = True
        pms_diff = pms_total - total
        if abs(pms_diff) >= tolerance:
            issues.append(f"PMS total off by {pms_diff:+}")

    if any_closed and missing:
        issues.append(f"{missing} entr{'y' if missing == 1 else 'ies'} not marked as entered in PMS")

    status: Literal["open", "balanced", "mismatch"]
    status = "open" if not any_closed else ("mismatch" if issues else "balanced")

    return Reconciliation(
        total_base=total, by_method=by_method, by_channel=by_channel, cash=cash_results,
        card_recorded=card, card_terminal=terminal_total, card_difference=card_diff,
        pms_total=pms_total, pms_difference=pms_diff, missing_in_pms=missing,
        status=status, issues=issues,
    )
