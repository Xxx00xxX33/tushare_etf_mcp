import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Callable, Iterable, List, Optional
from functools import partial

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

try:
    import tushare as ts  # type: ignore
    from pandas import DataFrame  # type: ignore
    import akshare as ak  # type: ignore
except Exception:
    # We defer ImportError until runtime; see get_pro() below
    ts = None  # type: ignore
    DataFrame = None  # type: ignore
    ak = None  # type: ignore


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


async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E", limit: int = 20) -> dict:
    """MCP tool: Calculate interval performance for ETFs (limited to avoid timeout)."""
    pro = get_pro()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    
    try:
        # Run blocking Tushare call in thread pool with timeout
        df_list: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=15.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    funds = df_list_to_rows(df_list, ["ts_code", "name"])
    results: List[dict] = []
    total_funds = len(funds)
    funds_to_process = funds[:limit]  # Limit number of ETFs to process
    
    
    import time
    start_time = time.time()
    max_duration = 50  # Maximum 50 seconds for all processing
    for fund in funds:
        code = fund.get("ts_code") or fund.get("code") or fund.get("fund_code")
        # Check overall timeout
        if time.time() - start_time > max_duration:
            break
            
        name = fund.get("name") or fund.get("fund_name")
        if not code:
            continue
        try:
            # Run blocking Tushare call in thread pool with timeout
            nav_df: DataFrame = await asyncio.wait_for(
                asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end),
                timeout=10.0
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
    
    # Add informative note
    elapsed_time = time.time() - start_time
    note = f"Returned {len(results)} ETFs"
    if len(results) < total_funds:
        note += f" (limited from {total_funds} total ETFs to avoid timeout)"
    if elapsed_time > max_duration:
        note += f" (stopped after {max_duration}s timeout)"
    note += f". Processing time: {elapsed_time:.1f}s"
    
    response_text = json.dumps(results, ensure_ascii=False, indent=2)
    return {
        "content": [
            {"type": "text", "text": response_text},
            {"type": "text", "text": f"\n\nNote: {note}"}
        ]
    }

import time

async def tool_top_etfs_by_period(*, period: str = "day", limit: int = 10, market: str = "E") -> dict:
    """
    获取指定时间周期内涨幅排行前 N 的 ETF
    
    Args:
        period: 时间周期，"day"=当日涨幅, "week"=近一周涨幅, "month"=近一月涨幅
        limit: 返回数量，默认 10
        market: 市场类型，"E"=ETF, "O"=LOF
    
    Returns:
        MCP 格式的响应，包含涨幅排行前 N 的 ETF
    """
    start_time = time.time()
    
    try:
        if period == "day":
            # 使用 AkShare 获取当日涨幅排行（快速）
            results = await _get_day_top_etfs(limit)
            period_desc = "当日"
        elif period == "week":
            # 使用 Tushare 计算近一周涨幅
            results = await _get_period_top_etfs(days=7, limit=limit, market=market)
            period_desc = "近一周"
        elif period == "month":
            # 使用 Tushare 计算近一月涨幅
            results = await _get_period_top_etfs(days=30, limit=limit, market=market)
            period_desc = "近一月"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid period: {period}. Must be one of: day, week, month"
            )
        
        elapsed = time.time() - start_time
        
        # 格式化输出
        output_lines = [f"{period_desc}涨幅前 {len(results)} 的 ETF：\n"]
        
        for i, etf in enumerate(results, 1):
            if period == "day":
                line = (
                    f"{i}. {etf['名称']} ({etf['代码']})\n"
                    f"   最新价: {etf['最新价']:.2f}  "
                    f"涨跌幅: {etf['涨跌幅']:.2f}%  "
                    f"成交额: {etf['成交额']/100000000:.2f}亿\n"
                    f"   主力净流入: {etf['主力净流入-净额']/100000000:.2f}亿\n"
                )
            else:
                line = (
                    f"{i}. {etf['name']} ({etf['ts_code']})\n"
                    f"   {period_desc}涨幅: {etf['gain']:.2f}%\n"
                )
            output_lines.append(line)
        
        output_lines.append(f"\n处理时间: {elapsed:.1f} 秒")
        
        if period != "day" and len(results) < limit:
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
        raise HTTPException(
            status_code=504,
            detail=f"Request timed out while fetching {period} ETF performance data"
        )
    except Exception as exc:
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
    # 排除条件1: 代码以513开头的港股ETF
    if code.startswith('513'):
        return False
    
    # 排除条件2: 名称中包含港股相关关键词
    hk_keywords = ['港股', '香港', '恒生', '恒指', 'H股', 'HK', '港', '中概']
    if any(keyword in name for keyword in hk_keywords):
        return False
    
    # 排除条件3: 美股、日本、欧洲等海外市场ETF
    overseas_keywords = ['美股', '纳斯达克', '标普', 'NASDAQ', 'S&P', '日本', '欧洲', '德国', '法国']
    if any(keyword in name for keyword in overseas_keywords):
        return False
    
    # 保留条件: 上交所和深交所的主流A股ETF
    # 上交所: 51xxxx, 58xxxx (但513xxx是港股)
    # 深交所: 15xxxx, 16xxxx
    if code.startswith(('510', '511', '512', '515', '516', '518', '588', '150', '159', '160')):
        return True
    
    # 其他情况默认保留（谨慎起见）
    return True


