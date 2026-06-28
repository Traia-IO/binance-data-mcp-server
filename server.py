#!/usr/bin/env python3
"""binance-data MCP Server — FastMCP with D402 payment wrapper (FREE).

Exposes PUBLIC Binance market + Web3 data as MCP tools, faithfully replicating
the logic of 12 legacy script-based skills. No API keys / secrets — all upstreams
are public, no-auth endpoints, so every tool is priced at 0 (free).

Architecture (matches the standard d402 server template):
- FastMCP for tool decorators + Context.
- @require_payment_for_tool(price=0) per tool — D402PaymentMiddleware wraps /mcp.
- D402_TESTING_MODE / D402_FREE_ACCESS make the price-0 tools callable freely.

Tools (legacy skill it replaces):
  binance_klines / binance_orderbook .......... market-data primitives
  binance_whale_activity ...................... whale-tracker
  binance_pnl_leaderboard ..................... binance-pnl-rank
  binance_smart_money_inflows ................. binance-smart-money
  binance_meme_rank ........................... binance-meme-rank
  binance_meme_rush ........................... binance-meme-rush
  binance_social_hype ......................... binance-social-hype
  binance_token_rank .......................... binance-token-rank
  binance_topic_rush .......................... binance-topic-rush
  binance_trading_signal ...................... binance-trading-signal
  binance_rsi_signal .......................... rsi-signal
  binance_technical_analysis .................. technical-analysis
  binance_trend_momentum_entry ................ trend-momentum-entry

Environment Variables:
- SERVER_ADDRESS: Payment address (IATP wallet contract)
- MCP_OPERATOR_PRIVATE_KEY: Operator signing key
- D402_TESTING_MODE: Skip facilitator (default: true)
"""

import os
import logging
from typing import Any, Dict, Optional
from datetime import datetime

import httpx
from dotenv import load_dotenv
import uvicorn

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('binance-data_mcp')

# FastMCP from official SDK
from mcp.server.fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

# D402 payment protocol — Starlette middleware
from traia_iatp.d402.starlette_middleware import D402PaymentMiddleware
from traia_iatp.d402.mcp_middleware import require_payment_for_tool, get_active_api_key
from traia_iatp.d402.payment_introspection import extract_payment_configs_from_mcp
from traia_iatp.d402.types import TokenAmount, TokenAsset, EIP712Domain

from indicators import (
    ema, rsi, macd, bollinger, atr, vwap, volume_spike,
    bullish_stacked, price_above, r1, r2, r3,
)
from patterns import evaluate

# Configuration
STAGE = os.getenv("STAGE", "MAINNET").upper()
PORT = int(os.getenv("PORT", "8000"))
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS")
if not SERVER_ADDRESS:
    raise ValueError("SERVER_ADDRESS required for payment protocol")

logger.info("=" * 80)
logger.info("binance-data MCP Server (FastMCP + D402 Wrapper, FREE)")
logger.info(f"Payment: {SERVER_ADDRESS}")
logger.info("=" * 80)

mcp = FastMCP("binance-data MCP Server", host="0.0.0.0")
logger.info("✅ FastMCP server created")

# FREE price: amount "0" on USDC/arbitrum_one. Reused by every tool decorator so
# D402PaymentMiddleware registers each tool yet never charges (price 0).
FREE_PRICE = TokenAmount(
    amount="0",
    asset=TokenAsset(
        address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        decimals=6,
        network="arbitrum_one",
        eip712=EIP712Domain(name="IATPWallet", version="1"),
    ),
)

# ── Upstreams ────────────────────────────────────────────────────────────────
SPOT_API = "https://data-api.binance.vision/api/v3"
PNL_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/market/leaderboard/query/ai"
INFLOW_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
MEME_RANK_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/exclusive/rank/list/ai"
MEME_RUSH_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/rank/list/ai"
SOCIAL_HYPE_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard/ai"
TOKEN_RANK_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list/ai"
TOPIC_RUSH_API = "https://web3.binance.com/bapi/defi/v2/public/wallet-direct/buw/wallet/market/token/social-rush/rank/list/ai"
TRADING_SIGNAL_API = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 binance-web3/2.1 (Skill)"
WEB3_HEADERS = {"Accept-Encoding": "identity", "User-Agent": UA}

# ── Lookup tables (verbatim from the .mjs) ───────────────────────────────────
MEME_RUSH_STAGES = {"new": 10, "finalizing": 20, "migrated": 30}
MEME_RUSH_STAGE_LABELS = {10: "New", 20: "Finalizing", 30: "Migrated"}
MEME_RUSH_PROTOCOLS = {
    1001: "Pump.fun", 1002: "Moonit", 1003: "Pump AMM", 1004: "Launch Lab",
    1005: "Raydium V4", 1006: "Raydium CPMM", 1007: "Raydium CLMM", 1008: "BONK",
    1009: "Dynamic BC", 1010: "Moonshot", 1011: "Jup Studio", 1012: "Bags",
    1013: "Believer", 1014: "Meteora DAMM", 1015: "Meteora Pools", 1016: "Orca",
    2001: "Four.meme", 2002: "Flap",
}
TOKEN_RANK_RANK_TYPES = {"trending": 10, "search": 11, "alpha": 20, "stock": 40}
TOKEN_RANK_PERIODS = {"1m": 10, "5m": 20, "1h": 30, "4h": 40, "24h": 50}
TOKEN_RANK_SORT_MAP = {
    "default": 0, "search": 2, "launch": 10, "liquidity": 20, "holders": 30,
    "marketCap": 40, "priceChange": 50, "txCount": 60, "volume": 70, "price": 90, "traders": 100,
}
TOPIC_RUSH_TYPES = {"latest": 10, "rising": 20}
TOPIC_RUSH_SORTS = {"time": 10, "inflow": 20}


