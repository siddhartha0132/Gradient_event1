import time

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module
from app.core.security import hash_password
from app.db import session as session_module
from app.db.models import Round, Team, User

PASSWORD = "pw"

GOOD_BOT = "def strategy(my_history, opp_history):\n    return opp_history[-1] if opp_history else 'C'\n"
MEAN_BOT = "def strategy(my_history, opp_history):\n    return 'D'\n"
NICE_BOT = "def strategy(my_history, opp_history):\n    return 'C'\n"
BAD_BOT = "import os\ndef strategy(my_history, opp_history):\n    return 'C'\n"


def _clear_caches():
    settings_module.get_settings.cache_clear()
    for fn in (session_module.async_engine, session_module.async_sessions,
               session_module.sync_engine, session_module.sync_sessions):
        fn.cache_clear()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("IC_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("IC_CLIENT_DIST", str(tmp_path / "no-client"))
    _clear_caches()
    session_module.create_tables()
    with session_module.sync_sessions()() as s:
        s.add(Round(index=1, name="Opening Moves", game="prisoners_dilemma", turns=20, repetitions=1,
                    keep_fraction=0.5, seed="test-seed"))
        s.add(Round(index=2, name="Endgame", game="stag_hunt", turns=20, repetitions=1, keep_count=1))
        s.add(User(username="organiser", role="organiser", password_hash=hash_password(PASSWORD)))
        for i in range(1, 5):
            team = Team(name=f"Team {i}")
            s.add(team)
            s.flush()
            s.add(User(username=f"team{i}", role="team", team_id=team.id, password_hash=hash_password(PASSWORD)))
        s.commit()
    yield session_module.sync_sessions()
    _clear_caches()


@pytest.fixture
def client(db):
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, username):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_for(predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out waiting")
