"""Signal generation for MNZ BOT.

A signal is a transparent, rule-based reading of the bars that were actually
fetched. It is never a prediction and never invents prices:

* direction comes from weighted indicator components (trend, MACD momentum,
  RSI, market structure);
* strength comes from the weighted score, and is capped by data quality;
* simulated TP/SL levels are ATR multiples of the last close;
* sample or stale data can never produce a BUY/SELL label; it becomes WAIT with
  an explicit reason;
* outcomes are measured later against real subsequent bars (TP/SL first touch).

Labels: BUY, SELL, WAIT.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
from analysis import indicators
from data.market_data import PriceData

BUY = "BUY"
SELL = "SELL"
WAIT = "WAIT"

STRENGTH_STRONG = "Strong"
STRENGTH_MODERATE = "Moderate"
STRENGTH_WEAK = "Weak"


@dataclass
class Signal:
    """One signal reading for an instrument and timeframe."""

    symbol: str
    market: str
    timeframe: str
    label: str
    price: float
    score: float
    quality: int
    strength: str
    entry_ref: float | None
    tp: float | None
    sl: float | None
    explanation: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    data_quality: str = "unavailable"
    source: str = ""
    is_sample: bool = False
    bar_time: str | None = None
    created_at: str | None = None
    status: str = "Open"
    outcome: str = ""
    outcome_price: float | None = None
    outcome_at: str | None = None
    id: int | None = None

    @property
    def actionable(self) -> bool:
        return self.label in {BUY, SELL} and not self.is_sample and self.data_quality == "current"

    @property
    def risk_reward(self) -> float | None:
        if self.tp is None or self.sl is None or self.entry_ref is None:
            return None
        risk = abs(self.entry_ref - self.sl)
        reward = abs(self.tp - self.entry_ref)
        return reward / risk if risk else None

    def to_db(self) -> dict:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "label": self.label,
            "timeframe": self.timeframe,
            "price": self.price,
            "entry_ref": self.entry_ref,
            "tp": self.tp,
            "sl": self.sl,
            "strength": self.strength,
            "quality": self.quality,
            "score": self.score,
            "explanation": self.explanation,
            "metrics": self.metrics,
            "data_quality": self.data_quality,
            "source": self.source,
            "is_sample": self.is_sample,
            "bar_time": self.bar_time,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Signal":
        try:
            metrics = json.loads(row.get("metrics_json") or "{}")
        except (TypeError, ValueError):
            metrics = {}
        return cls(
            id=row.get("id"),
            symbol=row["symbol"],
            market=row.get("market", ""),
            timeframe=row.get("timeframe", config.DEFAULT_TIMEFRAME),
            label=row["label"],
            price=float(row["price"]),
            score=float(row.get("score") or 0.0),
            quality=int(row.get("quality") or 0),
            strength=row.get("strength", STRENGTH_WEAK),
            entry_ref=row.get("entry_ref"),
            tp=row.get("tp"),
            sl=row.get("sl"),
            explanation=row.get("explanation", ""),
            reasons=list(metrics.get("reasons", [])) if isinstance(metrics, dict) else [],
            warnings=list(metrics.get("warnings", [])) if isinstance(metrics, dict) else [],
            metrics=metrics if isinstance(metrics, dict) else {},
            data_quality=row.get("data_quality", "unavailable"),
            source=row.get("source", ""),
            is_sample=bool(row.get("is_sample")),
            bar_time=row.get("bar_time"),
            created_at=row.get("created_at"),
            status=row.get("status", "Open"),
            outcome=row.get("outcome") or "",
            outcome_price=row.get("outcome_price"),
            outcome_at=row.get("outcome_at"),
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def round_price(value: float | None) -> float | None:
    if value is None or not _finite(value):
        return None
    magnitude = abs(float(value))
    if magnitude >= 1000:
        return round(float(value), 2)
    if magnitude >= 10:
        return round(float(value), 3)
    return round(float(value), 5)


def _structure_score(snap: indicators.IndicatorSnapshot) -> float:
    """Directional structure from DI spread and price distance from the slow MA."""
    if not _finite(snap.adx) or not _finite(snap.plus_di) or not _finite(snap.minus_di):
        return 0.0
    denominator = (snap.plus_di + snap.minus_di) or 1.0
    di_spread = float(np.clip((snap.plus_di - snap.minus_di) / denominator, -1, 1))
    # ADX scales conviction: a weak trend contributes less structure signal.
    trend_weight = float(np.clip((snap.adx - 12) / 25.0, 0.0, 1.0))
    ma_distance = 0.0
    if _finite(snap.sma_slow) and _finite(snap.atr) and snap.atr:
        ma_distance = float(np.tanh((snap.close - snap.sma_slow) / (snap.atr * 2.0)))
    return float(np.clip((0.6 * di_spread + 0.4 * ma_distance) * trend_weight, -1, 1))


def _confirmations(components: dict[str, float], direction: int) -> tuple[list[str], list[str]]:
    """Split components into those supporting ``direction`` and those opposing it.

    A component only counts as evidence when it is finite and at least
    ``SIGNAL_CONFIRMATION_FLOOR`` in magnitude, so a near-zero reading is treated
    as no opinion rather than a confirmation.
    """
    supporting: list[str] = []
    opposing: list[str] = []
    if direction == 0:
        return supporting, opposing
    for name, value in components.items():
        if not _finite(value) or abs(float(value)) < config.SIGNAL_CONFIRMATION_FLOOR:
            continue
        if (float(value) > 0) == (direction > 0):
            supporting.append(name)
        else:
            opposing.append(name)
    return supporting, opposing


def _agreement(components: dict[str, float], weights: dict[str, float]) -> float:
    weighted = [abs(weights[key] * value) for key, value in components.items() if _finite(value)]
    total = sum(weighted)
    if total <= 0:
        return 0.0
    net = abs(sum(weights[key] * value for key, value in components.items() if _finite(value)))
    return float(np.clip(net / total, 0, 1))


def _quality(
    snap: indicators.IndicatorSnapshot,
    data: PriceData,
    components: dict[str, float],
    weights: dict[str, float],
    score: float,
    *,
    confirmations: int = 0,
    adx_weak: bool = False,
    higher_aligned: bool = False,
) -> int:
    agreement = _agreement(components, weights)
    quality = 35 + 40 * agreement + 25 * min(abs(score) / 0.6, 1.0)
    # Reward broad agreement and mark the minimum-evidence case down.
    if confirmations >= 3:
        quality += 5
    elif confirmations == config.SIGNAL_MIN_CONFIRMATIONS:
        quality -= 5
    if adx_weak:
        quality -= 8
    if higher_aligned:
        quality += 4
    if snap.bars < 120:
        quality -= 8
    if snap.volatility_label == "High":
        quality -= 10
    elif snap.volatility_label == "Elevated":
        quality -= 4
    if data.stale:
        quality -= 25
    if data.is_sample:
        quality = min(quality, 30)
    if not data.ok:
        quality = 0
    return int(max(0, min(100, round(quality))))


def _strength(label: str, quality: int, score: float) -> str:
    if label == WAIT:
        return "Wait"
    magnitude = abs(score)
    if quality >= 70 and magnitude >= 0.45:
        return STRENGTH_STRONG
    if quality >= 55 and magnitude >= 0.30:
        return STRENGTH_MODERATE
    return STRENGTH_WEAK


def _targets(label: str, price: float, atr_value: float | None) -> tuple[float | None, float | None]:
    if label == WAIT:
        return None, None
    distance = None
    if atr_value and _finite(atr_value) and atr_value > 0:
        distance = float(atr_value) * config.SIGNAL_SL_ATR
    distance = max(distance or price * 0.0025, price * 0.0008)
    if label == BUY:
        return round_price(price + distance * (config.SIGNAL_TP_ATR / config.SIGNAL_SL_ATR)), round_price(price - distance)
    return round_price(price - distance * (config.SIGNAL_TP_ATR / config.SIGNAL_SL_ATR)), round_price(price + distance)


# One step up from the scanned timeframe, built from the bars already fetched.
_HIGHER_RULES: dict[str, str | None] = {
    "M1": "5min", "M5": "30min", "M15": "1h", "M30": "4h",
    "H1": "1D", "H4": "1D", "D1": "1W",
}
_HIGHER_LABELS = {
    "M1": "M5", "M5": "M30", "M15": "H1", "M30": "H4",
    "H1": "D1", "H4": "D1", "D1": "W1",
}


def _resample_frame(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate the loaded bars to a coarser rule, without another request."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    try:
        out = frame.resample(rule, label="right", closed="right").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        })
    except (TypeError, ValueError):
        return pd.DataFrame()
    return out.dropna(subset=["Close"])


def _higher_trend(data: PriceData, timeframe: str) -> float:
    """Trend score of the next timeframe up, or NaN when there is too little."""
    rule = _HIGHER_RULES.get(timeframe)
    if not rule:
        return float("nan")
    frame = _resample_frame(data.frame, rule)
    if frame.empty or len(frame) < 30:
        return float("nan")
    snap = indicators.snapshot(frame, fast=20, slow=50, long_window=100)
    return float(snap.trend_score) if _finite(snap.trend_score) else float("nan")


def _higher_state(higher_score: float, direction: int) -> str:
    """``aligned``, ``against``, ``neutral`` or ``unavailable`` for a direction."""
    if direction == 0 or not _finite(higher_score):
        return "unavailable" if not _finite(higher_score) else "neutral"
    value = float(higher_score)
    if abs(value) < 0.2:
        return "neutral"
    return "aligned" if (value > 0) == (direction > 0) else "against"


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None or not _finite(value):
        return "n/a"
    return f"{float(value):,.{digits}f}{suffix}"


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #
def build_signal(
    *,
    symbol: str,
    market: str,
    timeframe: str,
    data: PriceData,
    settings: config.StrategySettings,
) -> Signal:
    """Compute a signal from the supplied bars."""
    now = config.utcnow().isoformat(timespec="seconds")
    bar_time = data.last_bar_time.isoformat(timespec="seconds") if data.last_bar_time else None
    base = dict(
        symbol=symbol, market=market, timeframe=timeframe, price=data.last_price or 0.0,
        created_at=now, bar_time=bar_time, source=data.source_label,
        is_sample=data.is_sample, data_quality=data.quality,
    )

    if not data.ok or data.last_price is None:
        return Signal(
            label=WAIT, score=0.0, quality=0, strength="Wait", entry_ref=None, tp=None, sl=None,
            explanation="No verified price history is available, so no signal is produced.",
            reasons=["The data provider returned no usable bars for this instrument."],
            warnings=[data.error or "Data unavailable."],
            metrics={"error": data.error}, status="No data", **base,
        )

    snap = indicators.snapshot(
        data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
    )
    weights = config.SIGNAL_WEIGHTS.get(market, config.SIGNAL_WEIGHTS["default"])
    components = {
        "trend": snap.trend_score,
        "momentum": snap.momentum_score,
        "rsi": snap.rsi_score,
        "structure": _structure_score(snap),
    }
    score = float(np.clip(sum(weights[key] * components[key] for key in components), -1, 1))

    warnings: list[str] = []
    reasons: list[str] = []
    label = WAIT
    direction = 1 if score >= config.SIGNAL_BUY_THRESHOLD else -1 if score <= config.SIGNAL_SELL_THRESHOLD else 0
    supporting, opposing = _confirmations(components, direction)
    higher_score = _higher_trend(data, timeframe)
    higher_state = _higher_state(higher_score, direction)
    adx_weak = _finite(snap.adx) and float(snap.adx) < config.SIGNAL_RANGE_ADX
    threshold = max(
        abs(config.SIGNAL_BUY_THRESHOLD),
        config.SIGNAL_RANGE_THRESHOLD if adx_weak else 0.0,
    )
    if snap.bars < config.SIGNAL_MIN_BARS:
        warnings.append(
            f"Only {snap.bars} bars are available; at least {config.SIGNAL_MIN_BARS} are needed."
        )
    elif data.is_sample:
        warnings.append("Offline sample data — this reading is a demonstration, not the market.")
    elif data.stale:
        warnings.append("The last bar is older than expected for this timeframe; treat the reading as delayed.")
    elif direction and abs(score) >= threshold:
        if len(supporting) < config.SIGNAL_MIN_CONFIRMATIONS:
            warnings.append(
                f"Only {len(supporting)} indicator component(s) support a {'BUY' if direction > 0 else 'SELL'} "
                f"reading; {config.SIGNAL_MIN_CONFIRMATIONS} are required, so this is WAIT."
            )
        elif higher_state == "against":
            warnings.append(
                f"The higher timeframe disagrees: its trend score is {higher_score:+.2f} against "
                f"this {'bullish' if direction > 0 else 'bearish'} reading, so this is WAIT."
            )
        else:
            label = BUY if direction > 0 else SELL
    elif direction and adx_weak:
        warnings.append(
            f"The score pointed {'up' if direction > 0 else 'down'}, but ADX is {snap.adx:.1f} "
            f"(below {config.SIGNAL_RANGE_ADX:.0f}), so the market is ranging. This reading needs "
            f"|score| ≥ {config.SIGNAL_RANGE_THRESHOLD:.2f} in a range and is WAIT."
        )

    quality = _quality(
        snap, data, components, weights, score,
        confirmations=len(supporting), adx_weak=adx_weak,
        higher_aligned=higher_state == "aligned",
    )
    strength = _strength(label, quality, score)
    tp, sl = _targets(label, float(data.last_price), snap.atr)

    # Explanations are generated from the measured values only.
    reasons.append(f"Trend structure reads {snap.trend_label.lower()} (score {snap.trend_score:+.2f}).")
    if _finite(snap.macd_hist):
        reasons.append(
            f"MACD histogram is {'positive' if snap.macd_hist > 0 else 'negative'} "
            f"({snap.macd_hist:+.4f}), and 20-bar momentum is {_fmt(snap.roc_20, 2, '%')}."
        )
    if _finite(snap.rsi):
        reasons.append(f"RSI(14) is {snap.rsi:.1f}, which the rule set reads as {_rsi_words(snap.rsi)}.")
    if _finite(snap.adx):
        reasons.append(f"ADX is {snap.adx:.1f} — {snap.adx_state.lower()}.")
    if _finite(snap.atr_pct):
        reasons.append(f"ATR is {snap.atr_pct:.2f}% of price, a {snap.volatility_label.lower()} volatility regime.")
    if direction:
        reasons.append(
            f"{len(supporting)} of {len(components)} indicator components agree with the "
            f"{'bullish' if direction > 0 else 'bearish'} score"
            + (f" ({', '.join(supporting)})" if supporting else "")
            + (f"; {', '.join(opposing)} disagree." if opposing else ".")
        )
    if _finite(higher_score):
        reasons.append(
            f"The {_HIGHER_LABELS.get(timeframe, 'higher')} trend reads "
            f"{higher_score:+.2f}, which is {higher_state} with this reading."
        )

    if label == BUY:
        summary = (
            f"Weighted evidence is constructive ({score:+.2f}). The last close is {_fmt(data.last_price)}, "
            f"with a reference stop at {_fmt(sl)} and simulated target at {_fmt(tp)}."
        )
    elif label == SELL:
        summary = (
            f"Weighted evidence is defensive ({score:+.2f}). The last close is {_fmt(data.last_price)}, "
            f"with a reference stop at {_fmt(sl)} and simulated target at {_fmt(tp)}."
        )
    elif snap.bars < config.SIGNAL_MIN_BARS:
        summary = "Not enough history to compute a signal. No direction is assigned."
    elif direction and abs(score) >= threshold and len(supporting) < config.SIGNAL_MIN_CONFIRMATIONS:
        summary = (
            f"The weighted score is {score:+.2f}, but only {len(supporting)} indicator component(s) "
            f"agree with it. {config.SIGNAL_MIN_CONFIRMATIONS} independent components must agree "
            "before a direction is published, so the reading is WAIT."
        )
    elif direction and abs(score) >= threshold:
        summary = (
            f"The weighted score is {score:+.2f} on {timeframe}, but the "
            f"{_HIGHER_LABELS.get(timeframe, 'higher')} trend is leaning the other way "
            f"({higher_score:+.2f}). MNZ does not publish a signal that fights the higher "
            "timeframe, so the reading is WAIT."
        )
    elif direction and adx_weak:
        summary = (
            f"The weighted score is {score:+.2f}, but ADX is {snap.adx:.1f} — the market is ranging. "
            f"In a range the same score is weaker evidence, so a direction needs |score| ≥ "
            f"{config.SIGNAL_RANGE_THRESHOLD:.2f}; this is WAIT."
        )
    else:
        summary = (
            f"No clear edge: the weighted score ({score:+.2f}) is inside the "
            f"±{threshold:.2f} threshold, so the reading is WAIT."
        )

    if data.is_sample:
        summary += " This is SAMPLE data, so the WAIT label is mandatory and the signal is not actionable."

    metrics = {
        "components": components,
        "weights": weights,
        "confirmations": len(supporting),
        "supporting": supporting,
        "opposing": opposing,
        "threshold": round(threshold, 3),
        "adx_weak": adx_weak,
        "higher_timeframe": _HIGHER_LABELS.get(timeframe, ""),
        "higher_trend": round(higher_score, 3) if _finite(higher_score) else None,
        "higher_alignment": higher_state,
        "bars": snap.bars,
        "rsi": snap.rsi,
        "adx": snap.adx,
        "atr_pct": snap.atr_pct,
        "trend": snap.trend_label,
        "volatility": snap.volatility_label,
        "volume_ratio": snap.volume_ratio,
        "reasons": reasons,
        "warnings": warnings,
        "quality_inputs": {
            "agreement": round(_agreement(components, weights), 3),
            "confirmations": len(supporting),
            "adx_weak": adx_weak,
            "stale": data.stale,
            "sample": data.is_sample,
        },
    }
    return Signal(
        label=label, score=round(score, 4), quality=quality, strength=strength,
        entry_ref=round_price(float(data.last_price)), tp=tp, sl=sl,
        explanation=summary, reasons=reasons, warnings=warnings, metrics=metrics,
        status="Open" if label in {BUY, SELL} else "No trade",
        **base,
    )


def _rsi_words(value: float) -> str:
    if value >= 70:
        return "overbought (caution on new longs)"
    if value >= 55:
        return "constructive momentum"
    if value >= 45:
        return "neutral"
    if value >= 30:
        return "soft momentum"
    return "oversold"


# --------------------------------------------------------------------------- #
# Trade plan: what to do now, and for how long
# --------------------------------------------------------------------------- #
def _level(value: float | None) -> str:
    """A stored price at the precision the signal recorded it with."""
    rounded = round_price(value)
    return "n/a" if rounded is None else f"{rounded:,}"


def _stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def valid_until(row: dict) -> datetime | None:
    """When the reading stops being a plan for the coming bars.

    A signal is published against one timeframe, so its window is a fixed
    number of bars of that same timeframe (``config.SIGNAL_VALID_BARS``).
    """
    anchor = _stamp(row.get("created_at")) or _stamp(row.get("bar_time"))
    if anchor is None:
        return None
    horizon = config.SIGNAL_VALID_BARS * config.timeframe(row.get("timeframe")).minutes
    return anchor + timedelta(minutes=horizon)


def plan(row: dict, *, now: datetime | None = None) -> dict:
    """The stored reading as an instruction: side, entry, stop, target, window.

    Built only from values already stored on the signal — no new prices and no
    new direction. ``state`` is ``actionable`` (follow the plan now),
    ``waiting`` (no trade), ``expired`` (window closed: rescan) or ``closed``
    (the simulated target or stop was already reached).
    """
    now = now or config.utcnow()
    label = row.get("label") or WAIT
    entry = row.get("entry_ref")
    stop = row.get("sl")
    target = row.get("tp")
    expires = valid_until(row)
    countdown = ""
    if expires is not None:
        left = max(0, int((expires - now).total_seconds() // 60))
        countdown = f"{left // 60}h {left % 60:02d}m" if left >= 60 else f"{left}m"

    risk_reward = None
    if entry is not None and stop is not None and target is not None:
        risk = abs(float(entry) - float(stop))
        risk_reward = abs(float(target) - float(entry)) / risk if risk else None

    outcome = row.get("outcome") or ""
    status = row.get("status") or "Open"
    if label not in {BUY, SELL}:
        state, action = "waiting", "Wait"
        summary = "No trade: the reading is WAIT, so there is no entry, stop or target to follow."
    elif outcome or status in {"Closed", "Unresolved"}:
        state, action = "closed", "Done"
        result = outcome or ("ambiguous — TP and SL touched in the same bar"
                             if status == "Unresolved" else "outcome recorded")
        summary = f"Closed — {result}. Nothing left to do on this plan."
    elif entry is None or stop is None or target is None:
        state, action = "waiting", "Wait"
        summary = "No levels were stored for this reading, so it is not a usable plan."
    elif expires is not None and now >= expires:
        state, action = "expired", "Rescan"
        summary = (
            f"Expired — this plan is older than {config.SIGNAL_VALID_BARS} "
            f"{row.get('timeframe') or config.DEFAULT_TIMEFRAME} bars. Ignore the levels and "
            "run a fresh scan."
        )
    else:
        state = "actionable"
        action = "Buy" if label == BUY else "Sell"
        summary = (
            f"{action} near {_level(entry)}, stop at {_level(stop)}, "
            f"target at {_level(target)}."
        )
    return {
        "action": action,
        "state": state,
        "label": label,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_reward": risk_reward,
        # A window only means something for a trade that can still be taken.
        "valid_until": expires if label in {BUY, SELL} else None,
        "countdown": countdown if label in {BUY, SELL} else "",
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# Outcome measurement
# --------------------------------------------------------------------------- #
def evaluate_outcome(signal: Signal | dict, data: PriceData) -> dict | None:
    """Measure a signal against subsequent bars (TP/SL first touch).

    Returns ``None`` when the signal is WAIT/No trade or price has not yet
    reached either level. Outcomes are never inferred when both levels are
    touched inside the same bar — that case is reported as unresolved.
    """
    row = signal.to_db() if isinstance(signal, Signal) else signal
    label = row.get("label")
    if label not in {BUY, SELL}:
        return None
    tp, sl = row.get("tp"), row.get("sl")
    if tp is None or sl is None or data is None or not data.ok:
        return None
    try:
        start = pd.Timestamp(row.get("bar_time") or row.get("created_at") or "")
    except (TypeError, ValueError):
        return None
    frame = data.frame
    if frame.empty:
        return None
    later = frame[frame.index > start]
    if later.empty:
        return None
    for stamp, bar in later.iterrows():
        hit_tp = float(bar["High"]) >= float(tp) if label == BUY else float(bar["Low"]) <= float(tp)
        hit_sl = float(bar["Low"]) <= float(sl) if label == BUY else float(bar["High"]) >= float(sl)
        if hit_tp and hit_sl:
            return {
                "status": "Unresolved",
                "outcome": "Ambiguous bar (both levels touched)",
                "outcome_price": None,
                "outcome_at": stamp.isoformat(timespec="seconds"),
            }
        if hit_tp:
            return {
                "status": "Closed", "outcome": "TP hit", "outcome_price": float(tp),
                "outcome_at": stamp.isoformat(timespec="seconds"),
            }
        if hit_sl:
            return {
                "status": "Closed", "outcome": "SL hit", "outcome_price": float(sl),
                "outcome_at": stamp.isoformat(timespec="seconds"),
            }
    return None


def outcome_status_label(row: dict) -> str:
    if row.get("label") not in {BUY, SELL}:
        return "No trade"
    status = row.get("status") or "Open"
    if status == "Closed":
        return row.get("outcome") or "Closed"
    if status == "Unresolved":
        return row.get("outcome") or "Unresolved"
    return "Open / pending"


def r_multiple(row: dict) -> float | None:
    """Signed R multiple of a resolved signal (TP = +reward/risk, SL = −1).

    Returns ``None`` when the row is unresolved or the levels are unusable, so
    averages never silently treat a pending signal as a loss.
    """
    if row.get("status") != "Closed" or row.get("outcome") not in {"TP hit", "SL hit"}:
        return None
    try:
        entry = float(row["entry_ref"])
        tp = float(row["tp"])
        sl = float(row["sl"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    if row["outcome"] == "TP hit":
        return abs(tp - entry) / risk
    return -1.0


def quality_band(quality: int) -> str:
    """Coarse quality bucket used for performance breakdowns."""
    if quality >= 90:
        return "90–100"
    if quality >= 75:
        return "75–89"
    if quality >= 60:
        return "60–74"
    return "Below 60"


def _breakdown(closed: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in closed:
        groups.setdefault(str(row.get(key) or "—"), []).append(row)
    out: list[dict] = []
    for name, members in groups.items():
        r_values = [value for value in (r_multiple(row) for row in members) if value is not None]
        wins = sum(value > 0 for value in r_values)
        out.append({
            "name": name,
            "resolved": len(members),
            "hit_rate": wins / len(members) * 100 if members else float("nan"),
            "avg_r": float(np.mean(r_values)) if r_values else float("nan"),
        })
    return sorted(out, key=lambda item: (-item["resolved"], item["name"]))


def _bucket_metrics(members: list[dict]) -> dict:
    """Hit rate, expectancy and profit factor for resolved signals in a group."""
    r_values = [value for value in (r_multiple(row) for row in members) if value is not None]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    return {
        "resolved": len(r_values),
        "tp_hits": len(wins),
        "sl_hits": len(losses),
        "hit_rate": (len(wins) / len(r_values) * 100) if r_values else float("nan"),
        "expectancy_r": float(np.mean(r_values)) if r_values else float("nan"),
        "profit_factor": (
            sum(wins) / abs(sum(losses)) if losses and sum(losses) else float("nan")
        ),
    }


def calibration(rows: list[dict], *, min_sample: int | None = None) -> dict:
    """Measure this account's own signals by market, timeframe and quality band.

    Only signals whose simulated TP or SL was actually reached are counted, so a
    pending or ambiguous signal can never improve or damage the record. Groups
    smaller than ``min_sample`` are returned with ``reliable=False`` instead of
    being hidden or presented as an edge.
    """
    threshold = int(min_sample if min_sample is not None else config.CALIBRATION_MIN_SAMPLE)
    resolved_rows = [
        row for row in rows
        if row.get("status") == "Closed" and row.get("outcome") in {"TP hit", "SL hit"}
    ]
    directional = [row for row in rows if row.get("label") in {BUY, SELL}]

    def group(key: str, order: list[str] | None = None) -> list[dict]:
        buckets: dict[str, list[dict]] = {}
        for row in resolved_rows:
            if key == "quality":
                name = quality_band(int(row.get("quality") or 0))
            else:
                name = str(row.get(key) or "—")
            buckets.setdefault(name, []).append(row)
        names = order if order is not None else sorted(buckets, key=lambda item: (-len(buckets[item]), item))
        out: list[dict] = []
        for name in names:
            members = buckets.get(name) or []
            if not members:
                continue
            item = {"name": name, **_bucket_metrics(members)}
            item["reliable"] = item["resolved"] >= threshold
            out.append(item)
        return out

    overall = _bucket_metrics(resolved_rows)
    return {
        "signals": len(rows),
        "directional": len(directional),
        "resolved": overall["resolved"],
        "min_sample": threshold,
        "overall": overall,
        "by_market": group("market"),
        "by_timeframe": group("timeframe"),
        "by_quality": group("quality", order=["90–100", "75–89", "60–74", "Below 60"]),
        "note": (
            "Hit rate counts signals whose simulated TP was reached before the simulated SL. "
            "Expectancy is the average R per resolved signal (TP near +1.7R at the default "
            "ATR targets, SL exactly −1R). Groups below the minimum sample are indicative only."
        ),
    }


def signal_performance(rows: list[dict]) -> dict:
    """Historical performance of stored signals, counting only resolved ones.

    ``avg_r`` and ``expectancy_r`` are measured in units of the simulated risk
    (entry to stop), so they are comparable across instruments and timeframes.
    """
    closed = [row for row in rows if row.get("status") == "Closed"]
    tp = [row for row in closed if row.get("outcome") == "TP hit"]
    sl = [row for row in closed if row.get("outcome") == "SL hit"]
    directional = [row for row in rows if row.get("label") in {BUY, SELL}]
    r_values = [value for value in (r_multiple(row) for row in closed) if value is not None]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    bands = {band: [] for band in ["90–100", "75–89", "60–74", "Below 60"]}
    for row in closed:
        bands[quality_band(int(row.get("quality") or 0))].append(row)
    quality_rows = []
    for band, members in bands.items():
        if not members:
            continue
        band_r = [value for value in (r_multiple(row) for row in members) if value is not None]
        quality_rows.append({
            "name": band,
            "resolved": len(members),
            "hit_rate": sum(value > 0 for value in band_r) / len(members) * 100,
            "avg_r": float(np.mean(band_r)) if band_r else float("nan"),
        })
    return {
        "signals": len(rows),
        "directional": len(directional),
        "resolved": len(closed),
        "tp_hits": len(tp),
        "sl_hits": len(sl),
        "open": len([row for row in rows if (row.get("status") or "Open") == "Open"]),
        "hit_rate": (len(tp) / len(closed) * 100) if closed else float("nan"),
        "avg_r": float(np.mean(r_values)) if r_values else float("nan"),
        "expectancy_r": float(np.mean(r_values)) if r_values else float("nan"),
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else float("nan"),
        "sample_size": len(r_values),
        "breakdown": {
            "timeframe": _breakdown(closed, "timeframe"),
            "instrument": _breakdown(closed, "symbol"),
            "quality": quality_rows,
        },
        "note": (
            "Measured from stored signals against subsequent provider bars; unresolved "
            "signals are excluded. R = reward ÷ simulated risk (entry to stop)."
        ),
    }
