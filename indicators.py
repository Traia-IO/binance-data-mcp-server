"""indicators.py — Pure-function technical indicator engine.

Faithful Python port of the legacy ``indicators.mjs`` (+ the JS Math.round-based
rounding helpers and snapshot trend/band logic from ``snapshot.mjs``).

No third-party dependencies. All formulas explicit. Every function returns
``None`` when there is insufficient data — matching the .mjs ``return null`` paths.

OHLCV inputs are plain lists of floats. Candle order is oldest -> newest
(Binance klines order), so ``values[-1]`` is the most recent candle.
"""

from __future__ import annotations

import math
from typing import Optional


# ── JS Math.round-faithful rounding helpers ───────────────────────────────
#
# JavaScript's Math.round rounds half *up* (toward +Infinity): Math.round(2.5)
# == 3, Math.round(-2.5) == -2. Python's built-in round() is banker's rounding
# (round-half-to-even), which would diverge on exact .5 cases. snapshot.mjs's
# r1/r2/r3 are `Math.round(v * 10^d) / 10^d`, so we replicate that exactly.

def _js_round(x: float) -> float:
    """Replicate JavaScript Math.round: round half toward +Infinity."""
    return math.floor(x + 0.5)


def r1(v: Optional[float]) -> Optional[float]:
    """snapshot.mjs r1: Math.round(v*10)/10 (1 decimal), pass-through None."""
    if v is None:
        return None
    return _js_round(v * 10) / 10


def r2(v: Optional[float]) -> Optional[float]:
    """snapshot.mjs r2: Math.round(v*100)/100 (2 decimals), pass-through None."""
    if v is None:
        return None
    return _js_round(v * 100) / 100


def r3(v: Optional[float]) -> Optional[float]:
    """snapshot.mjs r3: Math.round(v*1000)/1000 (3 decimals), pass-through None."""
    if v is None:
        return None
    return _js_round(v * 1000) / 1000


# ── Internal stat helpers (not exported in the .mjs) ───────────────────────

def _sum(arr: list[float]) -> float:
    s = 0.0
    for x in arr:
        s += x
    return s


def _mean(arr: list[float]) -> Optional[float]:
    """Arithmetic mean. Returns None on empty input (matches mean() in .mjs)."""
    if len(arr) == 0:
        return None
    return _sum(arr) / len(arr)


def _stddev(arr: list[float]) -> Optional[float]:
    """Population standard deviation (divides by N, NOT N-1).

    Matches indicators.mjs stddev(): returns None if fewer than 2 elements,
    else sqrt(sum((x-mean)^2) / N).
    """
    if len(arr) < 2:
        return None
    m = _sum(arr) / len(arr)
    ss = 0.0
    for x in arr:
        d = x - m
        ss += d * d
    return math.sqrt(ss / len(arr))


# ── SMA ────────────────────────────────────────────────────────────────────

def sma(values: list[float], period: int) -> Optional[float]:
    """Simple Moving Average — latest value only.

    Formula: mean of the last `period` values. None if len < period.
    """
    if len(values) < period:
        return None
    return _mean(values[-period:])


# ── EMA (SMA-seeded) ─────────────────────────────────────────────────────────

def ema_series(values: list[float], period: int) -> Optional[list[float]]:
    """Exponential Moving Average — full series.

    Seed: SMA of the first `period` values.
    Multiplier k = 2 / (period + 1).
    Recurrence: EMA_i = value_i * k + EMA_{i-1} * (1 - k).
    The returned series starts at the seed (one element per i from
    period-1 onward), so its length is len(values) - period + 1.
    None if len(values) < period.
    """
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    seed = _mean(values[:period])
    result: list[float] = [seed]  # type: ignore[list-item]

    for i in range(period, len(values)):
        prev = result[-1]
        result.append(values[i] * k + prev * (1 - k))
    return result


def ema(values: list[float], period: int) -> Optional[float]:
    """Exponential Moving Average — latest value only (last of ema_series)."""
    series = ema_series(values, period)
    return series[-1] if series else None


# ── RSI (Wilder smoothing) ─────────────────────────────────────────────────

def rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index using Wilder smoothing.

    Step 1: price changes = diffs of consecutive closes.
    Step 2: first avgGain/avgLoss = simple mean of the first `period` changes
            (gains summed, losses summed as absolute values, each / period).
    Step 3: for each remaining change, Wilder smoothing:
            avg = (avg_prev * (period - 1) + current) / period.
    Step 4: if avgLoss == 0 -> 100; if avgGain == 0 -> 0;
            else RS = avgGain / avgLoss; RSI = 100 - 100 / (1 + RS).
    None if len(closes) < period + 1.
    """
    if len(closes) < period + 1:
        return None

    changes: list[float] = []
    for i in range(1, len(closes)):
        changes.append(closes[i] - closes[i - 1])

    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(period):
        if changes[i] > 0:
            avg_gain += changes[i]
        else:
            avg_loss += abs(changes[i])
    avg_gain /= period
    avg_loss /= period

    for i in range(period, len(changes)):
        gain = changes[i] if changes[i] > 0 else 0.0
        loss = abs(changes[i]) if changes[i] < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


# ── MACD ────────────────────────────────────────────────────────────────────

def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Optional[dict]:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(signal_period) of MACD line.

    Requires len(closes) >= slow + signal_period - 1.
    The fast EMA series is longer than the slow one; align by trimming the
    start of the fast series by `offset = len(fast) - len(slow)`, then
    macdLine_i = fast[i + offset] - slow[i]. The signal line is the EMA of the
    MACD line; histogram = value - signal (value/signal are the last elements).
    Returns {"value", "signal", "histogram"} or None.
    """
    if len(closes) < slow + signal_period - 1:
        return None

    fast_series = ema_series(closes, fast)
    slow_series = ema_series(closes, slow)
    if not fast_series or not slow_series:
        return None

    offset = len(fast_series) - len(slow_series)
    macd_line: list[float] = []
    for i in range(len(slow_series)):
        macd_line.append(fast_series[i + offset] - slow_series[i])

    signal_series = ema_series(macd_line, signal_period)
    if not signal_series:
        return None

    value = macd_line[-1]
    signal = signal_series[-1]
    return {"value": value, "signal": signal, "histogram": value - signal}


# ── Bollinger Bands ─────────────────────────────────────────────────────────

def bollinger(closes: list[float], period: int = 20, mult: float = 2) -> Optional[dict]:
    """Bollinger Bands: middle = SMA(period); bands = middle ± mult * stddev.

    Uses POPULATION stddev (divide by N) over the last `period` closes.
    widthRatio = (upper - lower) / middle, or 0 when middle == 0.
    None if len(closes) < period.
    Returns {"upper", "middle", "lower", "widthRatio"}.
    """
    if len(closes) < period:
        return None

    window = closes[-period:]
    middle = _mean(window)
    sd = _stddev(window)
    if middle is None or sd is None:
        return None

    upper = middle + mult * sd
    lower = middle - mult * sd
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "widthRatio": ((upper - lower) / middle) if middle != 0 else 0,
    }


# ── ATR (Wilder smoothing) ──────────────────────────────────────────────────

def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """Average True Range using Wilder smoothing.

    True Range series:
      tr[0]  = high[0] - low[0]
      tr[i]  = max(high[i]-low[i], |high[i]-close[i-1]|, |low[i]-close[i-1]|)
    First ATR = simple mean of tr[1 .. period] (i.e. tr.slice(1, period+1)).
    Wilder smoothing for i from period+1 onward:
      atr = (atr_prev * (period - 1) + tr[i]) / period.
    len is min of the three input lengths; None if len < period + 1.
    """
    length = min(len(highs), len(lows), len(closes))
    if length < period + 1:
        return None

    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, length):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    atr_val = _mean(tr[1 : period + 1])
    if atr_val is None:
        return None

    for i in range(period + 1, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[i]) / period
    return atr_val


# ── VWAP ────────────────────────────────────────────────────────────────────

def vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> Optional[float]:
    """Volume Weighted Average Price over the given candle window.

    Typical price tp_i = (high_i + low_i + close_i) / 3.
    VWAP = sum(tp_i * vol_i) / sum(vol_i).
    len is min of the four input lengths; None if len == 0 or sum(vol) <= 0.
    """
    length = min(len(highs), len(lows), len(closes), len(volumes))
    if length == 0:
        return None

    cum_pv = 0.0
    cum_v = 0.0
    for i in range(length):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        cum_pv += tp * volumes[i]
        cum_v += volumes[i]
    return (cum_pv / cum_v) if cum_v > 0 else None


# ── Volume Spike ────────────────────────────────────────────────────────────

def volume_spike(
    volumes: list[float],
    period: int = 20,
    threshold: float = 1.5,
) -> Optional[dict]:
    """Compare the latest candle volume to the SMA of the `period` prior candles.

    prior = volumes[-(period+1):-1]  (the `period` candles before the last one).
    avgVol = mean(prior); relativeVolume = current / avgVol;
    spike = relativeVolume >= threshold.
    None if len(volumes) < period + 1, or avgVol is None/0.
    Returns {"relativeVolume", "spike"}.
    """
    if len(volumes) < period + 1:
        return None

    prior = volumes[-(period + 1):-1]
    avg_vol = _mean(prior)
    if avg_vol is None or avg_vol == 0:
        return None

    current = volumes[-1]
    relative_volume = current / avg_vol
    return {"relativeVolume": relative_volume, "spike": relative_volume >= threshold}


# ── EMA-stacking / band-position helpers (from snapshot.mjs trend logic) ────

def bullish_stacked(
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float],
) -> Optional[bool]:
    """True iff ema20 > ema50 > ema200 (bullish EMA stack). None if any is None."""
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    return ema20 > ema50 and ema50 > ema200


def bearish_stacked(
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float],
) -> Optional[bool]:
    """True iff ema20 < ema50 < ema200 (bearish EMA stack). None if any is None."""
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    return ema20 < ema50 and ema50 < ema200


def price_above(price: float, level: Optional[float]) -> Optional[bool]:
    """price > level, or None if level is None. Mirrors priceAboveEmaXX/Vwap."""
    if level is None:
        return None
    return price > level
