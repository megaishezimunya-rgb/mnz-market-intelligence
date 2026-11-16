"""MNZ visual system: theme, charts and reusable components.

Black, white and charcoal only.  No gradients, no gold, no decorative motion.
Every helper here renders through Streamlit so the pages stay declarative.
"""

from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from plotly.subplots import make_subplots

import config
from analysis import indicators
from analysis.market_analyst import AnalystReport
from data.market_data import PriceData

COLORS = config.COLORS
_TEMPLATE = "mnz"

CSS = """
<style>
:root {
  --mnz-black: #0A0A0B;
  --mnz-panel: #121214;
  --mnz-panel-alt: #17171A;
  --mnz-border: #26262A;
  --mnz-border-strong: #3A3A40;
  --mnz-text: #F4F4F5;
  --mnz-muted: #8C8C93;
  --mnz-font: "Inter", "Helvetica Neue", Helvetica, Arial, system-ui, -apple-system, sans-serif;
}

html, body, [class*="css"], .stApp, button, input, textarea, select {
  font-family: var(--mnz-font);
  -webkit-font-smoothing: antialiased;
}

.stApp { background: var(--mnz-black); color: var(--mnz-text); }

[data-testid="stHeader"] { background: transparent; }
[data-testid="stHeader"] > div { background: transparent; }
[data-testid="stToolbar"] { right: 1rem; }

.block-container {
  padding-top: 2.4rem;
  padding-bottom: 3rem;
  max-width: 1520px;
}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {
  background: #070708;
  border-right: 1px solid var(--mnz-border);
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0.4rem; }
[data-testid="stSidebar"] .block-container { padding-top: 0.8rem; }

.mnz-logo {
  padding: 0.6rem 0 1.1rem 0;
  margin-bottom: 0.9rem;
  border-bottom: 1px solid var(--mnz-border);
}
.mnz-logo .mark {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  color: #FFFFFF;
  font-size: 2.05rem;
  font-weight: 700;
  letter-spacing: 0.22em;
  line-height: 1;
}
.mnz-logo .mark .tick {
  display: inline-block;
  width: 7px; height: 7px;
  background: #FFFFFF;
  margin-bottom: 3px;
}
.mnz-logo .sub {
  margin-top: 0.55rem;
  font-size: 0.6rem;
  letter-spacing: 0.3em;
  color: var(--mnz-muted);
  text-transform: uppercase;
  white-space: nowrap;
}
.mnz-logo .ver {
  margin-top: 0.35rem;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: #5C5C64;
}

.mnz-nav-caption {
  font-size: 0.6rem;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: #5C5C64;
  margin: 0.2rem 0 0.5rem 0;
}

[data-testid="stSidebar"] div[role="radiogroup"] { gap: 2px; }
[data-testid="stSidebar"] div[role="radiogroup"] label {
  padding: 0.5rem 0.7rem;
  border-radius: 7px;
  border: 1px solid transparent;
  color: #B9B9C0;
  font-size: 0.86rem;
  letter-spacing: 0.01em;
  transition: none;
  cursor: pointer;
}
[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
  background: #131316;
  color: #FFFFFF;
}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
  background: #F4F4F5;
  color: #0A0A0B;
  font-weight: 600;
  border-color: #F4F4F5;
}
/* Hide the radio circle: it is the first child of the label's flex wrapper. */
[data-testid="stSidebar"] div[role="radiogroup"] label > div { gap: 0 !important; }
[data-testid="stSidebar"] div[role="radiogroup"] label > div > div:first-child { display: none; }
[data-testid="stSidebar"] div[role="radiogroup"] label [data-testid="stMarkdownContainer"] { display: block !important; }
[data-testid="stSidebar"] div[role="radiogroup"] label p { font-size: 0.86rem; color: inherit; }
[data-testid="stSidebar"] div[role="radiogroup"] label[data-selected="true"],
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
  background: #F4F4F5;
  color: #0A0A0B;
  border-color: #F4F4F5;
}
[data-testid="stSidebar"] div[role="radiogroup"] label[data-selected="true"] p,
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
  color: #0A0A0B;
  font-weight: 600;
}

.mnz-sidebar-foot {
  margin-top: 1.2rem;
  padding-top: 0.9rem;
  border-top: 1px solid var(--mnz-border);
  font-size: 0.66rem;
  line-height: 1.6;
  color: #6E6E76;
  letter-spacing: 0.02em;
}
.mnz-sidebar-foot strong { color: #B9B9C0; font-weight: 600; letter-spacing: 0.12em; }

/* ---------- Typography ---------- */
h1, h2, h3, h4 { color: var(--mnz-text); font-family: var(--mnz-font); }
h1 { font-size: 1.7rem !important; font-weight: 600 !important; letter-spacing: -0.02em; margin-bottom: 0.1rem !important; }
h2 { font-size: 1.22rem !important; font-weight: 600 !important; letter-spacing: -0.01em; }
h3 {
  font-size: 0.74rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mnz-muted) !important;
  margin-top: 0.4rem !important;
}
p, li, label, span { color: var(--mnz-text); }
a { color: #FFFFFF; }

.mnz-page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--mnz-border);
  margin-bottom: 1.3rem;
}
.mnz-page-head .titles h1 { margin: 0 !important; }
.mnz-page-head .sub {
  font-size: 0.82rem;
  color: var(--mnz-muted);
  margin-top: 0.35rem;
  max-width: 70ch;
  line-height: 1.5;
}
.mnz-page-head .tag {
  flex: 0 0 auto;
  font-size: 0.62rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--mnz-muted);
  border: 1px solid var(--mnz-border-strong);
  padding: 0.3rem 0.55rem;
  border-radius: 4px;
  white-space: nowrap;
}

/* ---------- Demo bar ---------- */
.mnz-demo-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  border: 1px solid var(--mnz-border-strong);
  background: var(--mnz-panel);
  border-left: 3px solid #FFFFFF;
  padding: 0.6rem 0.9rem;
  margin-bottom: 1.4rem;
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #E6E6E8;
}
.mnz-demo-bar .right { color: var(--mnz-muted); letter-spacing: 0.1em; }
.mnz-demo-bar .dot {
  display: inline-block; width: 6px; height: 6px; background: #FFFFFF;
  margin-right: 0.55rem; vertical-align: middle;
}

/* ---------- Cards & KPI ---------- */
.mnz-card {
  background: var(--mnz-panel);
  border: 1px solid var(--mnz-border);
  border-radius: 10px;
  padding: 0.95rem 1.05rem;
  margin-bottom: 0.75rem;
}
.mnz-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 0.6rem;
  margin-bottom: 0.9rem;
}
.mnz-kpi {
  background: var(--mnz-panel);
  border: 1px solid var(--mnz-border);
  border-radius: 10px;
  padding: 0.85rem 1rem 0.9rem 1rem;
  height: 100%;
}
.mnz-kpi .label {
  font-size: 0.62rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--mnz-muted);
  margin-bottom: 0.42rem;
  line-height: 1.4;
  white-space: normal;
  overflow-wrap: anywhere;
}
.mnz-kpi .value {
  font-size: 1.42rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  color: #FFFFFF;
  word-break: break-word;
}
.mnz-kpi .note {
  font-size: 0.7rem;
  color: var(--mnz-muted);
  margin-top: 0.35rem;
  line-height: 1.4;
}
.mnz-kpi .value.up::before { content: "▲ "; font-size: 0.7em; }
.mnz-kpi .value.down::before { content: "▼ "; font-size: 0.7em; }

/* ---------- Labels / pills ---------- */
.mnz-pill {
  display: inline-block;
  font-size: 0.64rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  padding: 0.3rem 0.6rem;
  border-radius: 4px;
  border: 1px solid var(--mnz-border-strong);
  color: var(--mnz-text);
  background: transparent;
  white-space: nowrap;
}
.mnz-pill.buy { background: #FFFFFF; color: #0A0A0B; border-color: #FFFFFF; font-weight: 700; }
.mnz-pill.sell { background: #2A2A2E; color: #FFFFFF; border-color: #6E6E76; font-weight: 700; }
.mnz-pill.wait { background: transparent; color: #B9B9C0; border-color: #3A3A40; font-weight: 600; }
.mnz-pill.nodata { background: transparent; color: #8C8C93; border-style: dashed; }

.mnz-report-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
  margin-bottom: 0.55rem;
}
.mnz-report-head .sym { font-size: 1.1rem; font-weight: 600; letter-spacing: 0.02em; }
.mnz-report-head .conf { font-size: 0.7rem; color: var(--mnz-muted); letter-spacing: 0.08em; }

.mnz-notice {
  border: 1px solid var(--mnz-border);
  border-left: 2px solid #6E6E76;
  background: var(--mnz-panel);
  padding: 0.7rem 0.9rem;
  border-radius: 4px;
  font-size: 0.78rem;
  line-height: 1.55;
  color: #C9C9CE;
  margin: 0.55rem 0 0.9rem 0;
}
.mnz-notice.warn { border-left-color: #FFFFFF; color: #EFEFF1; }
.mnz-notice strong { color: #FFFFFF; letter-spacing: 0.06em; }

.mnz-source {
  font-size: 0.68rem;
  color: #6E6E76;
  letter-spacing: 0.03em;
  line-height: 1.6;
  margin: 0.15rem 0 0.9rem 0;
}
.mnz-source .sample { color: #FFFFFF; font-weight: 600; letter-spacing: 0.12em; }

.mnz-section {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  margin: 1.5rem 0 0.7rem 0;
  padding-bottom: 0.45rem;
  border-bottom: 1px solid var(--mnz-border);
}
.mnz-section .title {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #D6D6DA;
  white-space: nowrap;
}
.mnz-section .caption { font-size: 0.7rem; color: var(--mnz-muted); }

.mnz-footer {
  margin-top: 2.2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--mnz-border);
  font-size: 0.68rem;
  color: #5C5C64;
  line-height: 1.7;
}

/* ---------- Widgets ---------- */
div[data-testid="stButton"] > button,
div[data-testid="stFormSubmitButton"] > button,
div[data-testid="stDownloadButton"] > button {
  border-radius: 6px;
  border: 1px solid #FFFFFF;
  background: #FFFFFF;
  color: #0A0A0B;
  font-weight: 600;
  letter-spacing: 0.08em;
  font-size: 0.72rem;
  text-transform: uppercase;
  padding: 0.45rem 0.95rem;
  box-shadow: none;
}
/* Streamlit renders button labels as markdown paragraphs, which would otherwise
   keep the global light text colour and disappear on a white button. */
div[data-testid="stButton"] > button p,
div[data-testid="stFormSubmitButton"] > button p,
div[data-testid="stDownloadButton"] > button p,
div[data-testid="stButton"] > button span,
div[data-testid="stFormSubmitButton"] > button span,
div[data-testid="stDownloadButton"] > button span {
  color: inherit !important;
  font-size: inherit !important;
  letter-spacing: inherit !important;
  text-transform: inherit !important;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover {
  background: #D9D9DE;
  border-color: #D9D9DE;
  color: #0A0A0B;
}
div[data-testid="stButton"] > button[kind="secondary"] {
  background: transparent;
  color: #F4F4F5;
  border: 1px solid var(--mnz-border-strong);
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
  border-color: #FFFFFF;
  background: #17171A;
  color: #FFFFFF;
}

div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-testid="stDateInput"] input {
  background: var(--mnz-panel-alt) !important;
  border-color: var(--mnz-border) !important;
  color: var(--mnz-text) !important;
  border-radius: 6px !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus {
  border-color: #FFFFFF !important;
  box-shadow: none !important;
}
div[data-testid="stWidgetLabel"] p {
  font-size: 0.7rem !important;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--mnz-muted) !important;
}

/* Multiselect chips use primaryColor by default, which is white here.
   Override them so selected instruments stay readable. */
/* Let selected chips wrap instead of scrolling off the edge on narrow screens. */
div[data-testid="stMultiSelect"] div[data-testid="stMultiSelectTagsContainer"],
div[data-testid="stMultiSelect"] div[data-rac],
div[data-testid="stMultiSelect"] div[data-rac] > div {
  height: auto !important;
  max-height: none !important;
}
div[data-testid="stMultiSelect"] div[data-testid="stMultiSelectTagsContainer"] {
  flex-wrap: wrap;
  overflow: visible;
  row-gap: 0.3rem;
  padding: 0.35rem 0;
}
div[data-testid="stMultiSelect"] div[data-rac] { min-height: 40px; }
[data-testid="stMultiSelect"] span[data-tag] {
  background-color: #1C1C20 !important;
  border: 1px solid #3A3A40 !important;
  border-radius: 4px !important;
  color: #F4F4F5 !important;
}
[data-testid="stMultiSelect"] span[data-tag] > span { color: #F4F4F5 !important; }
[data-testid="stMultiSelect"] span[data-tag] button { color: #B9B9C0 !important; }

/* Dropdown options sit on the dark panel; keep hover/selection monochrome. */
div[data-baseweb="popover"] ul,
div[data-baseweb="menu"] {
  background-color: #17171A !important;
  border: 1px solid #2A2A2E !important;
}
div[data-baseweb="popover"] li:hover,
div[data-baseweb="menu"] li:hover { background-color: #26262A !important; }

/* Selected options in multiselect / selectbox dropdowns. */
div[data-baseweb="popover"] li[aria-selected="true"],
div[data-baseweb="menu"] li[aria-selected="true"] {
  background-color: #F4F4F5 !important;
  color: #0A0A0B !important;
}
div[data-baseweb="popover"] li[aria-selected="true"] span,
div[data-baseweb="menu"] li[aria-selected="true"] span { color: #0A0A0B !important; }

/* Checkbox sentences should stay sentence case rather than all-caps labels. */
div[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p,
div[data-testid="stCheckbox"] label p {
  text-transform: none !important;
  font-size: 0.8rem !important;
  letter-spacing: 0 !important;
  color: #C9C9CE !important;
}

/* Wrapping table for long-form values (analyst readings, fundamentals, events). */
.mnz-html-table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--mnz-border);
  border-radius: 8px;
  margin: 0.1rem 0 0.7rem 0;
  background: var(--mnz-panel);
}
.mnz-html-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.mnz-html-table th {
  text-align: left;
  padding: 0.55rem 0.75rem;
  font-size: 0.62rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--mnz-muted);
  border-bottom: 1px solid var(--mnz-border);
  white-space: nowrap;
  font-weight: 500;
}
.mnz-html-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid #1D1D21;
  color: var(--mnz-text);
  vertical-align: top;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.mnz-html-table td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mnz-html-table tbody tr:last-child td { border-bottom: none; }

/* Keep long caution text in checkboxes readable on small screens. */
@media (max-width: 900px) {
  .mnz-html-table { font-size: 0.76rem; }
  .mnz-html-table th, .mnz-html-table td { padding: 0.45rem 0.55rem; }
}

/* On phones, stack long tables into labelled rows instead of clipping them. */
@media (max-width: 640px) {
  .mnz-html-table-wrap { overflow-x: visible; }
  .mnz-html-table { min-width: 0 !important; display: block; }
  .mnz-html-table thead { display: none; }
  .mnz-html-table tbody { display: block; }
  .mnz-html-table tr { display: block; padding: 0.65rem 0.75rem; border-bottom: 1px solid #1D1D21; }
  .mnz-html-table tbody tr:last-child { border-bottom: none; }
  .mnz-html-table td {
    display: block;
    border: none;
    padding: 0.08rem 0;
    overflow-wrap: anywhere;
  }
  .mnz-html-table td:first-child {
    font-size: 0.64rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--mnz-muted);
    padding-bottom: 0.2rem;
  }
  .mnz-html-table td.num { text-align: left; }
}

div[data-testid="stTabs"] button {
  color: var(--mnz-muted);
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 500;
}
div[data-testid="stTabs"] button[aria-selected="true"] { color: #FFFFFF; }
div[data-testid="stTabs"] div[data-baseweb="tab-highlight"] { background: #FFFFFF; }
div[data-testid="stTabs"] div[data-baseweb="tab-border"] { background: var(--mnz-border); }

div[data-testid="stExpander"] details {
  border: 1px solid var(--mnz-border);
  border-radius: 8px;
  background: var(--mnz-panel);
}
div[data-testid="stExpander"] summary { font-size: 0.8rem; color: #D6D6DA; }

div[data-testid="stDataFrame"] { border: 1px solid var(--mnz-border); border-radius: 8px; }
div[data-testid="stDataFrame"] * { font-size: 0.8rem; }

[data-testid="stMetric"] {
  background: var(--mnz-panel);
  border: 1px solid var(--mnz-border);
  border-radius: 10px;
  padding: 0.8rem 1rem;
}
[data-testid="stMetricLabel"] p { font-size: 0.66rem !important; letter-spacing: 0.15em; text-transform: uppercase; color: var(--mnz-muted) !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem !important; font-weight: 600 !important; }

div[data-testid="stAlert"] { border-radius: 6px; border: 1px solid var(--mnz-border); }

hr { border-color: var(--mnz-border) !important; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #0A0A0B; }
::-webkit-scrollbar-thumb { background: #2A2A2E; border-radius: 4px; }

/* ---------- Responsive ---------- */
@media (max-width: 900px) {
  .block-container { padding-top: 1.6rem; padding-left: 1rem; padding-right: 1rem; }
  .mnz-logo .mark { font-size: 1.65rem; }
  .mnz-page-head { flex-direction: column; align-items: flex-start; }
  .mnz-page-head .tag { align-self: flex-start; }
  .mnz-kpi .value { font-size: 1.2rem; }
  .mnz-demo-bar { font-size: 0.6rem; }
  .mnz-section { flex-direction: column; align-items: flex-start; }
  .mnz-section .title { white-space: normal; }
}
</style>
"""


