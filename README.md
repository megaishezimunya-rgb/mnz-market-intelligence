# MNZ BOT

A premium, responsive multi-market **analysis, scanning and simulation** platform built with
Python, Streamlit, Pandas, Plotly, and SQLite locally or PostgreSQL when `DATABASE_URL` is set.

Version 2.0 upgrades the existing MNZ Market Intelligence app in place — same project, same
Streamlit entry point, same deployment model — into a six-section product with accounts,
persistent signals, a continuous scanner, a $100 simulated account and a grounded assistant.

> **DEMO ONLY.** Every balance, position and result is virtual. MNZ has no broker connection,
> no order routing, no API trading keys and never asks for brokerage credentials. Automated
> execution is disabled in code. Nothing here is financial advice.

---

## 1. What is in this build

Signed-out visitors see the **public website** (Home, Features, Platform Compatibility, How It
Works, Pricing, Academy, Support, Login, Register). Signed-in users get six sections:

| Section | Contents |
|---|---|
| **Home** | Scanner status, monitored categories, latest signals, demo equity, open simulated positions, unread alerts, connection health, upcoming event windows |
| **Markets** | Scanner (Scan one / Scan all / continuous Start–Pause–Resume–Stop), interactive charts, RSI/MACD/EMA/SMA/Bollinger/ATR/ADX, Strategy Lab (backtests, period comparison, market comparison), Conditions monitor, Economic calendar |
| **Signals** | Signal Centre, full history with date/instrument/direction filters, measured TP/SL outcomes, performance, Smart Alerts and alert history |
| **Demo** | $100 virtual account, 1/3/5 slots, TP/SL auto-exits, open/closed positions, journal, Performance Centre |
| **MNZ AI** | Grounded assistant with Beginner/Professional modes over the loaded instrument, stored signal, indicators, demo state and scan conditions |
| **Settings** | Profile, notifications, display, demo Safety Guard, Help Centre, platform compatibility, data connection and account controls |

### Preserved from version 1

- SQLite persistence for accounts, simulated trades and equity snapshots, with optional PostgreSQL.
- Indicator library (SMA, EMA, RSI, MACD, ATR, Bollinger, stochastic, ROC, drawdown).
- Explainable, rule-based market analyst and per-market strategy defaults.
- Backtesting engine with costs, fitted structures for short windows, and period comparison.
- Demo accounting model and portfolio analytics.
- Delayed Yahoo Finance feed with explicit source, timestamp and quality labelling.

### Added or rebuilt in version 2

- Local authentication (PBKDF2-SHA256, hashed session tokens, URL-restored sessions) and
  per-user isolation for accounts, signals, alerts, journal and settings.
- Brand and layout rebuild: `#090B0F` background, `#151922` cards, `#20D68A` / `#F04452`
  indicators, desktop collapsible sidebar, phone bottom navigation.
- Signal engine with quality score, ATR-based simulated TP/SL, first-touch outcome measurement
  and WAIT gating for stale or sample data.
- Continuous scanner using Streamlit fragments with real start/pause/resume/stop state.
- Smart Alerts with thresholds, daily cap, deduplication per bar, and saved history.
- Signals, alerts, journal, equity snapshots and per-user settings persisted (SQLite or PostgreSQL).
- Public website with honest pricing, compatibility and academy pages.
- ADX and +DI/−DI, H4 aggregation, M1–D1 timeframe mapping.
- Mnz Safety Guard and Market Conditions monitor.
- 90 automated tests (see §7).

---

## 2. Markets and data honesty

Available from the connected **Yahoo Finance** feed:

- **Forex** — 10 majors and crosses.
- **Global Indices** — including **US30** (`^DJI`), S&P 500, Nasdaq 100, FTSE, DAX, Euro Stoxx,
  Nikkei, Hang Seng, ASX 200, Sensex.
- **Stocks** — 12 large-cap US equities.
- **Commodities** — gold, silver, WTI, Brent, copper, gas, corn, wheat.
- **Crypto** — BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE.

**Synthetic indices** are a Deriv product. No Deriv connection is configured, so those
instruments are listed as *awaiting a data connection* and no prices are shown or invented.

Timeframes: **M1, M5, M15, M30, H1, H4, D1**. H4 is aggregated from hourly provider bars and
labelled as such. Intraday history is provider-limited.

Rules the app enforces:

- Every chart shows source, interval, bar count, last-bar timestamp and freshness.
- Missing data produces an explicit message, never an estimate.
- Offline sample data is **opt-in**, watermarked, capped at quality 30 and can never produce
  BUY or SELL.
