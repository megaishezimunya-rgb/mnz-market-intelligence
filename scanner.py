"""Market scanner and smart alerts for MNZ BOT.

Scanning fetches real bars for the selected instruments, builds a signal with
:mod:`analysis.signals`, and persists it once per bar. Nothing is scanned for a
market whose feed is unavailable (for example synthetic indices without a Deriv
connection).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

import config
import notifications
from analysis import signals
from data import market_data
from data.market_data import PriceData
from database.database import Database


@dataclass
class ScanResult:
    symbol: str
    name: str
    market: str
    timeframe: str
    signal: signals.Signal | None = None
    data: PriceData | None = None
    error: str = ""
    change_pct: float | None = None
    scanned_at: str = ""

    @property
    def ok(self) -> bool:
        return self.signal is not None and self.data is not None and self.data.ok

    @property
    def label(self) -> str:
        return self.signal.label if self.signal else "WAIT"

    @property
    def quality(self) -> int:
        return self.signal.quality if self.signal else 0

    @property
    def strength(self) -> str:
        return self.signal.strength if self.signal else "Wait"

    @property
    def score(self) -> float:
        return self.signal.score if self.signal else 0.0

    @property
    def price(self) -> float | None:
        return self.signal.price if self.signal else None


def settings_for(market: str) -> config.StrategySettings:
    """Use the market's default strategy structure for signal sizing."""
    return config.ENGINE_STRATEGY_DEFAULTS.get(
        market, config.StrategySettings(fast_ma=50, slow_ma=200)
    )


def scan_symbol(
    symbol: str,
    market: str,
    timeframe: str,
    *,
    allow_sample: bool = False,
    settings: config.StrategySettings | None = None,
    force_refresh: bool = False,
    ttl: int | None = None,
) -> ScanResult:
    instrument = config.instrument_index().get(symbol)
    name = instrument.label if instrument else symbol
    data = market_data.get_timeframe_history(
        symbol, timeframe, allow_sample=allow_sample,
        force_refresh=force_refresh, ttl=ttl,
    )
    if not data.ok:
        return ScanResult(
            symbol=symbol, name=name, market=market, timeframe=timeframe,
            data=data, error=data.error or "No data returned.",
            scanned_at=config.utcnow().isoformat(timespec="seconds"),
        )
    change = None
    if data.bars >= 2:
        previous = float(data.frame["Close"].iloc[-2])
        if previous:
            change = (float(data.last_price) / previous - 1) * 100
    signal = signals.build_signal(
        symbol=symbol, market=market, timeframe=timeframe, data=data,
        settings=settings or settings_for(market),
    )
    return ScanResult(
        symbol=symbol, name=name, market=market, timeframe=timeframe,
        signal=signal, data=data, change_pct=change,
        scanned_at=config.utcnow().isoformat(timespec="seconds"),
    )


def scan_many(
    symbols: list[str],
    market: str,
    timeframe: str,
    *,
    allow_sample: bool = False,
    progress=None,
    pause_seconds: float = 0.15,
    force_refresh: bool = False,
    ttl: int | None = None,
) -> list[ScanResult]:
    """Scan instruments sequentially, tolerating individual failures."""
    results: list[ScanResult] = []
    for index, symbol in enumerate(symbols):
        results.append(scan_symbol(
            symbol, market, timeframe, allow_sample=allow_sample,
            force_refresh=force_refresh, ttl=ttl,
        ))
        if progress is not None:
            progress(index + 1, len(symbols), symbol)
        if pause_seconds and index < len(symbols) - 1:
            time.sleep(pause_seconds)
    return results


def persist_signal(db: Database, user_id: int, signal: signals.Signal) -> tuple[dict | None, bool]:
    """Store a signal once per bar/label combination.

    Returns ``(row, created)``. Re-scans of the same bar do not create duplicates,
    so continuous scanning does not inflate the history.
    """
    last = db.latest_signal_for(user_id, signal.symbol, signal.timeframe)
    if last and last.get("bar_time") == signal.bar_time and last.get("label") == signal.label:
        return last, False
    payload = signal.to_db()
    payload["user_id"] = user_id
    row = db.insert_signal(payload)
    return row, True