# --------------------------------------------------------------------------- #
# Setup and primitives
# --------------------------------------------------------------------------- #
def inject_theme() -> None:
    """Apply the MNZ visual system once per page render."""
    st.markdown(CSS, unsafe_allow_html=True)
    _register_plotly_template()


def _register_plotly_template() -> None:
    if _TEMPLATE in pio.templates:
        return
    pio.templates[_TEMPLATE] = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family='Inter, "Helvetica Neue", Arial, sans-serif', color=COLORS["muted"], size=11),
            colorway=config.CHART_COLORWAY,
            margin=dict(l=8, r=8, t=28, b=8),
            xaxis=dict(gridcolor=COLORS["grid"], zeroline=False, linecolor=COLORS["charcoal"],
                       tickfont=dict(size=10, color=COLORS["muted"])),
            yaxis=dict(gridcolor=COLORS["grid"], zeroline=False, linecolor=COLORS["charcoal"],
                       tickfont=dict(size=10, color=COLORS["muted"])),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                        font=dict(size=10, color=COLORS["muted"]), bgcolor="rgba(0,0,0,0)"),
            hoverlabel=dict(bgcolor="#17171A", bordercolor="#3A3A40",
                            font=dict(color="#F4F4F5", size=11)),
            hovermode="x unified",
        )
    )


