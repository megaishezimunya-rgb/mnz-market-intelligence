# MNZ MARKET INTELLIGENCE

A premium, multi-market analysis platform built with Python, Streamlit, Pandas, Plotly,
SQLite and free historical market data.

**Version 1 is DEMO-ONLY.** Every trade is simulated with virtual money. The application
has no broker connection, no order routing, no API trading keys and never asks for
brokerage or financial-account credentials. The automated execution module is disabled and
unimplemented by design.

---

## 1. What it does

MNZ analyses five separate markets, each with **its own engine, settings and strategy
configuration** — one strategy is not assumed to work equally well everywhere:

| Engine | Coverage | Default strategy character |
|---|---|---|
| **Forex** | 10 major and cross pairs | 50/200 trend following, 2 bps simulated cost, long-only, 50% size |
| **Crypto** | BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE | 21/100 trend following, no RSI entry filter, 15 bps cost, 50% size |
| **Stocks** | 12 large-cap equities with provider fundamentals | 50/200 trend following with RSI filter, 5 bps cost, 100% size |
| **Commodities** | Gold, silver, WTI, Brent, copper, gas, corn, wheat | 40/150 trend following, shorts enabled, 6 bps cost, 60% size |
| **Indices** | 10 global benchmarks with proxy breadth | 50/200 trend following, 3 bps cost, 100% size |

Each engine provides:

- moving averages, RSI, MACD, trend classification and momentum scoring;
- ATR-based volatility monitoring and volume analysis;
- engine-specific context — FX/commodity session timing, crypto 24/7 notes, stock
  fundamentals and earnings awareness, commodity supply/demand background, index breadth;
- its own editable strategy settings, used by the analysis, the strategy state and backtests.

### Navigation (12 sections, all functional)

1. **Overview** — market selection, data availability, selected instruments, trends,
   analysis summaries, virtual balance and demo performance.
2. **Forex** — pair analysis, sessions, scheduled event awareness.
3. **Crypto** — trend, momentum, volatility, volume, 24/7 context.
4. **Stocks** — ticker search, price analysis, fundamentals, earnings.
5. **Commodities** — trend, volatility, supply/demand context, events.
6. **Indices** — trend, momentum, volatility, proxy market breadth.
7. **AI Market Analyst** — plain-language summaries, indicator readings, BUY/SELL/WAIT
   educational labels, weighted reasoning, data provenance, cross-market view.
8. **Strategy Testing** — per-engine backtests with costs, win rate, return, drawdown,
   trade count and comparison across market periods.
9. **Demo Trading** — virtual entries/exits, simulated costs, open/closed positions, P&L,
   maximum drawdown, equity curve.
10. **Trade History** — filtered simulated trade log with CSV export.
11. **Performance Reports** — equity curve, drawdown, monthly returns, engine breakdown,
    trade statistics, saved backtests, CSV exports.
12. **Settings** — demo account, per-engine strategies, data provider, safety and roadmap.

---

## 2. Project structure