# ── HTTP helpers ─────────────────────────────────────────────────────────────
async def _get(url: str, params: Optional[Dict[str, Any]] = None,
               headers: Optional[Dict[str, str]] = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params, headers=headers or {"User-Agent": UA})
        r.raise_for_status()
        return r.json()


async def _post_json(url: str, body: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=body,
                         headers={**WEB3_HEADERS, "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()


def _num(n) -> float:
    """Mirror JS Number(x || 0): null/None/'' -> 0, else float."""
    if n is None or n == "":
        return 0.0
    try:
        return float(n)
    except (TypeError, ValueError):
        return 0.0


def _topic_name(name) -> str:
    if not name or not isinstance(name, dict):
        return "Unknown"
    if name.get("topicNameEn"):
        return name["topicNameEn"]
    if name.get("topicNameCn"):
        return name["topicNameCn"]
    for v in name.values():
        if isinstance(v, str) and v:
            return v
    return "Unknown"


def _extract_tags(token_tag) -> list:
    if not token_tag or not isinstance(token_tag, dict):
        return []
    tags = []
    for category, items in token_tag.items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    tags.append({"category": category, "name": item.get("tagName") or item.get("name") or "unknown"})
                else:
                    tags.append({"category": category, "name": "unknown"})
    return tags


def _price_delta(alert, current) -> float:
    a = _num(alert)
    c = _num(current)
    if a == 0:
        return 0.0
    return ((c - a) / a) * 100


# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================
# START_CUSTOM_TOOLS

# ── spot market-data primitives ──────────────────────────────────────────────
@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Candlestick/kline OHLCV bars for a symbol.")
async def binance_klines(context: Context, symbol: str = "BTCUSDT",
                         interval: str = "1h", limit: int = 100) -> dict:
    """Candlestick/kline data. GET data-api.binance.vision/api/v3/klines.

    interval e.g. 1m,5m,15m,1h,4h,1d. limit max 1000.
    """
    symbol = symbol.upper()
    raw = await _get(f"{SPOT_API}/klines",
                     {"symbol": symbol, "interval": interval, "limit": limit})
    candles = [{
        "openTime": k[0], "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
        "closeTime": k[6], "quoteVolume": float(k[7]), "trades": k[8],
    } for k in raw]
    return {"symbol": symbol, "interval": interval, "count": len(candles), "candles": candles}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Order book depth (bids/asks) for a symbol.")
async def binance_orderbook(context: Context, symbol: str = "BTCUSDT", limit: int = 20) -> dict:
    """Order book depth. GET data-api.binance.vision/api/v3/depth.

    limit one of 5,10,20,50,100,500,1000,5000.
    """
    symbol = symbol.upper()
    book = await _get(f"{SPOT_API}/depth", {"symbol": symbol, "limit": limit})
    bids = [{"price": float(p), "qty": float(q)} for p, q in book.get("bids", [])]
    asks = [{"price": float(p), "qty": float(q)} for p, q in book.get("asks", [])]
    return {"symbol": symbol, "lastUpdateId": book.get("lastUpdateId"), "bids": bids, "asks": asks}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Whale-activity analysis: large trades, orderbook imbalance, walls.")
async def binance_whale_activity(context: Context, symbol: str = "BTCUSDT",
                                 depth: int = 20, thresholdPct: int = 90) -> dict:
    """Whale-activity analysis (replicates whale-tracker).

    Pulls 24h ticker + last 1000 trades + order book, then computes large trades
    above the `thresholdPct` percentile (buy/sell pressure), order book imbalance
    (bid/ask ratio + sentiment), and support/resistance walls (>= 3x avg level).
    """
    symbol = symbol.upper()
    ob_limit = max(depth, 20)
    ticker = await _get(f"{SPOT_API}/ticker/24hr", {"symbol": symbol})
    trades = await _get(f"{SPOT_API}/trades", {"symbol": symbol, "limit": 1000})
    book = await _get(f"{SPOT_API}/depth", {"symbol": symbol, "limit": ob_limit})

    price = float(ticker["lastPrice"])
    sizes = [float(t["qty"]) * float(t["price"]) for t in trades]
    srt = sorted(sizes)
    idx = int(len(srt) * thresholdPct / 100)
    threshold = srt[idx] if idx < len(srt) else (srt[-1] if srt else 0.0)

    large = []
    for t, sz in zip(trades, sizes):
        if sz >= threshold:
            large.append({"time": t["time"], "price": float(t["price"]),
                          "qty": float(t["qty"]), "value": sz,
                          "side": "SELL" if t["isBuyerMaker"] else "BUY"})
    buys = [t for t in large if t["side"] == "BUY"]
    sells = [t for t in large if t["side"] == "SELL"]
    buy_vol = sum(t["value"] for t in buys)
    sell_vol = sum(t["value"] for t in sells)
    if buy_vol > sell_vol * 1.2:
        whale_bias = "BUY"
    elif sell_vol > buy_vol * 1.2:
        whale_bias = "SELL"
    else:
        whale_bias = "NEUTRAL"

    bids = book["bids"][:depth]
    asks = book["asks"][:depth]
    bid_vol = sum(float(b[1]) for b in bids)
    ask_vol = sum(float(a[1]) for a in asks)
    bid_val = sum(float(b[0]) * float(b[1]) for b in bids)
    ask_val = sum(float(a[0]) * float(a[1]) for a in asks)
    ratio = (bid_vol / ask_vol) if ask_vol > 0 else float("inf")
    avg_bid = bid_vol / (len(bids) or 1)
    avg_ask = ask_vol / (len(asks) or 1)
    bid_walls = [{"price": float(b[0]), "size": float(b[1])} for b in bids if float(b[1]) >= avg_bid * 3]
    ask_walls = [{"price": float(a[0]), "size": float(a[1])} for a in asks if float(a[1]) >= avg_ask * 3]
    sentiment = "BULLISH" if ratio > 1.5 else "BEARISH" if ratio < 0.67 else "NEUTRAL"
    recent = sorted(large, key=lambda t: t["time"], reverse=True)[:10]

    return {
        "symbol": symbol, "price": price,
        "priceChangePercent": float(ticker["priceChangePercent"]),
        "largeTrades": {
            "thresholdPct": thresholdPct, "thresholdValue": threshold,
            "buyCount": len(buys), "sellCount": len(sells),
            "buyVolume": buy_vol, "sellVolume": sell_vol,
            "whaleBias": whale_bias, "recent": recent,
        },
        "orderbook": {
            "depth": depth, "bidVolume": bid_vol, "askVolume": ask_vol,
            "bidValue": bid_val, "askValue": ask_val,
            "ratio": (None if ratio == float("inf") else ratio),
            "sentiment": sentiment, "supportWalls": bid_walls[:5], "resistanceWalls": ask_walls[:5],
        },
        "summary": {"whaleBias": whale_bias, "orderbookSentiment": sentiment,
                    "ratio": (None if ratio == float("inf") else ratio)},
    }


# ── Binance Web3 (Pulse / wallet-direct) rankings & signals ──────────────────
@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Top-trader PnL leaderboard (Binance Web3).")
async def binance_pnl_leaderboard(context: Context, chainId: str = "56", period: str = "30d",
                                  tag: str = "ALL", page: int = 1, size: int = 25,
                                  pnlMin: Optional[float] = None,
                                  winRateMin: Optional[float] = None) -> dict:
    """Binance Web3 top-trader PnL leaderboard (replicates binance-pnl-rank).

    GET leaderboard/query/ai. chainId '56'=BSC, 'CT_501'=Solana. size capped at 25.
    """
    size = min(size, 25)
    params = {"chainId": chainId, "period": period, "tag": tag.upper(),
              "pageNo": str(page), "pageSize": str(size), "sortBy": "0", "orderBy": "0"}
    if pnlMin is not None:
        params["PNLMin"] = str(pnlMin)
    if winRateMin is not None:
        params["winRateMin"] = str(winRateMin)

    json_ = await _get(PNL_API, params, WEB3_HEADERS)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    data = json_.get("data") or {}
    traders_raw = data.get("data") or []

    traders = [{
        "address": t.get("address"), "label": t.get("addressLabel"), "tags": t.get("tags") or [],
        "pnl": float(t.get("realizedPnl") or 0), "pnlPercent": float(t.get("realizedPnlPercent") or 0),
        "winRate": float(t.get("winRate") or 0), "totalVolume": float(t.get("totalVolume") or 0),
        "buyVolume": float(t.get("buyVolume") or 0), "sellVolume": float(t.get("sellVolume") or 0),
        "totalTxCnt": int(t.get("totalTxCnt") or 0), "tokensTraded": int(t.get("totalTradedTokens") or 0),
        "topEarningTokens": [{
            "symbol": tk.get("tokenSymbol"), "address": tk.get("tokenAddress"),
            "pnl": float(tk.get("realizedPnl") or 0), "profitRate": float(tk.get("profitRate") or 0),
        } for tk in (t.get("topEarningTokens") or [])[:5]],
    } for t in traders_raw]

    return {"chainId": chainId, "period": period, "tag": tag.upper(),
            "page": data.get("current") or 1, "pages": data.get("pages") or 0,
            "count": len(traders), "traders": traders}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Smart-money token inflow rankings (Binance Web3).")
async def binance_smart_money_inflows(context: Context, chainId: str = "56", period: str = "24h") -> dict:
    """Binance Web3 smart-money token inflow rankings (replicates binance-smart-money).

    POST inflow/rank/query/ai with body {chainId, period, tagType:2}.
    """
    body = {"chainId": chainId, "period": period, "tagType": 2}
    json_ = await _post_json(INFLOW_API, body)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    tokens_raw = json_.get("data") or []

    tokens = [{
        "tokenName": t.get("tokenName"), "contractAddress": t.get("ca"), "chainId": chainId,
        "inflow": float(t.get("inflow") or 0), "traders": int(t.get("traders") or 0),
        "price": float(t.get("price") or 0), "marketCap": float(t.get("marketCap") or 0),
        "volume": float(t.get("volume") or 0), "priceChange": float(t.get("priceChangeRate") or 0),
        "liquidity": float(t.get("liquidity") or 0), "holders": int(t.get("holders") or 0),
        "kycHolders": int(t.get("kycHolders") or 0),
        "riskLevel": int(t.get("tokenRiskLevel") if t.get("tokenRiskLevel") is not None else -1),
    } for t in tokens_raw[:25]]

    return {"chainId": chainId, "period": period, "count": len(tokens),
            "netInflowTokens": sum(1 for t in tokens if t["inflow"] > 0),
            "netOutflowTokens": sum(1 for t in tokens if t["inflow"] < 0),
            "totalNetInflow": sum(t["inflow"] for t in tokens), "tokens": tokens}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Top-100 Pulse launchpad meme tokens by breakout score.")
async def binance_meme_rank(context: Context, chainId: str = "56") -> dict:
    """Binance Web3 top-100 Pulse meme tokens scored by breakout potential.

    GET pulse/exclusive/rank/list/ai. chainId (default 56=BSC).
    """
    json_ = await _get(MEME_RANK_API, {"chainId": chainId}, WEB3_HEADERS)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    tokens = (json_.get("data") or {}).get("tokens") or []

    result = [{
        "symbol": t.get("symbol") or None, "contractAddress": t.get("contractAddress") or None,
        "chainId": t.get("chainId") or chainId, "rank": int(_num(t.get("rank"))),
        "score": _num(t.get("score")), "alphaStatus": int(_num(t.get("alphaStatus"))),
        "price": _num(t.get("price")), "marketCap": _num(t.get("marketCap")),
        "liquidity": _num(t.get("liquidity")), "volume": _num(t.get("volume")),
        "priceChange": _num(t.get("percentChange")), "priceChange7d": _num(t.get("percentChange7d")),
        "holders": int(_num(t.get("holders"))), "kycHolders": int(_num(t.get("kycHolders"))),
        "bnUniqueHolders": int(_num(t.get("bnUniqueHolders"))), "txCount": int(_num(t.get("count"))),
        "createTime": int(_num(t.get("createTime"))), "name": (t.get("metaInfo") or {}).get("name") or None,
    } for t in tokens[:30]]

    alpha_tokens = [t.get("symbol") for t in tokens if t.get("alphaStatus") == 1]
    return {"chainId": chainId, "count": len(tokens), "alphaListed": alpha_tokens, "tokens": result}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Meme launchpad tracker (new/finalizing/migrated tokens).")
async def binance_meme_rush(
    context: Context, chainId: str = "CT_501", stage: str = "new", limit: int = 30,
    protocol: str = "", progress_min: str = "", progress_max: str = "",
    mcap_min: str = "", mcap_max: str = "", vol_min: str = "", vol_max: str = "",
    holders_min: Optional[int] = None, no_wash: bool = False,
    dev_sold: bool = False, burned: bool = False,
) -> dict:
    """Binance Web3 meme launchpad tracker (replicates binance-meme-rush).

    POST pulse/rank/list/ai. stage=new|finalizing|migrated, limit<=200,
    protocol=comma-list of codes; filters mirror the legacy CLI flags.
    """
    rank_type = MEME_RUSH_STAGES.get(stage, 10)
    body: dict = {"chainId": chainId, "rankType": rank_type, "limit": min(limit, 200)}
    if protocol:
        body["protocol"] = [int(x) for x in protocol.split(",")]
    if progress_min != "":
        body["progressMin"] = progress_min
    if progress_max != "":
        body["progressMax"] = progress_max
    if mcap_min != "":
        body["marketCapMin"] = mcap_min
    if mcap_max != "":
        body["marketCapMax"] = mcap_max
    if vol_min != "":
        body["volumeMin"] = vol_min
    if vol_max != "":
        body["volumeMax"] = vol_max
    if holders_min is not None:
        body["holdersMin"] = holders_min
    if no_wash:
        body["excludeDevWashTrading"] = 1
        body["excludeInsiderWashTrading"] = 1
    if dev_sold:
        body["devPosition"] = 2
    if burned:
        body["devBurnedToken"] = 1

    json_ = await _post_json(MEME_RUSH_API, body)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    tokens = json_.get("data") or []

    result = [{
        "symbol": t.get("symbol") or None, "name": t.get("name") or None,
        "contractAddress": t.get("contractAddress") or None, "chainId": t.get("chainId") or chainId,
        "stage": MEME_RUSH_STAGE_LABELS.get(rank_type), "protocol": t.get("protocol") or None,
        "protocolName": MEME_RUSH_PROTOCOLS.get(t.get("protocol")), "progress": _num(t.get("progress")),
        "price": _num(t.get("price")), "priceChange": _num(t.get("priceChange")),
        "marketCap": _num(t.get("marketCap")), "liquidity": _num(t.get("liquidity")),
        "volume": _num(t.get("volume")), "holders": int(_num(t.get("holders"))),
        "countBuy": int(_num(t.get("countBuy"))), "countSell": int(_num(t.get("countSell"))),
        "holdersTop10Pct": _num(t.get("holdersTop10Percent")), "holdersDevPct": _num(t.get("holdersDevPercent")),
        "holdersSniperPct": _num(t.get("holdersSniperPercent")), "holdersInsiderPct": _num(t.get("holdersInsiderPercent")),
        "bundlerHoldingPct": _num(t.get("bundlerHoldingPercent")), "devAddress": t.get("devAddress") or None,
        "devSellPercent": _num(t.get("devSellPercent")), "devMigrateCount": _num(t.get("devMigrateCount")),
        "devSoldAll": t.get("devPosition") == 2, "devBurned": t.get("tagDevBurnedToken") == 1,
        "devWashTrading": t.get("tagDevWashTrading") == 1, "insiderWashTrading": t.get("tagInsiderWashTrading") == 1,
        "migrateStatus": t.get("migrateStatus") or 0, "migrateTime": int(_num(t.get("migrateTime"))),
        "createTime": int(_num(t.get("createTime"))), "exclusive": t.get("exclusive") == 1,
        "narrative": (t.get("narrativeText") or {}).get("en") or None,
        "socials": {
            "website": (t.get("socials") or {}).get("website") or None,
            "twitter": (t.get("socials") or {}).get("twitter") or None,
            "telegram": (t.get("socials") or {}).get("telegram") or None,
        },
    } for t in tokens]

    return {
        "chainId": chainId, "stage": MEME_RUSH_STAGE_LABELS.get(rank_type), "count": len(tokens),
        "summary": {
            "burned": sum(1 for t in tokens if t.get("tagDevBurnedToken") == 1),
            "devWashTrading": sum(1 for t in tokens if t.get("tagDevWashTrading") == 1),
            "migrated": sum(1 for t in tokens if t.get("migrateStatus") == 1),
        },
        "tokens": result,
    }


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Social-hype leaderboard with sentiment + AI summaries.")
async def binance_social_hype(context: Context, chainId: str = "56",
                              sentiment: str = "All", lang: str = "en") -> dict:
    """Binance Web3 social-hype leaderboard (replicates binance-social-hype).

    GET pulse/social/hype/rank/leaderboard/ai. socialLanguage=ALL, timeRange=1 fixed.
    """
    params = {"chainId": chainId, "sentiment": sentiment, "socialLanguage": "ALL",
              "targetLanguage": lang, "timeRange": "1"}
    json_ = await _get(SOCIAL_HYPE_API, params, WEB3_HEADERS)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    tokens = (json_.get("data") or {}).get("leaderBoardList") or []

    result = []
    for t in tokens[:20]:
        meta = t.get("metaInfo") or {}
        market = t.get("marketInfo") or {}
        social = t.get("socialHypeInfo") or {}
        result.append({
            "symbol": meta.get("symbol") or None, "contractAddress": meta.get("contractAddress") or None,
            "chainId": meta.get("chainId") or chainId, "socialHype": _num(social.get("socialHype")),
            "sentiment": social.get("sentiment") or None, "marketCap": _num(market.get("marketCap")),
            "priceChange": _num(market.get("priceChange")),
            "summary": social.get("socialSummaryBriefTranslated") or social.get("socialSummaryBrief") or None,
            "detailedSummary": social.get("socialSummaryDetailTranslated") or social.get("socialSummaryDetail") or None,
        })

    return {"chainId": chainId, "sentiment": sentiment, "count": len(tokens), "tokens": result}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Unified token rankings (trending/search/alpha/stock).")
async def binance_token_rank(
    context: Context, chainId: str = "56", type: str = "trending", period: str = "24h",
    sort: str = "default", asc: bool = False, size: int = 20, page: int = 1,
    mcap_min: Optional[float] = None, mcap_max: Optional[float] = None,
    vol_min: Optional[float] = None, vol_max: Optional[float] = None,
    liq_min: Optional[float] = None, liq_max: Optional[float] = None,
) -> dict:
    """Binance Web3 unified token rankings (replicates binance-token-rank).

    POST pulse/unified/rank/list/ai. period=1m|5m|1h|4h|24h, sort key, size<=200.
    """
    body: dict = {
        "rankType": TOKEN_RANK_RANK_TYPES.get(type, 10), "chainId": chainId,
        "period": TOKEN_RANK_PERIODS.get(period, 50), "sortBy": TOKEN_RANK_SORT_MAP.get(sort, 0),
        "orderAsc": asc, "page": page, "size": min(size, 200),
    }
    if mcap_min is not None:
        body["marketCapMin"] = mcap_min
    if mcap_max is not None:
        body["marketCapMax"] = mcap_max
    if vol_min is not None:
        body["volumeMin"] = vol_min
    if vol_max is not None:
        body["volumeMax"] = vol_max
    if liq_min is not None:
        body["liquidityMin"] = liq_min
    if liq_max is not None:
        body["liquidityMax"] = liq_max

    json_ = await _post_json(TOKEN_RANK_API, body)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    data = json_.get("data") or {}
    tokens = data.get("tokens") or []

    result = [{
        "symbol": t.get("symbol") or None, "contractAddress": t.get("contractAddress") or None,
        "chainId": t.get("chainId") or chainId, "price": _num(t.get("price")),
        "marketCap": _num(t.get("marketCap")), "liquidity": _num(t.get("liquidity")),
        "holders": int(_num(t.get("holders"))), "volume24h": _num(t.get("volume24h")),
        "priceChange24h": _num(t.get("percentChange24h")), "priceChange1h": _num(t.get("percentChange1h")),
        "launchTime": int(_num(t.get("launchTime"))), "kycHolders": int(_num(t.get("kycHolders"))),
        "holdersTop10Pct": _num(t.get("holdersTop10Percent")),
    } for t in tokens]

    return {"type": type, "chainId": chainId, "period": period, "total": data.get("total") or 0,
            "page": page, "showing": len(tokens), "tokens": result}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="AI hot-topic narratives with associated tokens by net inflow.")
async def binance_topic_rush(
    context: Context, chainId: str = "CT_501", type: str = "latest", sort: str = "time",
    asc: bool = False, keyword: str = "", inflow_min: str = "",
) -> dict:
    """Binance Web3 AI hot-topic narratives (replicates binance-topic-rush).

    GET v2 social-rush/rank/list/ai. type=latest|rising, sort=time|inflow.
    """
    params = {"chainId": chainId, "rankType": str(TOPIC_RUSH_TYPES.get(type, 10)),
              "sort": str(TOPIC_RUSH_SORTS.get(sort, 10)), "asc": str(asc).lower()}
    if keyword:
        params["keywords"] = keyword
    if inflow_min:
        params["netInflowMin"] = inflow_min

    json_ = await _get(TOPIC_RUSH_API, params, WEB3_HEADERS)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    topics = json_.get("data") or []

    result = []
    for t in topics:
        token_list = t.get("tokenList") or []
        result.append({
            "topicId": t.get("topicId") or None, "name": _topic_name(t.get("name")),
            "type": t.get("type") or None, "chainId": t.get("chainId") or chainId,
            "netInflow": _num(t.get("topicNetInflow")), "netInflow1h": _num(t.get("topicNetInflow1h")),
            "netInflowAth": _num(t.get("topicNetInflowAth")),
            "tokenCount": t.get("tokenSize") or len(token_list),
            "createTime": int(_num(t.get("createTime"))), "closed": t.get("close") == 1,
            "progress": _num(t.get("progress")),
            "aiSummary": (t.get("aiSummary") or {}).get("en") or (t.get("aiSummary") or {}).get("cn") or None,
            "topicLink": t.get("topicLink") or None,
            "tokens": [{
                "symbol": tk.get("symbol") or None, "contractAddress": tk.get("contractAddress") or None,
                "chainId": tk.get("chainId") or chainId, "marketCap": _num(tk.get("marketCap")),
                "liquidity": _num(tk.get("liquidity")), "netInflow": _num(tk.get("netInflow")),
                "netInflow1h": _num(tk.get("netInflow1h")), "priceChange24h": _num(tk.get("priceChange24h")),
                "holders": int(_num(tk.get("holders"))), "kolHolders": int(_num(tk.get("kolHolders"))),
                "smartMoneyHolders": int(_num(tk.get("smartMoneyHolders"))), "protocol": tk.get("protocol") or None,
                "onBondingCurve": tk.get("internal") == 1, "migrated": tk.get("migrateStatus") == 1,
            } for tk in token_list[:10]],
        })

    return {"type": "Rising" if type == "rising" else "Latest",
            "chainId": chainId, "count": len(topics), "topics": result}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Smart-money buy/sell signals (trigger price, max gain, exit rate).")
async def binance_trading_signal(
    context: Context, chainId: str = "CT_501", size: int = 50, page: int = 1,
    active_only: bool = False, buys_only: bool = False, sells_only: bool = False,
) -> dict:
    """Binance Web3 smart-money buy/sell signals (replicates binance-trading-signal).

    POST web/signal/smart-money/ai. size<=100; active/buys/sells filter client-side.
    """
    body = {"smartSignalType": "", "page": page, "pageSize": min(size, 100), "chainId": chainId}
    json_ = await _post_json(TRADING_SIGNAL_API, body)
    if not json_.get("success") or json_.get("code") != "000000":
        raise RuntimeError(f"API error: {json_.get('code')} {json_.get('message', '')}")
    signals = json_.get("data") or []

    if active_only:
        signals = [s for s in signals if s.get("status") == "active"]
    if buys_only:
        signals = [s for s in signals if s.get("direction") == "buy"]
    if sells_only:
        signals = [s for s in signals if s.get("direction") == "sell"]

    active = [s for s in signals if s.get("status") == "active"]
    buys = [s for s in signals if s.get("direction") == "buy"]
    sells = [s for s in signals if s.get("direction") == "sell"]

    best_active = sorted([s for s in active if s.get("direction") == "buy"],
                         key=lambda s: _num(s.get("maxGain")), reverse=True)[:5]
    top_buys = [{
        "ticker": s.get("ticker"), "smartMoneyCount": int(_num(s.get("smartMoneyCount"))),
        "maxGain": _num(s.get("maxGain")),
        "currentDelta": _price_delta(s.get("alertPrice"), s.get("currentPrice")),
        "exitRate": _num(s.get("exitRate")),
    } for s in best_active]

    result = [{
        "signalId": s.get("signalId"), "ticker": s.get("ticker") or None,
        "contractAddress": s.get("contractAddress") or None, "chainId": s.get("chainId") or chainId,
        "direction": s.get("direction") or None, "status": s.get("status") or None,
        "smartMoneyCount": int(_num(s.get("smartMoneyCount"))), "alertPrice": _num(s.get("alertPrice")),
        "currentPrice": _num(s.get("currentPrice")),
        "priceChange": _price_delta(s.get("alertPrice"), s.get("currentPrice")),
        "highestPrice": _num(s.get("highestPrice")), "maxGain": _num(s.get("maxGain")),
        "exitRate": _num(s.get("exitRate")), "alertMarketCap": _num(s.get("alertMarketCap")),
        "currentMarketCap": _num(s.get("currentMarketCap")), "totalTokenValue": _num(s.get("totalTokenValue")),
        "signalTriggerTime": int(_num(s.get("signalTriggerTime"))), "highestPriceTime": int(_num(s.get("highestPriceTime"))),
        "isAlpha": s.get("isAlpha") or False, "launchPlatform": s.get("launchPlatform") or None,
        "signalCount": int(_num(s.get("signalCount"))), "tags": _extract_tags(s.get("tokenTag")),
    } for s in signals[:50]]

    return {"chainId": chainId, "total": len(signals), "active": len(active),
            "buys": len(buys), "sells": len(sells), "topActiveBuys": top_buys, "signals": result}


# ── technical analysis (klines-based) ────────────────────────────────────────
@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="RSI-based BUY/SELL/NEUTRAL signal (Wilder smoothing).")
async def binance_rsi_signal(context: Context, symbol: str = "ETHUSDT", interval: str = "15m",
                             period: int = 14, oversold: float = 30, overbought: float = 70) -> dict:
    """RSI-based BUY/SELL/NEUTRAL signal (replicates rsi-signal).

    GET /klines. Returns rsi, signal, price, timestamp, config.
    """
    symbol = symbol.upper()
    limit = max(period * 3, 50)
    raw = await _get(f"{SPOT_API}/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    closes = [_num(k[4]) for k in raw]
    timestamps = [k[0] for k in raw]

    def _rsi(c: list, p: int):
        if len(c) < p + 1:
            return None
        avg_gain = avg_loss = 0.0
        for i in range(1, p + 1):
            change = c[i] - c[i - 1]
            if change > 0:
                avg_gain += change
            else:
                avg_loss += abs(change)
        avg_gain /= p
        avg_loss /= p
        for i in range(p + 1, len(c)):
            change = c[i] - c[i - 1]
            gain = change if change > 0 else 0
            loss = abs(change) if change < 0 else 0
            avg_gain = (avg_gain * (p - 1) + gain) / p
            avg_loss = (avg_loss * (p - 1) + loss) / p
        if avg_loss == 0:
            return 100
        if avg_gain == 0:
            return 0
        return 100 - 100 / (1 + avg_gain / avg_loss)

    rsi_value = _rsi(closes, period)
    if rsi_value is None:
        return {"symbol": symbol, "interval": interval, "rsi": None, "signal": "NO_DATA",
                "price": None, "timestamp": None,
                "config": {"period": period, "oversold": oversold, "overbought": overbought}}

    signal = "NEUTRAL"
    if rsi_value < oversold:
        signal = "BUY"
    elif rsi_value > overbought:
        signal = "SELL"

    return {"symbol": symbol, "interval": interval, "rsi": round(rsi_value * 10) / 10,
            "signal": signal, "price": closes[-1], "timestamp": timestamps[-1],
            "config": {"period": period, "oversold": oversold, "overbought": overbought}}


async def _ta_snapshot(symbol: str, interval: str, limit: int) -> dict:
    """Compute the technical-analysis snapshot (shared by the TA tool and the
    trend-momentum entry tool). Faithful port of technical-analysis + snapshot."""
    symbol = symbol.upper()
    limit = max(35, min(1000, int(limit)))
    raw = await _get(f"{SPOT_API}/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not raw:
        return {"error": f"No kline data returned for {symbol} ({interval})"}

    timestamps, highs, lows, closes, volumes = [], [], [], [], []
    for k in raw:
        timestamps.append(k[0])
        highs.append(float(k[2]))
        lows.append(float(k[3]))
        closes.append(float(k[4]))
        volumes.append(float(k[5]))

    price = closes[-1]
    ts = timestamps[-1]

    ema20 = r2(ema(closes, 20))
    ema50 = r2(ema(closes, 50))
    ema200 = r2(ema(closes, 200))
    trend = {
        "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "priceAboveEma20": price_above(price, ema20),
        "priceAboveEma50": price_above(price, ema50),
        "bullishStacked": bullish_stacked(ema20, ema50, ema200),
    }

    rsi_val = r1(rsi(closes, 14))
    macd_val = macd(closes, 12, 26, 9)
    momentum = {
        "rsi": rsi_val,
        "rsiOversold": (rsi_val < 30) if rsi_val is not None else None,
        "rsiOverbought": (rsi_val > 70) if rsi_val is not None else None,
        "macd": ({
            "value": r2(macd_val["value"]), "signal": r2(macd_val["signal"]),
            "histogram": r2(macd_val["histogram"]),
            "bullish": macd_val["value"] > macd_val["signal"],
        } if macd_val is not None else None),
    }

    bol_val = bollinger(closes, 20, 2)
    volatility = {
        "bollinger": ({
            "upper": r2(bol_val["upper"]), "middle": r2(bol_val["middle"]),
            "lower": r2(bol_val["lower"]), "widthRatio": r3(bol_val["widthRatio"]),
        } if bol_val is not None else None),
        "atr": r2(atr(highs, lows, closes, 14)),
    }

    vwap_val = r2(vwap(highs, lows, closes, volumes))
    vol_spike = volume_spike(volumes, 20, 1.5)
    volume = {
        "vwap": vwap_val, "priceAboveVwap": price_above(price, vwap_val),
        "relativeVolume": r1(vol_spike["relativeVolume"]) if vol_spike else None,
        "volumeSpike": vol_spike["spike"] if vol_spike else None,
    }

    return {"symbol": symbol, "interval": interval, "timestamp": ts, "price": r2(price),
            "trend": trend, "momentum": momentum, "volatility": volatility, "volume": volume}


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Comprehensive TA snapshot (EMA/RSI/MACD/Bollinger/ATR/VWAP).")
async def binance_technical_analysis(context: Context, symbol: str = "BTCUSDT",
                                     interval: str = "4h", limit: int = 200) -> dict:
    """Comprehensive TA snapshot from Binance klines (replicates technical-analysis).

    Computes EMA(20/50/200), RSI(14), MACD(12/26/9), Bollinger(20,2), ATR(14),
    VWAP and volume-spike. limit clamped to [35, 1000].
    """
    return await _ta_snapshot(symbol, interval, limit)


@mcp.tool()
@require_payment_for_tool(price=FREE_PRICE, description="Rule-based entry signal LONG/SHORT/NO_TRADE with confidence.")
async def binance_trend_momentum_entry(context: Context, symbol: str = "BTCUSDT",
                                       interval: str = "4h", limit: int = 200, spot: bool = False) -> dict:
    """Rule-based entry signal (replicates trend-momentum-entry).

    Fetches the TA snapshot internally, evaluates 5 trend/momentum patterns with
    historical-rate-blended confidence (60% rules + 40% history). spot=True maps
    LONG/SHORT/NO_TRADE -> BUY/SELL/NEUTRAL.
    """
    snapshot = await _ta_snapshot(symbol, interval, limit)
    missing = [k for k in ("trend", "momentum", "volatility", "volume") if not snapshot.get(k)]
    if missing:
        return {"error": f"snapshot missing sections: {', '.join(missing)}"}

    result = evaluate(snapshot)

    def map_action(action):
        if not spot:
            return action
        return {"LONG": "BUY", "SHORT": "SELL"}.get(action, "NEUTRAL")

    return {**result, "action": map_action(result["action"])}

# END_CUSTOM_TOOLS


# ── Plain-REST face (reliable agent routing) ────────────────────────────────
# The MCP session handshake (initialize -> mcp-session-id -> tools/call over SSE)
# is unreliable to drive from an agent's generic http_fetch tool, so we ALSO
# expose every tool as a simple `POST /v1/binance/<tool>` with a JSON arg body —
# the same pattern that makes the talib-signals-backed skills reliable. The tool
# bodies don't use `context` (it's only accepted for the MCP/payment wrapper),
# and @require_payment_for_tool is metadata-only, so the functions are directly
# callable with context=None.
_REST_TOOLS = {
    "binance_klines": binance_klines,
    "binance_orderbook": binance_orderbook,
    "binance_whale_activity": binance_whale_activity,
    "binance_pnl_leaderboard": binance_pnl_leaderboard,
    "binance_smart_money_inflows": binance_smart_money_inflows,
    "binance_meme_rank": binance_meme_rank,
    "binance_meme_rush": binance_meme_rush,
    "binance_social_hype": binance_social_hype,
    "binance_token_rank": binance_token_rank,
    "binance_topic_rush": binance_topic_rush,
    "binance_trading_signal": binance_trading_signal,
    "binance_rsi_signal": binance_rsi_signal,
    "binance_technical_analysis": binance_technical_analysis,
    "binance_trend_momentum_entry": binance_trend_momentum_entry,
}


async def _rest_dispatch(request: Request) -> JSONResponse:
    """POST /v1/binance/<tool> with a JSON body of the tool's args. Free; no MCP session."""
    tool = request.path_params.get("tool", "")
    fn = _REST_TOOLS.get(tool)
    if fn is None:
        return JSONResponse(
            {"error": f"unknown tool '{tool}'", "available": sorted(_REST_TOOLS)},
            status_code=404,
        )
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    try:
        result = await fn(context=None, **body)
        return JSONResponse(result)
    except TypeError as e:
        return JSONResponse({"error": f"bad request params: {e}"}, status_code=400)
    except Exception as e:  # upstream/runtime failure
        logger.exception("REST dispatch failed for tool %s", tool)
        return JSONResponse({"error": str(e)}, status_code=502)


# ============================================================================
# APPLICATION SETUP WITH STARLETTE MIDDLEWARE
# ============================================================================
def create_app_with_middleware():
    """Create Starlette app with d402 payment middleware (price-0 tools => free)."""
    logger.info("🔧 Creating FastMCP app with middleware...")
    app = mcp.streamable_http_app()

    tool_payment_configs = extract_payment_configs_from_mcp(mcp, SERVER_ADDRESS)
    logger.info(f"📊 Extracted {len(tool_payment_configs)} payment configs from decorators")

    facilitator_url = os.getenv("FACILITATOR_URL") or os.getenv("D402_FACILITATOR_URL")
    operator_key = os.getenv("MCP_OPERATOR_PRIVATE_KEY")
    network = os.getenv("NETWORK") or os.getenv("DEFAULT_SETTLEMENT_NETWORK", "arbitrum_one")
    testing_mode = os.getenv("D402_TESTING_MODE", "true").lower() == "true"

    logger.info("=" * 60)
    logger.info("D402 Payment Protocol Configuration:")
    logger.info(f"  Server Address: {SERVER_ADDRESS}")
    logger.info(f"  Network: {network}")
    logger.info(f"  Operator Key: {'✅ Set' if operator_key else '❌ Not set'}")
    logger.info(f"  Testing Mode: {testing_mode}")
    logger.info("=" * 60)

    if not facilitator_url and not testing_mode:
        raise ValueError("Set FACILITATOR_URL or enable D402_TESTING_MODE=true")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
    app.add_middleware(
        D402PaymentMiddleware,
        tool_payment_configs=tool_payment_configs,
        server_address=SERVER_ADDRESS,
        requires_auth=False,
        internal_api_key=None,
        testing_mode=testing_mode,
        facilitator_url=facilitator_url,
        facilitator_api_key=os.getenv("D402_FACILITATOR_API_KEY"),
        server_name="binance-data-mcp-server",
    )
    logger.info("✅ Added D402PaymentMiddleware (price-0 tools = free)")

    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse(content={
            "status": "healthy", "service": "binance-data-mcp-server",
            "timestamp": datetime.now().isoformat(),
        })
    app.router.routes.append(Route("/health", health_check, methods=["GET"]))
    logger.info("✅ Added /health endpoint")

    # Plain-REST face for reliable agent routing (parallel to /mcp).
    app.router.routes.append(Route("/v1/binance/{tool}", _rest_dispatch, methods=["POST"]))
    logger.info("✅ Added /v1/binance/{tool} REST routes (%d tools)", len(_REST_TOOLS))

    return app


if __name__ == "__main__":
    logger.info("Starting binance-data MCP Server")
    app = create_app_with_middleware()
    uvicorn.run(app, host="0.0.0.0", port=PORT,
                log_level=os.getenv("LOG_LEVEL", "info").lower())
