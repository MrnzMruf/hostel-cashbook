"""Admin commands.

    python -m app.cli create-user mery --role staff
    python -m app.cli create-user shahin --role manager
    python -m app.cli seed-demo          # sample data for screenshots / demos
"""
import argparse
import getpass
import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import CashCount, DayClose, Entry, Expense, Handover, PaymentMethod, Rate, Role, User
from app.services.ledger import to_base


def create_user(username: str, role: str, password: str | None, full_name: str) -> None:
    password = password or getpass.getpass(f"Password for {username}: ")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit(f"User {username} already exists.")
        db.add(User(username=username, full_name=full_name, role=Role(role), password_hash=hash_password(password)))
        db.commit()
    print(f"Created {role} user '{username}'.")


DEMO_GUESTS = ["Anna K.", "Lukas M.", "Sofia R.", "Daniel P.", "Mei L.", "Oliver S.", "Ivan D.", "Sara B.",
               "Tom H.", "Lea F.", "Arman G.", "Nina V."]


def seed_demo(days: int = 14) -> None:
    """Fictional data only. Never commit real guest data."""
    rnd = random.Random(42)
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == "demo")):
            db.add(User(username="demo", full_name="Demo Reception", role=Role.staff, password_hash=hash_password("demo")))
            db.add(User(username="manager", full_name="Demo Manager", role=Role.manager, password_hash=hash_password("manager")))
        rates = {"USD": Decimal("385"), "EUR": Decimal("450"), "RUB": Decimal("4.8")}
        for cur, r in rates.items():
            if not db.get(Rate, cur):
                db.add(Rate(currency=cur, base_per_unit=r))
        db.flush()
        demo = db.scalar(select(User).where(User.username == "demo"))
        manager = db.scalar(select(User).where(User.username == "manager"))

        opening = Decimal("20000")
        start = date.today() - timedelta(days=days)
        for i in range(days):
            d = start + timedelta(days=i)
            cash_amd = Decimal("0")
            card = Decimal("0")
            total = Decimal("0")
            for _ in range(rnd.randint(3, 7)):
                ch = rnd.choice(settings.channels)
                method = PaymentMethod.ota if ch in ("Booking.com", "Agoda", "Trip.com") and rnd.random() < .4 \
                    else rnd.choice([PaymentMethod.cash, PaymentMethod.cash, PaymentMethod.card, PaymentMethod.bank])
                amount = Decimal(rnd.choice([6000, 7000, 8500, 12000, 14000, 17000]))
                base = to_base(amount, Decimal("1"))
                db.add(Entry(day=d, guest=rnd.choice(DEMO_GUESTS), channel=ch, method=method, amount=amount,
                             currency="AMD", rate=Decimal("1"), base_amount=base, in_pms=True,
                             booking_ref=f"DEMO{rnd.randint(10000, 99999)}" if ch not in ("Walk-in", "Direct") else "",
                             created_by_id=demo.id))
                total += base
                if method == PaymentMethod.cash:
                    cash_amd += amount
                elif method == PaymentMethod.card:
                    card += base
            hand = Decimal("0")
            if i % 3 == 2:
                hand = Decimal("30000")
                db.add(Handover(day=d, amount=hand, currency="AMD", time="21:00", created_by_id=demo.id,
                                confirmed_by_id=manager.id))
            exp = Decimal("0")
            if rnd.random() < .3:
                exp = Decimal("2500")
                db.add(Expense(day=d, description="Cleaning supplies", amount=exp, currency="AMD", created_by_id=demo.id))
            counted = opening + cash_amd - hand - exp
            if i == days - 4:
                counted -= Decimal("5000")  # one day with a missing 5,000 AMD, to show a mismatch
            db.add(CashCount(day=d, currency="AMD", opening=opening, counted=counted))
            db.add(DayClose(day=d, terminal_total=card, pms_total=total, updated_by_id=demo.id))
            opening = counted
        db.commit()
    print("Seeded demo data. Sign in as demo/demo (staff) or manager/manager.")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", choices=[r.value for r in Role], default="staff")
    cu.add_argument("--password")
    cu.add_argument("--name", default="")
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--days", type=int, default=14)
    a = p.parse_args()
    if a.cmd == "create-user":
        create_user(a.username, a.role, a.password, a.name)
    else:
        seed_demo(a.days)


if __name__ == "__main__":
    main()