- Stale bars cannot produce a directional signal.

---

## 3. Signals, quality and Safety Guard

Direction is a weighted combination of trend structure, MACD momentum, RSI and market
structure, with per-market weights:

```
score = Σ weight × component          clipped to [-1, +1]
BUY  ≥ +0.28      SELL ≤ −0.28      otherwise WAIT
```

- **Entry reference** is the last verified close.
- **Simulated SL** is 1.5 × ATR from entry; **TP** is 2.6 × ATR.
- **Evidence gate.** A direction is published only when at least **two** indicator components
  point the same way by at least 0.15; one strong reading on its own stays WAIT. When ADX is
  below 18 the market is ranging, so the bar rises to |score| ≥ 0.45.
- **Higher-timeframe check.** The same loaded bars are resampled one step up (H1 → D1,
  M15 → H1, D1 → W1) and its trend must not oppose the reading; an opposing higher trend turns
  the signal into WAIT, an aligned one adds to quality. No extra provider request is made.
- **Evidence on the card.** Every signal shows how many of the four components agreed, whether
  the higher timeframe was aligned and whether the market was ranging.
- **Quality (0–100)** combines component agreement, signal magnitude, bar count, volatility
  regime, confirmation count and freshness. Sample data caps quality at 30.
- **Strength** is Strong / Moderate / Weak from quality and magnitude.
- **Outcomes** are measured later against actual subsequent bars (first touch of TP or SL).
  A bar that touches both is reported as ambiguous/unresolved rather than guessed.
- **Signal Calibration** groups the account's own resolved signals by market, timeframe and
  quality band and reports TP-first hit rate, expectancy in R and profit factor. Groups with
  fewer than 10 resolved signals are labelled *Too few* instead of being presented as an edge.
- **Safety Guard** shows pass/blocked checks for provider response, real-data status,
  freshness, simulated-only levels and quality.

Alerts are created only for new directional signals that meet the user's strength and quality
thresholds, from current data, capped per day and deduplicated per bar.

MNZ AI can rank the stored setups on request (*"which setup is best?"*): it orders the latest
verified BUY/SELL reading per instrument by quality then score, excludes sample and stale data,
and quotes the stored entry/TP/SL with reward-to-risk. It ranks what is already stored — it does
not scan, fetch or invent a setup.

---

## 4. Demo trading model

- Starting virtual balance: **$100**.
- Slots: **1, 3 or 5** open positions. A slot is occupied only after a position is created.
- Entries come from a stored signal (side, entry, TP, SL pre-filled) or manual what-if entry.
- Quantity suggestion: `equity × risk% ÷ |entry − stop|`, capped at 10× equity notional.
- Simulated costs in basis points on entry and exit.
- TP/SL are checked against the latest delayed price when the Demo page is opened.

Accounting (auditable):

```
cash     = starting balance − entry costs + realised gross P&L − exit costs
equity   = cash + unrealised gross P&L
realised = Σ (gross P&L − entry cost − exit cost) for closed trades
```

Every balance, position and result is labelled DEMO.

---

## 5. Authentication and storage

- Email + password accounts, PBKDF2-HMAC-SHA256 (210,000 iterations, per-user salt).
- Session tokens are random, stored only as SHA-256 hashes with a 30-day expiry, and restored
  from the URL so a browser refresh keeps you signed in. Signing out deletes the session.
- Repeated failed sign-ins or registrations for the same email back off exponentially — five
  attempts are free, then 30 s, 60 s, 120 s and so on, capped at 15 minutes, and a success
  clears the counter. The counter is keyed by email and stored in the database
  (`login_attempts`), so a redeploy, a restart or a second server process sees the same
  backoff instead of handing out fresh attempts. Quiet for 15 minutes resets the count, and
  counters untouched for seven days are pruned. It slows online guessing, not a determined
  attacker with many addresses.
- Signed-in users can change their password in Settings → Profile by entering the current one;
  the change ends every other session for the account, so a stolen session cannot outlive it.
  The session making the change stays signed in.
- All user data is scoped by `user_id` or `account_id`:
  - `users`, `sessions`, `accounts`, `trades`, `equity_snapshots`
  - `signals`, `alerts`, `journal`, `user_settings`, `backtest_runs`
  - `delivery_attempts` (outbound Telegram outcomes, survives restarts)
  - `login_attempts` (failed sign-in counters per email, survives restarts)