```
mnz_market_intelligence/
├── app.py                     Streamlit entry point and sidebar navigation
├── config.py                  Brand, palette, universes, per-engine defaults, safety flags
├── state.py                   Session state, settings persistence, navigation helpers
├── ui.py                      Theme (CSS), Plotly template, charts and components
├── requirements.txt
├── README.md
├── conftest.py
├── .streamlit/
│   └── config.toml            Dark theme, custom navigation enabled
├── engines/
│   ├── base.py                Engine interface, sessions, shared formatting
│   ├── forex.py               Sessions, pair focus, recurring event windows
│   ├── crypto.py              24/7 market notes, volatility monitoring
│   ├── stocks.py              Provider fundamentals, earnings calendar, ticker search
│   ├── commodities.py         Supply/demand context, futures roll caveats
│   └── indices.py             Global indices, proxy market breadth
├── analysis/
│   ├── indicators.py          SMA, EMA, RSI, MACD, ATR, Bollinger, drawdown, snapshots
│   ├── market_analyst.py      Weighted, explainable BUY/SELL/WAIT analysis
│   └── backtesting.py         Strategy backtests, period comparison, latest signal
├── data/
│   └── market_data.py         yfinance access, normalisation, caching, sample fallback
├── database/
│   └── database.py            SQLite schema and queries (accounts, trades, snapshots…)
├── simulator/
│   ├── demo_account.py        Virtual cash, P&L accounting, drawdown, reset
│   ├── virtual_trades.py      Trade model, mark-to-market, validation
│   └── portfolio.py           Equity curve, allocation, monthly returns, statistics
├── pages/
│   ├── engine_common.py       Shared engine page flow, strategy form
│   ├── overview.py, forex_page.py, crypto_page.py, stocks_page.py,
│   ├── commodities_page.py, indices_page.py, analyst_page.py,
│   ├── strategy_testing.py, demo_trading.py, trade_history.py,
│   └── reports.py, settings.py
├── tests/
│   ├── test_indicators.py
│   ├── test_backtesting.py
│   ├── test_simulator.py
│   └── test_analyst_engines.py
└── mnz_data/                  Created at first run: mnz.db (SQLite) — git-ignored
```

---

## 3. Windows installation

Tested with Python 3.12 on Windows 10/11. Python 3.10 or newer is required.

### Step 1 — Install Python

1. Download Python from <https://www.python.org/downloads/windows/> (64-bit installer).
2. During installation, tick **“Add python.exe to PATH”**.
3. Open **PowerShell** (Start → “PowerShell”) and verify:

```powershell
python --version
```

You should see something like `Python 3.12.x`. If `python` is not recognised, close and
reopen PowerShell, or reinstall Python with the PATH option enabled.

### Step 2 — Open the project folder

```powershell
cd "C:\path\to\mnz_market_intelligence"
```

If your folder contains `app.py` at the top level, you are in the right place.

### Step 3 — Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation with an execution-policy error, either run the command
below (current user only) or use Command Prompt instead:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Command Prompt alternative:

```bat
.venv\Scripts\activate.bat
```

Your prompt should now begin with `(.venv)`.

### Step 4 — Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This installs Streamlit, Pandas, NumPy, Plotly, yfinance and pytest. Installation can take
a few minutes on the first run.

### Step 5 — Launch the application

```powershell
python -m streamlit run app.py
```

(`python -m streamlit ...` avoids PATH problems with the `streamlit` launcher.)

Streamlit prints a local URL, normally:

```
Local URL: http://localhost:8501
```

Open it in your browser. To use a different port:

```powershell
python -m streamlit run app.py --server.port 8600
```

Stop the server with `Ctrl+C` in the PowerShell window.

### Step 6 — Optional: run the tests

```powershell
python -m pytest -q
```

---

## 4. First-run behaviour and data honesty

Market data comes from **Yahoo Finance through yfinance** — a free, delayed feed. Prices may
lag by 15–20 minutes, intraday history is limited, and some symbols or periods return
nothing.

MNZ never invents live prices. Specifically:

- Every chart and table shows its **source, interval, bar count and last-bar timestamp**.
- Missing data produces an explicit error message, and the instrument is excluded from
  analysis rather than estimated.
- If the provider cannot be reached and **“Allow clearly-labelled offline sample data”** is
  enabled (Settings → Data & provider), the app generates a deterministic synthetic series
  so the interface remains explorable. Those rows are labelled **SAMPLE DATA** on the chart
  watermark, in the source line, in the analyst report and in the data-quality column.
  Sample data means nothing for real markets.
- Turn the fallback off to see strict error handling instead.

Economic-event information is **awareness, not a live calendar**: MNZ lists recurring
release windows (for example US non-farm payrolls on the first Friday, ~13:30 UTC) and says
so wherever they appear. Confirm times with an official calendar.

---

## 5. AI Market Analyst — how the labels are produced

The analyst is a transparent rule system, not a language model and not advice.

