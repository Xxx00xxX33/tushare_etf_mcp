import os
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Callable, Iterable, List, Optional
from functools import partial

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

try:
    import tushare as ts  # type: ignore
    from pandas import DataFrame  # type: ignore
except Exception:
    # We defer ImportError until runtime; see get_pro() below
    ts = None  # type: ignore
    DataFrame = None  # type: ignore


app = FastAPI(
    title="ETF MCP Server",
    description=(
        "A streamable HTTP MCP server providing access to Chinese A‑share ETF "
        "data via the TuShare API.  All endpoints return streaming JSON lines."
    ),
    version="0.1.0",
)


def get_pro():
    """Initialise and return a TuShare pro_api client.

    The TuShare token must be supplied via the `TUSHARE_TOKEN` environment
    variable.  If the module is not installed or the token is missing the
    caller receives a HTTP 500/400 error accordingly.
    """
    if ts is None:
        raise HTTPException(
            status_code=500,
            detail="The 'tushare' library is not installed. Please install it via requirements.txt.",
        )
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=500,
            detail="TUSHARE_TOKEN environment variable is not set. Please provide your TuShare API token.",
        )
    # Only set token once per process
    if not hasattr(get_pro, "_client"):
        ts.set_token(token)
        setattr(get_pro, "_client", ts.pro_api())
    return getattr(get_pro, "_client")


def df_to_dicts(df: "DataFrame") -> List[dict]:
    """Convert a pandas DataFrame into a list of dictionaries.

    This helper is defined separately so that the TuShare import can fail
    gracefully until actually needed.  The JSON conversion uses pandas'
    built‑in method for performance and consistent field names.
    """
    return df.to_dict(orient="records")


async def stream_json_lines(rows: Iterable[dict]) -> AsyncGenerator[bytes, None]:
    """Yield a sequence of dictionaries as JSON lines.

    Each dictionary is serialised to a JSON string (preserving non‑ASCII
    characters) and followed by a newline.  Streaming yields control back to
    the event loop between items.
    """
    for row in rows:
        # Use ensure_ascii=False so Chinese names aren't escaped
        line = json.dumps(row, ensure_ascii=False) + "\n"
        yield line.encode("utf-8")
        # Avoid blocking the event loop for large datasets
        await asyncio.sleep(0)


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    """Return a short welcome message and hint at the available endpoints."""
    return (
        "ETF MCP Server is running. Available endpoints:\n"
        "/etfs – list available ETFs\n"
        "/etf/{ts_code}/history – historical NAV for a given ETF\n"
        "/etf_performance – interval performance for all ETFs\n"
        "/etf/{ts_code}/holdings – constituent holdings for a given ETF\n"
    )


