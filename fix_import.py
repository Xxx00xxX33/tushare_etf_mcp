import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Callable, Iterable, List, Optional
from functools import partial

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

# Import tushare separately to avoid failure if akshare is missing
try:
    import tushare as ts  # type: ignore
    from pandas import DataFrame  # type: ignore
except ImportError as e:
    # Only set ts to None if tushare import fails
    ts = None  # type: ignore
    DataFrame = None  # type: ignore

# Import akshare separately (optional)
try:
    import akshare as ak  # type: ignore
except ImportError:
    ak = None  # type: ignore

# Rest of the code should remain the same