1. Each engine computes indicators from the last bars: trend structure (MA alignment and
   price location), MACD momentum, RSI, volume versus its 50-bar average, ATR volatility.
2. Direction components are weighted **per engine** (see Settings → Engine strategies, or
   the weight table on the AI Market Analyst page). Volatility and session liquidity adjust
   conviction rather than direction.
3. The weighted score is clipped to `[-1, +1]`:
   - `≥ +0.25` → **BUY BIAS**
   - `≤ −0.25` → **SELL BIAS**
   - otherwise → **WAIT**
   - fewer than 210 bars → **NO DATA**
4. Conviction combines score strength, component agreement, volatility and **data quality**
   (current < delayed < sample). Sample data caps conviction near 40%; it cannot be 100%.
5. The page always states why: component scores and weights, plain-language sentences,
   indicator readings, cautions, source, timestamp and any stale/missing data.

These labels are educational. They are not financial advice, not a recommendation and do
not consider your circumstances.

---

## 6. Demo trading simulator

- Starting virtual balance: **$10,000** (configurable in Settings; changing it resets the
  demo account).
- Long or short, fractional quantities, manual entry and exit prices defaulting to the
  latest available close.
- Simulated transaction costs in basis points, charged on **both** entry and exit.
- Virtual P&L, win rate, profit factor, holding period and maximum drawdown from recorded
  equity snapshots.
- Open and closed positions, complete trade history, CSV exports.

Accounting model (documented so the numbers are auditable):

```
cash     = starting balance − entry costs + realised gross P&L − exit costs
equity   = cash + unrealised gross P&L of open positions
realised = Σ (gross P&L − entry cost − exit cost) for closed trades
```

Notional is never deducted from cash — this is a notional demo, not a margin model, so the
simulator caps notional at 10× virtual equity. Nothing is sent anywhere: trades live only
in `mnz_data/mnz.db`.

---

## 7. Backtesting

Strategy Testing runs the selected engine's own configuration against historical bars:

- entries on trend (fast MA above slow MA) with an optional RSI entry *state*: the filter
  arms when RSI falls below the entry ceiling and stays armed until RSI reaches the exit
  level, so a trend can be entered after the pullback even if RSI has drifted back up;
- automatic fitting for short windows: when fewer than two slow-MA lengths of history are
  available, the run fits the same fast/slow ratio to the window (a 1-year EURUSD run uses
  roughly 22/86), and says so in the result header, the warnings and the period comparison —
  no prices are padded or estimated;
- windows too short even to fit a structure (under 60 bars) are reported as insufficient;
- saved results store the structure that actually ran;
- exits on trend reversal, RSI extremity or an optional time stop;
- bar-close fills, no intrabar look-ahead;
- costs in basis points on entry and exit notional;
- results: total simulated return, buy & hold comparison, maximum drawdown, win rate,
  number of trades, total costs, profit factor, exposure, annualised return and bar-return
  Sharpe;
- comparison across the last 3 months, 12 months, 3 years, 5 years and full history —
  windows with insufficient warm-up are reported as insufficient instead of filled;
- downloadable trade list and saved runs (visible in Performance Reports).

**Historical results do not guarantee future performance.** Backtests ignore financing,
taxes, liquidity, intrabar stop execution and behavioural effects.

GitHub Actions runs `python -m pytest -q` on every push and pull request
(`.github/workflows/tests.yml`), installing `requirements.txt` on Python 3.12.

---

## 8. Configuration

Most defaults live in `config.py`:

| Setting | Purpose |
|---|---|
| `INSTRUMENTS` | Instrument universes per engine |
| `ENGINE_STRATEGY_DEFAULTS` | Each engine's own moving averages, RSI, cost and size defaults |
| `ANALYST_WEIGHTS` | Per-engine weighting of analytical components |
| `TIMEFRAMES` | Period/interval choices (1 month 5m → maximum weekly) |
| `DEMO_STARTING_BALANCE` | Default virtual starting balance |
| `ALLOW_SAMPLE_DATA_FALLBACK` | Default for the offline sample-data toggle |
| `DATA_CACHE_TTL_SECONDS` | Provider cache lifetime |