async def _get_day_top_etfs(limit: int) -> list:
    """
    使用 Tushare 获取当日涨幅排行前 N 的 ETF
    注意：由于 AkShare fund_etf_spot_em 接口不稳定，改用 Tushare 实现
    """
    pro = get_pro()
    
    try:
        # 1. 获取今日日期
        today = datetime.now().strftime('%Y%m%d')
        
        # 2. 获取 ETF 列表
        funds_df = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market='E'),
            timeout=15.0
        )
        
        if funds_df.empty:
            return []
        
        # 3. 过滤A股ETF
        funds_filtered = funds_df[funds_df.apply(
            lambda row: is_a_share_etf(str(row['ts_code'])[:6], str(row['name'])),
            axis=1
        )]
        
        # 4. 获取今日和昨日的净值数据，计算涨跌幅
        results = []
        
        # 为了提高效率，只处理 limit * 3 个 ETF
        funds_to_process = funds_filtered.head(limit * 3)
        
        for _, fund in funds_to_process.iterrows():
            try:
                # 获取最近 5 天的数据（确保有今日和昨日）
                end_date = datetime.now()
                start_date = end_date - timedelta(days=5)
                
                nav_df = await asyncio.wait_for(
                    asyncio.to_thread(
                        pro.fund_nav,
                        ts_code=fund['ts_code'],
                        start_date=start_date.strftime('%Y%m%d'),
                        end_date=end_date.strftime('%Y%m%d')
                    ),
                    timeout=8.0
                )
                
                if not nav_df.empty and len(nav_df) >= 2:
                    # 按日期排序
                    nav_df_sorted = nav_df.sort_values(by='nav_date', ascending=False)
                    
                    # 计算涨跌幅：(今日 - 昨日) / 昨日 * 100
                    if len(nav_df_sorted) >= 2:
                        today_nav = nav_df_sorted.iloc[0]['unit_nav']
                        yesterday_nav = nav_df_sorted.iloc[1]['unit_nav']
                        
                        if today_nav and yesterday_nav and yesterday_nav > 0:
                            pct_change = (today_nav - yesterday_nav) / yesterday_nav * 100
                            
                            results.append({
                                'ts_code': fund['ts_code'],
                                'name': fund['name'],
                                'latest_nav': float(today_nav),
                                'pct_change': round(float(pct_change), 2),
                                'nav_date': nav_df_sorted.iloc[0]['nav_date']
                            })
            
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
        
        # 5. 按涨跌幅排序并返回前 N 个
        results_sorted = sorted(results, key=lambda x: x['pct_change'], reverse=True)
        return results_sorted[:limit]
        
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Tushare API request timed out"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Tushare API error: {exc}"
        )


async def _get_period_top_etfs(days: int, limit: int, market: str) -> list:
    """
    使用 Tushare 计算指定天数内的涨幅排行
    """
    pro = get_pro()
    
    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    
    try:
        # 1. 获取 ETF 列表
        funds_df = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=15.0
        )
        
        if funds_df.empty:
            return []
        
        # 2. 过滤掉港股ETF和海外ETF
        funds_filtered = funds_df[funds_df.apply(
            lambda row: is_a_share_etf(
                str(row['ts_code'])[:6],  # 取前6位代码
                str(row['name'])
            ), 
            axis=1
        )]
        
        # 3. 限制处理数量（处理 3 倍数量以确保有足够的有效数据）
        funds_to_process = funds_filtered.head(limit * 3)
        
        # 4. 计算每个 ETF 的涨幅
        results = []
        overall_start = time.time()
        
        for _, fund in funds_to_process.iterrows():
            # 整体超时保护
            if time.time() - overall_start > 50:
                break
            
            try:
                nav_df = await asyncio.wait_for(
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
                    
                    # 计算涨幅
                    start_nav = nav_df_sorted.iloc[0]['unit_nav']
                    end_nav = nav_df_sorted.iloc[-1]['unit_nav']
                    
                    if start_nav and end_nav and start_nav > 0:
                        gain = (end_nav - start_nav) / start_nav * 100
                        
                        results.append({
                            'ts_code': fund['ts_code'],
                            'name': fund['name'],
                            'gain': gain,
                            'start_nav': start_nav,
                            'end_nav': end_nav
                        })
                
            except asyncio.TimeoutError:
                # 单个 ETF 超时，跳过继续处理下一个
                continue
            except Exception:
                # 其他错误也跳过
                continue
        
        # 4. 按涨幅降序排序并取前 N 个
        results_sorted = sorted(results, key=lambda x: x['gain'], reverse=True)
        return results_sorted[:limit]
        
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"TuShare API request timed out while fetching ETF list"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"TuShare API error: {exc}"
        )



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
        description="Get top N ETFs by gain/loss for a specific time period (day/week/month). Uses fast AkShare API for daily data, Tushare for weekly/monthly.",
        input_schema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: 'day' for daily gain, 'week' for weekly gain, 'month' for monthly gain",
                    "enum": ["day", "week", "month"],
                    "default": "day",
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
