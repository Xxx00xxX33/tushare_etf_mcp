import os
import json
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import AsyncGenerator, Callable, Iterable, List, Optional
from functools import partial

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Use more specific ImportError to avoid catching unrelated exceptions
ts = None
DataFrame = None
pd_isna = None
ak = None

try:
    import tushare as ts_module
    ts = ts_module
    logger.info("tushare library imported successfully.")
except ImportError:
    logger.error("tushare library not found.")
except Exception as e:
    logger.error(f"Error importing tushare: {e}")

try:
    from pandas import DataFrame as pd_DataFrame, isna as pd_isna_func
    DataFrame = pd_DataFrame
    pd_isna = pd_isna_func
    logger.info("pandas library imported successfully.")
except ImportError:
    logger.error("pandas library not found.")
except Exception as e:
    logger.error(f"Error importing pandas: {e}")

try:
    import akshare as ak_module
    ak = ak_module
    logger.info("akshare library imported successfully.")
except ImportError:
    logger.info("akshare library not found (optional).") # akshare is optional
except Exception as e:
    logger.error(f"Error importing akshare: {e}")


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
    logger.info("Attempting to get Tushare pro_api client.")
    if ts is None:
        logger.error("tushare library is None in get_pro().")
        raise HTTPException(
            status_code=500,
            detail="The 'tushare' library is not installed. Please install it via requirements.txt.",
        )
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        logger.error("TUSHARE_TOKEN environment variable is not set.")
        raise HTTPException(
            status_code=500,
            detail="TUSHARE_TOKEN environment variable is not set. Please provide your TuShare API token.",
        )
    logger.info(f"TUSHARE_TOKEN retrieved: {token is not None}")
    
    # Ensure token is set before calling pro_api
    if not getattr(ts, "_token_set", False):
        try:
            ts.set_token(token)
            setattr(ts, "_token_set", True)
            logger.info("Tushare token set successfully.")
        except Exception as e:
            logger.error(f"Error setting Tushare token: {e}")
            raise HTTPException(status_code=500, detail=f"Error setting Tushare token: {e}")
    
    # Only set client once per process
    if not hasattr(get_pro, "_client"):
        try:
            setattr(get_pro, "_client", ts.pro_api())
            logger.info("Tushare pro_api client initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing Tushare pro_api: {e}")
            raise HTTPException(status_code=500, detail=f"Error initializing Tushare pro_api: {e}")
    return getattr(get_pro, "_client")

