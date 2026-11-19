"""The Broker page has to stay honest: named sources, dated checks, no referral.

These tests fail if an entity is dropped from the page, if a result loses its
status, or if a commission-earning link ever creeps onto it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import state  # noqa: E402
from auth import hash_password  # noqa: E402
from database.database import Database  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")


def _render(page: str) -> str:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["public_page"] = page
    at.run()
    assert not at.exception, at.exception
    return "\n".join(str(element.value) for element in at.markdown)


def test_every_reviewed_entity_is_listed_with_its_status():
    rendered = _render("Broker")
    for row in config.BROKER_REVIEW:
        assert row["name"] in rendered, row["name"]
        assert row["status"] in rendered, row["status"]


def test_page_carries_no_link_or_referral_code():
    rendered = _render("Broker").lower()
    for marker in ("href", "http", "crm.", "/links/go", "t.me", "wa.me"):
        assert marker not in rendered, marker


def test_page_states_the_relationship_and_the_risk():
    rendered = _render("Broker")
    assert "not a broker" in rendered
    assert "No referral links" in rendered
    assert "Risk notice" in rendered
    assert config.BROKER_VERIFICATION_DATE in rendered


def test_settings_compatibility_carries_the_same_record(tmp_path, monkeypatch):
    """A planned integration in Settings must not read as an endorsement."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "broker.db")
    state.get_database.clear()
    database = Database(config.DB_PATH)
    account = database.create_account("Broker Demo", config.DEMO_STARTING_BALANCE)
    user = database.create_user(
        email="broker@example.com", name="Broker User",
        password_hash=hash_password("password123"), account_id=int(account["id"]),
    )
    try:
        at = AppTest.from_file(APP, default_timeout=90)
        at.session_state["mnz_user"] = user
        at.session_state["_mnz_bootstrapped"] = True
        at.session_state["mnz_page"] = "Settings"
        at.session_state["nav_radio"] = "Settings"
        at.run()
        assert not at.exception, at.exception
        rendered = "\n".join(str(element.value) for element in at.markdown)
        assert "Broker due diligence" in rendered
        assert "Planned is not an endorsement" in rendered
        for row in config.BROKER_REVIEW:
            assert row["status"] in rendered, row["status"]
    finally:
        state.get_database.clear()


def test_unverified_principal_is_flagged_not_softened():
    razor = next(row for row in config.BROKER_REVIEW if row["name"].startswith("Razor"))
    assert razor["tone"] == "bad"
    assert "Not verified" in razor["status"]
