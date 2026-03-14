# 🧠 Token Sentiment Score

An **x402-gated** FastAPI microservice that analyzes recent social media mentions of any crypto token and returns a sentiment score from **-100** (very negative) to **+100** (very positive).

Built on [x402](https://x402.org) — pay-per-call with USDC on Base. No API keys, no accounts, no friction.

---

## How it works

1. Client sends `POST /api/analyze` with a token symbol and name
2. Service checks for an `X-PAYMENT` header (x402 protocol)
3. If missing → returns **402 Payment Required** with payment details
4. Client attaches USDC payment proof and retries
5. Service queries Brave Search for recent Twitter/Reddit mentions
6. Keyword-based sentiment analysis returns a structured score

---

## Endpoints

### `POST /api/analyze` *(requires x402 payment)*

**Request body:**
```json
{
  "token_symbol": "BTC",
  "token_name": "Bitcoin",
  "chain_id": 8453
}
```

**Response:**
```json
{
  "token_symbol": "BTC",
  "token_name": "Bitcoin",
  "sentiment_score": 42.5,
  "mention_count": 18,
  "positive_ratio": 0.61,
  "negative_ratio": 0.22,
  "neutral_ratio": 0.17,
  "summary": "Sentiment for BTC (Bitcoin) is mildly positive based on 18 recent social mentions. 61% positive, 22% negative, 17% neutral. Score: +42.5/100.",
  "search_available": true
}
```

### `GET /health`

Returns service health and configuration status.

### `GET /mcp` or `GET /mcp.json`

Returns the MCP (Model Context Protocol) manifest for AI agent discovery.

---

## x402 Payment Details

| Field | Value |
|-------|-------|
| Network | Base (chain ID 8453) |
| Asset | USDC |
| Price | $0.05 per call (50,000 USDC units) |
| Receive address | Set via `WALLET_ADDRESS` env var |

### Payment flow (x402)

```
Client → POST /api/analyze (no payment header)
Server → 402 Payment Required + payment details
Client → pays via Base/USDC, attaches X-PAYMENT header
Client → POST /api/analyze (with X-PAYMENT header)
Server → 200 OK + sentiment data
```

---

## Setup

### Environment variables

```bash
cp .env.example .env
# Edit .env:
WALLET_ADDRESS=0xYourWalletAddressHere
BRAVE_SEARCH_API_KEY=your_brave_api_key_here  # optional
```

Get a Brave Search API key at [brave.com/search/api](https://brave.com/search/api/) (free tier available).

### Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Run with Docker

```bash
docker build -t token-sentiment-api .
docker run -p 8080:8080 \
  -e WALLET_ADDRESS=0xYourAddress \
  -e BRAVE_SEARCH_API_KEY=your_key \
  token-sentiment-api
```

---

## Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

1. Fork this repo
2. Connect to Railway
3. Set env vars: `WALLET_ADDRESS`, `BRAVE_SEARCH_API_KEY`
4. Deploy — Railway auto-detects the Dockerfile

The `railway.toml` is pre-configured with the Dockerfile builder and `/health` healthcheck.

---

## Architecture

```
FastAPI (port 8080)
├── POST /api/analyze     ← x402-gated sentiment endpoint
├── GET  /health          ← health check (no payment required)
├── GET  /mcp             ← MCP manifest for AI agents
└── GET  /mcp.json        ← same manifest (alt path)
```

**Sentiment engine:** Keyword-based lexicon (no external ML dependency). Fast, deterministic, and free to run.

**Search:** Brave Web Search API — queries `{SYMBOL} {NAME} crypto site:twitter.com OR site:reddit.com` with `freshness=pw` (past week).

---

## License

MIT