def _style(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(template=_TEMPLATE, height=height)
    if title:
        fig.update_layout(title=dict(text=title.upper(), font=dict(size=10, color=COLORS["muted"]),
                                     x=0, xanchor="left", y=0.98))
    return fig


def brand_logo() -> None:
    """Prominent MNZ wordmark for the navigation sidebar."""
    st.markdown(
        '<div class="mnz-logo"><div class="mark"><span class="tick"></span>MNZ</div>'
        f'<div class="sub">{escape(config.TAGLINE)}</div>'
        f'<div class="ver">VERSION {escape(config.VERSION)} · DEMO</div></div>',
        unsafe_allow_html=True,
    )


def flash(message: str, kind: str = "success") -> None:
    """Queue a message to show after the next rerun."""
    st.session_state["_mnz_flash"] = (kind, message)


def pop_flash() -> None:
    """Display and clear a queued flash message."""
    item = st.session_state.pop("_mnz_flash", None)
    if not item:
        return
    kind, message = item if isinstance(item, tuple) else ("success", str(item))
    display = {"success": st.success, "error": st.error, "info": st.info, "warning": st.warning}.get(kind, st.success)
    display(message)


def page_header(title: str, subtitle: str = "", tag: str | None = None) -> None:
    tag_html = f'<div class="tag">{escape(tag)}</div>' if tag else ""
    st.markdown(
        f'<div class="mnz-page-head"><div class="titles"><h1>{escape(title)}</h1>'
        f'<div class="sub">{escape(subtitle)}</div></div>{tag_html}</div>',
        unsafe_allow_html=True,
    )


def demo_bar(right: str | None = None) -> None:
    right_text = escape(right) if right else "Python · Streamlit · SQLite · virtual only"
    st.markdown(
        f'<div class="mnz-demo-bar"><span><span class="dot"></span>DEMO MODE — {escape(config.DEMO_BANNER.split("— ", 1)[-1])}</span>'
        f'<span class="right">{right_text}</span></div>',
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = "") -> None:
    st.markdown(
        f'<div class="mnz-section"><div class="title">{escape(title)}</div>'
        f'<div class="caption">{escape(caption)}</div></div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, note: str = "", trend: int = 0) -> str:
    cls = "up" if trend > 0 else "down" if trend < 0 else ""
    return (
        f'<div class="mnz-kpi"><div class="label">{escape(label)}</div>'
        f'<div class="value {cls}">{escape(value)}</div>'
        + (f'<div class="note">{escape(note)}</div>' if note else "")
        + "</div>"
    )


def kpi_row(items: list[dict]) -> None:
    """Render a responsive grid of KPI cards.

    Each item: ``{label, value, note?, trend?}``. A CSS grid is used instead of
    Streamlit columns so the cards reflow onto one column on mobile.
    """
    if not items:
        return
    cards = "".join(
        kpi(item.get("label", ""), item.get("value", "—"), item.get("note", ""), item.get("trend", 0))
        for item in items
    )
    st.markdown(f'<div class="mnz-kpi-grid">{cards}</div>', unsafe_allow_html=True)


def notice(text: str, kind: str = "info") -> None:
    cls = "mnz-notice warn" if kind == "warn" else "mnz-notice"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


def source_line(price: PriceData | None = None, extra: str = "") -> None:
    if price is None:
        if extra:
            st.markdown(f'<div class="mnz-source">{escape(extra)}</div>', unsafe_allow_html=True)
        return
    if price.ok:
        stamp = price.last_bar_time.strftime("%Y-%m-%d %H:%M") if price.last_bar_time else "unknown"
        quality = price.status_note()
        sample = '<span class="sample">SAMPLE DATA · </span>' if price.is_sample else ""
        text = (
            f"{sample}{escape(price.source_label)} · {price.bars} bars · last bar {escape(stamp)} UTC · "
            f"{escape(quality)}"
        )
    else:
        text = f"Data unavailable · {escape(price.error or 'no rows returned')}"
    if extra:
        text = f"{text} · {escape(extra)}"
    st.markdown(f'<div class="mnz-source">{text}</div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown(
        f'<div class="mnz-footer">{escape(config.DISCLAIMER)}<br>'
        f'{escape(config.BRAND)} · {escape(config.APP_NAME)} v{escape(config.VERSION)} · '
        f'DEMO ONLY — no broker connection, no live orders, no real money.</div>',
        unsafe_allow_html=True,
    )


def empty_state(message: str, hint: str = "") -> None:
    """Neutral empty state; callers supply the full sentence so wording is not duplicated."""
    notice(escape(message) + (f"<br>{escape(hint)}" if hint else ""), "warn")


# --------------------------------------------------------------------------- #
# Table rendering (single place to adapt to Streamlit versions)
# --------------------------------------------------------------------------- #
def show_table(frame: pd.DataFrame, height: int | None = None, columns: list[str] | None = None) -> None:
    if frame is None or frame.empty:
        notice("No rows to display.", "warn")
        return
    view = frame[columns] if columns else frame
    options: dict = {"width": "stretch", "hide_index": True}
    if height is not None:
        options["height"] = int(height)
    st.dataframe(view, **options)


def show_chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "responsive": True})


