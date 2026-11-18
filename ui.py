"""MNZ BOT visual system: theme, charts and reusable components.

Black surfaces, white text, green for positive/up and red for negative/down.
Desktop uses the collapsible sidebar; on phones the sidebar is replaced by a
fixed touch-sized bottom navigation bar (rendered by ``app.py``).
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
from data.market_data import PriceData

GREEN = config.PALETTE["green"]
RED = config.PALETTE["red"]
MUTED = config.PALETTE["muted"]
CARD = config.PALETTE["card"]
BORDER = config.PALETTE["border"]
_TEMPLATE = "mnz_bot"

CSS = """
<style>
:root {
  --bg: #090B0F;
  --card: #151922;
  --card-alt: #1B202B;
  --border: #232A38;
  --muted: #8C93A3;
  --text: #FFFFFF;
  --green: #20D68A;
  --red: #F04452;
  --font: "Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}

html, body, [class*="css"], .stApp, button, input, textarea, select {
  font-family: var(--font);
  -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--bg); color: var(--text); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stHeader"] > div { background: transparent; }
[data-testid="stToolbar"] { right: .8rem; }
.block-container {
  padding-top: 1.8rem;
  padding-bottom: 3.2rem;
  max-width: 1500px;
}
h1, h2, h3, h4 { color: var(--text); font-family: var(--font); }
h1 { font-size: 1.85rem !important; font-weight: 700 !important; letter-spacing: -0.03em; margin-bottom: .1rem !important; }
h2 { font-size: 1.25rem !important; font-weight: 650 !important; letter-spacing: -0.02em; }
h3 {
  font-size: .72rem !important; font-weight: 600 !important; letter-spacing: .18em;
  text-transform: uppercase; color: var(--muted) !important; margin-top: .4rem !important;
}
p, li, label, span { color: var(--text); }
a { color: var(--green); }
hr { border-color: var(--border) !important; }

/* ---------------- Sidebar (desktop) ---------------- */
[data-testid="stSidebar"] {
  background: #070A0E;
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] > div:first-child { padding-top: .3rem; }
[data-testid="stSidebar"] .block-container { padding-top: .7rem; }

.mnz-logo {
  padding: .5rem 0 1rem 0;
  margin-bottom: .8rem;
  border-bottom: 1px solid var(--border);
}
.mnz-logo .mark {
  display: flex; align-items: center; gap: .55rem;
  color: #FFF; font-size: 1.55rem; font-weight: 800; letter-spacing: .04em; line-height: 1;
}
.mnz-logo .mark .dot {
  width: 10px; height: 10px; border-radius: 3px; background: var(--green);
  box-shadow: 0 0 14px rgba(32,214,138,.55);
}
.mnz-logo .sub {
  margin-top: .5rem; font-size: .58rem; letter-spacing: .28em;
  color: var(--muted); text-transform: uppercase;
}
.mnz-logo .ver { margin-top: .3rem; font-size: .58rem; letter-spacing: .12em; color: #56607A; }

.mnz-nav-caption {
  font-size: .58rem; letter-spacing: .22em; text-transform: uppercase;
  color: #56607A; margin: .2rem 0 .45rem 0;
}
[data-testid="stSidebar"] div[role="radiogroup"] { gap: 3px; }
[data-testid="stSidebar"] div[role="radiogroup"] label {
  padding: .55rem .75rem;
  border-radius: 9px;
  border: 1px solid transparent;
  color: #AEB6C6;
  font-size: .88rem;
  cursor: pointer;
}
[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: #11161F; color: #FFF; }
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
  background: rgba(32,214,138,.10);
  border-color: rgba(32,214,138,.35);
  color: #FFF;
}
[data-testid="stSidebar"] div[role="radiogroup"] label > div { gap: 0 !important; }
[data-testid="stSidebar"] div[role="radiogroup"] label > div > div:first-child { display: none; }
[data-testid="stSidebar"] div[role="radiogroup"] label p { font-size: .88rem; color: inherit; font-weight: 500; }
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p { font-weight: 650; }

.mnz-sidebar-foot {
  margin-top: 1.1rem; padding-top: .9rem; border-top: 1px solid var(--border);
  font-size: .64rem; line-height: 1.65; color: #6B7488; letter-spacing: .02em;
}
.mnz-sidebar-foot strong { color: #AEB6C6; font-weight: 600; letter-spacing: .1em; }

/* ---------------- Headers ---------------- */
.mnz-page-head {
  display: flex; justify-content: space-between; align-items: flex-end;
  gap: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);
  margin-bottom: 1.3rem;
}
.mnz-page-head h1 { margin: 0 !important; }
.mnz-page-head .sub {
  font-size: .84rem; color: var(--muted); margin-top: .35rem;
  max-width: 78ch; line-height: 1.55;
}
.mnz-page-head .tag {
  flex: 0 0 auto; font-size: .6rem; letter-spacing: .16em; text-transform: uppercase;
  color: var(--green); border: 1px solid rgba(32,214,138,.35);
  background: rgba(32,214,138,.07); padding: .32rem .6rem; border-radius: 999px;
  white-space: nowrap;
}

/* ---------------- Cards / KPI ---------------- */
.mnz-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: .75rem;
}
.mnz-kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: .65rem; margin-bottom: .9rem;
}
.mnz-kpi {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: .9rem 1rem; height: 100%;
}
.mnz-kpi .label {
  font-size: .6rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); margin-bottom: .4rem; line-height: 1.4;
}
.mnz-kpi .value {
  font-size: 1.4rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.15;
  font-variant-numeric: tabular-nums; color: #FFF; word-break: break-word;
}
.mnz-kpi .note { font-size: .7rem; color: var(--muted); margin-top: .32rem; line-height: 1.45; }
.mnz-kpi .value.up { color: var(--green); }
.mnz-kpi .value.down { color: var(--red); }

