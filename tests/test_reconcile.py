from decimal import Decimal as D

from app.services.reconcile import CashLine, Count, IncomeLine, reconcile


def inc(method, amount, currency="AMD", rate=1, channel="Walk-in", in_pms=True):
    return IncomeLine(method, channel, D(amount), currency, D(amount) * D(rate), in_pms)


def test_untouched_day_is_open():
    r = reconcile([inc("cash", 8000)], [], [], [], None, None)
    assert r.status == "open"
    assert r.total_base == D(8000)


def test_balanced_day():
    r = reconcile(
        income=[inc("cash", 8000), inc("card", 12000), inc("ota", 15000, channel="Booking.com")],
        handovers=[CashLine(D(10000), "AMD")],
        expenses=[CashLine(D(2000), "AMD")],
        counts=[Count("AMD", D(20000), D(16000))],  # 20000 + 8000 - 10000 - 2000
        terminal_total=D(12000),
        pms_total=D(35000),
    )
    assert r.status == "balanced", r.issues
    assert r.cash[0].expected == D(16000)
    assert r.by_method == {"cash": D(8000), "card": D(12000), "ota": D(15000)}


def test_handover_not_recorded_shows_as_cash_short():
    # Manager took 10,000 but nobody wrote it down: the drawer looks 10,000 short.
    r = reconcile([inc("cash", 8000)], [], [], [Count("AMD", D(20000), D(18000))], None, None)
    assert r.status == "mismatch"
    assert r.cash[0].difference == D(-10000)


def test_ota_prepaid_never_counts_as_cash():
    r = reconcile([inc("ota", 15000, channel="Agoda")], [], [], [Count("AMD", D(0), D(0))], None, None)
    assert r.status == "balanced"
    assert r.cash[0].cash_in == D(0)


def test_cash_is_tracked_per_currency():
    r = reconcile(
        income=[inc("cash", 20, "USD", 385), inc("cash", 5000)],
        handovers=[], expenses=[],
        counts=[Count("AMD", D(0), D(5000)), Count("USD", D(100), D(110))],
        terminal_total=None, pms_total=None,
    )
    usd = next(c for c in r.cash if c.currency == "USD")
    assert usd.expected == D(120)
    assert usd.difference == D(-10)
    assert r.status == "mismatch"
    assert r.cash[0].currency == "AMD"  # base currency is always listed first


def test_card_and_pms_differences():
    r = reconcile([inc("card", 12000, in_pms=False)], [], [], [], D(11000), D(0))
    assert r.card_difference == D(-1000)
    assert r.pms_difference == D(-12000)
    assert r.missing_in_pms == 1
    assert len(r.issues) == 3


def test_tolerance_absorbs_rounding():
    r = reconcile([inc("card", "100.40")], [], [], [], D("100"), None, tolerance=D(1))
    assert r.status == "balanced"
