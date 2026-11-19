"""MNZ AI — a grounded market assistant.

This is deliberately *not* a language model that can hallucinate prices. It is a
deterministic assistant: every number it states is read from the fetched
:class:`PriceData`, the computed indicator snapshot or the stored signal. When
data is missing it says so and points to the screen that can load it.

It cannot see news, and it never claims to know why a market moved beyond what
the measured indicators show.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import config
from analysis import indicators
from analysis.signals import Signal
from data.market_data import PriceData

INDICATOR_HELP = {
    "rsi": (
        "RSI (Relative Strength Index) measures the speed of recent gains against losses on a "
        "0–100 scale. Above 70 is usually read as overbought, below 30 as oversold. It is a "
        "momentum gauge, not a buy/sell instruction — strong trends can stay overbought for a long time."
    ),
    "macd": (
        "MACD subtracts a slower EMA from a faster one (12 and 26 bars by default) and adds a "
        "9-bar signal line. When the MACD line is above its signal line, short-term momentum is "
        "positive; the histogram shows how far apart they are."
    ),
    "ema": (
        "An EMA (Exponential Moving Average) weights recent prices more heavily than an SMA, so it "
        "turns faster. Traders use it to read the direction of the recent trend."
    ),
    "sma": (
        "An SMA (Simple Moving Average) is the plain average of the last N closes. Price above a "
        "rising SMA is a common description of an uptrend; the crossover of a fast and slow SMA is "
        "a classic trend signal."
    ),
    "bollinger": (
        "Bollinger Bands place a moving average in the middle with bands two standard deviations "
        "above and below. Wide bands mean high volatility; price hugging a band shows a strong move, "
        "not automatically a reversal."
    ),
    "atr": (
        "ATR (Average True Range) measures how much an instrument typically moves per bar, including "
        "gaps. MNZ uses it to size simulated stops and targets, so a volatile market gets wider levels."
    ),
    "adx": (
        "ADX (Average Directional Index) measures trend *strength*, not direction. Below about 20 the "
        "market is usually ranging; above 25 it is trending, and above 40 the trend is strong. "
        "+DI and -DI show which side is in control."
    ),
}


@dataclass
class AssistantContext:
    mode: str = "Beginner"
    symbol: str = ""
    data: PriceData | None = None
    signal: Signal | None = None
    snapshot: indicators.IndicatorSnapshot | None = None
    equity: float | None = None
    starting_balance: float | None = None
    open_positions: int = 0
    closed_positions: int = 0
    conditions: dict | None = None
    recent_signals: list[dict] = field(default_factory=list)
    timeframe: str = config.DEFAULT_TIMEFRAME
    alerts_unread: int = 0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _has(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _num(value, digits: int = 2) -> str:
    return f"{float(value):,.{digits}f}" if _has(value) else "n/a"


def _quote_block(ctx: AssistantContext) -> str:
    data = ctx.data
    if data is None or not data.ok:
        return (
            "I don't have a verified price for this instrument. Open **Markets**, choose an "
            "instrument and timeframe, and I can read the data that loads."
        )
    stamp = data.last_bar_time.strftime("%Y-%m-%d %H:%M") if data.last_bar_time else "unknown"
    quality = (
        "SAMPLE data (not real)" if data.is_sample
        else f"delayed feed ({data.status_note().lower()})"
    )
    change = ""
    if data.bars >= 2:
        previous = float(data.frame["Close"].iloc[-2])
        if previous:
            delta = (float(data.last_price) / previous - 1) * 100
            change = f" The latest bar changed {delta:+.2f}%."
    basic = (
        f"**{ctx.symbol}** last traded at **{data.last_price:,.5g}** on the {ctx.timeframe} "
        f"timeframe (bar time {stamp} UTC, {quality}).{change}"
    )
    snap = ctx.snapshot
    if snap is None:
        return basic
    if ctx.mode == "Beginner":
        return basic + (
            f"\n\nThe trend reads **{snap.trend_label.lower()}**, RSI is **{_num(snap.rsi, 1)}**, "
            f"and volatility is **{snap.volatility_label.lower()}**. "
            "That describes the recent bars, not what happens next."
        )
    return basic + (
        f"\n\n- Trend: **{snap.trend_label}** (score {snap.trend_score:+.2f})\n"
        f"- RSI(14): **{_num(snap.rsi, 1)}** · MACD hist: **{_num(snap.macd_hist, 4)}**\n"
        f"- ADX(14): **{_num(snap.adx, 1)}** ({snap.adx_state}) · +DI {_num(snap.plus_di, 1)} / "
        f"-DI {_num(snap.minus_di, 1)}\n"
        f"- ATR: **{_num(snap.atr_pct, 2)}%** of price ({snap.volatility_label} volatility) · "
        f"Bollinger width {_num(snap.bb_width, 2)}%\n"
        f"- Bars loaded: **{snap.bars}** · data quality: **{data.quality}**"
    )


def _signal_block(ctx: AssistantContext) -> str:
    signal = ctx.signal
    if signal is None:
        return (
            "No signal has been generated for this instrument yet. Open **Markets** and run a scan, "
            "or use **Signals → Signal Centre** to scan now."
        )
    lines = [
        f"The current reading for **{signal.symbol}** on **{signal.timeframe}** is "
        f"**{signal.label}** with **{signal.strength.lower()}** strength and a quality score of "
        f"**{signal.quality}/100**.",
        "",
        signal.explanation,
    ]
    if signal.label in {"BUY", "SELL"}:
        target_line = (
            f"\nReference entry **{signal.entry_ref}**, simulated take profit **{signal.tp}**, "
            f"simulated stop loss **{signal.sl}**."
        )
        if signal.risk_reward:
            target_line += f" That is a {signal.risk_reward:.2f}:1 simulated reward-to-risk."
        lines.append(target_line)
    confirmations = (signal.metrics or {}).get("confirmations")
    if confirmations:
        lines.append(
            f"\n**{confirmations}** indicator component(s) agree with this reading; MNZ requires "
            f"at least **{config.SIGNAL_MIN_CONFIRMATIONS}** before publishing a direction."
        )
    alignment = (signal.metrics or {}).get("higher_alignment")
    if alignment and alignment != "unavailable":
        higher_label = (signal.metrics or {}).get("higher_timeframe") or "higher"
        lines.append(f"The **{higher_label}** trend is **{alignment}** with it.")
    if ctx.mode == "Professional" and signal.metrics:
        components = signal.metrics.get("components", {})
        weights = signal.metrics.get("weights", {})
        if components:
            rendered = ", ".join(
                f"{key} {components[key]:+.2f} (w {weights.get(key, 0):.2f})"
                for key in components
            )
            lines.append(f"\nComponent scores: {rendered}. Weighted score {signal.score:+.2f}.")
    if signal.warnings:
        lines.append("\n**Cautions**")
        lines.extend(f"- {warning}" for warning in signal.warnings)
    lines.append(
        "\nThis is a rule-based reading of delayed data. It is not financial advice and it does "
        "not place any order."
    )
    return "\n".join(lines)


def _demo_block(ctx: AssistantContext) -> str:
    if ctx.equity is None:
        return "The demo account is not loaded."
    start = float(ctx.starting_balance or 0)
    change_pct = ((ctx.equity - start) / start * 100) if start else 0.0
    return (
        f"Your **DEMO** account holds **${ctx.equity:,.2f}** in virtual equity against a "
        f"${start:,.2f} starting balance ({change_pct:+.2f}%), with **{ctx.open_positions}** open "
        f"and **{ctx.closed_positions}** closed simulated positions.\n\n"
        "Every figure is simulated. MNZ is not connected to a broker and cannot place real orders."
    )


def _conditions_block(ctx: AssistantContext) -> str:
    conditions = ctx.conditions
    if not conditions or not conditions.get("usable"):
        return (
            "No scan has run yet, so I have no verified cross-market picture. Open **Markets** and "
            "press **Scan All** first."
        )
    return (
        f"Across the **{conditions['usable']}** instruments with usable data in the last scan, "
        f"**{conditions['bullish']}** read BUY, **{conditions['bearish']}** read SELL and "
        f"**{conditions['waiting']}** read WAIT. The net bias is "
        f"**{conditions['label'].lower()}**, with an average signal quality of "
        f"**{conditions['avg_quality']}/100**."
        + (" Some instruments were showing sample data and are excluded from actionable signals."
           if conditions.get("sample") else "")
    )


def _number(value, digits: int = 2) -> str:
    return _num(value, digits) if _has(value) else "n/a"


def _best_setups_block(ctx: AssistantContext) -> str:
    """Rank the stored directional signals that are verified and current.

    The ranking is by stored quality and then score, and it only ranks signals
    that already exist — it never scans, fetches or invents a setup.
    """
    rows = [row for row in ctx.recent_signals if row.get("label") in {"BUY", "SELL"}]
    verified = [
        row for row in rows
        if not row.get("is_sample") and row.get("data_quality") == "current"
    ]
    if not verified:
        if rows:
            return (
                "Every stored BUY/SELL reading I can see came from sample or stale data, so I "
                "won't rank them as setups. Open **Markets** and press **Scan all** on a live "
                "feed, then ask again."
            )
        return (
            "I have no stored BUY/SELL reading to rank yet. Open **Markets** and press "
            "**Scan instrument** or **Scan all**; the signal that is stored can then be compared "
            "with the others on quality, score and reward-to-risk."
        )

    def quality(row: dict) -> int:
        try:
            return int(row.get("quality") or 0)
        except (TypeError, ValueError):
            return 0

    def score(row: dict) -> float:
        try:
            return abs(float(row.get("score") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(verified, key=lambda row: (-quality(row), -score(row)))
    lines = [
        f"Ranked by stored quality, then weighted score, across **{len(verified)}** verified "
        "BUY/SELL reading(s) already in your Signal Centre:",
        "",
    ]
    for index, row in enumerate(ranked[:5], start=1):
        reward = ""
        try:
            entry = float(row["entry_ref"])
            tp = float(row["tp"])
            sl = float(row["sl"])
            if entry and abs(entry - sl) > 0:
                reward = f", {abs(tp - entry) / abs(entry - sl):.2f}:1 reward-to-risk"
        except (KeyError, TypeError, ValueError):
            reward = ""
        lines.append(
            f"{index}. **{row.get('symbol', '')}** {str(row.get('label', '')).lower()} on "
            f"**{row.get('timeframe', '')}** — quality **{quality(row)}/100**, "
            f"{str(row.get('strength', '')).lower()} strength, score {_number(row.get('score'), 2)}"
            f"{reward}."
        )
    lines.append(
        "\nQuality ranks how much independent evidence agreed and how clean the data was; it "
        "is not a probability of profit. These are rule-based readings of delayed data, not "
        "recommendations, and no order is placed anywhere."
    )
    return "\n".join(lines)


def _how_to_block() -> str:
    return (
        "**Getting around MNZ BOT**\n\n"
        "1. **Markets** — pick a category and instrument, choose M1–D1, then scan one instrument or "
        "the whole shortlist. Charts show EMA/SMA with RSI, MACD and ADX below.\n"
        "2. **Signals** — every stored signal, its quality score, simulated TP/SL and its measured "
        "outcome, plus Smart Alerts.\n"
        "3. **Demo** — open a simulated position from a signal or manually, using 1, 3 or 5 slots. "
        "Everything is virtual.\n"
        "4. **Settings** — notifications, display preferences, Safety Guard and compatibility.\n\n"
        "Signals are mechanical readings of delayed data, never instructions to trade."
    )


def _risk_block(ctx: AssistantContext) -> str:
    return (
        "Risk in MNZ is framed for simulation only:\n\n"
        "- A signal's simulated stop is placed 1.5× ATR from the reference price, so more volatile "
        "instruments get wider stops.\n"
        "- Demo position size is derived from virtual equity and the stop distance, so one losing "
        "trade cannot wipe the account.\n"
        "- Only **1, 3 or 5** demo slots can be open at once, which caps simulated exposure.\n"
        "- Data staleness and sample data are surfaced by the **MNZ Safety Guard** before a signal "
        "is treated as usable.\n\n"
        "None of this is financial advice, and simulated results do not predict real outcomes."
    )


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def answer(question: str, ctx: AssistantContext) -> str:
    """Answer a question using only the supplied verified context."""
    text = (question or "").strip().lower()
    lead = "Here is what the data shows." if ctx.mode == "Beginner" else "Grounded reading:"

    if not text:
        return "Ask me about the current instrument, a signal, an indicator, or how the platform works."

    if any(word in text for word in ("mt5", "metatrader", "razor", "broker", "connect")):
        return (
            "MNZ has **no broker connection**. MetaTrader 5 and Razor Markets are listed as "
            "*planned compatibility targets* in **Settings → Platform Compatibility**, and no "
            "account, balance or connection status is shown for them because none exists.\n\n"
            "The only active data source is the delayed public market feed used for analysis. "
            "Execution is disabled in this build."
        )

    if any(word in text for word in ("alert", "notification")):
        return (
            "**Smart Alerts** are created only when a *new* stored signal is directional (BUY or "
            "SELL), meets your minimum strength and quality in Notification settings, and comes from "
            "current — not sample or stale — data. They are capped per day and recorded in "
            "**Signals → Alert history**, so nothing is invented after the fact."
            + (f"\n\nYou currently have **{ctx.alerts_unread}** unread alerts." if ctx.alerts_unread else "")
        )

    if any(word in text for word in ("demo", "balance", "virtual", "slot", "position")):
        return _demo_block(ctx)

    if any(word in text for word in ("how do i", "how to", "navigate", "use the app", "help", "start")):
        return _how_to_block()

    if any(word in text for word in ("risk", "safety", "stop loss", "position size")):
        return _risk_block(ctx)

    if any(word in text for word in (
        "best setup", "best trade", "best signal", "strongest", "highest quality",
        "top setup", "top pick", "rank", "opportunit", "which setup", "compare setups",
    )):
        return _best_setups_block(ctx)

    if any(word in text for word in ("signal", "buy", "sell", "wait", "setup", "trade idea")):
        return _signal_block(ctx)

    for name, explanation in INDICATOR_HELP.items():
        if name in text:
            reading = ""
            if ctx.snapshot is not None:
                snap = ctx.snapshot
                if name == "rsi" and _has(snap.rsi):
                    reading = f"\n\nOn {ctx.symbol or 'this instrument'}, RSI is currently **{snap.rsi:.1f}**."
                elif name == "macd" and _has(snap.macd_hist):
                    reading = f"\n\nOn {ctx.symbol or 'this instrument'}, the MACD histogram is **{snap.macd_hist:+.4f}** ({snap.macd_state.lower()})."
                elif name == "atr" and _has(snap.atr_pct):
                    reading = f"\n\nOn {ctx.symbol or 'this instrument'}, ATR is **{snap.atr_pct:.2f}%** of price."
                elif name == "adx" and _has(snap.adx):
                    reading = f"\n\nOn {ctx.symbol or 'this instrument'}, ADX is **{snap.adx:.1f}** ({snap.adx_state.lower()})."
                elif name == "bollinger" and _has(snap.bb_width):
                    reading = f"\n\nOn {ctx.symbol or 'this instrument'}, Bollinger width is **{snap.bb_width:.2f}%**."
                elif name in {"sma", "ema"} and _has(snap.sma_slow):
                    reading = (
                        f"\n\nOn {ctx.symbol or 'this instrument'}, the slow SMA is **{snap.sma_slow:,.5g}** "
                        f"and the fast EMA is **{snap.ema_fast:,.5g}**."
                    )
            return explanation + reading

    if any(word in text for word in ("market", "condition", "why", "move", "moved", "news")):
        if "why" in text or "move" in text or "news" in text:
            context = _quote_block(ctx)
            return (
                f"{lead}\n\n{context}\n\nI can describe the measured move, but MNZ has **no news "
                "feed**, so I cannot tell you which headline caused it. Anyone who gives you a cause "
                "without a source is guessing."
            )
        return f"{lead}\n\n{_conditions_block(ctx)}"

    # Default: current instrument overview, then the market picture.
    return f"{lead}\n\n{_quote_block(ctx)}\n\n{_conditions_block(ctx)}"


SUGGESTED_QUESTIONS = [
    "Explain the current signal",
    "What is RSI?",
    "How do the demo slots work?",
    "What do the market conditions look like?",
    "Is MT5 connected?",
    "How does the Safety Guard work?",
]