def html_table(
    frame: pd.DataFrame,
    *,
    columns: list[str] | None = None,
    numeric: list[str] | None = None,
    min_width: int = 520,
) -> None:
    """Render a wrapping HTML table for long-form content.

    Streamlit's dataframe clips long cell text, which is wrong for analyst
    interpretations, fundamentals and event notes. This table wraps instead and
    scrolls horizontally on narrow screens.
    """
    if frame is None or frame.empty:
        notice("No rows to display.", "warn")
        return
    view = frame[columns] if columns else frame
    numeric_columns = set(numeric or [])

    def cell(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float) and not np.isfinite(value):
            return "—"
        return escape(str(value))

    head = "".join(f"<th>{escape(str(col))}</th>" for col in view.columns)
    body_rows = []
    for _, row in view.iterrows():
        cells = []
        for col in view.columns:
            css = ' class="num"' if col in numeric_columns else ""
            cells.append(f"<td{css}>{cell(row[col])}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f'<div class="mnz-html-table-wrap"><table class="mnz-html-table" '
        f'style="min-width:{int(min_width)}px"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def money(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.{digits}f}"


def pct(value: float | None, digits: int = 2, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def price_fmt(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    magnitude = abs(float(value))
    if magnitude >= 1000:
        return f"{value:,.2f}"
    if magnitude >= 10:
        return f"{value:,.3f}"
    return f"{value:,.5f}"


def number(value: float | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:,.{digits}f}"


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def price_chart(
    frame: pd.DataFrame,
    *,
    title: str = "",
    overlays: dict[str, pd.Series] | None = None,
    show_volume: bool = True,
    is_sample: bool = False,
    height: int = 430,
) -> go.Figure:
    """Candlestick chart with optional moving-average overlays and volume."""
    if frame is None or frame.empty:
        fig = go.Figure()
        fig.add_annotation(text="No price data available", showarrow=False,
                           font=dict(color=COLORS["muted"], size=13))
        return _style(fig, height)

    has_volume = show_volume and "Volume" in frame and float(frame["Volume"].sum()) > 0
    rows = 2 if has_volume else 1
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        row_heights=[0.76, 0.24] if has_volume else [1.0],
        vertical_spacing=0.04,
    )
    fig.add_trace(
        go.Candlestick(
            x=frame.index, open=frame["Open"], high=frame["High"],
            low=frame["Low"], close=frame["Close"], name="Price",
            increasing=dict(line=dict(color=COLORS["white"], width=1), fillcolor=COLORS["white"]),
            decreasing=dict(line=dict(color=COLORS["charcoal_light"], width=1), fillcolor=COLORS["charcoal"]),
            showlegend=False,
        ),
        row=1, col=1,
    )

    for index, (label, series) in enumerate((overlays or {}).items()):
        fig.add_trace(
            go.Scatter(
                x=frame.index, y=series, mode="lines", name=label,
                line=dict(color=[COLORS["line_secondary"], COLORS["white"], COLORS["line_tertiary"]][index % 3],
                          width=1.3, dash="solid" if index != 0 else "dot"),
                hovertemplate=f"{label}: %{{y:,.2f}}<extra></extra>",
            ),
            row=1, col=1,
        )

    if has_volume:
        colors = [
            COLORS["white"] if close >= open_ else COLORS["charcoal_light"]
            for close, open_ in zip(frame["Close"], frame["Open"])
        ]
        fig.add_trace(
            go.Bar(x=frame.index, y=frame["Volume"], name="Volume",
                   marker=dict(color=colors, line=dict(width=0)), showlegend=False),
            row=2, col=1,
        )
        fig.update_yaxes(title_text="", row=2, col=1, showgrid=False)
        fig.update_layout(height=height)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        bargap=0.15,
        hovermode="x unified",
        margin=dict(l=8, r=8, t=22, b=8),
    )
    fig.update_yaxes(side="right", row=1, col=1)
    fig.update_xaxes(showgrid=False)
    fig = _style(fig, height, title or None)
    if is_sample:
        fig.add_annotation(
            text="SAMPLE DATA", xref="paper", yref="paper", x=0.5, y=0.55,
            showarrow=False, font=dict(size=38, color="rgba(255,255,255,0.10)"),
        )
    return fig


def momentum_chart(frame: pd.DataFrame, rsi_series: pd.Series, macd_frame: pd.DataFrame,
                   *, height: int = 320) -> go.Figure:
    """RSI and MACD stacked beneath the price chart."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.45, 0.55], vertical_spacing=0.1,
                        subplot_titles=("RSI (14)", "MACD (12, 26, 9)"))
    fig.add_trace(
        go.Scatter(x=frame.index, y=rsi_series, name="RSI", mode="lines",
                   line=dict(color=COLORS["white"], width=1.3),
                   hovertemplate="RSI: %{y:.1f}<extra></extra>"),
        row=1, col=1,
    )
    fig.add_hline(y=70, line=dict(color=COLORS["charcoal_light"], width=1, dash="dot"), row=1, col=1)
    fig.add_hline(y=30, line=dict(color=COLORS["charcoal_light"], width=1, dash="dot"), row=1, col=1)
    fig.update_yaxes(range=[0, 100], row=1, col=1, side="right")

    hist_colors = [COLORS["white"] if value >= 0 else COLORS["charcoal_light"] for value in macd_frame["hist"].fillna(0)]
    fig.add_trace(
        go.Bar(x=frame.index, y=macd_frame["hist"], name="Histogram",
               marker=dict(color=hist_colors, line=dict(width=0))),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=frame.index, y=macd_frame["macd"], name="MACD",
                   line=dict(color=COLORS["white"], width=1.4)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=frame.index, y=macd_frame["signal"], name="Signal",
                   line=dict(color=COLORS["line_secondary"], width=1.2, dash="dot")),
        row=2, col=1,
    )
    fig.update_yaxes(side="right", row=2, col=1)
    fig.update_xaxes(showgrid=False)
    fig.update_annotations(font=dict(size=10, color=COLORS["muted"]))
    fig.update_layout(bargap=0.2, hovermode="x unified", margin=dict(l=8, r=8, t=24, b=8))
    return _style(fig, height)


def equity_chart(history: pd.DataFrame, starting_balance: float | None = None,
                 *, height: int = 320, title: str = "") -> go.Figure:
    """Virtual equity curve with the starting balance as a dashed reference."""
    fig = go.Figure()
    if history is None or history.empty:
        fig.add_annotation(text="No equity history recorded yet", showarrow=False,
                           font=dict(color=COLORS["muted"], size=13))
        return _style(fig, height, title or None)
    x = history["ts"] if "ts" in history else history.index
    fig.add_trace(go.Scatter(
        x=x, y=history["equity"], mode="lines", name="Equity",
        line=dict(color=COLORS["white"], width=1.8),
        hovertemplate="Equity: $%{y:,.2f}<extra></extra>",
    ))
    # Scale around the recorded equity instead of anchoring at $0: a flat or
    # near-flat account would otherwise sit on the top edge of the plot.
    values = pd.to_numeric(history["equity"], errors="coerce").dropna()
    if not values.empty:
        low, high = float(values.min()), float(values.max())
        if starting_balance:
            low, high = min(low, float(starting_balance)), max(high, float(starting_balance))
        span = max(high - low, abs(high) * 0.0015, 1.0)
        pad = span * 0.4
        fig.update_yaxes(range=[low - pad, high + pad])
    if starting_balance:
        fig.add_hline(y=starting_balance, line=dict(color=COLORS["charcoal_light"], width=1, dash="dot"),
                      annotation_text="starting balance", annotation_position="top left",
                      annotation_font=dict(size=9, color=COLORS["muted"]))
    fig.update_yaxes(side="right", tickprefix="$")
    fig.update_xaxes(showgrid=False)
    return _style(fig, height, title or None)


def drawdown_chart(history: pd.DataFrame, *, height: int = 240) -> go.Figure:
    fig = go.Figure()
    if history is None or history.empty:
        fig.add_annotation(text="No drawdown history", showarrow=False, font=dict(color=COLORS["muted"]))
        return _style(fig, height)
    x = history["ts"] if "ts" in history else history.index
    fig.add_trace(go.Scatter(
        x=x, y=history["drawdown_pct"], mode="lines", name="Drawdown",
        line=dict(color=COLORS["line_secondary"], width=1.4),
        fill="tozeroy", fillcolor="rgba(255,255,255,0.07)",
        hovertemplate="Drawdown: %{y:.2f}%<extra></extra>",
    ))
    fig.update_yaxes(side="right", ticksuffix="%")
    fig.update_xaxes(showgrid=False)
    return _style(fig, height)


def bar_chart(frame: pd.DataFrame, x: str, y: str, *, height: int = 300, horizontal: bool = False,
              color_by_sign: bool = True, title: str = "") -> go.Figure:
    fig = go.Figure()
    if frame is None or frame.empty:
        fig.add_annotation(text="Nothing to plot", showarrow=False, font=dict(color=COLORS["muted"]))
        return _style(fig, height, title or None)
    values = frame[y].astype(float)
    colors = [
        COLORS["white"] if value >= 0 else COLORS["charcoal_light"] for value in values.fillna(0)
    ] if color_by_sign else COLORS["white"]
    if horizontal:
        fig.add_trace(go.Bar(x=values, y=frame[x], orientation="h",
                             marker=dict(color=colors, line=dict(width=0)),
                             hovertemplate="%{x:,.2f}<extra></extra>"))
        fig.update_xaxes(zeroline=True, zerolinecolor=COLORS["charcoal"])
        fig.update_yaxes(autorange="reversed")
    else:
        fig.add_trace(go.Bar(x=frame[x], y=values,
                             marker=dict(color=colors, line=dict(width=0)),
                             hovertemplate="%{y:,.2f}<extra></extra>"))
        fig.update_yaxes(zeroline=True, zerolinecolor=COLORS["charcoal"])
    fig.update_layout(bargap=0.35, showlegend=False)
    return _style(fig, height, title or None)


def component_chart(report: AnalystReport, *, height: int = 300) -> go.Figure:
    """Weighted contribution of each analytical component.

    The reading and weight live in the axis label so bars never collide with
    annotations, and the axis scales to the actual contributions instead of a
    fixed ±1 range that would flatten small scores.
    """
    rows = [
        {"Component": c.name, "Score": (c.score or 0.0) * c.weight,
         "Detail": f"{c.reading} · weight {c.weight:.0%}"}
        for c in report.components if c.included and c.score is not None and c.kind == "direction"
    ]
    fig = bar_chart(pd.DataFrame(rows), "Component", "Score", horizontal=True, height=height)
    if rows:
        magnitudes = [abs(float(value)) for value in fig.data[0].x]
        limit = max([value for value in magnitudes if np.isfinite(value)] + [0.1]) * 1.18
        fig.update_xaxes(range=[-limit, limit], tickformat=".2f")
        fig.update_yaxes(automargin=True)
        details = [row["Detail"] for row in rows]
        fig.update_traces(
            customdata=details,
            hovertemplate="%{y}<br>%{customdata}<br>contribution %{x:.2f}<extra></extra>",
        )
    return fig


# --------------------------------------------------------------------------- #
# Analyst report renderer
# --------------------------------------------------------------------------- #
def label_pill(label: str) -> str:
    cls = "nodata"
    if label == "BUY BIAS":
        cls = "buy"
    elif label == "SELL BIAS":
        cls = "sell"
    elif label == "WAIT":
        cls = "wait"
    return f'<span class="mnz-pill {cls}">{escape(label)}</span>'


def render_report(report: AnalystReport, *, show_components: bool = True, show_data_notes: bool = True) -> None:
    """Render a complete analyst report with its reasoning and data provenance."""
    st.markdown(
        f'<div class="mnz-report-head"><span class="sym">{escape(report.symbol)}</span>'
        f"{label_pill(report.label)}"
        f'<span class="conf">CONVICTION {report.confidence}% · SCORE {report.score:+.2f} · '
        f"{escape(report.trend.upper())}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="mnz-card" style="margin-bottom:0.8rem">{escape(report.summary)}</div>',
        unsafe_allow_html=True,
    )

    if report.label == "NO DATA":
        for note in report.data_notes:
            st.caption(note)
        return

    section("Indicator readings", "what the model measured")
    html_table(pd.DataFrame(report.readings), min_width=560)

    if show_components:
        section("Why this label", "weighted evidence")
        show_chart(component_chart(report, height=max(260, 50 * len(report.components))))

    with st.expander("Reasoning detail", expanded=False):
        for reason in report.reasons:
            st.markdown(f"- {reason}")
        if report.cautions:
            st.markdown("**Cautions**")
            for caution in report.cautions:
                st.markdown(f"- {caution}")
        st.markdown("**Educational label only.** This is not financial advice, and the model does "
                    "not know your circumstances, horizon or risk tolerance.")

    if show_data_notes:
        with st.expander("Data, sources and timestamps", expanded=False):
            for note in report.data_notes:
                st.markdown(f"- {note}")
            st.caption(config.TIME_SOURCE_NOTE)

    if report.is_sample:
        st.markdown(
            '<div class="mnz-notice warn"><strong>SAMPLE DATA.</strong> This analysis was produced from a '
            "synthetic offline series, not live market prices. It demonstrates the interface only.</div>",
            unsafe_allow_html=True,
        )


def render_context_table(facts: list[tuple[str, str]]) -> None:
    if not facts:
        return
    frame = pd.DataFrame(facts, columns=["Field", "Value"])
    html_table(frame, min_width=480)
