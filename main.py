"""
Token Sentiment Score — x402-gated FastAPI service.
Accepts a crypto token symbol/name, searches recent social mentions via Brave Search,
and returns a sentiment score from -100 to +100.
"""

import os
import re
import json
import math
import textwrap
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BRAVE_API_KEY: Optional[str] = os.getenv("BRAVE_SEARCH_API_KEY")
WALLET_ADDRESS: str = os.getenv("WALLET_ADDRESS", "0x0000000000000000000000000000000000000000")
PORT: int = 8080

# x402 payment config
X402_PRICE_USDC_UNITS = 50000   # $0.05 in USDC (6 decimals)
X402_NETWORK = "base"
X402_ASSET = "USDC"

# ---------------------------------------------------------------------------
# Simple keyword-based sentiment lexicon
# ---------------------------------------------------------------------------
POSITIVE_WORDS = {
    "bullish", "moon", "pump", "surge", "rally", "gain", "gains", "up",
    "ath", "high", "buy", "buying", "long", "growth", "profit", "profits",
    "win", "winning", "great", "good", "excellent", "amazing", "awesome",
    "hodl", "accumulate", "undervalued", "breakout", "potential", "adoption",
    "partnership", "launch", "listing", "positive", "strong", "strength",
    "support", "recovery", "recover", "rise", "rising", "rise", "soar",
    "outperform", "upgrade", "opportunity", "boom",
}
NEGATIVE_WORDS = {
    "bearish", "dump", "crash", "drop", "fall", "sell", "selling", "short",
    "loss", "losses", "low", "down", "scam", "fraud", "rug", "rugpull",
    "bad", "terrible", "awful", "horrible", "panic", "fear", "uncertain",
    "overvalued", "bubble", "collapse", "hack", "exploit", "attack",
    "delist", "delisted", "ban", "banned", "negative", "weak", "weakness",
    "risk", "danger", "warning", "caution", "decline", "declining",
    "underperform", "downgrade", "manipulation",
}


def score_text(text: str) -> float:
    """Return a raw sentiment value for a snippet of text."""
    words = re.findall(r"\b\w+\b", text.lower())
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total  # -1 to +1


