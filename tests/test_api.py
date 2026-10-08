DAY = "2026-10-08"


def test_requires_login(client):
    assert client.get(f"/api/days/{DAY}").status_code == 401


def test_wrong_password(client):
    r = client.post("/api/auth/token", data={"username": "staff", "password": "nope"})
    assert r.status_code == 401


def test_full_day_flow(client, staff):
    pay = lambda **kw: client.post("/api/entries", headers=staff, json={"day": DAY, **kw})
    assert pay(guest="Anna", channel="Walk-in", method="cash", amount=8000).status_code == 201
    assert pay(guest="Tom", channel="Hostelworld", method="card", amount=12000, in_pms=True).status_code == 201
    r = pay(guest="Lea", channel="Airbnb", method="cash", amount=20, currency="USD", in_pms=True)
    assert r.json()["base_amount"] == 7700  # rate captured at entry time

    client.post("/api/handovers", headers=staff, json={"day": DAY, "amount": 5000, "time": "21:00"})
    client.post("/api/expenses", headers=staff, json={"day": DAY, "amount": 1000, "description": "soap"})

    r = client.put(f"/api/days/{DAY}/close", headers=staff, json={
        "terminal_total": 12000, "pms_total": 27700,
        "cash": [{"currency": "AMD", "opening": 10000, "counted": 12000},
                 {"currency": "USD", "opening": 0, "counted": 20}],
    })
    assert r.status_code == 200, r.text
    rec = r.json()["reconciliation"]
    # Anna's payment is not ticked as entered in the PMS yet
    assert rec["status"] == "mismatch"
    assert rec["missing_in_pms"] == 1
    assert all(c["difference"] == 0 for c in rec["cash"])

    anna = r.json()["entries"][0]
    client.patch(f"/api/entries/{anna['id']}", headers=staff, json={"in_pms": True})
    assert client.get(f"/api/days/{DAY}", headers=staff).json()["reconciliation"]["status"] == "balanced"

    # next day's opening float is suggested from today's count
    nxt = client.get("/api/days/2026-10-09", headers=staff).json()
    assert nxt["suggested_opening"] == {"AMD": 12000, "USD": 20}


def test_unknown_currency_rate_is_a_clear_error(client, staff):
    r = client.post("/api/entries", headers=staff, json={"day": DAY, "channel": "Walk-in", "method": "cash", "amount": 10, "currency": "EUR"})
    assert r.status_code == 400
    assert "EUR" in r.json()["detail"]


def test_validation(client, staff):
    bad = client.post("/api/entries", headers=staff, json={"day": DAY, "channel": "MySpace", "method": "cash", "amount": 10})
    assert bad.status_code == 422
    neg = client.post("/api/entries", headers=staff, json={"day": DAY, "channel": "Walk-in", "method": "cash", "amount": -5})
    assert neg.status_code == 422


def test_only_manager_confirms_handover_and_confirmed_ones_are_protected(client, staff, manager):
    h = client.post("/api/handovers", headers=staff, json={"day": DAY, "amount": 30000}).json()
    assert client.post(f"/api/handovers/{h['id']}/confirm", headers=staff).status_code == 403
    r = client.post(f"/api/handovers/{h['id']}/confirm", headers=manager)
    assert r.json()["confirmed"] is True
    assert client.delete(f"/api/handovers/{h['id']}", headers=staff).status_code == 403
    assert client.delete(f"/api/handovers/{h['id']}", headers=manager).status_code == 204


def test_only_manager_sets_rates(client, staff, manager):
    body = [{"currency": "EUR", "base_per_unit": 450}]
    assert client.put("/api/rates", headers=staff, json=body).status_code == 403
    rates = client.put("/api/rates", headers=manager, json=body).json()
    assert {r["currency"] for r in rates} == {"USD", "EUR"}


def test_monthly_report_and_csv(client, staff):
    for d, amt in [("2026-10-01", 7000), ("2026-10-15", 9000), ("2026-11-01", 5000)]:
        client.post("/api/entries", headers=staff, json={"day": d, "channel": "Booking.com", "method": "ota", "amount": amt})
    m = client.get("/api/reports/monthly?month=2026-10", headers=staff).json()
    assert m["total_base"] == 16000
    assert m["by_channel"] == {"Booking.com": 16000}
    assert [d["day"] for d in m["days"]] == ["2026-10-01", "2026-10-15"]

    csv = client.get("/api/reports/monthly.csv?month=2026-10", headers=staff)
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.count("\n") == 3  # header + two rows

    assert client.get("/api/reports/monthly?month=2026-13", headers=staff).status_code == 400
