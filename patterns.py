"""patterns.py — Rule-based pattern matching + historical success rates + scoring.

Faithful Python port of the legacy ``patterns.mjs`` (+ the decision flow from
``entry-decision.mjs``). Consumes the normalized snapshot produced by the
``binance_technical_analysis`` tool. All checks derive values from that snapshot
shape ({price, trend, momentum, volatility, volume}); no extra fields needed.
"""

from __future__ import annotations


# ── Historical Success Rates (from backtested data) ──────────────────
# Replace with live data as you accumulate your own trade results.

SUCCESS_RATES = {
    "bullish_trend_alignment": {"rate": 0.86, "samples": 164},
    "sma_macd_bullish":        {"rate": 0.82, "samples": 184},
    "bearish_trend_alignment": {"rate": 0.65, "samples": 103},
    "bullish_reversal":        {"rate": 0.45, "samples": 79},
    "bearish_reversal":        {"rate": 0.30, "samples": 355},
}


# ── Snapshot accessors (mirror JS optional-chaining `?.`) ─────────────

def _get(d, *keys):
    """Safe nested lookup; returns None if any link is missing/None (like ?.)."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


# ── Derived Checks ───────────────────────────────────────────────────

def bb_position(snap):
    bb = _get(snap, "volatility", "bollinger")
    price = snap.get("price")
    if not bb or price is None:
        return None
    if price > bb.get("upper"):
        return "above_upper"
    if price > bb.get("middle"):
        return "upper_half"
    if price > bb.get("lower"):
        return "lower_half"
    return "below_lower"


def is_bullish_trend(snap):
    return _get(snap, "trend", "bullishStacked") is True and \
        _get(snap, "trend", "priceAboveEma20") is True


def is_bearish_stacked(snap):
    trend = snap.get("trend") or {}
    ema20, ema50, ema200 = trend.get("ema20"), trend.get("ema50"), trend.get("ema200")
    return (ema20 is not None and ema50 is not None and ema200 is not None
            and ema20 < ema50 and ema50 < ema200)


def is_bearish_trend(snap):
    return is_bearish_stacked(snap) and _get(snap, "trend", "priceAboveEma50") is False


def has_bullish_momentum(snap):
    rsi = _get(snap, "momentum", "rsi")
    return isinstance(rsi, (int, float)) and not isinstance(rsi, bool) and \
        rsi >= 40 and _get(snap, "momentum", "macd", "bullish") is True


def has_bearish_momentum(snap):
    rsi = _get(snap, "momentum", "rsi")
    return isinstance(rsi, (int, float)) and not isinstance(rsi, bool) and \
        rsi <= 60 and _get(snap, "momentum", "macd", "bullish") is False


def has_long_volume(snap):
    return _get(snap, "volume", "volumeSpike") is True and \
        _get(snap, "volume", "priceAboveVwap") is True


def has_short_volume(snap):
    return _get(snap, "volume", "volumeSpike") is True and \
        _get(snap, "volume", "priceAboveVwap") is False


def is_near_lower(snap):
    pos = bb_position(snap)
    return pos == "lower_half" or pos == "below_lower"


def is_near_upper(snap):
    pos = bb_position(snap)
    return pos == "upper_half" or pos == "above_upper"


def is_bb_neutral(snap):
    pos = bb_position(snap)
    return pos == "lower_half" or pos == "upper_half"


def is_oversold(snap):
    rsi = _get(snap, "momentum", "rsi")
    return isinstance(rsi, (int, float)) and not isinstance(rsi, bool) and rsi < 35


def is_overbought(snap):
    rsi = _get(snap, "momentum", "rsi")
    return isinstance(rsi, (int, float)) and not isinstance(rsi, bool) and rsi > 65


# ── Pattern Evaluators ───────────────────────────────────────────────

def bullish_trend_alignment(snap):
    trend = is_bullish_trend(snap)
    momentum = has_bullish_momentum(snap)
    volume = has_long_volume(snap)

    reasons = []
    failed_checks = []

    if trend:
        reasons.append("Bullish EMA stacking confirmed (20 > 50 > 200)")
    else:
        failed_checks.append("EMA stacking is not bullish")

    if momentum:
        rsi = _get(snap, "momentum", "rsi")
        reasons.append(f"Momentum aligned: RSI {rsi if rsi is not None else '?'}, MACD bullish")
    else:
        failed_checks.append("Momentum not aligned (RSI < 40 or MACD bearish)")

    if volume:
        reasons.append("Volume spike with price above VWAP")
    else:
        failed_checks.append("No volume confirmation (no spike or below VWAP)")

    scores = {"trend": 3 if trend else 0, "momentum": 2 if momentum else 0,
              "volume": 1 if volume else 0, "volatility": 0}
    score = scores["trend"] + scores["momentum"] + scores["volume"]

    return {
        "pattern": "bullish_trend_alignment",
        "direction": "LONG",
        "matched": bool(trend and momentum),  # volume is bonus, not required
        "score": score,
        "reasons": reasons,
        "failedChecks": failed_checks,
        "scores": scores,
    }


def sma_macd_bullish(snap):
    above_ema = _get(snap, "trend", "priceAboveEma20") is True
    macd_bull = _get(snap, "momentum", "macd", "bullish") is True
    neutral = is_bb_neutral(snap)
    volume = has_long_volume(snap)

    reasons = []
    failed_checks = []

    if above_ema:
        reasons.append("Price above EMA(20)")
    else:
        failed_checks.append("Price below EMA(20)")

    if macd_bull:
        reasons.append("MACD bullish (value > signal)")
    else:
        failed_checks.append("MACD not bullish")

    if neutral:
        reasons.append("Bollinger position neutral — room to run")
    else:
        failed_checks.append("Bollinger position extreme (overbought/oversold zone)")

    if volume:
        reasons.append("Volume spike confirms participation")
    else:
        failed_checks.append("No volume spike confirmation")

    scores = {"trend": 2 if above_ema else 0, "momentum": 2 if macd_bull else 0,
              "volume": 1 if volume else 0, "volatility": 1 if neutral else 0}
    score = scores["trend"] + scores["momentum"] + scores["volume"] + scores["volatility"]

    return {
        "pattern": "sma_macd_bullish",
        "direction": "LONG",
        "matched": bool(above_ema and macd_bull and neutral),
        "score": score,
        "reasons": reasons,
        "failedChecks": failed_checks,
        "scores": scores,
    }


def bearish_trend_alignment(snap):
    trend = is_bearish_trend(snap)
    momentum = has_bearish_momentum(snap)
    volume = has_short_volume(snap)
    near_upper = is_near_upper(snap)

    reasons = []
    failed_checks = []

    if trend:
        reasons.append("Bearish EMA stacking confirmed (20 < 50 < 200)")
    else:
        failed_checks.append("EMA stacking is not bearish")

    if momentum:
        rsi = _get(snap, "momentum", "rsi")
        reasons.append(f"Momentum aligned: RSI {rsi if rsi is not None else '?'}, MACD bearish")
    else:
        failed_checks.append("Momentum not aligned (RSI > 60 or MACD bullish)")

    if volume:
        reasons.append("Volume spike with price below VWAP")
    else:
        failed_checks.append("No short volume confirmation")

    if near_upper:
        reasons.append("Price near upper Bollinger — pullback zone")
    else:
        failed_checks.append("Price not in upper Bollinger zone")

    scores = {"trend": 2 if trend else 0, "momentum": 2 if momentum else 0,
              "volume": 1 if volume else 0, "volatility": 1 if near_upper else 0}
    score = scores["trend"] + scores["momentum"] + scores["volume"] + scores["volatility"]

    return {
        "pattern": "bearish_trend_alignment",
        "direction": "SHORT",
        "matched": bool(trend and momentum and volume),  # ALL required — higher bar for shorts
        "score": score,
        "reasons": reasons,
        "failedChecks": failed_checks,
        "scores": scores,
    }


def bullish_reversal(snap):
    oversold = is_oversold(snap)
    macd_bull = _get(snap, "momentum", "macd", "bullish") is True
    near_lower = is_near_lower(snap)
    not_bearish = not is_bearish_trend(snap)

    reasons = []
    failed_checks = []

    if oversold:
        reasons.append(f"RSI oversold at {_get(snap, 'momentum', 'rsi')}")
    else:
        failed_checks.append("RSI not in oversold zone (< 35)")

    if macd_bull:
        reasons.append("MACD turning bullish")
    else:
        failed_checks.append("MACD not bullish")

    if near_lower:
        reasons.append("Price near lower Bollinger band")
    else:
        failed_checks.append("Price not near lower band")

    if not_bearish:
        reasons.append("Trend not strongly bearish against reversal")
    else:
        failed_checks.append("Strong bearish trend opposes reversal")

    momentum_score = 2 if (oversold and macd_bull) else (1 if (oversold or macd_bull) else 0)
    scores = {"trend": 1 if not_bearish else 0, "momentum": momentum_score,
              "volume": 0, "volatility": 1 if near_lower else 0}
    score = scores["trend"] + scores["momentum"] + scores["volatility"]

    return {
        "pattern": "bullish_reversal",
        "direction": "LONG",
        "matched": bool(oversold and macd_bull and near_lower),
        "score": score,
        "reasons": reasons,
        "failedChecks": failed_checks,
        "scores": scores,
    }


def bearish_reversal(snap):
    overbought = is_overbought(snap)
    macd_bear = _get(snap, "momentum", "macd", "bullish") is False
    near_upper = is_near_upper(snap)
    not_bullish = not is_bullish_trend(snap)

    reasons = []
    failed_checks = []

    if overbought:
        reasons.append(f"RSI overbought at {_get(snap, 'momentum', 'rsi')}")
    else:
        failed_checks.append("RSI not in overbought zone (> 65)")

    if macd_bear:
        reasons.append("MACD turning bearish")
    else:
        failed_checks.append("MACD not bearish")

    if near_upper:
        reasons.append("Price near upper Bollinger band")
    else:
        failed_checks.append("Price not near upper band")

    if not_bullish:
        reasons.append("Trend not strongly bullish against reversal")
    else:
        failed_checks.append("Strong bullish trend opposes reversal")

    momentum_score = 2 if (overbought and macd_bear) else (1 if (overbought or macd_bear) else 0)
    scores = {"trend": 1 if not_bullish else 0, "momentum": momentum_score,
              "volume": 0, "volatility": 1 if near_upper else 0}
    score = scores["trend"] + scores["momentum"] + scores["volatility"]

    return {
        "pattern": "bearish_reversal",
        "direction": "SHORT",
        "matched": bool(overbought and macd_bear and near_upper),
        "score": score,
        "reasons": reasons,
        "failedChecks": failed_checks,
        "scores": scores,
    }


# ── Scoring ──────────────────────────────────────────────────────────

def confidence_label(v):
    if v >= 0.8:
        return "high"
    if v >= 0.55:
        return "medium"
    return "low"


def final_confidence(rule_score, success_rate):
    normalized = min(rule_score / 6, 1)
    return normalized * 0.6 + (success_rate or 0) * 0.4


def should_trade(rate, samples):
    return rate >= 0.6 and samples >= 50


# ── Main Evaluate ────────────────────────────────────────────────────

def evaluate(snapshot):
    results = [
        bullish_trend_alignment(snapshot),
        sma_macd_bullish(snapshot),
        bearish_trend_alignment(snapshot),
        bullish_reversal(snapshot),
        bearish_reversal(snapshot),
    ]

    matched = [r for r in results if r["matched"]]

    # No pattern matched
    if len(matched) == 0:
        best = sorted(results, key=lambda r: r["score"], reverse=True)[0]
        return {
            "action": "NO_TRADE",
            "confidence": round(min((best["score"] if best else 0) / 6, 0.49), 3),
            "confidenceLabel": "low",
            "pattern": None,
            "reasons": ["No valid entry pattern matched"],
            "failedChecks": best["failedChecks"] if best else [],
            "scores": best["scores"] if best else {},
            "edge": None,
        }

    # Enrich with success rate data
    enriched = []
    for r in matched:
        stats = SUCCESS_RATES.get(r["pattern"], {"rate": 0, "samples": 0})
        conf = final_confidence(r["score"], stats["rate"])
        e = dict(r)
        e["finalConfidence"] = conf
        e["tradeAllowed"] = should_trade(stats["rate"], stats["samples"])
        e["edge"] = stats
        enriched.append(e)

    # Filter by success rate gate
    allowed = [r for r in enriched if r["tradeAllowed"]]

    if len(allowed) == 0:
        best = sorted(enriched, key=lambda r: r["finalConfidence"], reverse=True)[0]
        return {
            "action": "NO_TRADE",
            "confidence": best["finalConfidence"],
            "confidenceLabel": confidence_label(best["finalConfidence"]),
            "pattern": best["pattern"],
            "reasons": ["Pattern matched but historical success rate too low to trade"],
            "failedChecks": [
                f"{best['pattern']}: {round(best['edge']['rate'] * 100)}% rate / {best['edge']['samples']} samples"
            ],
            "scores": best["scores"],
            "edge": best["edge"],
        }

    # Check for conflicting directions
    longs = [r for r in allowed if r["direction"] == "LONG"]
    shorts = [r for r in allowed if r["direction"] == "SHORT"]

    if len(longs) > 0 and len(shorts) > 0:
        best_long = sorted(longs, key=lambda r: r["finalConfidence"], reverse=True)[0]
        best_short = sorted(shorts, key=lambda r: r["finalConfidence"], reverse=True)[0]

        if abs(best_long["finalConfidence"] - best_short["finalConfidence"]) < 0.1:
            return {
                "action": "NO_TRADE",
                "confidence": max(best_long["finalConfidence"], best_short["finalConfidence"]),
                "confidenceLabel": "low",
                "pattern": None,
                "reasons": ["Conflicting LONG and SHORT signals too close in strength"],
                "failedChecks": [f"LONG({best_long['pattern']}) vs SHORT({best_short['pattern']})"],
                "scores": {},
                "edge": None,
            }

    # Pick winner
    winner = sorted(allowed, key=lambda r: r["finalConfidence"], reverse=True)[0]

    return {
        "action": winner["direction"],
        "confidence": round(winner["finalConfidence"], 3),
        "confidenceLabel": confidence_label(winner["finalConfidence"]),
        "pattern": winner["pattern"],
        "reasons": winner["reasons"],
        "failedChecks": winner["failedChecks"],
        "scores": winner["scores"],
        "edge": winner["edge"],
    }
