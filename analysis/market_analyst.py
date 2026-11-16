"""MNZ AI Market Analyst.

A transparent, rule-based analyst — not a language model and not advice.  It
combines indicator readings with engine-specific weights, explains every label
in plain language, states its data quality and explicitly reports anything that
is missing, stale or simulated.

Labels are educational:
    BUY BIAS   — the weighted evidence leans constructive
    SELL BIAS  — the weighted evidence leans defensive
    WAIT       — no clear edge, or signals conflict
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from analysis import indicators
from data.market_data import PriceData

BUY_LABEL = "BUY BIAS"
SELL_LABEL = "SELL BIAS"
WAIT_LABEL = "WAIT"
NO_DATA_LABEL = "NO DATA"


@dataclass
class Component:
    name: str
    weight: float
    score: float | None
    included: bool
    reading: str
    detail: str
    kind: str = "direction"  # direction | context


@dataclass
class AnalystReport:
    engine: str
    symbol: str
    label: str
    score: float
    confidence: int
    summary: str
    trend: str
    price: float | None
    change_pct: float | None
    readings: list[dict] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    data_notes: list[str] = field(default_factory=list)
    data_quality: str = "unavailable"
    source: str = ""
    timestamp: str = ""
    is_sample: bool = False
    bars: int = 0

    @property
    def heading(self) -> str:
        return f"{self.label} — {self.symbol}"

    def to_row(self) -> dict:
        return {
            "Symbol": self.symbol,
            "Market": self.engine.title(),
            "Label": self.label,
            "Score": round(self.score, 3),
            "Conviction %": self.confidence,
            "Trend": self.trend,
            "Price": self.price,
            "Change %": self.change_pct,
            "Data": "Sample" if self.is_sample else self.data_quality,
        }


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _fmt(value: float, digits: int = 2, suffix: str = "") -> str:
    if not _finite(value):
        return "n/a"
    return f"{float(value):,.{digits}f}{suffix}"


def _trend_component(snap: indicators.IndicatorSnapshot, weight: float) -> Component:
    if not _finite(snap.trend_score) or snap.bars < 30:
        return Component("Trend structure", weight, None, False, "Insufficient history",
                          "Not enough bars to establish a moving-average structure.")
    detail = (
        f"Price {_fmt(snap.close)} vs fast MA {_fmt(snap.sma_fast)} and slow MA {_fmt(snap.sma_slow)}; "
        f"fast MA is {'above' if snap.sma_fast > snap.sma_slow else 'below'} the slow MA."
        if _finite(snap.sma_fast) and _finite(snap.sma_slow)
        else "Moving averages are still forming."
    )
    return Component("Trend structure", weight, snap.trend_score, True, snap.trend_label, detail)


def _momentum_component(snap: indicators.IndicatorSnapshot, weight: float) -> Component:
    if not _finite(snap.macd_hist):
        return Component("MACD momentum", weight, None, False, "Unavailable",
                          "MACD needs more history at this interval.")
    reading = snap.macd_state
    direction = "above" if snap.macd_hist > 0 else "below"
    detail = (
        f"MACD histogram is {direction} zero ({_fmt(snap.macd_hist, 4)}); "
        f"20-bar rate of change {_fmt(snap.roc_20, 2, '%')}."
    )
    return Component("MACD momentum", weight, snap.momentum_score, True, reading, detail)


def _rsi_component(snap: indicators.IndicatorSnapshot, weight: float) -> Component:
    if not _finite(snap.rsi):
        return Component("RSI", weight, None, False, "Unavailable", "RSI needs more history.")
    value = snap.rsi
    if value >= 70:
        reading = "Overbought"
        detail = f"RSI {value:.0f} is in the overbought zone — a caution for new longs, not a sell signal by itself."
    elif value <= 30:
        reading = "Oversold"
        detail = f"RSI {value:.0f} is oversold — stretched to the downside, which can mean bounce risk or persistent weakness."
    elif value >= 55:
        reading = "Firm"
        detail = f"RSI {value:.0f} shows healthy upside momentum without being stretched."
    elif value <= 45:
        reading = "Soft"
        detail = f"RSI {value:.0f} shows mild downside momentum."
    else:
        reading = "Neutral"
        detail = f"RSI {value:.0f} sits mid-range, giving no directional edge."
    return Component("RSI", weight, snap.rsi_score, True, reading, detail)


def _volume_component(snap: indicators.IndicatorSnapshot, weight: float) -> Component | None:
    if not _finite(snap.volume_ratio):
        return None
    ratio = snap.volume_ratio
    if ratio >= 1.2:
        reading = "Expanding"
    elif ratio <= 0.8:
        reading = "Contracting"
    else:
        reading = "Average"
    detail = f"10-bar volume is {ratio:.2f}x its 50-bar average, which {'confirms' if ratio >= 1.2 else 'does not confirm'} the current move."
    return Component("Volume", weight, snap.volume_score, True, reading, detail)


def _volatility_component(snap: indicators.IndicatorSnapshot, weight: float) -> Component:
    if not _finite(snap.atr_pct):
        return Component("Volatility", weight, None, False, "Unavailable", "ATR could not be computed.", "context")
    detail = (
        f"Average true range is {snap.atr_pct:.2f}% of price (annualised volatility "
        f"{_fmt(snap.annual_vol, 1, '%')}). Wider ranges need smaller simulated positions."
    )
    return Component("Volatility", weight, snap.volatility_score, True, snap.volatility_label, detail, "context")


def _session_component(engine_key: str, weight: float) -> Component | None:
    from engines import base as engine_base

    if engine_key not in {"forex", "commodities"}:
        return None
    active = engine_base.active_sessions()
    reading = ", ".join(active) if active else "Between sessions"
    detail = engine_base.liquidity_note()
    return Component("Session liquidity", weight, 0.0, True, reading, detail, "context")


def _label_for(score: float) -> str:
    if score >= config.BUY_THRESHOLD:
        return BUY_LABEL
    if score <= config.SELL_THRESHOLD:
        return SELL_LABEL
    return WAIT_LABEL


def analyze(
    engine_key: str,
    data: PriceData,
    settings: config.StrategySettings,
    *,
    context=None,
    engine_title: str | None = None,
) -> AnalystReport:
    """Build a complete, explainable analyst report for one instrument."""
    title = engine_title or (context.headline if context and context.headline else engine_key.title())
    fired_at = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")

    if not data.ok:
        report = AnalystReport(
            engine=engine_key,
            symbol=data.symbol,
            label=NO_DATA_LABEL,
            score=0.0,
            confidence=0,
            trend="Unknown",
            price=None,
            change_pct=None,
            summary=(
                "No usable price history was returned for this instrument, so no analytical "
                "label can be produced. MNZ does not estimate prices when data is missing."
            ),
            data_quality="unavailable",
            source=data.source,
            timestamp=fired_at,
            bars=0,
            data_notes=[data.error or "Provider returned no data."],
        )
        report.data_notes.append(config.TIME_SOURCE_NOTE)
        return report

    snap = indicators.snapshot(
        data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
    )
    weights = config.ANALYST_WEIGHTS.get(engine_key, {})

    components: list[Component] = [
        _trend_component(snap, weights.get("trend", 0.35)),
        _momentum_component(snap, weights.get("momentum", 0.25)),
        _rsi_component(snap, weights.get("rsi", 0.15)),
    ]
    volume = _volume_component(snap, weights.get("volume", 0.10))
    if volume:
        components.append(volume)
    components.append(_volatility_component(snap, weights.get("volatility", 0.10)))
    session = _session_component(engine_key, weights.get("session", 0.0))
    if session:
        components.append(session)

    direction = [c for c in components if c.kind == "direction" and c.included and c.score is not None]
    total_weight = sum(c.weight for c in direction)
    score = (
        float(sum(c.score * c.weight for c in direction) / total_weight) if total_weight > 0 else 0.0
    )
    score = float(np.clip(score, -1.0, 1.0))

    # Agreement among direction components, weighted.
    if score > 0:
        agree = sum(c.weight for c in direction if c.score > 0)
    elif score < 0:
        agree = sum(c.weight for c in direction if c.score < 0)
    else:
        agree = sum(c.weight for c in direction if abs(c.score) < 0.05)
    agreement = agree / total_weight if total_weight else 0.0

    quality = data.quality
    quality_multiplier = {"current": 1.0, "delayed": 0.85, "sample": 0.4, "unavailable": 0.0}[quality]
    raw_confidence = (55 + 40 * abs(score)) * (0.6 + 0.4 * agreement)
    if snap.volatility_label == "High":
        raw_confidence *= 0.9
    confidence = int(np.clip(round(raw_confidence * quality_multiplier), 0, 95))

    label = NO_DATA_LABEL if snap.bars < config.MIN_BARS_FOR_ANALYSIS else _label_for(score)
    if label == NO_DATA_LABEL:
        confidence = min(confidence, 20)

    # -- plain-language explanation ----------------------------------------- #
    trend_phrase = snap.trend_label.lower()
    above_below = "above" if _finite(snap.sma_slow) and snap.close > snap.sma_slow else "below"
    rsi_phrase = (
        "overbought" if snap.rsi >= 70 else "oversold" if snap.rsi <= 30
        else "firm" if snap.rsi >= 55 else "soft" if snap.rsi <= 45 else "neutral"
    ) if _finite(snap.rsi) else "unavailable"
    momentum_phrase = (
        "positive" if _finite(snap.macd_hist) and snap.macd_hist > 0
        else "negative" if _finite(snap.macd_hist) else "unavailable"
    )
    sentences = [
        f"{data.symbol} is in a {trend_phrase}, trading {above_below} its {settings.slow_ma}-bar average "
        f"at {_fmt(snap.close)}.",
        f"MACD momentum is {momentum_phrase} and RSI at {_fmt(snap.rsi, 0)} reads {rsi_phrase}.",
        f"Volatility is {snap.volatility_label.lower()} with an average true range of {_fmt(snap.atr_pct, 2, '%')} of price.",
    ]
    if label == BUY_LABEL:
        sentences.append(
            f"The weighted evidence leans constructive, so the educational label is BUY BIAS with {confidence}% conviction."
        )
    elif label == SELL_LABEL:
        sentences.append(
            f"The weighted evidence leans defensive, so the educational label is SELL BIAS with {confidence}% conviction."
        )
    elif label == WAIT_LABEL:
        sentences.append(
            "Signals conflict or the edge is too small to act on, so the educational label is WAIT."
            f" Conviction in that assessment is {confidence}%."
        )
    else:
        sentences.append(
            f"Only {snap.bars} bars are available; at least {config.MIN_BARS_FOR_ANALYSIS} are needed for a meaningful reading."
        )

    reasons = [
        f"Trend: {snap.trend_label} (score {snap.trend_score:+.2f}, weight {weights.get('trend', 0.35):.0%}).",
        f"Momentum: {snap.macd_state} (score {snap.momentum_score:+.2f}, weight {weights.get('momentum', 0.25):.0%}).",
        f"RSI {_fmt(snap.rsi, 0)} — {rsi_phrase} (score {snap.rsi_score:+.2f}, weight {weights.get('rsi', 0.15):.0%}).",
    ]
    if volume:
        reasons.append(f"Volume is {volume.reading.lower()} (score {snap.volume_score:+.2f}, weight {volume.weight:.0%}).")
    reasons.append(
        f"Volatility is {snap.volatility_label.lower()}, which adjusts conviction rather than direction."
    )

    cautions: list[str] = []
    if snap.volatility_label in {"High", "Elevated"}:
        cautions.append(f"Volatility is {snap.volatility_label.lower()}; simulated position sizes should be reduced.")
    if _finite(snap.rsi) and snap.rsi >= 75:
        cautions.append("RSI above 75 means an extended move — chasing here increases risk.")
    if label == WAIT_LABEL:
        cautions.append("A WAIT label is not a prediction of reversal; it means the model has no clear edge.")
    if engine_key == "stocks" and context is not None:
        earnings = (context.extras or {}).get("earnings") if hasattr(context, "extras") else None
        if earnings and earnings.get("available") and earnings.get("next_date"):
            cautions.append("An earnings event could invalidate technical signals with an overnight gap.")
    if engine_key == "crypto":
        cautions.append("Crypto trades 24/7, so signals can change outside traditional market hours.")
    if engine_key == "forex":
        cautions.append("FX signals are sensitive to scheduled central-bank and inflation releases.")

    data_notes = [
        f"Source: {data.source_label}.",
        f"Bars: {data.bars} at {data.interval} interval (period: {data.period}).",
        f"Last bar: {data.last_bar_time.strftime('%Y-%m-%d %H:%M') if data.last_bar_time else 'unknown'}.",
        f"Analysis generated: {fired_at}.",
    ]
    if data.is_sample:
        data_notes.insert(0, "SAMPLE DATA: this is a synthetic offline series, not real market data.")
    if data.stale:
        data_notes.append(f"Data looks stale (last bar {data.age_minutes:.0f} minutes old).")
    if not data.is_sample:
        data_notes.append(config.TIME_SOURCE_NOTE)
    for note in data.notes:
        if note not in data_notes:
            data_notes.append(note)
    if context is not None:
        data_notes.extend(f"Context note: {n}" for n in getattr(context, "notes", [])[:2])

    readings = [
        {"Indicator": "Last price", "Reading": _fmt(snap.close), "Interpretation": "Latest closing price of the most recent bar."},
        {"Indicator": f"Fast MA ({settings.fast_ma})", "Reading": _fmt(snap.sma_fast),
         "Interpretation": "Short-term trend reference."},
        {"Indicator": f"Slow MA ({settings.slow_ma})", "Reading": _fmt(snap.sma_slow),
         "Interpretation": "Medium-term trend reference."},
        {"Indicator": "RSI (14)", "Reading": _fmt(snap.rsi, 1), "Interpretation": "Above 70 overbought, below 30 oversold."},
        {"Indicator": "MACD histogram", "Reading": _fmt(snap.macd_hist, 4), "Interpretation": snap.macd_state},
        {"Indicator": "ATR %", "Reading": _fmt(snap.atr_pct, 2, "%"), "Interpretation": f"Volatility regime: {snap.volatility_label}."},
        {"Indicator": "Volume vs 50-bar avg", "Reading": f"{snap.volume_ratio:.2f}x" if _finite(snap.volume_ratio) else "n/a",
         "Interpretation": "Above 1.0 means recent activity is heavier than usual."},
        {"Indicator": "20-bar rate of change", "Reading": _fmt(snap.roc_20, 2, "%"), "Interpretation": "Recent price change over 20 bars."},
        {"Indicator": "Trend structure", "Reading": snap.trend_label, "Interpretation": "Rule-based moving-average classification."},
    ]

    change_pct = None
    if data.bars >= 2:
        prev = float(data.frame["Close"].iloc[-2])
        if prev:
            change_pct = (float(data.frame["Close"].iloc[-1]) / prev - 1) * 100

    report = AnalystReport(
        engine=engine_key,
        symbol=data.symbol,
        label=label,
        score=score,
        confidence=confidence,
        summary=" ".join(sentences),
        trend=snap.trend_label,
        price=snap.close if _finite(snap.close) else None,
        change_pct=change_pct,
        readings=readings,
        components=components,
        reasons=reasons,
        cautions=cautions,
        data_notes=data_notes,
        data_quality=quality,
        source=data.source_label,
        timestamp=fired_at,
        is_sample=data.is_sample,
        bars=snap.bars,
    )
    report.readings.append({"Indicator": "Engine", "Reading": title, "Interpretation": "Market-specific configuration applied."})
    return report


def summarise(engine_key: str, data_map: dict[str, PriceData], settings: config.StrategySettings) -> pd.DataFrame:
    """Analyse several instruments and return one comparison table."""
    rows = []
    for symbol, data in data_map.items():
        report = analyze(engine_key, data, settings)
        row = report.to_row()
        row["Symbol"] = symbol
        rows.append(row)
    return pd.DataFrame(rows)


def overall_market_view(reports: list[AnalystReport]) -> dict:
    """Aggregate several reports into a single descriptive market view."""
    usable = [r for r in reports if r.label not in {NO_DATA_LABEL}]
    if not usable:
        return {
            "headline": "No analysable data",
            "detail": "No instrument returned enough history for an analytical view.",
            "breadth": 0.0,
        }
    bullish = sum(1 for r in usable if r.label == BUY_LABEL)
    bearish = sum(1 for r in usable if r.label == SELL_LABEL)
    neutral = sum(1 for r in usable if r.label == WAIT_LABEL)
    avg_score = float(np.mean([r.score for r in usable]))
    if avg_score >= config.BUY_THRESHOLD:
        tone = "constructive"
    elif avg_score <= config.SELL_THRESHOLD:
        tone = "defensive"
    else:
        tone = "mixed"
    return {
        "headline": f"Market tone is {tone}",
        "detail": (
            f"Across {len(usable)} analysed instruments: {bullish} buy-biased, {bearish} sell-biased "
            f"and {neutral} on wait. Average weighted score {avg_score:+.2f}."
        ),
        "average_score": avg_score,
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "breadth": bullish / len(usable) * 100,
    }