# --------------------------------------------------------------------------- #
# Smart alerts
# --------------------------------------------------------------------------- #
def maybe_alert(
    db: Database,
    user_id: int,
    signal_row: dict,
    prefs: dict,
    *,
    timeframe: str,
) -> dict | None:
    """Create an in-app alert for a new, high-quality directional signal.

    Preferences decide whether the signal qualifies. Sample and stale data never
    alert, so the notification history cannot contain invented signals.
    """
    if not prefs.get("enabled", True) or not prefs.get("in_app", True):
        return None
    if signal_row.get("label") not in {"BUY", "SELL"}:
        return None
    if signal_row.get("is_sample") or signal_row.get("data_quality") != "current":
        return None
    allowed = prefs.get("min_strength", config.ALERT_STRENGTHS[1])
    order = {name: index for index, name in enumerate(config.ALERT_STRENGTHS[::-1])}
    if order.get(signal_row.get("strength"), 0) < order.get(allowed, 0):
        return None
    if int(signal_row.get("quality") or 0) < int(prefs.get("min_quality", config.ALERT_MIN_QUALITY)):
        return None
    since = (config.utcnow() - timedelta(days=1)).isoformat(timespec="seconds")
    if db.alerts_since(user_id, since) >= config.ALERT_MAX_PER_DAY:
        return None
    if db.alert_exists(user_id, signal_row["symbol"], signal_row.get("bar_time")):
        return None

    direction = signal_row["label"]
    title = f"{direction} signal · {signal_row['symbol']} · {timeframe}"
    message = (
        f"{signal_row['symbol']} produced a {signal_row.get('strength', '').lower()} {direction} reading "
        f"on {timeframe} at {signal_row['price']:.6g}. Signal quality {signal_row['quality']}/100. "
        f"Simulated TP {signal_row.get('tp')} / SL {signal_row.get('sl')}. "
        "Rule-based reading of delayed data — not advice."
    )
    alert = db.add_alert({
        "user_id": user_id,
        "symbol": signal_row["symbol"],
        "market": signal_row.get("market", ""),
        "kind": "signal",
        "severity": "buy" if direction == "BUY" else "sell",
        "title": title,
        "message": message,
        "signal_id": signal_row.get("id"),
    })
    # Outbound delivery is optional and best-effort; the in-app alert above is
    # already stored, so a delivery failure can never lose it.
    notifications.deliver(alert, prefs)
    return alert


# --------------------------------------------------------------------------- #
# Conditions monitor
# --------------------------------------------------------------------------- #
def market_conditions(results: list[ScanResult]) -> dict:
    """Summarise the scanned set without inventing breadth data."""
    usable = [r for r in results if r.ok]
    if not usable:
        return {
            "scanned": len(results), "usable": 0, "bullish": 0, "bearish": 0, "waiting": 0,
            "avg_quality": 0, "sample": 0, "stale": 0, "label": "No verified data",
        }
    bullish = sum(1 for r in usable if r.label == "BUY")
    bearish = sum(1 for r in usable if r.label == "SELL")
    waiting = sum(1 for r in usable if r.label not in {"BUY", "SELL"})
    qualities = [r.quality for r in usable]
    sample = sum(1 for r in usable if r.signal and r.signal.is_sample)
    stale = sum(1 for r in usable if r.data and r.data.stale)
    net = (bullish - bearish) / len(usable)
    if net >= 0.34:
        label = "Risk-on / constructive"
    elif net <= -0.34:
        label = "Risk-off / defensive"
    else:
        label = "Mixed / indecisive"
    return {
        "scanned": len(results), "usable": len(usable), "bullish": bullish, "bearish": bearish,
        "waiting": waiting, "avg_quality": round(float(np.mean(qualities)), 1),
        "sample": sample, "stale": stale, "label": label, "net": round(net, 3),
    }


def safety_guard(data: PriceData | None, signal_row: dict | None) -> list[dict]:
    """MNZ Safety Guard: explicit checks before a signal is treated as usable."""
    checks: list[dict] = []
    if data is None:
        checks.append({"name": "Data connection", "ok": False, "detail": "No data request has been made."})
        return checks
    checks.append({
        "name": "Provider response",
        "ok": data.ok,
        "detail": "Bars received." if data.ok else (data.error or "No bars returned."),
    })
    checks.append({
        "name": "Real market data",
        "ok": data.ok and not data.is_sample,
        "detail": "Live delayed feed." if not data.is_sample else "SAMPLE data — not real market prices.",
    })
    checks.append({
        "name": "Freshness",
        "ok": not data.stale,
        "detail": data.status_note(),
    })
    checks.append({
        "name": "Simulated targets only",
        "ok": True,
        "detail": "TP/SL are simulated levels. No order is placed anywhere.",
    })
    if signal_row is not None:
        quality = int(signal_row.get("quality") or 0)
        checks.append({
            "name": "Signal quality",
            "ok": quality >= config.ALERT_MIN_QUALITY,
            "detail": f"{quality}/100 (minimum {config.ALERT_MIN_QUALITY} to alert).",
        })
    return checks