@app.get("/etfs")
async def list_etfs(market: str = Query("E", description="Market code, default 'E' for ETFs")) -> StreamingResponse:
    """Stream the list of ETF funds from TuShare.

    The `market` parameter is passed to `pro.fund_basic` to filter the type
    of funds returned.  According to TuShare's documentation the value `'E'`
    selects ETF products.  Each row is emitted as a JSON object on its own
    line.  If the API call fails, a HTTPException is raised.
    """
    pro = get_pro()
    try:
        # Run blocking Tushare call in thread pool
        df: DataFrame = await asyncio.to_thread(pro.fund_basic, market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/x-ndjson")


@app.get("/etf/{ts_code}/history")
async def etf_history(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD or YYYYMMDD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD or YYYYMMDD format"),
) -> StreamingResponse:
    """Stream historical NAV data for a single ETF.

    The `ts_code` path parameter identifies the fund.  Optional `start_date`
    and `end_date` query parameters can restrict the date range.  Dates may
    be supplied in either YYYY‑MM‑DD or YYYYMMDD format; hyphens are stripped
    before passing to TuShare.
    """
    pro = get_pro()

    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise(start_date)
    end = normalise(end_date)
    try:
        # Run blocking Tushare call in thread pool
        df: DataFrame = await asyncio.to_thread(pro.fund_nav, ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/x-ndjson")


@app.get("/etf/{ts_code}/holdings")
async def etf_holdings(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD or YYYYMMDD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD or YYYYMMDD format"),
) -> StreamingResponse:
    """Stream constituent holdings for a single ETF.

    The `ts_code` path parameter identifies the fund.  Optional `start_date`
    and `end_date` query parameters can restrict the date range.  Dates may
    be supplied in either YYYY‑MM‑DD or YYYYMMDD format; hyphens are stripped
    before passing to TuShare.
    """
    pro = get_pro()

    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise(start_date)
    end = normalise(end_date)
    try:
        # Run blocking Tushare call in thread pool
        df: DataFrame = await asyncio.to_thread(pro.fund_portfolio, ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/x-ndjson")


@app.get("/etf_performance")
async def etf_performance(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD or YYYYMMDD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD or YYYYMMDD format"),
    market: str = Query("E", description="Market code, default 'E' for ETFs"),
) -> StreamingResponse:
    """Stream interval performance for all ETFs.

    For each ETF in the given market, this endpoint retrieves historical NAV
    data between `start_date` and `end_date`, then computes the percentage
    change from the first to the last available price.  Results are streamed
    as JSON lines.  Funds with insufficient data or errors are skipped.
    """
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")

    try:
        # Run blocking Tushare call in thread pool
        df_list: DataFrame = await asyncio.to_thread(pro.fund_basic, market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")

    funds = df_list_to_rows(df_list, ["ts_code", "name"])

    async def generate_performance() -> AsyncGenerator[bytes, None]:
        for fund in funds:
            code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
            name = fund.get("name") or fund.get("fund_name")
            if not code:
                continue
            try:
                # Run blocking Tushare call in thread pool
                nav_df: DataFrame = await asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end)
            except Exception as exc:
                error_row = {"ts_code": code, "name": name, "error": str(exc)}
                line = json.dumps(error_row, ensure_ascii=False) + "\n"
                yield line.encode("utf-8")
                continue

            if nav_df.empty or len(nav_df.index) < 2:
                continue

            price_col: Optional[str] = None
            for candidate in ["unit_nav", "nav", "per_nav", "accu_nav"]:
                if candidate in nav_df.columns:
                    price_col = candidate
                    break
            if price_col is None:
                continue

            start_price = nav_df.iloc[0][price_col]
            end_price = nav_df.iloc[-1][price_col]
            try:
                start_float = float(start_price)
                end_float = float(end_price)
            except Exception:
                continue

            if start_float == 0:
                continue

            change = (end_float - start_float) / start_float * 100
            result = {
                "ts_code": code,
                "name": name,
                "start_price": start_float,
                "end_price": end_float,
                "change_pct": round(change, 2),
            }
            line = json.dumps(result, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")
            await asyncio.sleep(0)

    return StreamingResponse(generate_performance(), media_type="application/x-ndjson")


def df_list_to_rows(df: "DataFrame", columns: List[str]) -> List[dict]:
    """Extract specific columns from a DataFrame and return as a list of dicts."""
    if df.empty:
        return []
    available = [c for c in columns if c in df.columns]
    if not available:
        return []
    return df[available].to_dict(orient="records")


# MCP code start

class Tool:
    """Simple container for MCP tool metadata and execution logic."""

    def __init__(self, name: str, description: str, input_schema: dict, run: Callable[..., asyncio.Future]):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.run = run

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


async def tool_list_etfs(*, market: str = "E") -> dict:
    """MCP tool: List all ETF funds."""
    pro = get_pro()
    try:
        # Run blocking Tushare call in thread pool with timeout
        df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    rows = df_to_dicts(df)
    return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)}]}


async def tool_etf_history(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """MCP tool: Get historical NAV data for an ETF."""
    pro = get_pro()

    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise(start_date)
    end = normalise(end_date)
    try:
        # Run blocking Tushare call in thread pool with timeout
        df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_nav, ts_code=ts_code, start_date=start, end_date=end),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    rows = df_to_dicts(df)
    return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)}]}


async def tool_etf_holdings(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """MCP tool: Get constituent holdings for an ETF."""
    pro = get_pro()

    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise(start_date)
    end = normalise(end_date)
    try:
        # Run blocking Tushare call in thread pool with timeout
        df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_portfolio, ts_code=ts_code, start_date=start, end_date=end),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    rows = df_to_dicts(df)
    return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)}]}


