"""FastAPI backend (Task 5.1).

    uvicorn backend.api.main:app --reload

Endpoints
    GET  /api/health                  liveness + whether the LLM key is present
    GET  /api/price/{ticker}          OHLCV for the chart, capped at as_of
    GET  /api/evidence/{ticker}       the evidence pack, no model calls
    POST /api/forecast/{ticker}       run the pipeline, return the finished result
    WS   /api/stream/{ticker}         run the pipeline, stream each stage as it lands

OWNERSHIP OF THE LIVE UX IS THE WEBSOCKET, NOT THE POST. A full multi-agent
forecast takes 30-90 seconds. Many proxies and load balancers cut an idle HTTP
request well before that, so a POST that runs the whole pipeline is a request
that works in development and times out in front of an audience. The POST is kept
because it is the honest programmatic interface, and it is documented as slow; the
dashboard uses the WebSocket.

THE INDIA BOUNDARY IS ENFORCED HERE TOO, with the same error text the CLI uses. A
boundary that holds in one entry point and not another is not a boundary.

SECURITY (the section any AI-agent viva asks about):
  - CORS is an explicit allowlist. Never allow_origins=["*"] — with credentials
    enabled that is an open door, and it costs nothing to name the two origins
    this project actually serves.
  - A simple per-IP rate limit, in-process. Enough for a single-node demo; it is
    not a substitute for a real gateway and is documented as such.
  - No secret ever crosses this boundary. /api/health reports whether a key is
    configured, never any part of the key itself.
  - Ticker input is validated by tickers.resolve() before it reaches any fetch,
    so a crafted symbol cannot become a URL or a filesystem path downstream.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import llm
from backend.config import Config
from backend.tools import calendar_nse
from backend.tools.tickers import UnsupportedMarketError, resolve

app = FastAPI(
    title="Multi-Agent Financial Forecasting — NSE/BSE",
    description=(
        "Leakage-free multi-agent forecasting for Indian equities. "
        "Every endpoint takes an as_of date and cannot see past it."
    ),
    version="1.0.0",
)

# Explicit origins only: the Streamlit dashboard and local development.
ALLOWED_ORIGINS = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60
# Forecasts are far more expensive than reads -- they cost real LLM quota.
FORECAST_LIMIT_REQUESTS = 5

_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(client_ip: str, path: str) -> bool:
    """Sliding-window counter, per IP.

    In-process and therefore per-worker: it protects a single-node demo from a
    runaway client or a refresh loop, not from a determined attacker. Production
    would put this in the gateway. Saying which one you built matters more than
    pretending the simple one is the other.
    """
    limit = FORECAST_LIMIT_REQUESTS if "forecast" in path or "stream" in path \
        else RATE_LIMIT_REQUESTS
    now = time.time()
    bucket = _hits[f"{client_ip}:{limit}"]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    if request.url.path.startswith("/api/") and _rate_limited(client_ip, request.url.path):
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Try again in "
                               f"{RATE_LIMIT_WINDOW_SECONDS} seconds."},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------
class ForecastRequest(BaseModel):
    as_of: str = Field(description="YYYY-MM-DD cutoff. The system cannot see past it.")
    system: str = Field(default="multiagent",
                        description="multiagent | multiagent-nodebate | baseline")
    horizon_sessions: int = Field(default=Config.HORIZON_SESSIONS)
    drop: list[str] = Field(default_factory=list,
                            description="specialists to leave out, for ablation")
    nonce: str = Field(default="", description="cache-buster for repeat runs")


def _resolve_or_400(ticker: str, as_of: Optional[date] = None) -> str:
    """The India boundary, returning the same message the CLI prints."""
    try:
        return resolve(ticker, as_of=as_of)
    except UnsupportedMarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise HTTPException(status_code=400,
                            detail=f"'{value}' is not a valid YYYY-MM-DD date") from exc


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    """Liveness, plus what the system can currently do.

    Reports only WHETHER a key is configured. The key itself never crosses this
    boundary, in any form.
    """
    return {
        "status": "ok",
        "market": "NSE/BSE (Indian equities only)",
        "currency": Config.CURRENCY,
        "benchmark": Config.BENCHMARK,
        "horizon_sessions": Config.HORIZON_SESSIONS,
        "llm_configured": llm.is_configured(),
        "llm_model": Config.GEMINI_MODEL if llm.is_configured() else None,
        "available_systems": (
            ["baseline", "multiagent", "multiagent-nodebate"]
            if llm.is_configured() else ["naive-momentum", "naive-alwaysup"]
        ),
    }


@app.get("/api/price/{ticker}")
def price(
    ticker: str,
    as_of: str = Query(..., description="YYYY-MM-DD"),
    sessions: int = Query(250, ge=20, le=2000),
) -> dict:
    """OHLCV for the chart. Never returns a row after as_of."""
    as_of_d = _parse_date(as_of)
    resolved = _resolve_or_400(ticker, as_of_d)

    from backend.tools import market_data

    snapped = calendar_nse.previous_trading_day(as_of_d)
    start = date(snapped.year - 3, snapped.month, min(snapped.day, 28))
    try:
        df = market_data.get_price_history(
            resolved, start=start.isoformat(), end=snapped.isoformat(),
            as_of=snapped.isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"price fetch failed: {exc}") from exc

    if df.empty:
        raise HTTPException(status_code=404,
                            detail=f"no price data for {resolved} at {snapped}")

    tail = df.tail(sessions)
    return {
        "ticker": resolved,
        "as_of": snapped.isoformat(),
        "currency": Config.CURRENCY,
        "source": df.attrs.get("source", "unknown"),
        "candles": [
            {
                "date": idx.date().isoformat(),
                "open": round(float(row.open), 2),
                "high": round(float(row.high), 2),
                "low": round(float(row.low), 2),
                "close": round(float(row.close), 2),
                "volume": int(row.volume),
            }
            for idx, row in tail.iterrows()
        ],
    }


@app.get("/api/evidence/{ticker}")
def evidence(
    ticker: str,
    as_of: str = Query(..., description="YYYY-MM-DD"),
    extras: bool = Query(False, description="include fundamentals, news and macro"),
) -> dict:
    """The evidence pack, with no model calls. Useful for demonstrating the
    leakage controls without spending quota."""
    as_of_d = _parse_date(as_of)
    _resolve_or_400(ticker, as_of_d)

    from backend.context import build as build_context

    try:
        ctx = build_context(ticker, as_of_d, with_fundamentals=extras,
                            with_news=extras, with_macro=extras)
    except UnsupportedMarketError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "ticker": ctx.ticker,
        "as_of": str(ctx.as_of),
        "last_close": ctx.last_close,
        "sessions_loaded": len(ctx.prices),
        "source": ctx.source,
        "horizon_sessions": ctx.horizon_sessions,
        "target_date": str(ctx.target_date) if ctx.target_date else None,
        "indicators": ctx.indicators,
        "benchmark": ctx.benchmark,
        "fundamentals": ctx.fundamentals,
        "news": ctx.news,
        "macro": ctx.macro,
        "notes": ctx.notes,
    }


@app.post("/api/forecast/{ticker}")
async def forecast(ticker: str, req: ForecastRequest) -> dict:
    """Run a forecast and return the finished result.

    SLOW BY NATURE: 30-90 seconds for the full multi-agent system. Prefer the
    WebSocket for anything user-facing; this endpoint exists for scripts and for
    reproducing a single result.
    """
    as_of_d = _parse_date(req.as_of)
    _resolve_or_400(ticker, as_of_d)

    if not llm.is_configured():
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured on the server; LLM systems "
                   "are unavailable. The /api/evidence and /api/price endpoints "
                   "work without it.",
        )

    def _run() -> dict:
        from backend.eval.harness import get_forecaster

        fn = get_forecaster(req.system)
        record = fn(ticker, req.as_of,
                    horizon_sessions=req.horizon_sessions, nonce=req.nonce)
        return record.model_dump(mode="json")

    try:
        # The pipeline is synchronous and CPU/IO bound; running it in a worker
        # thread keeps the event loop free to serve other requests.
        return await asyncio.to_thread(_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"{type(exc).__name__}: {exc}") from exc


@app.websocket("/api/stream/{ticker}")
async def stream_forecast(websocket: WebSocket, ticker: str) -> None:
    """Run the pipeline, streaming one message per completed stage.

    This owns the live UX. The client sends {"as_of": "...", "debate": true, ...}
    once, then receives progress events until {"event": "done"} or
    {"event": "error"}.
    """
    await websocket.accept()
    try:
        params: dict[str, Any] = await websocket.receive_json()
    except Exception:
        await websocket.close(code=1003)
        return

    as_of = params.get("as_of")
    if not as_of:
        await websocket.send_json({"event": "error", "detail": "as_of is required"})
        await websocket.close()
        return

    try:
        as_of_d = datetime.fromisoformat(str(as_of)).date()
        resolve(ticker, as_of=as_of_d)
    except (UnsupportedMarketError, ValueError) as exc:
        # The boundary applies here exactly as it does over HTTP.
        await websocket.send_json({"event": "error", "detail": str(exc)})
        await websocket.close()
        return

    if not llm.is_configured():
        await websocket.send_json({
            "event": "error",
            "detail": "GEMINI_API_KEY is not configured on the server.",
        })
        await websocket.close()
        return

    from backend.graph.pipeline import stream as stream_pipeline

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _produce() -> None:
        """Drive the synchronous generator on a worker thread, feeding the queue."""
        try:
            for event in stream_pipeline(
                ticker, str(as_of),
                debate=bool(params.get("debate", True)),
                drop=tuple(params.get("drop", ()) or ()),
                nonce=str(params.get("nonce", "")),
                horizon_sessions=int(params.get("horizon_sessions",
                                                Config.HORIZON_SESSIONS)),
            ):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "error", "detail": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = asyncio.create_task(asyncio.to_thread(_produce))
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await task
        try:
            await websocket.close()
        except RuntimeError:
            pass  # already closed by the client


@app.get("/api/results")
def results() -> dict:
    """List the committed results files, so the dashboard can show real numbers
    without re-running anything."""
    from backend.eval.harness import RESULTS_DIR

    if not RESULTS_DIR.exists():
        return {"results": []}
    return {
        "results": sorted(
            (
                {"name": p.name, "kind": p.suffix.lstrip("."),
                 "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(
                     timespec="seconds")}
                for p in RESULTS_DIR.iterdir() if p.is_file()
            ),
            key=lambda r: r["modified"], reverse=True,
        )
    }


@app.get("/api/results/{filename}")
def get_result(filename: str) -> dict:
    from backend.eval.harness import RESULTS_DIR
    import json
    
    file_path = RESULTS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")
        
    content = file_path.read_text(encoding="utf-8")
    if filename.endswith(".json"):
        return {"content": json.loads(content)}
    return {"content": content}


@app.get("/api/demo")
def get_demo() -> dict:
    """Serve a cached, known-good run with zero live API calls."""
    from backend.eval.harness import RESULTS_DIR
    import json
    
    demo_file = RESULTS_DIR / "demo" / "sample.json"
    if not demo_file.exists():
        raise HTTPException(status_code=404, detail="Demo run not found")
        
    return json.loads(demo_file.read_text(encoding="utf-8"))