def df_to_dicts(df: "DataFrame") -> List[dict]:
    """Convert a pandas DataFrame into a list of dictionaries.

    This helper is defined separately so that the TuShare import can fail
    gracefully until actually needed.  The JSON conversion uses pandas'
    built‑in method for performance and consistent field names.
    """
    if DataFrame is None:
        logger.error("pandas DataFrame is None in df_to_dicts().")
        raise HTTPException(
            status_code=500,
            detail="The 'pandas' library is not installed. Please install it via requirements.txt.",
        )
    if df.empty:
        return []
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
    logger.info(f"Received request for /etfs with market: {market}")
    pro = get_pro()
    try:
        # Run blocking Tushare call in thread pool
        df: DataFrame = await asyncio.to_thread(pro.fund_basic, market=market)
        logger.info(f"fund_basic call successful, returned {len(df)} rows.")
    except Exception as exc:
        logger.error(f"TuShare API error in /etfs: {exc}")
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
    logger.info(f"Received request for /etf/{ts_code}/history from {start_date} to {end_date}")
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
        logger.info(f"fund_nav call for {ts_code} successful, returned {len(df)} rows.")
    except Exception as exc:
        logger.error(f"TuShare API error in /etf/{ts_code}/history: {exc}")
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
    logger.info(f"Received request for /etf/{ts_code}/holdings from {start_date} to {end_date}")
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
        logger.info(f"fund_portfolio call for {ts_code} successful, returned {len(df)} rows.")
    except Exception as exc:
        logger.error(f"TuShare API error in /etf/{ts_code}/holdings: {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    rows = df_to_dicts(df)
    return StreamingResponse(stream_json_lines(rows), media_type="application/x-ndjson")


@app.get("/etf_performance")
async def etf_performance(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD or YYYYMMDD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD or YYYYMMDD format"),
    market: str = Query("E", description="Market code, default 'E' for ETFs"),
    limit: int = Query(20, description="Maximum number of ETFs to process (default 20 to avoid timeout)")
) -> StreamingResponse:
    """Stream interval performance for all ETFs.

    For each ETF in the given market, this endpoint retrieves historical NAV
    data between `start_date` and `end_date`, then computes the percentage
    change from the first to the last available price.  Results are streamed
    as JSON lines.  Funds with insufficient data or errors are skipped.
    """
    logger.info(f"Received request for /etf_performance from {start_date} to {end_date} for market: {market}, limit: {limit}")
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")

    try:
        # Run blocking Tushare call in thread pool
        df_list: DataFrame = await asyncio.to_thread(pro.fund_basic, market=market)
        logger.info(f"fund_basic call for performance successful, returned {len(df_list)} funds.")
    except Exception as exc:
        logger.error(f"TuShare API error in /etf_performance (fund_basic): {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")

    funds = df_list_to_rows(df_list, ["ts_code", "name"])
    results: List[dict] = []
    total_funds = len(funds)
    funds_to_process = funds[:limit]  # Limit number of ETFs to process
    
    import time
    start_time = time.time()
    max_duration = 50  # Maximum 50 seconds for all processing
    for fund in funds_to_process: # Only iterate over funds_to_process
        code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
        # Check overall timeout
        if time.time() - start_time > max_duration:
            logger.warning(f"Exceeded max_duration ({max_duration}s) in etf_performance, breaking loop.")
            break
            
        name = fund.get("name") or fund.get("fund_name")
        if not code:
            logger.warning(f"Skipping fund due to missing code: {fund}")
            continue
        try:
            # Run blocking Tushare call in thread pool with timeout
            nav_df: DataFrame = await asyncio.wait_for(
                asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end),
                timeout=10.0
            )
            logger.debug(f"fund_nav call for {code} successful.")
        except asyncio.TimeoutError:
            logger.warning(f"TuShare API request for {code} timed out.")
            results.append({"ts_code": code, "name": name, "error": "Request timed out"})
            continue
        except Exception as exc:
            logger.error(f"TuShare API error for {code} in etf_performance: {exc}")
            results.append({"ts_code": code, "name": name, "error": str(exc)})
            continue
        
        if nav_df.empty or len(nav_df.index) < 2:
            logger.info(f"Skipping {code}: insufficient NAV data.")
            continue
        
        price_col: Optional[str] = None
        for candidate in ["unit_nav", "nav", "per_nav", "accu_nav"]:
            if candidate in nav_df.columns:
                # Ensure the column is not entirely NaN before selecting
                if pd_isna is not None and not pd_isna(nav_df[candidate]).all():
                    price_col = candidate
                    break
        if price_col is None:
            logger.warning(f"Skipping {code}: no valid price column found or all values are NaN.")
            continue
        
        start_price = nav_df.iloc[0][price_col]
        end_price = nav_df.iloc[-1][price_col]
        try:
            start_float = float(start_price)
            end_float = float(end_price)
        except ValueError:
            logger.warning(f"Skipping {code}: invalid price value encountered (not floatable).")
            continue
        
        if start_float == 0:
            logger.warning(f"Skipping {code}: start_price is zero.")
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
        logger.debug(f"Calculated performance for {code}: {change:.2f}%")
        # Yield control to event loop
        await asyncio.sleep(0)
    
    # Add informative note
    elapsed_time = time.time() - start_time
    note = f"Returned {len(results)} ETFs"
    if len(results) < total_funds:
        note += f" (limited from {total_funds} total ETFs to avoid timeout)"
    if elapsed_time > max_duration:
        note += f" (stopped after {max_duration:.1f}s timeout)"
    note += f". Processing time: {elapsed_time:.1f}s"
    logger.info(f"etf_performance finished. {note}")
    
    response_text = json.dumps(results, ensure_ascii=False, indent=2)
    return {
        "content": [
            {"type": "text", "text": response_text},
            {"type": "text", "text": f"\n\nNote: {note}"}
        ]
    }


def df_list_to_rows(df: "DataFrame", columns: List[str]) -> List[dict]:
    """Extract specific columns from a DataFrame and return as a list of dicts."""
    if DataFrame is None:
        logger.error("pandas DataFrame is None in df_list_to_rows().")
        raise HTTPException(
            status_code=500,
            detail="The 'pandas' library is not installed. Please install it via requirements.txt.",
        )
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