async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E") -> dict:
    """MCP tool: Calculate interval performance for all ETFs."""
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    
    try:
        # Run blocking Tushare call in thread pool with timeout
        df_list: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    funds = df_list_to_rows(df_list, ["ts_code", "name"])
    results: List[dict] = []
    
    for fund in funds:
        code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
        name = fund.get("name") or fund.get("fund_name")
        if not code:
            continue
        try:
            # Run blocking Tushare call in thread pool with timeout
            nav_df: DataFrame = await asyncio.wait_for(
                asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            results.append({"ts_code": code, "name": name, "error": "Request timed out"})
            continue
        except Exception as exc:
            results.append({"ts_code": code, "name": name, "error": str(exc)})
            continue
        
        if nav_df.empty or len(nav_df.index) < 2:
            continue
        
        price_col: Optional[str] = None
        for candidate in ["unit_nav", "nav", "per_nav", "accu_nav"]:
            if candidate in nav_df.columns:
                price_col = candidate
                break
        if price_col is None:
            continue
        
        start_price = nav_df.iloc[0][price_col]
        end_price = nav_df.iloc[-1][price_col]
        try:
            start_float = float(start_price)
            end_float = float(end_price)
        except Exception:
            continue
        
        if start_float == 0:
            continue
        
        change = (end_float - start_float) / start_float * 100
        results.append(
            {
                "ts_code": code,
                "name": name,
                "start_price": start_float,
                "end_price": end_float,
                "change_pct": round(change, 2),
            }
        )
        # Yield control to event loop
        await asyncio.sleep(0)
    
    return {"content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}]}


TOOLS: List[Tool] = [
    Tool(
        name="list_etfs",
        description="List all ETF funds available on the Chinese A-share market.",
        input_schema={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market code to filter ETF types (default 'E')",
                    "default": "E",
                }
            },
            "required": [],
        },
        run=tool_list_etfs,
    ),
    Tool(
        name="get_etf_history",
        description="Retrieve historical NAV (Net Asset Value) data for a specific ETF.",
        input_schema={
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "TuShare code of the ETF (e.g., '510050.SH')",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD or YYYYMMDD format (optional)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD or YYYYMMDD format (optional)",
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_history,
    ),
    Tool(
        name="get_etf_holdings",
        description="Retrieve constituent holdings for a specific ETF.",
        input_schema={
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "TuShare code of the ETF (e.g., '510050.SH')",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD or YYYYMMDD format (optional)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD or YYYYMMDD format (optional)",
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_holdings,
    ),
    Tool(
        name="get_etf_performance",
        description="Calculate interval performance (percentage change) for all ETFs between two dates.",
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD or YYYYMMDD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD or YYYYMMDD format",
                },
                "market": {
                    "type": "string",
                    "description": "Market code to filter ETF types (default 'E')",
                    "default": "E",
                },
            },
            "required": ["start_date", "end_date"],
        },
        run=tool_etf_performance,
    ),
]


@app.get("/.well-known/mcp-config")
async def mcp_config() -> dict:
    return {
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "name": "ETF MCP Server",
        "version": app.version,
        "description": app.description,
        "tools": [tool.name for tool in TOOLS],
    }

@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "transport": "streamable-http"}

@app.post("/mcp")
async def mcp_handler(request: Request):
    """MCP protocol handler with Server-Sent Events (SSE) transport."""
    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")

    def reply(result: Optional[dict] = None, *, error: Optional[dict] = None) -> dict:
        if error:
            return {"jsonrpc": "2.0", "error": error, "id": request_id}
        else:
            return {"jsonrpc": "2.0", "result": result, "id": request_id}

    # Generate response based on method
    response_data = None
    
    if method == "initialize":
        response_data = reply(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ETF MCP Server", "version": app.version},
            }
        )
    elif method == "tools/list":
        response_data = reply({"tools": [tool.as_dict() for tool in TOOLS]})
    elif method == "resources/list":
        response_data = reply({"resources": []})
    elif method == "prompts/list":
        response_data = reply({"prompts": []})
    elif method == "tools/call":
        params = body.get("params", {}) or {}
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        tool = next((t for t in TOOLS if t.name == name), None)
        if tool is None:
            response_data = reply(error={"code": -32601, "message": f"Unknown tool: {name}"})
        else:
            try:
                result = await tool.run(**args)
                response_data = reply(result=result)
            except HTTPException as http_exc:
                response_data = reply(error={"code": -32000, "message": http_exc.detail})
            except Exception as exc:
                response_data = reply(error={"code": -32603, "message": str(exc)})
    else:
        response_data = reply(error={"code": -32601, "message": f"Method not found: {method}"})
    
    # Return as Server-Sent Events (SSE) format
    async def event_generator():
        yield {
            "event": "message",
            "data": json.dumps(response_data, ensure_ascii=False)
        }
    
    return EventSourceResponse(event_generator())