Environment variables (optional):

- `MNZ_DB_PATH` — override the SQLite file location.
- `MNZ_CACHE_TTL` — override the cache lifetime in seconds.

Safety flags are hard-coded in `config.py`: `DEMO_ONLY = True`, `LIVE_EXECUTION_ENABLED =
False`, `BROKER_INTEGRATION_ENABLED = False`. There is no broker code anywhere in the
project.

---

## 9. Troubleshooting

| Symptom | Explanation and fix |
|---|---|
| “Provider rate limit reached (HTTP 429)” | Yahoo Finance throttles bursts. Wait a few minutes, press **Refresh data**, or raise the cache lifetime in Settings. |
| Charts are empty / “Data unavailable” | The symbol, period or interval may not exist at the provider. Try another timeframe. Intraday intervals have limited history. |
| Everything shows **SAMPLE DATA** | The provider is unreachable (offline, firewall, corporate proxy) and the fallback is enabled. Disable it in Settings for strict errors. |
| `python` not recognised | Reinstall Python with “Add python.exe to PATH”, or use the `py` launcher: `py -m streamlit run app.py`. |
| `ModuleNotFoundError: streamlit` | The virtual environment is not active, or dependencies are missing: activate `.venv` and reinstall requirements. |
| PowerShell blocks activation | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, or use `.venv\Scripts\activate.bat`. |
| Port already in use | `python -m streamlit run app.py --server.port 8600`. |
| Fundamentals or earnings missing | The provider did not return them. MNZ shows the reason and does not invent values. |

To reset the demo data completely, stop the app and delete `mnz_data/mnz.db` (it is
recreated on the next launch), or use **Reset demo account** on the Demo Trading page.

---

## 10. Limitations and planned commercial architecture

Not implemented in version 1:

- user authentication, individual customer accounts and per-user data isolation;
- subscription plans, billing and licence enforcement;
- automated order execution, broker connectivity and API trading keys (**permanently
  disabled in this build**);
- live economic calendar, real-time streaming quotes, options or futures term structure.

The storage layer is already account-scoped, settings are namespaced JSON keys, and the
dashboard is account-driven, so customer accounts, per-user settings, entitlements and
licensing could be added later without redesigning the data model. See Settings → Safety &
roadmap for the documented intent.

---

## 11. Deploying to Streamlit Community Cloud

The app is a long-running Streamlit server, so it needs a Python host — static hosting
will not run it. Streamlit Community Cloud is the simplest free option:

1. Commit the project and push it to a GitHub repository you have admin rights on
   (public is simplest; private repositories work but only one private app is allowed).
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
3. **Create app** → choose the repository and branch → main file `app.py` → advanced
   settings → Python 3.12 → **Deploy**.
4. No secrets are needed. The app never requests brokerage credentials or API keys, and
   `requirements.txt` is installed automatically.

What to expect from the hosted demo:

- **The SQLite database resets on restart.** The filesystem is ephemeral, so
  `mnz_data/mnz.db` is recreated whenever the app restarts, redeploys or wakes from
  sleep. Simulated trades, saved backtests and setting changes return to the default
  $10,000 demo account. Use a host with a persistent volume and set `MNZ_DB_PATH` if you
  need that data to survive.
- Apps sleep after 12 hours without traffic; the next visitor wakes the app.
- There is **no authentication**: anyone with the URL can place simulated trades, reset
  the demo account and edit settings. Share it accordingly.
- GitHub Actions runs the test suite on every push once the repository is published
  (see `.github/workflows/tests.yml`).

---

## 12. Disclaimer

MNZ MARKET INTELLIGENCE is an educational, analytical research tool. Nothing in it is
financial advice, an investment recommendation or a solicitation to trade. Trading carries
a risk of loss. Simulated and historical results do not guarantee future performance. The
software is provided as-is, without warranty.