async def tool_list_etfs(*, market: str = "E", keyword: Optional[str] = None, limit: int = 50) -> dict:
    """MCP tool: List ETF funds with optional keyword search.
    
    Args:
        market: Market code (default 'E' for ETFs)
        keyword: Optional keyword to search in ETF name or code
        limit: Maximum number of results to return (default 50)
    """
    logger.info(f"Tool call: list_etfs with market: {market}, keyword: {keyword}, limit: {limit}")
    pro = get_pro()
    try:
        # Run blocking Tushare call in thread pool with timeout
        df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=30.0
        )
        logger.info(f"Tool list_etfs: fund_basic call successful, returned {len(df)} rows.")
    except asyncio.TimeoutError:
        logger.error("Tool list_etfs: TuShare API request timed out after 30 seconds.")
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        logger.error(f"Tool list_etfs: TuShare API error: {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    # Filter by keyword if provided
    if keyword:
        keyword_lower = keyword.lower()
        df = df[
            df['name'].str.contains(keyword, case=False, na=False) | 
            df['ts_code'].str.contains(keyword, case=False, na=False)
        ]
        logger.info(f"After keyword filter '{keyword}': {len(df)} rows")
    
    # Filter to A-share ETFs only
    df = df[df.apply(
        lambda row: is_a_share_etf(
            str(row['ts_code'])[:6],
            str(row['name'])
        ),
        axis=1
    )]
    logger.info(f"After A-share filter: {len(df)} rows")
    
    # Limit results
    df = df.head(limit)
    
    rows = df_to_dicts(df)
    
    note = f"Found {len(rows)} ETF(s)"
    if keyword:
        note += f" matching keyword '{keyword}'"
    if len(rows) >= limit:
        note += f" (limited to {limit} results)"
    
    logger.info(f"Tool list_etfs: returning {len(rows)} results")
    return {
        "content": [
            {"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)},
            {"type": "text", "text": f"\n\n{note}"}
        ]
    }


async def tool_etf_history(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100) -> dict:
    """MCP tool: Get historical NAV data for an ETF.
    
    Args:
        ts_code: ETF code (e.g., '510050.SH')
        start_date: Start date in YYYY-MM-DD or YYYYMMDD format (optional)
        end_date: End date in YYYY-MM-DD or YYYYMMDD format (optional)
        limit: Maximum number of records to return (default 100, most recent)
    """
    logger.info(f"Tool call: get_etf_history for {ts_code} from {start_date} to {end_date}, limit: {limit}")
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
        logger.info(f"Tool get_etf_history for {ts_code} successful, returned {len(df)} rows.")
    except asyncio.TimeoutError:
        logger.error(f"Tool get_etf_history for {ts_code}: TuShare API request timed out after 30 seconds.")
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        logger.error(f"Tool get_etf_history for {ts_code}: TuShare API error: {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    total_records = len(df)
    
    # Sort by date descending and limit results
    if 'nav_date' in df.columns:
        df = df.sort_values('nav_date', ascending=False)
    elif 'end_date' in df.columns:
        df = df.sort_values('end_date', ascending=False)
    
    df = df.head(limit)
    
    rows = df_to_dicts(df)
    
    note = f"Returned {len(rows)} record(s)"
    if total_records > limit:
        note += f" (limited from {total_records} total records, showing most recent)"
    
    logger.info(f"Tool get_etf_history: returning {len(rows)} results")
    return {
        "content": [
            {"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)},
            {"type": "text", "text": f"\n\n{note}"}
        ]
    }


async def tool_etf_holdings(*, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 50) -> dict:
    """MCP tool: Get constituent holdings for an ETF.
    
    Args:
        ts_code: ETF code (e.g., '510050.SH')
        start_date: Start date in YYYY-MM-DD or YYYYMMDD format (optional)
        end_date: End date in YYYY-MM-DD or YYYYMMDD format (optional)
        limit: Maximum number of holdings to return (default 50, top holdings by weight)
    """
    logger.info(f"Tool call: get_etf_holdings for {ts_code} from {start_date} to {end_date}, limit: {limit}")
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
        logger.info(f"Tool get_etf_holdings for {ts_code} successful, returned {len(df)} rows.")
    except asyncio.TimeoutError:
        logger.error(f"Tool get_etf_holdings for {ts_code}: TuShare API request timed out after 30 seconds.")
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        logger.error(f"Tool get_etf_holdings for {ts_code}: TuShare API error: {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    total_holdings = len(df)
    
    # Sort by weight/proportion if available, then limit
    if 'mkv' in df.columns:
        df = df.sort_values('mkv', ascending=False)
    elif 'per_nav' in df.columns:
        df = df.sort_values('per_nav', ascending=False)
    
    df = df.head(limit)
    
    rows = df_to_dicts(df)
    
    note = f"Returned {len(rows)} holding(s)"
    if total_holdings > limit:
        note += f" (limited from {total_holdings} total holdings, showing top holdings)"
    
    logger.info(f"Tool get_etf_holdings: returning {len(rows)} results")
    return {
        "content": [
            {"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)},
            {"type": "text", "text": f"\n\n{note}"}
        ]
    }


async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E", limit: int = 20) -> dict:
    """MCP tool: Calculate interval performance for ETFs (limited to avoid timeout)."""
    logger.info(f"Tool call: get_etf_performance from {start_date} to {end_date} for market: {market}, limit: {limit}")
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    
    try:
        # Run blocking Tushare call in thread pool with timeout
        df_list: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=15.0
        )
        logger.info(f"Tool get_etf_performance: fund_basic call successful, returned {len(df_list)} funds.")
    except asyncio.TimeoutError:
        logger.error("Tool get_etf_performance: fund_basic TuShare API request timed out after 15 seconds.")
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        logger.error(f"Tool get_etf_performance: TuShare API error (fund_basic): {exc}")
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    funds = df_list_to_rows(df_list, ["ts_code", "name"])
    results: List[dict] = []
    total_funds = len(funds)
    funds_to_process = funds[:limit]  # Limit number of ETFs to process
    
    
    import time
    start_time = time.time()
    max_duration = 50  # Maximum 50 seconds for all processing
    for fund in funds_to_process: # Only iterate over funds_to_process
        code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
        # Check overall timeout
        if time.time() - start_time > max_duration:
            logger.warning(f"Tool get_etf_performance: Exceeded max_duration ({max_duration}s), breaking loop.")
            break
            
        name = fund.get("name") or fund.get("fund_name")
        if not code:
            logger.warning(f"Tool get_etf_performance: Skipping fund due to missing code: {fund}")
            continue
        try:
            # Run blocking Tushare call in thread pool with timeout
            nav_df: DataFrame = await asyncio.wait_for(
                asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end),
                timeout=10.0
            )
            logger.debug(f"Tool get_etf_performance: fund_nav call for {code} successful.")
        except asyncio.TimeoutError:
            logger.warning(f"Tool get_etf_performance: TuShare API request for {code} timed out.")
            results.append({"ts_code": code, "name": name, "error": "Request timed out"})
            continue
        except Exception as exc:
            logger.error(f"Tool get_etf_performance: TuShare API error for {code}: {exc}")
            results.append({"ts_code": code, "name": name, "error": str(exc)})
            continue
        
        if nav_df.empty or len(nav_df.index) < 2:
            logger.info(f"Tool get_etf_performance: Skipping {code}: insufficient NAV data.")
            continue
        
        price_col: Optional[str] = None
        for candidate in ["unit_nav", "nav", "per_nav", "accu_nav"]:
            if candidate in nav_df.columns:
                # Ensure the column is not entirely NaN before selecting
                if pd_isna is not None and not pd_isna(nav_df[candidate]).all():
                    price_col = candidate
                    break
        if price_col is None:
            logger.warning(f"Tool get_etf_performance: Skipping {code}: no valid price column found or all values are NaN.")
            continue
        
        start_price = nav_df.iloc[0][price_col]
        end_price = nav_df.iloc[-1][price_col]
        try:
            start_float = float(start_price)
            end_float = float(end_price)
        except ValueError:
            logger.warning(f"Tool get_etf_performance: Skipping {code}: invalid price value encountered (not floatable).")
            continue
        
        if start_float == 0:
            logger.warning(f"Tool get_etf_performance: Skipping {code}: start_price is zero.")
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
        logger.debug(f"Tool get_etf_performance: Calculated performance for {code}: {change:.2f}%")
        # Yield control to event loop
        await asyncio.sleep(0)
    
    # Add informative note
    elapsed_time = time.time() - start_time
    note = f"Returned {len(results)} ETFs"
    if len(results) < total_funds:
        note += f" (limited from {total_funds} total ETFs to avoid timeout)"
    if elapsed_time > max_duration:
        note += f" (stopped after {max_duration:.1f}s timeout)"
    note += f". Processing time: {elapsed_time:.1f}s"
    logger.info(f"etf_performance finished. {note}")
    
    response_text = json.dumps(results, ensure_ascii=False, indent=2)
    return {
        "content": [
            {"type": "text", "text": response_text},
            {"type": "text", "text": f"\n\nNote: {note}"}
        ]
    }


async def tool_top_etfs_by_period(*, period: str = "week", limit: int = 10, market: str = "E") -> dict:
    """
    获取指定时间周期内涨幅排行前 N 的 ETF
    
    Args:
        period: 时间周期，"week"=近一周涨幅, "month"=近一月涨幅
        limit: 返回数量，默认 10
        market: 市场类型，"E"=ETF, "O"=LOF
    
    Returns:
        MCP 格式的响应，包含涨幅排行前 N 的 ETF
    """
    logger.info(f"Tool call: top_etfs_by_period with period: {period}, limit: {limit}, market: {market}")
    start_time = time.time()
    
    try:
        if period == "week":
            # 使用 Tushare 计算近一周涨幅
            results = await _get_period_top_etfs(days=7, limit=limit, market=market)
            period_desc = "近一周"
        elif period == "month":
            # 使用 Tushare 计算近一月涨幅
            results = await _get_period_top_etfs(days=30, limit=limit, market=market)
            period_desc = "近一月"
        else:
            logger.error(f"Tool top_etfs_by_period: Invalid period: {period}.")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid period: {period}. Must be one of: week, month"
            )
        
        elapsed = time.time() - start_time
        logger.info(f"Tool top_etfs_by_period finished. Elapsed time: {elapsed:.1f}s")
        
        # 格式化输出
        output_lines = [f"{period_desc}涨幅前 {len(results)} 的 ETF：\n\n"]
        
        for i, etf in enumerate(results, 1):
            line = (
                f"{i}. {etf['name']} ({etf['ts_code']})\n"
                f"   {period_desc}涨幅: {etf['gain']:.2f}%\n"
            )
            output_lines.append(line)
        
        output_lines.append(f"\n处理时间: {elapsed:.1f} 秒")
        
        if len(results) < limit:
            output_lines.append(
                f"\n注意: 仅返回 {len(results)} 个 ETF（部分 ETF 数据不足或获取失败）"
            )
        
        return {
            "content": [{
                "type": "text",
                "text": "".join(output_lines)
            }]
        }
        
    except asyncio.TimeoutError:
        logger.error(f"Tool top_etfs_by_period: Request timed out while fetching {period} ETF performance data.")
        raise HTTPException(
            status_code=504,
            detail=f"Request timed out while fetching {period} ETF performance data"
        )
    except Exception as exc:
        logger.error(f"Tool top_etfs_by_period: Error fetching {period} ETF performance: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching {period} ETF performance: {exc}"
        )


def is_a_share_etf(code: str, name: str) -> bool:
    """
    判断是否为A股ETF（排除港股ETF和其他非A股ETF）
    
    Args:
        code: ETF代码
        name: ETF名称
    
    Returns:
        True if A股ETF, False otherwise
    """
    # Defensive check for NaN or non-string inputs
    if not isinstance(code, str) or not isinstance(name, str):
        logger.debug(f"is_a_share_etf: Invalid input type - code: {type(code)}, name: {type(name)}")
        return False
        
    # 排除条件1: 代码以513开头的港股ETF
    if code.startswith('513'):
        logger.debug(f"is_a_share_etf: Excluded {code} (Hong Kong ETF - 513 prefix).")
        return False
    
    # 排除条件2: 名称中包含港股相关关键词
    hk_keywords = ['港股', '香港', '恒生', '恒指', 'H股', 'HK', '港', '中概']
    if any(keyword in name for keyword in hk_keywords):
        logger.debug(f"is_a_share_etf: Excluded {name} (Hong Kong keyword in name).")
        return False
    
    # 排除条件3: 美股、日本、欧洲等海外市场ETF
    overseas_keywords = ['美股', '纳斯达克', '标普', 'NASDAQ', 'S&P', '日本', '欧洲', '德国', '法国']
    if any(keyword in name for keyword in overseas_keywords):
        logger.debug(f"is_a_share_etf: Excluded {name} (Overseas keyword in name).")
        return False
    
    # 保留条件: 上交所和深交所的主流A股ETF
    # 上交所: 51xxxx, 58xxxx (但513xxx是港股)
    # 深交所: 15xxxx, 16xxxx
    if code.startswith(('510', '511', '512', '515', '516', '518', '588', '150', '159', '160')):
        logger.debug(f"is_a_share_etf: Included {code} (A-share prefix).")
        return True
    
    # 其他情况默认保留（谨慎起见）
    logger.debug(f"is_a_share_etf: Included {code} (default - no specific exclusion/inclusion met).")
    return True


async def _get_period_top_etfs(days: int, limit: int, market: str) -> list:
    """
    使用 Tushare 计算指定天数内的涨幅排行
    """
    logger.info(f"Calling _get_period_top_etfs for {days} days, limit {limit}, market {market}")
    pro = get_pro()
    
    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    logger.info(f"Date range: {start_date_str} to {end_date_str}")
    
    try:
        # 1. 获取 ETF 列表
        funds_df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=15.0
        )
        logger.info(f"_get_period_top_etfs: fund_basic call successful, returned {len(funds_df)} funds.")
        
        if funds_df.empty:
            logger.info("funds_df is empty, returning empty list.")
            return []
        
        # 2. 过滤掉港股ETF和海外ETF
        # Ensure pd_isna is imported and used for NaN checks
        if pd_isna is None:
            logger.error("pandas isna function not available in _get_period_top_etfs.")
            raise HTTPException(status_code=500, detail="pandas isna function not available.")
            
        funds_filtered = funds_df[funds_df.apply(
            lambda row: is_a_share_etf(
                str(row['ts_code']) if not pd_isna(row['ts_code']) else '', # Handle NaN
                str(row['name']) if not pd_isna(row['name']) else '' # Handle NaN
            ), 
            axis=1
        )]
        logger.info(f"After A-share filtering, {len(funds_filtered)} funds remaining.")
        
        # 3. 限制处理数量（处理 3 倍数量以确保有足够的有效数据）
        funds_to_process = funds_filtered.head(limit * 3)
        logger.info(f"Processing top {len(funds_to_process)} funds to get desired limit of {limit}.")
        
        # 4. 计算每个 ETF 的涨幅
        results = []
        overall_start = time.time()
        
        for _, fund in funds_to_process.iterrows():
            # 整体超时保护
            if time.time() - overall_start > 50:
                logger.warning("Overall timeout exceeded in _get_period_top_etfs, breaking loop.")
                break
            
            try:
                nav_df: DataFrame = await asyncio.wait_for(
                    asyncio.to_thread(
                        pro.fund_nav,
                        ts_code=fund['ts_code'],
                        start_date=start_date_str,
                        end_date=end_date_str
                    ),
                    timeout=10.0
                )
                
                if not nav_df.empty and len(nav_df) >= 2:
                    # 按日期排序
                    nav_df_sorted = nav_df.sort_values(by='nav_date')
                    
                    # Ensure 'unit_nav' column exists and is not entirely NaN
                    if 'unit_nav' not in nav_df_sorted.columns or nav_df_sorted['unit_nav'].isnull().all():
                        logger.warning(f"Skipping {fund['ts_code']}: 'unit_nav' column missing or all NaN.")
                        continue # Skip if no valid NAV data
                        
                    # 计算涨幅
                    start_nav = nav_df_sorted.iloc[0]['unit_nav']
                    end_nav = nav_df_sorted.iloc[-1]['unit_nav']
                    
                    if start_nav is not None and end_nav is not None and start_nav > 0: # Ensure not None
                        gain = (end_nav - start_nav) / start_nav * 100
                        logger.debug(f"Calculated gain for {fund['ts_code']}: {gain:.2f}%")
                        
                        results.append({
                            'ts_code': fund['ts_code'],
                            'name': fund['name'],
                            'gain': gain,
                            'start_nav': start_nav,
                            'end_nav': end_nav
                        })
                    else:
                        logger.warning(f"Skipping {fund['ts_code']}: start_nav or end_nav not valid or start_nav is zero ({start_nav}, {end_nav}).")
                else:
                    logger.info(f"Skipping {fund['ts_code']}: insufficient NAV data (empty or less than 2 rows).")
                
            except asyncio.TimeoutError:
                logger.warning(f"Single ETF ({fund['ts_code']}) fund_nav request timed out, skipping.")
                continue
            except Exception as e:
                logger.error(f"Error processing ETF {fund['ts_code']}: {e}, skipping.")
                continue
        
        # 4. 按涨幅降序排序并取前 N 个
        results_sorted = sorted(results, key=lambda x: x['gain'], reverse=True)
        final_results = results_sorted[:limit]
        logger.info(f"Finished processing, returning {len(final_results)} top ETFs.")
        return final_results
        
    except asyncio.TimeoutError:
        logger.error("_get_period_top_etfs: TuShare API request timed out while fetching ETF list.")
        raise HTTPException(
            status_code=504,
            detail=f"TuShare API request timed out while fetching ETF list"
        )
    except Exception as exc:
        logger.error(f"_get_period_top_etfs: TuShare API error: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"TuShare API error: {exc}"
        )



TOOLS: List[Tool] = [
    Tool(
        name="list_etfs",
        description="Search and list ETF funds on the Chinese A-share market. Use keyword parameter to search by name or code. Returns up to 50 results by default.",
        input_schema={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market code to filter ETF types (default 'E' for ETFs)",
                    "default": "E",
                },
                "keyword": {
                    "type": "string",
                    "description": "Optional keyword to search in ETF name or code (e.g., '科技', '医药', '510')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 50)",
                    "default": 50,
                }
            },
            "required": [],
        },
        run=tool_list_etfs,
    ),
    Tool(
        name="get_etf_history",
        description="Retrieve historical NAV (Net Asset Value) data for a specific ETF. Returns up to 100 most recent records by default.",
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return (default 100, most recent)",
                    "default": 100,
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_history,
    ),
    Tool(
        name="get_etf_holdings",
        description="Retrieve constituent holdings for a specific ETF. Returns up to 50 top holdings by default.",
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of holdings to return (default 50, top holdings by weight)",
                    "default": 50,
                },
            },
            "required": ["ts_code"],
        },
        run=tool_etf_holdings,
    ),
    Tool(
        name="get_etf_performance",
        description="Calculate interval performance (percentage change) for ETFs between two dates. Limited to avoid timeout.",
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of ETFs to process (default 20 to avoid timeout)",
                    "default": 20,
                },
            },
            "required": ["start_date", "end_date"],
        },
        run=tool_etf_performance,
    ),
    Tool(
        name="get_top_etfs_by_period",
        description="Get top N A-share ETFs by gain/loss for a specific time period (week/month). Only returns ETFs with A-share components, excluding Hong Kong and overseas ETFs.",
        input_schema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: 'week' for weekly gain, 'month' for monthly gain",
                    "enum": ["week", "month"],
                    "default": "week",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of top ETFs to return (default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "market": {
                    "type": "string",
                    "description": "Market code: 'E' for ETF, 'O' for LOF (default 'E')",
                    "default": "E",
                },
            },
            "required": [],
        },
        run=tool_top_etfs_by_period,
    ),
]


@app.get("/.well-known/mcp-config")
async def mcp_config() -> dict:
    logger.info("Received request for /.well-known/mcp-config")
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
    logger.info("Received request for /health")
    return {"status": "healthy", "transport": "streamable-http"}

@app.post("/mcp")
async def mcp_handler(request: Request):
    """MCP protocol handler with Server-Sent Events (SSE) transport."""
    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")
    logger.info(f"Received MCP request: method={method}, id={request_id}")

    def reply(result: Optional[dict] = None, *, error: Optional[dict] = None) -> dict:
        if error:
            logger.error(f"Replying with error for request {request_id}: {error}")
            return {"jsonrpc": "2.0", "error": error, "id": request_id}
        else:
            logger.info(f"Replying with success for request {request_id}.")
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