/* ---------------- Pills ---------------- */
.mnz-pill {
  display: inline-block; font-size: .63rem; letter-spacing: .1em; text-transform: uppercase;
  padding: .28rem .6rem; border-radius: 999px; border: 1px solid var(--border);
  color: var(--text); background: transparent; white-space: nowrap; font-weight: 650;
}
.mnz-pill.buy { background: rgba(32,214,138,.14); color: var(--green); border-color: rgba(32,214,138,.45); }
.mnz-pill.sell { background: rgba(240,68,82,.14); color: var(--red); border-color: rgba(240,68,82,.45); }
.mnz-pill.wait { background: rgba(140,147,163,.12); color: #C7CEDA; border-color: #384255; }
.mnz-pill.nodata { border-style: dashed; color: var(--muted); }
.mnz-pill.strong { background: rgba(32,214,138,.14); color: var(--green); border-color: rgba(32,214,138,.35); }
.mnz-pill.moderate { background: rgba(255,255,255,.06); color: #D7DDEA; }
.mnz-pill.weak { background: transparent; color: var(--muted); }

/* ---------------- Signal card ---------------- */
.mnz-signal {
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: .95rem 1.05rem; margin-bottom: .65rem;
}
.mnz-signal .top { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.mnz-signal .sym { font-size: 1.02rem; font-weight: 700; letter-spacing: .01em; }
.mnz-signal .name { font-size: .76rem; color: var(--muted); }
.mnz-signal .meta { margin-left: auto; font-size: .7rem; color: var(--muted); white-space: nowrap; }
.mnz-signal .levels {
  display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: .5rem; margin-top: .8rem;
}
.mnz-signal .levels .item {
  background: #10141C; border: 1px solid #1E2532; border-radius: 10px; padding: .45rem .6rem;
}
.mnz-signal .levels .k { font-size: .56rem; letter-spacing: .14em; color: var(--muted); text-transform: uppercase; }
.mnz-signal .levels .v { font-size: .9rem; font-weight: 650; font-variant-numeric: tabular-nums; margin-top: .15rem; }
.mnz-signal .v.tp { color: var(--green); }
.mnz-signal .v.sl { color: var(--red); }
.mnz-signal .why { font-size: .78rem; color: #C7CEDA; line-height: 1.6; margin-top: .7rem; }
.mnz-quality { display: flex; align-items: center; gap: .45rem; margin-top: .7rem; }
.mnz-quality .bar { flex: 1; height: 5px; background: #1E2532; border-radius: 99px; overflow: hidden; }
.mnz-quality .bar span { display: block; height: 100%; border-radius: 99px; }
.mnz-quality .num { font-size: .66rem; color: var(--muted); letter-spacing: .06em; white-space: nowrap; }

/* ---------------- Notices / source ---------------- */
.mnz-notice {
  border: 1px solid var(--border); border-left: 3px solid var(--muted);
  background: var(--card); padding: .7rem .9rem; border-radius: 8px;
  font-size: .8rem; line-height: 1.6; color: #C7CEDA; margin: .55rem 0 .9rem 0;
}
.mnz-notice.warn { border-left-color: var(--red); color: #F2DDE0; }
.mnz-notice.ok { border-left-color: var(--green); color: #D8F5E9; }
.mnz-notice strong { color: #FFF; letter-spacing: .05em; }
.mnz-source { font-size: .67rem; color: #6B7488; letter-spacing: .02em; line-height: 1.6; margin: .15rem 0 .9rem 0; }
.mnz-source .sample { color: var(--red); font-weight: 700; letter-spacing: .1em; }

.mnz-section {
  display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
  gap: .25rem 1rem; margin: 1.5rem 0 .7rem 0; padding-bottom: .45rem;
  border-bottom: 1px solid var(--border);
}
.mnz-section .title { font-size: .7rem; font-weight: 650; letter-spacing: .18em; text-transform: uppercase; color: #D7DDEA; }
.mnz-section .caption { font-size: .69rem; color: var(--muted); }

.mnz-footer {
  margin-top: 2.2rem; padding-top: 1rem; border-top: 1px solid var(--border);
  font-size: .67rem; color: #5B657A; line-height: 1.7;
}

/* ---------------- Widgets ---------------- */
div[data-testid="stButton"] > button,
div[data-testid="stFormSubmitButton"] > button,
div[data-testid="stDownloadButton"] > button {
  border-radius: 10px; border: 1px solid var(--green); background: var(--green);
  color: #04140D; font-weight: 700; letter-spacing: .04em; font-size: .76rem;
  padding: .5rem .95rem; box-shadow: none; min-height: 42px;
}
div[data-testid="stButton"] > button p,
div[data-testid="stFormSubmitButton"] > button p,
div[data-testid="stDownloadButton"] > button p,
div[data-testid="stButton"] > button span,
div[data-testid="stFormSubmitButton"] > button span,
div[data-testid="stDownloadButton"] > button span {
  color: inherit !important; font-size: inherit !important; letter-spacing: inherit !important;
  text-transform: inherit !important; font-weight: inherit !important;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover { background: #3CE6A2; border-color: #3CE6A2; }
div[data-testid="stButton"] > button[kind="secondary"] {
  background: transparent; color: #E3E8F2; border: 1px solid #2F394B;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover { border-color: var(--green); color: var(--green); background: rgba(32,214,138,.06); }

div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-testid="stDateInput"] input,
div[data-testid="stTextArea"] textarea {
  background: #10141C !important; border-color: #263042 !important;
  color: var(--text) !important; border-radius: 10px !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus {
  border-color: var(--green) !important; box-shadow: none !important;
}
div[data-testid="stWidgetLabel"] p {
  font-size: .68rem !important; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted) !important;
}
div[data-testid="stCheckbox"] label p,
div[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p {
  text-transform: none !important; font-size: .82rem !important;
  letter-spacing: 0 !important; color: #C7CEDA !important;
}
[data-testid="stMultiSelect"] span[data-tag] {
  background-color: #1B2230 !important; border: 1px solid #2F394B !important;
  border-radius: 6px !important; color: #F4F4F5 !important;
}
div[data-baseweb="popover"] ul, div[data-baseweb="menu"] { background-color: #151922 !important; border: 1px solid #263042 !important; }
div[data-baseweb="popover"] li:hover, div[data-baseweb="menu"] li:hover { background-color: #1E2532 !important; }
div[data-baseweb="popover"] li[aria-selected="true"], div[data-baseweb="menu"] li[aria-selected="true"] {
  background-color: rgba(32,214,138,.16) !important; color: #FFF !important;
}

div[data-testid="stTabs"] button { color: var(--muted); font-size: .78rem; font-weight: 550; }
div[data-testid="stTabs"] button[aria-selected="true"] { color: #FFF; }
div[data-testid="stTabs"] div[data-baseweb="tab-highlight"] { background: var(--green); }
div[data-testid="stTabs"] div[data-baseweb="tab-border"] { background: var(--border); }

div[data-testid="stExpander"] details { border: 1px solid var(--border); border-radius: 12px; background: var(--card); }
div[data-testid="stExpander"] summary { font-size: .82rem; color: #D7DDEA; }
div[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 12px; }
div[data-testid="stMetric"] { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: .8rem 1rem; }
[data-testid="stMetricLabel"] p { font-size: .64rem !important; letter-spacing: .14em; text-transform: uppercase; color: var(--muted) !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem !important; font-weight: 700 !important; }
div[data-testid="stAlert"] { border-radius: 10px; border: 1px solid var(--border); }

/* ---------------- Tables ---------------- */
.mnz-html-table-wrap {
  width: 100%; overflow-x: auto; border: 1px solid var(--border);
  border-radius: 12px; margin: .1rem 0 .7rem 0; background: var(--card);
}
.mnz-html-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
.mnz-html-table th {
  text-align: left; padding: .55rem .75rem; font-size: .6rem; letter-spacing: .13em;
  text-transform: uppercase; color: var(--muted); border-bottom: 1px solid var(--border);
  white-space: nowrap; font-weight: 500;
}
.mnz-html-table td {
  padding: .52rem .75rem; border-bottom: 1px solid #1A2029; color: var(--text);
  vertical-align: top; line-height: 1.5; overflow-wrap: anywhere;
}
.mnz-html-table td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mnz-html-table tbody tr:last-child td { border-bottom: none; }

/* ---------------- Chat ---------------- */
.mnz-chat-user {
  background: rgba(32,214,138,.10); border: 1px solid rgba(32,214,138,.25);
  border-radius: 14px 14px 4px 14px; padding: .7rem .9rem; margin: .5rem 0 .5rem auto;
  max-width: 86%; font-size: .86rem; line-height: 1.6;
}
.mnz-chat-ai {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px 14px 14px 4px; padding: .8rem 1rem; margin: .5rem 0;
  max-width: 92%; font-size: .86rem; line-height: 1.65;
}
.mnz-chat-ai .who { font-size: .58rem; letter-spacing: .18em; color: var(--green); text-transform: uppercase; margin-bottom: .35rem; }

/* ---------------- Public site ---------------- */
.mnz-public { max-width: 1180px; margin: 0 auto; }
.mnz-public .topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: .9rem 0 1.4rem 0; border-bottom: 1px solid var(--border); margin-bottom: 2rem;
}
.mnz-public .wordmark { display: flex; align-items: center; gap: .5rem; font-weight: 800; letter-spacing: .06em; font-size: 1.15rem; }
.mnz-public .wordmark .dot { width: 9px; height: 9px; border-radius: 3px; background: var(--green); box-shadow: 0 0 12px rgba(32,214,138,.5); }
.mnz-hero { padding: 1.2rem 0 2.4rem 0; }
.mnz-hero .eyebrow { font-size: .64rem; letter-spacing: .22em; text-transform: uppercase; color: var(--green); margin-bottom: .8rem; }
.mnz-hero h1 { font-size: clamp(2rem, 5vw, 3.6rem) !important; line-height: 1.04; letter-spacing: -.04em; max-width: 16ch; margin: 0 0 1rem 0 !important; }
.mnz-hero p { font-size: 1rem; color: #B6BECD; max-width: 62ch; line-height: 1.7; }
.mnz-hero .actions { display: flex; gap: .6rem; flex-wrap: wrap; margin-top: 1.4rem; }
.mnz-btn {
  display: inline-block; padding: .65rem 1.1rem; border-radius: 10px;
  font-size: .8rem; font-weight: 700; text-decoration: none;
  background: var(--green); color: #04140D; border: 1px solid var(--green);
}
.mnz-btn.ghost { background: transparent; color: #E3E8F2; border-color: #2F394B; }
.mnz-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .8rem; margin: 1rem 0 2rem 0; }
.mnz-feature { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.15rem 1.2rem; }
.mnz-feature .icon { width: 30px; height: 30px; border-radius: 9px; background: rgba(32,214,138,.12); border: 1px solid rgba(32,214,138,.3); display: flex; align-items: center; justify-content: center; font-size: .8rem; color: var(--green); margin-bottom: .7rem; }
.mnz-feature h4 { font-size: .95rem; margin: 0 0 .35rem 0; letter-spacing: -.01em; }
.mnz-feature p { font-size: .8rem; color: #AEB6C6; line-height: 1.65; margin: 0; }
.mnz-band { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 1.8rem 0; margin: 1.5rem 0; }
.mnz-band h2 { margin-bottom: .5rem; }
.mnz-band p { color: #B6BECD; max-width: 72ch; line-height: 1.7; font-size: .9rem; }
.mnz-price { background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 1.4rem 1.3rem; position: relative; }
.mnz-price.featured { border-color: rgba(32,214,138,.45); box-shadow: 0 0 40px rgba(32,214,138,.06); }
.mnz-price .tier { font-size: .68rem; letter-spacing: .16em; text-transform: uppercase; color: var(--muted); }
.mnz-price .amount { font-size: 2rem; font-weight: 750; letter-spacing: -.03em; margin: .45rem 0 .1rem 0; }
.mnz-price .amount small { font-size: .7rem; color: var(--muted); font-weight: 500; letter-spacing: 0; }
.mnz-price ul { list-style: none; padding: 0; margin: .9rem 0 0 0; }
.mnz-price li { font-size: .8rem; color: #B6BECD; padding: .3rem 0 .3rem 1.1rem; position: relative; }
.mnz-price li::before { content: "✓"; position: absolute; left: 0; color: var(--green); }
.mnz-public .fine { font-size: .68rem; color: #5B657A; line-height: 1.7; margin-top: 2rem; }
.mnz-stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .7rem; margin: 1.4rem 0 .6rem 0; }
.mnz-stat { background: #0E1219; border: 1px solid var(--border); border-radius: 12px; padding: .8rem .9rem; }
.mnz-stat .k { font-size: .58rem; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
.mnz-stat .v { font-size: 1.15rem; font-weight: 700; margin-top: .25rem; }

/* ---------------- Mobile bottom navigation ---------------- */
.st-key-mobile_nav { display: none; }

@media (max-width: 900px) {
  .block-container { padding: 1.1rem .9rem 6.4rem .9rem; }
  .mnz-page-head { flex-direction: column; align-items: flex-start; }
  .mnz-page-head .tag { align-self: flex-start; }
  .mnz-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .5rem; }
  .mnz-kpi .value { font-size: 1.18rem; }
  .mnz-signal .levels { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .35rem; }
  .mnz-signal .meta { margin-left: 0; width: 100%; }
  .mnz-hero { padding-top: .4rem; }
  .mnz-public .topbar { margin-bottom: 1.2rem; }
  [data-testid="stSidebar"] { display: none; }
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarCollapseButton"],
  [data-testid="stExpandSidebarButton"],
  [data-testid="collapsedControl"] { display: none !important; }
  .st-key-mobile_nav {
    display: block; position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
    background: rgba(9,11,15,.97); border-top: 1px solid #232A38;
    padding: .3rem .35rem calc(.35rem + env(safe-area-inset-bottom)) .35rem;
    backdrop-filter: blur(14px);
  }
  .st-key-mobile_nav [data-testid="stHorizontalBlock"] { gap: 1px; }
  .st-key-mobile_nav [data-testid="column"] { padding: 0 !important; }
  .st-key-mobile_nav button {
    width: 100%; min-height: 52px; background: transparent !important;
    border: none !important; color: #7C879B !important; padding: .3rem 0 !important;
    border-radius: 10px !important; box-shadow: none !important;
  }
  .st-key-mobile_nav button p {
    font-size: .6rem !important; letter-spacing: .02em !important;
    font-weight: 600 !important; white-space: nowrap;
  }
  .st-key-mobile_nav button[kind="primary"] { color: var(--green) !important; }
  .st-key-mobile_nav button[kind="secondary"] { color: #7C879B !important; border: none !important; }
}

@media (max-width: 640px) {
  .mnz-html-table-wrap { overflow-x: visible; }
  .mnz-html-table { display: block; min-width: 0 !important; }
  .mnz-html-table thead { display: none; }
  .mnz-html-table tbody, .mnz-html-table tr { display: block; }
  .mnz-html-table tr { padding: .6rem .75rem; border-bottom: 1px solid #1A2029; }
  .mnz-html-table tr:last-child { border-bottom: none; }
  .mnz-html-table td { display: block; border: none; padding: .07rem 0; }
  .mnz-html-table td:first-child {
    font-size: .62rem; letter-spacing: .12em; text-transform: uppercase;
    color: var(--muted); padding-bottom: .2rem;
  }
  .mnz-html-table td.num { text-align: left; }
  .mnz-hero h1 { max-width: 100%; }
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: #2A3142; border-radius: 4px; }
</style>
"""


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    _register_template()


def _register_template() -> None:
    if _TEMPLATE in pio.templates:
        return
    pio.templates[_TEMPLATE] = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, -apple-system, Segoe UI, Arial, sans-serif",
                      color=MUTED, size=11),
            colorway=config.CHART_COLORWAY,
            margin=dict(l=6, r=6, t=26, b=6),
            xaxis=dict(gridcolor="#1A2029", zeroline=False, linecolor="#232A38",
                       tickfont=dict(size=10, color=MUTED)),
            yaxis=dict(gridcolor="#1A2029", zeroline=False, linecolor="#232A38",
                       tickfont=dict(size=10, color=MUTED)),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                        font=dict(size=10, color=MUTED), bgcolor="rgba(0,0,0,0)"),
            hoverlabel=dict(bgcolor="#1B202B", bordercolor="#2F394B",
                            font=dict(color="#FFFFFF", size=11)),
            hovermode="x unified",
        )
    )


def _style(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(template=_TEMPLATE, height=height)
    if title:
        fig.update_layout(title=dict(text=title.upper(), font=dict(size=10, color=MUTED),
                                     x=0, xanchor="left", y=0.98))
    return fig


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def brand_logo() -> None:
    st.markdown(
        '<div class="mnz-logo"><div class="mark"><span class="dot"></span>MNZ BOT</div>'
        f'<div class="sub">{escape(config.TAGLINE)}</div>'
        f'<div class="ver">v{escape(config.VERSION)} · DEMO</div></div>',
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", tag: str | None = None) -> None:
    tag_html = f'<div class="tag">{escape(tag)}</div>' if tag else ""
    st.markdown(
        f'<div class="mnz-page-head"><div><h1>{escape(title)}</h1>'
        f'<div class="sub">{escape(subtitle)}</div></div>{tag_html}</div>',
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = "") -> None:
    st.markdown(
        f'<div class="mnz-section"><div class="title">{escape(title)}</div>'
        f'<div class="caption">{escape(caption)}</div></div>',
        unsafe_allow_html=True,
    )


def demo_bar(right: str | None = None) -> None:
    text = escape(right) if right else "Virtual money · simulated positions only"
    st.markdown(
        '<div class="mnz-notice ok" style="display:flex;justify-content:space-between;gap:.6rem;'
        'align-items:center;flex-wrap:wrap;font-size:.7rem;letter-spacing:.06em;text-transform:uppercase">'
        '<span><strong>DEMO</strong> — no broker connected, no live orders</span>'
        f'<span style="color:#8C93A3">{text}</span></div>',
        unsafe_allow_html=True,
    )


def notice(text: str, kind: str = "info") -> None:
    cls = {"warn": "mnz-notice warn", "ok": "mnz-notice ok"}.get(kind, "mnz-notice")
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


def temporary_storage_notice() -> None:
    """Warn that accounts and demo records sit on storage that can be wiped."""
    notice(
        "<strong>Temporary storage.</strong> Accounts, demo positions and alert history are "
        "kept in a local file on this server, so they can be erased when the app restarts, "
        "sleeps or redeploys. Treat everything here as disposable and do not rely on it to "
        "keep records."
        "<br><small>Storage becomes permanent once the owner configures a "
        "<code>DATABASE_URL</code> PostgreSQL secret.</small>",
        "warn",
    )


def empty_state(message: str, hint: str = "") -> None:
    st.markdown(
        f'<div class="mnz-notice warn">{escape(message)}'
        + (f"<br>{escape(hint)}" if hint else "") + "</div>",
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
    cards = "".join(
        kpi(item.get("label", ""), item.get("value", "—"),
            item.get("note", ""), item.get("trend", 0))
        for item in items
    )
    st.markdown(f'<div class="mnz-kpi-grid">{cards}</div>', unsafe_allow_html=True)


def flash(message: str, kind: str = "success") -> None:
    st.session_state["_mnz_flash"] = (kind, message)


def pop_flash() -> None:
    item = st.session_state.pop("_mnz_flash", None)
    if not item:
        return
    kind, message = item if isinstance(item, tuple) else ("success", str(item))
    {"success": st.success, "error": st.error, "info": st.info,
     "warning": st.warning}.get(kind, st.success)(message)


def source_line(price: PriceData | None = None, extra: str = "") -> None:
    if price is None:
        if extra:
            st.markdown(f'<div class="mnz-source">{escape(extra)}</div>', unsafe_allow_html=True)
        return
    if price.ok:
        stamp = price.last_bar_time.strftime("%Y-%m-%d %H:%M") if price.last_bar_time else "unknown"
        sample = '<span class="sample">SAMPLE DATA · </span>' if price.is_sample else ""
        tf = f" · {price.timeframe}" if getattr(price, "timeframe", "") else ""
        text = (
            f"{sample}{escape(price.source_label)} · {price.bars} bars · interval {escape(price.interval)}"
            f"{escape(tf)} · last bar {escape(stamp)} UTC · {escape(price.status_note())}"
        )
    else:
        text = f"Data unavailable · {escape(price.error or 'no rows returned')}"
    if extra:
        text = f"{text} · {escape(extra)}"
    st.markdown(f'<div class="mnz-source">{text}</div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown(
        f'<div class="mnz-footer">{escape(config.DISCLAIMER)}<br><br>'
        f'{escape(config.BRAND)} v{escape(config.VERSION)} · DEMO ONLY — no broker '
        "connection, no live orders, no real money.</div>",
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


def label_pill(label: str) -> str:
    cls = {"BUY": "buy", "SELL": "sell", "WAIT": "wait"}.get(label, "nodata")
    return f'<span class="mnz-pill {cls}">{escape(label)}</span>'


def strength_pill(strength: str) -> str:
    cls = {"Strong": "strong", "Moderate": "moderate"}.get(strength, "weak")
    return f'<span class="mnz-pill {cls}">{escape(strength)}</span>'


def quality_bar(quality: int) -> str:
    value = max(0, min(100, int(quality)))
    color = GREEN if value >= 70 else ("#E7B75B" if value >= 50 else RED)
    return (
        f'<div class="mnz-quality"><div class="bar"><span style="width:{value}%;'
        f'background:{color}"></span></div><div class="num">QUALITY {value}/100</div></div>'
    )


def signal_card(row: dict, *, name: str = "", explanation: str | None = None,
                show_quality: bool = True) -> None:
    """Render a stored or freshly built signal."""
    label = row.get("label", "WAIT")
    tf = row.get("timeframe", "")
    strength = row.get("strength", "")
    meta = " · ".join(part for part in [
        escape(str(tf)) if tf else "", escape(str(row.get("created_at", ""))[:16].replace("T", " ")),
    ] if part)
    levels = ""
    if row.get("label") in {"BUY", "SELL"} and row.get("tp") is not None:
        levels = (
            '<div class="levels">'
            f'<div class="item"><div class="k">Entry reference</div><div class="v">{price_fmt(row.get("entry_ref"))}</div></div>'
            f'<div class="item"><div class="k">Simulated TP</div><div class="v tp">{price_fmt(row.get("tp"))}</div></div>'
            f'<div class="item"><div class="k">Simulated SL</div><div class="v sl">{price_fmt(row.get("sl"))}</div></div>'
            "</div>"
        )
    why = explanation if explanation is not None else row.get("explanation", "")
    quality = quality_bar(int(row.get("quality") or 0)) if show_quality else ""
    st.markdown(
        '<div class="mnz-signal"><div class="top">'
        f'{label_pill(label)}<span class="sym">{escape(str(row.get("symbol", "")))}</span>'
        f'<span class="name">{escape(name)}</span>{strength_pill(strength)}'
        f'<span class="meta">{meta}</span></div>'
        + (f'<div class="why">{escape(str(why))}</div>' if why else "")
        + levels + quality + "</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Tables / charts
# --------------------------------------------------------------------------- #
def show_table(frame: pd.DataFrame, height: int | None = None,
               columns: list[str] | None = None) -> None:
    if frame is None or frame.empty:
        notice("No rows to display.", "warn")
        return
    if columns:
        available = [column for column in columns if column in frame.columns]
        view = frame[available] if available else frame
    else:
        view = frame
    options: dict = {"width": "stretch", "hide_index": True}
    if height is not None:
        options["height"] = int(height)
    st.dataframe(view, **options)


def show_chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch",
                    config={"displayModeBar": False, "responsive": True})


def html_table(frame: pd.DataFrame, *, columns: list[str] | None = None,
               numeric: list[str] | None = None, min_width: int = 520) -> None:
    if frame is None or frame.empty:
        notice("No rows to display.", "warn")
        return
    if columns:
        available = [column for column in columns if column in frame.columns]
        view = frame[available] if available else frame
    else:
        view = frame
    numeric_columns = set(numeric or [])

    def cell(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float) and not np.isfinite(value):
            return "—"
        return escape(str(value))

    head = "".join(f"<th>{escape(str(col))}</th>" for col in view.columns)
    rows = []
    for _, row in view.iterrows():
        cells = []
        for col in view.columns:
            css = ' class="num"' if col in numeric_columns else ""
            cells.append(f"<td{css}>{cell(row[col])}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f'<div class="mnz-html-table-wrap"><table class="mnz-html-table" '
        f'style="min-width:{int(min_width)}px"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def price_chart(
    frame: pd.DataFrame,
    *,
    title: str = "",
    overlays: dict[str, pd.Series] | None = None,
    levels: dict[str, float] | None = None,
    show_volume: bool = True,
    is_sample: bool = False,
    height: int = 430,
) -> go.Figure:
    """Candlestick chart with overlays, optional simulated levels and volume."""
    if frame is None or frame.empty:
        fig = go.Figure()
        fig.add_annotation(text="No price data available", showarrow=False,
                           font=dict(color=MUTED, size=13))
        return _style(fig, height)

    has_volume = show_volume and "Volume" in frame and float(frame["Volume"].sum()) > 0
    rows = 2 if has_volume else 1
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        row_heights=[0.78, 0.22] if has_volume else [1.0],
        vertical_spacing=0.04,
    )
    fig.add_trace(
        go.Candlestick(
            x=frame.index, open=frame["Open"], high=frame["High"],
            low=frame["Low"], close=frame["Close"], name="Price",
            increasing=dict(line=dict(color=GREEN, width=1), fillcolor=GREEN),
            decreasing=dict(line=dict(color=RED, width=1), fillcolor=RED),
            showlegend=False,
        ),
        row=1, col=1,
    )

    palette = [GREEN, "#FFFFFF", "#8C93A3", "#5B7CFA"]
    for index, (label, series) in enumerate((overlays or {}).items()):
        fig.add_trace(
            go.Scatter(
                x=frame.index, y=series, mode="lines", name=label,
                line=dict(color=palette[index % len(palette)], width=1.25,
                          dash="solid" if index == 0 else "dot"),
                hovertemplate=f"{label}: %{{y:,.4f}}<extra></extra>",
            ),
            row=1, col=1,
        )

    for label, value in (levels or {}).items():
        if value is None or not np.isfinite(value):
            continue
        color = {"TP": GREEN, "SL": RED}.get(label.split()[0], "#8C93A3")
        fig.add_hline(y=float(value), row=1, col=1,
                      line=dict(color=color, width=1, dash="dash"),
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=9, color=color))

    if has_volume:
        colors = [GREEN if close >= open_ else RED
                  for close, open_ in zip(frame["Close"], frame["Open"])]
        fig.add_trace(
            go.Bar(x=frame.index, y=frame["Volume"], name="Volume",
                   marker=dict(color=colors, opacity=0.55, line=dict(width=0)),
                   showlegend=False),
            row=2, col=1,
        )
        fig.update_yaxes(title_text="", row=2, col=1, showgrid=False)
        fig.update_layout(height=height)

    fig.update_layout(xaxis_rangeslider_visible=False, bargap=0.15,
                      hovermode="x unified", margin=dict(l=6, r=6, t=22, b=6))
    fig.update_yaxes(side="right", row=1, col=1)
    fig.update_xaxes(showgrid=False)
    fig = _style(fig, height, title or None)
    if is_sample:
        fig.add_annotation(text="SAMPLE DATA", xref="paper", yref="paper", x=0.5, y=0.55,
                           showarrow=False, font=dict(size=38, color="rgba(240,68,82,0.12)"))
    return fig


def indicator_chart(frame: pd.DataFrame, rsi_series: pd.Series, macd_frame: pd.DataFrame,
                    adx_frame: pd.DataFrame | None = None, *, height: int = 420) -> go.Figure:
    """RSI, MACD and ADX stacked below the price chart."""
    has_adx = adx_frame is not None and not adx_frame.empty
    fig = make_subplots(
        rows=3 if has_adx else 2, cols=1, shared_xaxes=True,
        row_heights=[0.3, 0.4, 0.3] if has_adx else [0.42, 0.58],
        vertical_spacing=0.07,
        subplot_titles=("RSI (14)", "MACD (12, 26, 9)", "ADX (14)") if has_adx
        else ("RSI (14)", "MACD (12, 26, 9)"),
    )
    fig.add_trace(
        go.Scatter(x=frame.index, y=rsi_series, name="RSI", mode="lines",
                   line=dict(color=GREEN, width=1.3),
                   hovertemplate="RSI: %{y:.1f}<extra></extra>"),
        row=1, col=1,
    )
    fig.add_hline(y=70, line=dict(color="#2F394B", width=1, dash="dot"), row=1, col=1)
    fig.add_hline(y=30, line=dict(color="#2F394B", width=1, dash="dot"), row=1, col=1)
    fig.update_yaxes(range=[0, 100], row=1, col=1, side="right")

    hist_colors = [GREEN if value >= 0 else RED for value in macd_frame["hist"].fillna(0)]
    fig.add_trace(
        go.Bar(x=frame.index, y=macd_frame["hist"], name="Histogram",
               marker=dict(color=hist_colors, line=dict(width=0)), opacity=0.7),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=frame.index, y=macd_frame["macd"], name="MACD",
                   line=dict(color="#FFFFFF", width=1.4)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=frame.index, y=macd_frame["signal"], name="Signal",
                   line=dict(color="#8C93A3", width=1.2, dash="dot")),
        row=2, col=1,
    )
    fig.update_yaxes(side="right", row=2, col=1)

    if has_adx:
        fig.add_trace(
            go.Scatter(x=frame.index, y=adx_frame["adx"], name="ADX",
                       line=dict(color="#5B7CFA", width=1.3)),
            row=3, col=1,
        )
        fig.add_hline(y=25, line=dict(color="#2F394B", width=1, dash="dot"), row=3, col=1)
        fig.update_yaxes(range=[0, 60], side="right", row=3, col=1)
    fig.update_xaxes(showgrid=False)
    fig.update_annotations(font=dict(size=10, color=MUTED))
    fig.update_layout(bargap=0.2, hovermode="x unified", margin=dict(l=6, r=6, t=24, b=6))
    return _style(fig, height)


def equity_chart(history: pd.DataFrame, starting_balance: float | None = None,
                 *, height: int = 300, title: str = "") -> go.Figure:
    fig = go.Figure()
    if history is None or history.empty:
        fig.add_annotation(text="No equity history recorded yet", showarrow=False,
                           font=dict(color=MUTED, size=13))
        return _style(fig, height, title or None)
    x = history["ts"] if "ts" in history else history.index
    fig.add_trace(go.Scatter(
        x=x, y=history["equity"], mode="lines", name="Equity",
        line=dict(color=GREEN, width=2),
        fill="tozeroy", fillcolor="rgba(32,214,138,0.06)",
        hovertemplate="Equity: $%{y:,.2f}<extra></extra>",
    ))
    values = pd.to_numeric(history["equity"], errors="coerce").dropna()
    if not values.empty:
        low, high = float(values.min()), float(values.max())
        if starting_balance:
            low, high = min(low, float(starting_balance)), max(high, float(starting_balance))
        span = max(high - low, abs(high) * 0.002, 1.0)
        pad = span * 0.4
        fig.update_yaxes(range=[low - pad, high + pad])
    if starting_balance:
        fig.add_hline(y=starting_balance, line=dict(color="#3B4456", width=1, dash="dot"),
                      annotation_text="start", annotation_position="top left",
                      annotation_font=dict(size=9, color=MUTED))
    fig.update_yaxes(side="right", tickprefix="$")
    fig.update_xaxes(showgrid=False)
    return _style(fig, height, title or None)


def drawdown_chart(history: pd.DataFrame, *, height: int = 220) -> go.Figure:
    fig = go.Figure()
    if history is None or history.empty or "drawdown_pct" not in history:
        fig.add_annotation(text="No drawdown history", showarrow=False, font=dict(color=MUTED))
        return _style(fig, height)
    x = history["ts"] if "ts" in history else history.index
    fig.add_trace(go.Scatter(
        x=x, y=history["drawdown_pct"], mode="lines", name="Drawdown",
        line=dict(color=RED, width=1.3), fill="tozeroy", fillcolor="rgba(240,68,82,0.10)",
        hovertemplate="Drawdown: %{y:.2f}%<extra></extra>",
    ))
    fig.update_yaxes(side="right", ticksuffix="%")
    fig.update_xaxes(showgrid=False)
    return _style(fig, height)


def bar_chart(frame: pd.DataFrame, x: str, y: str, *, height: int = 280,
              horizontal: bool = False, color_by_sign: bool = True,
              title: str = "") -> go.Figure:
    fig = go.Figure()
    if frame is None or frame.empty:
        fig.add_annotation(text="Nothing to plot", showarrow=False, font=dict(color=MUTED))
        return _style(fig, height, title or None)
    values = frame[y].astype(float)
    colors = ([GREEN if value >= 0 else RED for value in values.fillna(0)]
              if color_by_sign else GREEN)
    if horizontal:
        fig.add_trace(go.Bar(x=values, y=frame[x], orientation="h",
                             marker=dict(color=colors, line=dict(width=0)),
                             hovertemplate="%{x:,.2f}<extra></extra>"))
        fig.update_xaxes(zeroline=True, zerolinecolor="#2F394B")
        fig.update_yaxes(autorange="reversed")
    else:
        fig.add_trace(go.Bar(x=frame[x], y=values,
                             marker=dict(color=colors, line=dict(width=0)),
                             hovertemplate="%{y:,.2f}<extra></extra>"))
        fig.update_yaxes(zeroline=True, zerolinecolor="#2F394B")
    fig.update_layout(bargap=0.35, showlegend=False)
    return _style(fig, height, title or None)
