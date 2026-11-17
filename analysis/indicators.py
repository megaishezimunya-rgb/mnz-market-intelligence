"""Technical indicators and indicator summary objects.

Pure Pandas/NumPy implementations so the project has no compiled dependency and
every calculation is testable.  All functions tolerate short or missing series
and return NaN rather than raising.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Primitive indicators
# --------------------------------------------------------------------------- #
def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=max(int(window), 1), min_periods=max(int(window), 1)).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (adjust=False, i.e. recursive)."""
    return series.ewm(span=max(int(span), 1), adjust=False, min_periods=max(int(span), 1)).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index, scaled 0–100."""
    period = max(int(period), 2)
    if series.empty:
        return pd.Series(dtype=float)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    values = 100 - (100 / (1 + rs))
    values = values.where(avg_loss != 0, 100.0)
    values = values.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return values


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal line and histogram."""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    line = fast_ema - slow_ema
    signal_line = line.ewm(span=max(int(signal), 1), adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": signal_line, "hist": line - signal_line})


def true_range(frame: pd.DataFrame) -> pd.Series:
    """True range from an OHLC frame."""
    if frame.empty:
        return pd.Series(dtype=float)
    high, low, close = frame["High"], frame["Low"], frame["Close"]
    prev_close = close.shift(1)
    ranges = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    period = max(int(period), 2)
    return true_range(frame).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Bollinger bands and normalised width."""
    mid = sma(series, window)
    std = series.rolling(window=max(int(window), 1), min_periods=max(int(window), 1)).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0.0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "width": width})


def stochastic(frame: pd.DataFrame, period: int = 14, smooth: int = 3) -> pd.Series:
    """Stochastic %K, smoothed."""
    if frame.empty:
        return pd.Series(dtype=float)
    low = frame["Low"].rolling(period, min_periods=period).min()
    high = frame["High"].rolling(period, min_periods=period).max()
    span = (high - low).replace(0.0, np.nan)
    k = 100 * (frame["Close"] - low) / span
    return k.rolling(max(int(smooth), 1), min_periods=1).mean()


def adx(frame: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder's Average Directional Index with +DI and -DI.

    ADX measures trend *strength* (not direction): readings above ~25 indicate a
    trending market, below ~20 a range.
    """
    period = max(int(period), 2)
    if frame is None or frame.empty or not {"High", "Low", "Close"} <= set(frame.columns):
        return pd.DataFrame(columns=["adx", "plus_di", "minus_di"])
    high, low = frame["High"].astype(float), frame["Low"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index
    )
    atr_series = true_range(frame).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    atr_safe = atr_series.replace(0.0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_series = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"adx": adx_series, "plus_di": plus_di, "minus_di": minus_di})


def roc(series: pd.Series, period: int = 20) -> pd.Series:
    """Rate of change in percent."""
    shifted = series.shift(max(int(period), 1))
    return (series / shifted.replace(0.0, np.nan) - 1.0) * 100.0


def returns(series: pd.Series) -> pd.Series:
    """Simple period returns."""
    return series.pct_change().replace([np.inf, -np.inf], np.nan)


def bars_per_year(index: pd.Index) -> float:
    """Estimate annualisation factor from the median bar spacing."""
    if len(index) < 3:
        return 252.0
    deltas = pd.Series(index).diff().dropna().dt.total_seconds()
    median = float(deltas.median()) if len(deltas) else 0.0
    if median <= 0:
        return 252.0
    # Daily/weekly/monthly bars trade on business calendars, so annualise with the
    # conventional trading-period counts rather than raw calendar time.
    if 20 * 3600 <= median <= 3 * 86400:
        return 252.0
    if 5 * 86400 <= median <= 9 * 86400:
        return 52.0
    if median >= 25 * 86400:
        return 12.0
    return float(np.clip(365.25 * 24 * 3600 / median, 12, 365 * 24 * 60))


def annualized_volatility(series: pd.Series, periods_per_year: float | None = None) -> float:
    """Annualised standard deviation of returns, in percent."""
    rets = returns(series).dropna()
    if len(rets) < 5:
        return float("nan")
    factor = periods_per_year if periods_per_year else bars_per_year(series.index)
    return float(rets.std(ddof=1) * np.sqrt(factor) * 100)


