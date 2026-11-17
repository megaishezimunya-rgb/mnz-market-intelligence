"""End-to-end rendering tests for the public site and the six-section app.

Market data is stubbed with a deterministic local frame so these tests never
depend on the network. The real provider path is exercised separately by the
running app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import state  # noqa: E402
from auth import hash_password  # noqa: E402
from data import market_data  # noqa: E402
from database.database import Database  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")
HEADINGS = {
    "Home": "Home",
    "Markets": "Markets",
    "Signals": "Signals",
    "Demo": "Demo",
    "MNZ AI": "MNZ AI",
    "Settings": "Settings",
}


def _fake_live(symbol, period, interval):
    n = 320
    rng = np.random.default_rng(abs(hash(symbol)) % (2**31))
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.008, n)))
    end = pd.Timestamp.utcnow().floor("h")
    index = pd.date_range(end=end, periods=n, freq="h")
    return market_data.PriceData(
        symbol=symbol, period=period, interval=interval,
        frame=pd.DataFrame({
            "Open": closes, "High": closes * 1.004, "Low": closes * 0.996,
            "Close": closes, "Volume": rng.uniform(1e5, 9e5, n),
        }, index=index),
        source="test feed", fetched_at=config.utcnow(), is_sample=False, delayed=True,
    )


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "smoke.db")
    monkeypatch.setattr(market_data, "_fetch_live", _fake_live)
    market_data.clear_cache()
    state.get_database.clear()

    db = Database(config.DB_PATH)
    account = db.create_account("Smoke Demo", config.DEMO_STARTING_BALANCE)
    user = db.create_user(
        email="smoke@example.com", name="Smoke User",
        password_hash=hash_password("password123"), account_id=int(account["id"]),
    )
    yield db, user
    state.get_database.clear()
    market_data.clear_cache()


def _signed_in(user: dict) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["mnz_user"] = user
    at.session_state["_mnz_bootstrapped"] = True
    return at


def _markdown(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.markdown)


def test_public_site_renders_signed_out():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    rendered = _markdown(at)
    assert "Read the market" in rendered
    assert "Create a free demo account" in [b.label for b in at.button]
    assert "Public navigation" == at.pills[0].label


def test_authenticated_pages_render(app_env):
    _, user = app_env
    at = _signed_in(user)
    at.run()
    assert not at.exception, at.exception
    assert at.radio[0].options == config.NAV_ITEMS

    for page in config.NAV_ITEMS:
        at.session_state["mnz_page"] = page
        at.session_state["nav_radio"] = page
        at.run()
        assert not at.exception, f"{page} raised: {at.exception}"
        assert f"<h1>{HEADINGS[page]}</h1>" in _markdown(at), f"{page} heading missing"


def test_mobile_navigation_has_all_six_sections(app_env):
    _, user = app_env
    at = _signed_in(user)
    at.run()
    labels = [button.label for button in at.button]
    for label in ["Home", "Markets", "Signals", "Demo", "AI", "Settings"]:
        assert label in labels


def test_login_flow_from_public_site(app_env):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["public_page"] = "Login"
    at.run()
    assert not at.exception, at.exception

    email = next(widget for widget in at.text_input if widget.label == "Email")
    password = next(widget for widget in at.text_input if widget.label == "Password")
    email.set_value("smoke@example.com")
    password.set_value("password123")
    submit = next(button for button in at.button if button.label == "Sign in")
    submit.click().run()

    assert not at.exception, at.exception
    assert at.session_state["mnz_user"]["email"] == "smoke@example.com"
    assert "<h1>Home</h1>" in _markdown(at)


def test_login_rejects_wrong_password(app_env):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["public_page"] = "Login"
    at.run()
    next(widget for widget in at.text_input if widget.label == "Email").set_value("smoke@example.com")
    next(widget for widget in at.text_input if widget.label == "Password").set_value("wrong-password")
    next(button for button in at.button if button.label == "Sign in").click().run()
    assert not at.exception
    assert any("incorrect" in error.value.lower() for error in at.error)
    assert "mnz_user" not in at.session_state


def test_scan_all_stores_signals_and_does_not_duplicate(app_env):
    db, user = app_env
    at = _signed_in(user)
    at.session_state["mnz_page"] = "Markets"
    at.session_state["nav_radio"] = "Markets"
    at.run()
    assert not at.exception, at.exception

    scan_all = next(button for button in at.button if button.label == "Scan all")
    scan_all.click().run()
    assert not at.exception, at.exception
    stored = db.list_signals(int(user["id"]), limit=100)
    assert len(stored) >= 5
    first_count = len(stored)

    scan_all = next(button for button in at.button if button.label == "Scan all")
    scan_all.click().run()
    assert not at.exception, at.exception
    assert len(db.list_signals(int(user["id"]), limit=100)) == first_count
