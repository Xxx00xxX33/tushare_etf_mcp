import os
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Callable, Iterable, List, Optional

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
    gracefully until actually needed.  The JSON conversion uses pandas’
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
        # Use ensure_ascii=False so Chinese names aren’t escaped
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
    of funds returned.  According to TuShare’s documentation the value `'E'`
    selects ETF products.  Each row is emitted as a JSON object on its own
    line.  If the API call fails, a HTTPException is raised.
    """
    pro = get_pro()
    try:
        df: DataFrame = pro.fund_basic(market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/json")


@app.get("/etf/{ts_code}/history")
async def etf_history(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="Start date in YYYYMMDD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYYMMDD format"),
) -> StreamingResponse:
    """Stream the historical NAV data for a given ETF.

    Parameters:
    - `ts_code` – the TuShare code of the fund (e.g. `510300.SH`).
    - `start_date`, `end_date` – optional date range filters.  If omitted,
      TuShare will return the entire history available.  Dates must be
      provided in `YYYYMMDD` format; any dashes will be removed.
    The response is a stream of JSON lines containing the NAV records.
    """
    pro = get_pro()
    # Normalize dates to the expected format (remove dashes if present)
    def normalise_date(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise_date(start_date)
    end = normalise_date(end_date)
    try:
        df: DataFrame = pro.fund_nav(ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/json")


@app.get("/etf/{ts_code}/holdings")
async def etf_holdings(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="Start date in YYYYMMDD format (optional)"),
    end_date: Optional[str] = Query(None, description="End date in YYYYMMDD format (optional)"),
) -> StreamingResponse:
    """Stream the component holdings for a given ETF.

    This endpoint queries TuShare’s `fund_portfolio` interface which returns
    quarterly composition information for mutual funds and ETFs.  You may
    optionally supply a start/end date to restrict the quarters returned.

    Returned records include fields such as `stk_code` (stock code), `name`
    (stock name) and `weight` (percentage of the fund).  See TuShare
    documentation for more details.
    """
    pro = get_pro()
    # Normalise dates
    def normalise_date(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")

    start = normalise_date(start_date)
    end = normalise_date(end_date)
    try:
        df: DataFrame = pro.fund_portfolio(ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/json")


@app.get("/etf_performance")
async def etf_performance(
    start_date: str = Query(..., description="Start date in YYYYMMDD format"),
    end_date: str = Query(..., description="End date in YYYYMMDD format"),
    market: str = Query("E", description="Market code, default 'E' for ETFs"),
) -> StreamingResponse:
    """Stream the percentage change in NAV over a given interval for all ETFs.

    The server will query `fund_basic` to obtain the list of ETFs and then
    individually request NAV data for each ETF between the supplied dates.
    For each ETF with at least two NAV entries in the interval the function
    computes the percentage change:

        (NAV_end − NAV_start) / NAV_start × 100

    The results are streamed progressively as JSON objects with the
    following fields:

    - `ts_code` – ETF TuShare code
    - `name` – ETF name
    - `start_price` – first NAV value in the interval
    - `end_price` – last NAV value in the interval
    - `change_pct` – percentage change rounded to 2 decimal places

    Notes:
    - The computation is synchronous within the request; depending on the
      number of ETFs and TuShare API quotas this call may take some time.
    - Dates must be supplied in `YYYYMMDD` format (dashes are removed automatically).
    """
    pro = get_pro()
    # Normalise input dates
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    try:
        df_list: DataFrame = pro.fund_basic(market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    # Convert DataFrame to list of dicts for iteration
    funds = df_list_to_rows(df_list, ["ts_code", "name"])

    async def performance_generator() -> AsyncGenerator[bytes, None]:
        for fund in funds:
            ts_code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
            name = fund.get("name") or fund.get("fund_name")
            if not ts_code:
                continue
            # Fetch NAV history for this fund
            try:
                nav_df: DataFrame = pro.fund_nav(ts_code=ts_code, start_date=start, end_date=end)
            except Exception as exc:
                # Skip funds that error out
                result = {
                    "ts_code": ts_code,
                    "name": name,
                    "error": str(exc),
                }
                line = json.dumps(result, ensure_ascii=False) + "\n"
                yield line.encode("utf-8")
                await asyncio.sleep(0)
                continue
            if nav_df.empty or len(nav_df.index) < 2:
                # Not enough data to compute a change
                continue
            # Determine which column to use for price
            price_col = None
            for candidate in ["unit_nav", "nav", "per_nav", "accu_nav"]:
                if candidate in nav_df.columns:
                    price_col = candidate
                    break
            if price_col is None:
                # Unexpected schema, skip
                continue
            start_price = nav_df.iloc[0][price_col]
            end_price = nav_df.iloc[-1][price_col]
            # Handle possible None or non‑numeric values
            try:
                start_float = float(start_price)
                end_float = float(end_price)
            except Exception:
                continue
            if start_float == 0:
                continue
            change = (end_float - start_float) / start_float * 100
            result = {
                "ts_code": ts_code,
                "name": name,
                "start_price": start_float,
                "end_price": end_float,
                "change_pct": round(change, 2),
            }
            line = json.dumps(result, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")
            await asyncio.sleep(0)
    return StreamingResponse(performance_generator(), media_type="application/json")


def df_list_to_rows(df: "DataFrame", columns: List[str]) -> List[dict]:
    """Return a list of dictionaries with only selected columns from a DataFrame.

    If a column is missing in the DataFrame it will be omitted in the resulting
    dictionaries.  This helper is used for iterating over ETF metadata.
    """
    if df is None:
        return []
    # Only use available columns
    available_cols = [c for c in columns if c in df.columns]
    if not available_cols:
        return []
    return df[available_cols].to_dict(orient="records")
# MCP code start
from fastapi import Request

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


async def tool_list_etfs(*, market: str = "E") -> List[dict]:
    pro = get_pro()
    try:
        df: DataFrame = pro.fund_basic(market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    return df_to_dicts(df)

async def tool_etf_history(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[dict]:
    pro = get_pro()
    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")
    start = normalise(start_date)
    end = normalise(end_date)
    try:
        df: DataFrame = pro.fund_nav(ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    return df_to_dicts(df)

async def tool_etf_holdings(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[dict]:
    pro = get_pro()
    def normalise(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.replace("-", "")
    start = normalise(start_date)
    end = normalise(end_date)
    try:
        df: DataFrame = pro.fund_portfolio(ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    return df_to_dicts(df)

async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E") -> List[dict]:
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    try:
        df_list: DataFrame = pro.fund_basic(market=market)
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
            nav_df: DataFrame = pro.fund_nav(ts_code=code, start_date=start, end_date=end)
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
    return results


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
                },
            },
            "required": [],
        },
        run=tool_list_etfs,
    ),
    Tool(
        name="etf_history",
        description="Get historical NAV data for a specific ETF.",
        input_schema={
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "TuShare code of the ETF (e.g. 510300.SH)",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYYMMDD format (optional)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYYMMDD format (optional)",
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_history,
    ),
    Tool(
        name="etf_holdings",
        description="Get holdings for a specific ETF over an optional date range.",
        input_schema={
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "TuShare code of the ETF",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYYMMDD format (optional)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYYMMDD format (optional)",
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_holdings,
    ),
    Tool(
        name="etf_performance",
        description="Compute percentage change over an interval for all ETFs.",
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYYMMDD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYYMMDD format",
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