def rolling_drawdown(equity: pd.Series) -> pd.Series:
    """Drawdown from running peak, in percent (<= 0)."""
    if equity.empty:
        return pd.Series(dtype=float)
    peak = equity.cummax()
    return (equity / peak.replace(0.0, np.nan) - 1.0) * 100.0


def max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough decline, in percent (> 0)."""
    series = pd.Series(equity).dropna()
    if series.empty:
        return 0.0
    dd = rolling_drawdown(series)
    worst = dd.min()
    return float(abs(worst)) if pd.notna(worst) else 0.0


# --------------------------------------------------------------------------- #
# Summary snapshot
# --------------------------------------------------------------------------- #
@dataclass
class IndicatorSnapshot:
    """Last-value readings plus rule-based component scores in [-1, 1]."""

    bars: int = 0
    close: float = float("nan")
    sma_fast: float = float("nan")
    sma_slow: float = float("nan")
    sma_long: float = float("nan")
    ema_fast: float = float("nan")
    ema_slow: float = float("nan")
    rsi: float = float("nan")
    macd: float = float("nan")
    macd_signal: float = float("nan")
    macd_hist: float = float("nan")
    macd_hist_atr: float = float("nan")
    atr: float = float("nan")
    atr_pct: float = float("nan")
    bb_width: float = float("nan")
    adx: float = float("nan")
    plus_di: float = float("nan")
    minus_di: float = float("nan")
    volume_ratio: float = float("nan")
    roc_20: float = float("nan")
    return_5: float = float("nan")
    return_20: float = float("nan")
    annual_vol: float = float("nan")
    trend_label: str = "Insufficient data"
    trend_score: float = 0.0
    momentum_score: float = 0.0
    rsi_score: float = 0.0
    volatility_label: str = "Unknown"
    volatility_score: float = 0.0
    volume_score: float = 0.0
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def adx_state(self) -> str:
        if not np.isfinite(self.adx):
            return "Unavailable"
        if self.adx >= 40:
            return f"Very strong trend ({self.adx:.1f})"
        if self.adx >= 25:
            return f"Trending ({self.adx:.1f})"
        if self.adx >= 20:
            return f"Weak trend ({self.adx:.1f})"
        return f"Range / no trend ({self.adx:.1f})"

    @property
    def macd_state(self) -> str:
        if not np.isfinite(self.macd_hist):
            return "Unavailable"
        if self.macd_hist > 0 and self.macd > self.macd_signal:
            return "Bullish (MACD above signal)"
        if self.macd_hist < 0 and self.macd < self.macd_signal:
            return "Bearish (MACD below signal)"
        return "Flat / crossing"


def _last(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return float("nan")
    value = series.iloc[-1]
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def trend_readout(snapshot: IndicatorSnapshot) -> tuple[str, float]:
    """Rule-based trend classification from moving-average structure."""
    close, fast, slow, long = snapshot.close, snapshot.sma_fast, snapshot.sma_slow, snapshot.sma_long
    if not np.isfinite(close) or not np.isfinite(fast):
        return "Insufficient data", 0.0
    score = 0.0
    score += 0.25 if close > fast else -0.25
    if np.isfinite(slow):
        score += 0.3 if fast > slow else -0.3
        score += 0.2 if slow > long else -0.2 if np.isfinite(long) else 0.0
    if np.isfinite(long):
        score += 0.25 if close > long else -0.25
    score = float(np.clip(score, -1, 1))
    if score >= 0.6:
        label = "Strong uptrend"
    elif score >= 0.2:
        label = "Uptrend"
    elif score <= -0.6:
        label = "Strong downtrend"
    elif score <= -0.2:
        label = "Downtrend"
    else:
        label = "Sideways / range"
    return label, score


def _rsi_score(value: float) -> float:
    """Mean-reversion interpretation of RSI (overbought is a caution, not a buy)."""
    if not np.isfinite(value):
        return 0.0
    if value >= 80:
        return -0.9
    if value >= 70:
        return -0.55
    if value >= 55:
        return 0.4
    if value >= 45:
        return 0.0
    if value >= 30:
        return -0.3
    if value >= 20:
        return 0.55
    return 0.85


def _volume_ratio(frame: pd.DataFrame, short: int = 10, long: int = 50) -> float:
    if "Volume" not in frame or frame.empty:
        return float("nan")
    volume = frame["Volume"].astype(float)
    if volume.tail(long).sum() <= 0:
        return float("nan")
    short_avg = volume.tail(short).mean()
    long_avg = volume.tail(long).mean()
    if not np.isfinite(long_avg) or long_avg <= 0:
        return float("nan")
    return float(short_avg / long_avg)


def _volatility_regime(atr_pct: float, reference: float) -> tuple[str, float]:
    if not np.isfinite(atr_pct):
        return "Unknown", 0.0
    if not np.isfinite(reference) or reference <= 0:
        return "Normal", 0.0
    ratio = atr_pct / reference
    if ratio >= 1.75:
        return "High", -0.3
    if ratio >= 1.2:
        return "Elevated", -0.15
    if ratio <= 0.6:
        return "Low", 0.1
    return "Normal", 0.0


def snapshot(
    frame: pd.DataFrame,
    *,
    fast: int = 50,
    slow: int = 200,
    long_window: int = 200,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> IndicatorSnapshot:
    """Compute a complete indicator snapshot for an OHLCV frame."""
    snap = IndicatorSnapshot(bars=0 if frame is None else len(frame))
    if frame is None or frame.empty or "Close" not in frame:
        return snap

    close = frame["Close"].astype(float)
    snap.bars = int(close.notna().sum())
    if snap.bars < 2:
        return snap

    snap.close = _last(close)
    snap.sma_fast = _last(sma(close, fast))
    snap.sma_slow = _last(sma(close, slow))
    snap.sma_long = _last(sma(close, long_window))
    snap.ema_fast = _last(ema(close, max(fast // 2, 5)))
    snap.ema_slow = _last(ema(close, max(slow // 2, 10)))
    snap.rsi = _last(rsi(close, rsi_period))

    macd_frame = macd(close)
    snap.macd = _last(macd_frame["macd"])
    snap.macd_signal = _last(macd_frame["signal"])
    snap.macd_hist = _last(macd_frame["hist"])

    atr_series = atr(frame, atr_period)
    snap.atr = _last(atr_series)
    snap.atr_pct = (
        float(snap.atr / snap.close * 100.0)
        if np.isfinite(snap.atr) and np.isfinite(snap.close) and snap.close
        else float("nan")
    )
    snap.macd_hist_atr = (
        float(snap.macd_hist / snap.atr) if np.isfinite(snap.atr) and snap.atr else float("nan")
    )

    snap.bb_width = _last(bollinger(close)["width"]) * 100 if snap.bars >= 20 else float("nan")
    adx_frame = adx(frame, rsi_period)
    if not adx_frame.empty:
        snap.adx = _last(adx_frame["adx"])
        snap.plus_di = _last(adx_frame["plus_di"])
        snap.minus_di = _last(adx_frame["minus_di"])
    snap.volume_ratio = _volume_ratio(frame)
    snap.roc_20 = _last(roc(close, 20))
    snap.return_5 = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if snap.bars > 6 else float("nan")
    snap.return_20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if snap.bars > 21 else float("nan")
    snap.annual_vol = annualized_volatility(close)

    snap.trend_label, snap.trend_score = trend_readout(snap)

    if np.isfinite(snap.macd_hist_atr):
        norm_hist = float(np.tanh(snap.macd_hist_atr * 2.0))
        norm_roc = float(np.tanh(snap.roc_20 / 12.0)) if np.isfinite(snap.roc_20) else 0.0
        snap.momentum_score = float(np.clip(norm_hist * 0.65 + norm_roc * 0.35, -1, 1))

    snap.rsi_score = _rsi_score(snap.rsi)

    reference = float(atr_series.tail(100).median()) if len(atr_series.dropna()) >= 20 else float("nan")
    reference_pct = (
        reference / snap.close * 100.0 if np.isfinite(reference) and snap.close else float("nan")
    )
    snap.volatility_label, snap.volatility_score = _volatility_regime(snap.atr_pct, reference_pct)

    if np.isfinite(snap.volume_ratio):
        direction = 1.0 if snap.trend_score >= 0 else -1.0
        snap.volume_score = float(np.clip(np.tanh((snap.volume_ratio - 1.0) * 1.5) * 0.6 * direction, -1, 1))

    return snap
