from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Rate, Role, User


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            User(username="staff", role=Role.staff, password_hash=hash_password("pw")),
            User(username="boss", role=Role.manager, password_hash=hash_password("pw")),
            Rate(currency="USD", base_per_unit=Decimal("385")),
        ])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def _get_db():
        with session_factory() as db:
            yield db
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username):
    r = client.post("/api/auth/token", data={"username": username, "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def staff(client):
    return _login(client, "staff")


@pytest.fixture()
def manager(client):
    return _login(client, "boss")