# ---------------------------------------------------------------------------
# Brave Search helper
# ---------------------------------------------------------------------------
async def brave_search(query: str, count: int = 20) -> dict:
    """Call the Brave Web Search API and return the raw response dict."""
    if not BRAVE_API_KEY:
        return {"_unavailable": True}

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {
        "q": query,
        "count": count,
        "freshness": "pw",   # past week
        "text_decorations": False,
        "search_lang": "en",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# x402 middleware (lightweight manual implementation)
# ---------------------------------------------------------------------------

def build_payment_required_response(path: str, base_url: str = "") -> JSONResponse:
    """Return a 402 Payment Required response per the x402 spec."""
    resource = (base_url.rstrip("/") + path) if base_url else path
    payload = {
        "x402Version": 1,
        "error": "Payment required",
        "accepts": [
            {
                "scheme": "exact",
                "network": X402_NETWORK,
                "maxAmountRequired": str(X402_PRICE_USDC_UNITS),
                "resource": resource,
                "description": "Token Sentiment Score API call",
                "mimeType": "application/json",
                "payTo": WALLET_ADDRESS,
                "maxTimeoutSeconds": 300,
                "asset": f"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC on Base
                "extra": {
                    "name": "USD Coin",
                    "version": "2",
                },
            }
        ],
    }
    return JSONResponse(status_code=402, content=payload)


def verify_payment_header(request: Request) -> bool:
    """
    Verify the X-PAYMENT header is present and structurally valid.
    In production, you would call the x402 facilitator to verify on-chain settlement.
    Here we accept any non-empty header value to keep the service self-contained.
    """
    payment_header = request.headers.get("X-PAYMENT") or request.headers.get("x-payment")
    return bool(payment_header)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Token Sentiment Score",
    description="x402-gated API that returns social sentiment scores for crypto tokens.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    token_symbol: str = Field(..., example="BTC", description="Token ticker symbol")
    token_name: str = Field(..., example="Bitcoin", description="Full token name")
    chain_id: Optional[int] = Field(None, example=8453, description="Optional chain ID")


class AnalyzeResponse(BaseModel):
    token_symbol: str
    token_name: str
    sentiment_score: float = Field(..., description="Sentiment from -100 (very negative) to +100 (very positive)")
    mention_count: int
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float
    summary: str
    search_available: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "token-sentiment-score",
        "version": "1.0.0",
        "search_available": bool(BRAVE_API_KEY),
        "wallet": WALLET_ADDRESS,
        "network": X402_NETWORK,
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, body: AnalyzeRequest):
    # --- x402 gate ---
    if not verify_payment_header(request):
        base = str(request.base_url).rstrip("/")
        return build_payment_required_response("/api/analyze", base)

    symbol = body.token_symbol.upper().strip()
    name = body.token_name.strip()

    query = f"{symbol} {name} crypto site:twitter.com OR site:reddit.com"

    # --- Fetch mentions ---
    try:
        data = await brave_search(query, count=20)
    except Exception as exc:
        data = {"_error": str(exc)}

    search_available = not data.get("_unavailable") and not data.get("_error")

    if not search_available:
        reason = "Search API key not configured" if data.get("_unavailable") else f"Search error: {data.get('_error')}"
        return AnalyzeResponse(
            token_symbol=symbol,
            token_name=name,
            sentiment_score=0.0,
            mention_count=0,
            positive_ratio=0.0,
            negative_ratio=0.0,
            neutral_ratio=1.0,
            summary=f"Search unavailable — {reason}. Configure BRAVE_SEARCH_API_KEY to enable sentiment analysis.",
            search_available=False,
        )

    # --- Parse results ---
    results = data.get("web", {}).get("results", [])
    snippets = []
    for r in results:
        parts = [r.get("title", ""), r.get("description", "")]
        snippets.append(" ".join(p for p in parts if p))

    mention_count = len(snippets)

    if mention_count == 0:
        return AnalyzeResponse(
            token_symbol=symbol,
            token_name=name,
            sentiment_score=0.0,
            mention_count=0,
            positive_ratio=0.0,
            negative_ratio=0.0,
            neutral_ratio=1.0,
            summary=f"No recent social mentions found for {symbol} ({name}).",
            search_available=True,
        )

    # --- Score each snippet ---
    scores = [score_text(s) for s in snippets]
    pos_count = sum(1 for s in scores if s > 0)
    neg_count = sum(1 for s in scores if s < 0)
    neu_count = sum(1 for s in scores if s == 0)

    positive_ratio = round(pos_count / mention_count, 4)
    negative_ratio = round(neg_count / mention_count, 4)
    neutral_ratio = round(neu_count / mention_count, 4)

    avg_score = sum(scores) / mention_count  # -1 to +1
    sentiment_score = round(avg_score * 100, 2)  # scale to -100..+100

    # --- Build summary ---
    if sentiment_score >= 30:
        mood = "strongly positive"
    elif sentiment_score >= 10:
        mood = "mildly positive"
    elif sentiment_score <= -30:
        mood = "strongly negative"
    elif sentiment_score <= -10:
        mood = "mildly negative"
    else:
        mood = "neutral"

    summary = (
        f"Sentiment for {symbol} ({name}) is {mood} based on {mention_count} recent social mentions. "
        f"{round(positive_ratio * 100)}% positive, {round(negative_ratio * 100)}% negative, "
        f"{round(neutral_ratio * 100)}% neutral. Score: {sentiment_score:+.1f}/100."
    )

    return AnalyzeResponse(
        token_symbol=symbol,
        token_name=name,
        sentiment_score=sentiment_score,
        mention_count=mention_count,
        positive_ratio=positive_ratio,
        negative_ratio=negative_ratio,
        neutral_ratio=neutral_ratio,
        summary=summary,
        search_available=True,
    )


# ---------------------------------------------------------------------------
# MCP manifest
# ---------------------------------------------------------------------------
MCP_MANIFEST = {
    "schema_version": "v1",
    "name_for_human": "Token Sentiment Score",
    "name_for_model": "token_sentiment_score",
    "description_for_human": "Get social sentiment scores for any crypto token using recent Twitter and Reddit mentions.",
    "description_for_model": (
        "Analyzes recent social media mentions of a crypto token and returns a sentiment score "
        "from -100 (very negative) to +100 (very positive), along with positive/negative/neutral ratios "
        "and a plain-English summary. Requires x402 micropayment ($0.05 per call on Base network)."
    ),
    "auth": {
        "type": "x402",
        "network": X402_NETWORK,
        "price_usd": 0.05,
    },
    "api": {
        "type": "openapi",
        "url": "/openapi.json",
    },
    "tools": [
        {
            "name": "analyze_token_sentiment",
            "description": "Analyze social sentiment for a crypto token.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "token_symbol": {"type": "string", "description": "Ticker symbol, e.g. BTC"},
                    "token_name": {"type": "string", "description": "Full name, e.g. Bitcoin"},
                    "chain_id": {"type": "integer", "description": "Optional chain ID, e.g. 8453 for Base"},
                },
                "required": ["token_symbol", "token_name"],
            },
            "endpoint": {
                "method": "POST",
                "path": "/api/analyze",
            },
        }
    ],
}


@app.get("/mcp")
@app.get("/mcp.json")
async def mcp_manifest():
    return JSONResponse(content=MCP_MANIFEST)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