Repository: `database/database.py`. Runtime database: `mnz_data/mnz.db` (git-ignored).

### Durable storage (important for real users)

On Streamlit Community Cloud the filesystem is ephemeral: a restart or redeploy recreates the
SQLite file, so accounts, demo positions and delivery history reset. The app uses SQLite by
default and automatically switches to PostgreSQL when a `DATABASE_URL` is present — no code
change and no extra flag.

#### Neon + Streamlit Cloud, step by step

Neon is the cheapest path (free plan, no card). Any managed Postgres works the same way.

1. Sign in at [neon.tech](https://neon.tech) and create a project — pick the region closest to
   your Streamlit app.
2. Open the project's **Connect** panel and copy the **connection string**. Take the pooled
   `-pooler` host; it already ends with `?sslmode=require`.
3. In Streamlit Cloud open your app → **Manage app** → **Settings** → **Secrets**, paste one line
   (keep the quotes — the file is TOML), then **Save**:

   ```toml
   DATABASE_URL = "postgresql://user:password@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require"
   ```

4. Streamlit reboots the app. On the first connection the app creates the schema, indexes and
   constraints; no manual SQL and no extra package (`psycopg[binary,pool]` is already in
   `requirements.txt`).
5. Confirm: Settings → Help Centre → Account and data shows **PostgreSQL (durable)** and the red
   *Temporary storage* banner is gone. To rotate credentials later, paste the new string in the
   same field — nothing else changes.

Root-level Streamlit secrets are exported as environment variables, which is how the app reads
`DATABASE_URL`. `postgres://` URLs are normalised to `postgresql://`, and TLS is controlled by
the provider's `sslmode` parameter.

Data already in a local SQLite file is **not** moved automatically. Carry it over once, from a
machine that still has the file (Streamlit's container loses it on restart), before you switch
the deployment:

```bash
DATABASE_URL="postgresql://..." python -m database.migrate --sqlite mnz_data/mnz.db
```

The migration refuses a non-empty target, copies every table in a single transaction (all or
nothing), preserves row ids, advances the id sequences and verifies row counts. Run it once,
then set the same `DATABASE_URL` in Secrets and redeploy. Running it again is refused because
the target already has data.

**SQLite fallback.** With no `DATABASE_URL`, the app keeps using SQLite at `MNZ_DB_PATH`
(default `mnz_data/mnz.db`). On a host with a persistent volume that is also durable:

```bash
MNZ_DB_PATH=/data/mnz.db
```

SQLite data survives a *rerun* (page refresh, session restart); it does not survive a container
restart on an ephemeral host. Back up either backend on a schedule — for SQLite,
`sqlite3 mnz.db ".backup backup.db"` is safe while the app is running.

The PostgreSQL driver is `psycopg` 3 with a small connection pool (at most four connections per
process). The pool is built for a hosted, serverless-friendly database:

- It **validates each connection before handing it out** and replaces it if the provider closed
  it, which is what happens when Neon suspends an idle compute. Connections are also recycled
  every five minutes so a provider idle timeout cannot leave a dead one behind.
- Only the **pooled** `-pooler` hostname is expected (PgBouncer, transaction mode), so
  protocol-level prepared statements are disabled there. A direct hostname keeps them.
- `sslmode` and `channel_binding` from the provider string are passed through unchanged; if a
  pooler rejects `channel_binding=require`, the app retries once with `prefer` (TLS still
  required) instead of failing the request.
- A connect timeout, bounded retries and a bounded wait for a connection mean a cold or
  unreachable database produces a readable error instead of hanging the login page.

All queries live in `database/database.py`; the public `Database` interface is identical for
both backends, so the rest of the app and the test suite are unchanged.

---

## 6. Run locally

Python 3.10+ (tested on 3.12).

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open <http://localhost:8501>, choose **Register**, and create an account. No secrets or API keys
are required.

Optional environment variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Optional PostgreSQL connection string; enables durable storage |
| `MNZ_DB_PATH` | SQLite file location when `DATABASE_URL` is not set |
| `MNZ_CACHE_TTL` | Provider cache lifetime in seconds (default 300) |
| `MNZ_TELEGRAM_BOT_TOKEN` | Optional. Bot token for outbound Smart Alert delivery |
| `MNZ_TELEGRAM_CHAT_ID` | Optional. Destination chat id for Telegram delivery |

Telegram delivery is off until BOTH variables are set (on Streamlit Cloud: App → Settings →
Secrets). The in-app alert is always saved first, and sending happens on a background worker
with a bounded queue — a slow Bot API call never delays a scan. Settings → Notifications shows
the last delivery attempt, whether it succeeded, the error if it failed, the sent/failed counts
and the current queue depth, so a delivery problem is visible instead of silent. A **Send test
message** button queues a real message through the same background sender and reports the
outcome, including "not configured" when the server has no credentials. Every attempt is written
to the `delivery_attempts` table and the last eight for the signed-in account are listed in
Settings, so failures remain visible after a restart (the live counters reset with the process).
Only the newest 50 attempts per account are kept; older rows are pruned on each insert.

---

## 7. Tests

```bash
python -m pytest -q
```

Current suite: **183 tests** (181 run by default; the two live PostgreSQL tests are skipped
unless `MNZ_TEST_DATABASE_URL` is set), covering indicators, backtesting, simulator accounting, engine
analyst, authentication and data isolation, signal labels/quality/targets/outcomes, scanner
persistence and alert gating, demo slots and TP/SL, AI grounding, expectancy/breakdowns, stale
position cleanup, provider cooldown, backend selection and SQL translation, stored failed-login
counters, password change and session revocation, non-blocking
Telegram delivery (slow send, failing send, full queue), and end-to-end rendering of
the public site plus all six sections (with a deterministic local feed, no network needed).

What the tests do **not** cover: real Yahoo Finance responses, actual browser layout at specific
screen sizes, and multi-user load. Those require a running deployment and manual/visual checks.

---

## 8. Deploying (preserving the existing URL)

The app remains a single Streamlit entry point (`app.py`) with `requirements.txt`, so the
existing Streamlit Community Cloud app can be updated by pushing this repository — no URL change
and no new deployment configuration are needed.

1. Commit and push to the repository branch the Streamlit app watches.
2. Streamlit Cloud installs `requirements.txt` and restarts `app.py`.
3. Sign in with an existing account, or register a new one.

Notes:

- Python 3.12; no secrets required unless you enable PostgreSQL or Telegram.
- Without `DATABASE_URL`, SQLite data resets when the container restarts (see §5).
- The public website and the application live in the same deployment: the website is the
  signed-out surface, the app is behind login. A fully separate marketing domain would be a
  separate static deployment sharing the same brand assets.

---

## 9. Still requires external integrations

| Capability | Status |
|---|---|
| Real-time streaming quotes | Not implemented — delayed Yahoo Finance only |
| Synthetic indices (Deriv) | Requires a Deriv market-data connection and app id |
| MT5 / Razor Markets | Planned targets only; no bridge, credentials or balances |
| Live order execution | Permanently disabled in this build |
| Live economic calendar feed | Not connected; recurring windows are labelled as typical |
| Billing / subscriptions | Not implemented; demo access is free |
| Outbound alert delivery | Optional Telegram via server env vars; no email provider |
| Durable hosted database | PostgreSQL via `DATABASE_URL`, or SQLite on a persistent volume |
| Native mobile app | Responsive web only |

---

## 10. Project structure

```
app.py                  Auth gate, sidebar/bottom navigation, page routing
config.py               Brand, palette, markets, timeframes, thresholds, demo defaults
auth.py                 PBKDF2 hashing, registration/login, hashed sessions
state.py                Session user, demo account, per-user settings, navigation
ui.py                   Theme, responsive CSS, charts and components
website.py              Public marketing site + login/register
scanner.py              Scan orchestration, signal persistence, alerts, conditions, Safety Guard
ai.py                   Grounded MNZ AI responses
analysis/
  indicators.py         Technical indicators incl. ADX
  signals.py            Signal engine, quality, ATR targets, outcome measurement
  market_analyst.py     Version 1 explainable analyst (retained)
  backtesting.py        Backtest engine and period comparison
data/market_data.py     Provider access, timeframe mapping, H4 aggregation, connection monitor
database/database.py    Schema and queries; SQLite and PostgreSQL backends
simulator/              Demo account, virtual trades, portfolio analytics
engines/                Per-market context engines (retained)
pages/                  home, markets, signals_page, demo_page, ai_page, settings_page, common
tests/                  pytest suite
```

---

## 11. Disclaimer

MNZ BOT is an educational market-analysis and simulation tool. Nothing in it is financial advice,
an investment recommendation or a solicitation to trade. Signals are rule-based readings of
delayed data, not predictions. Trading carries a risk of loss. Simulated and historical results
never guarantee future performance. The software is provided as-is, without warranty.
