from __future__ import annotations

import sys
from pathlib import Path

# Make sure the project root is importable so that `import app` and other
# top-level modules resolve the same way they do when Streamlit runs app.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from streamlit.testing.v1 import AppTest

PAGES = [
    "Overview",
    "Forex",
    "Crypto",
    "Stocks",
    "Commodities",
    "Indices",
    "AI Market Analyst",
    "Strategy Testing",
    "Demo Trading",
    "Trade History",
    "Performance Reports",
    "Settings",
]

HEADINGS = {
    "Overview": "Overview",
    "Forex": "Forex Engine",
    "Crypto": "Crypto Engine",
    "Stocks": "Stocks Engine",
    "Commodities": "Commodities Engine",
    "Indices": "Indices Engine",
    "AI Market Analyst": "AI Market Analyst",
    "Strategy Testing": "Strategy Testing",
    "Demo Trading": "Demo Trading",
    "Trade History": "Trade History",
    "Performance Reports": "Performance Reports",
    "Settings": "Settings",
}


@pytest.mark.parametrize("page", PAGES)
def test_app_renders_page(page):
    at = AppTest.from_file(str(_PROJECT_ROOT / "app.py"), default_timeout=30)
    at.run()
    at.radio[0].set_value(page).run()
    assert at.session_state["nav"] == page
    assert not at.exception, f"{page} raised: {at.exception}"
    rendered = "\n".join(str(element.value) for element in at.markdown)
    assert f"<h1>{HEADINGS[page]}</h1>" in rendered, f"{page} heading missing"
