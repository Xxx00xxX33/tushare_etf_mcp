## ETF MCP Server

This repository contains a simple **Model‑Context‑Protocol (MCP)** server built
with **FastAPI** that exposes a handful of tools for working with
exchange‑traded funds (ETFs) listed on the Chinese A‑share market via the
[**TuShare**](https://tushare.pro/) data interface.  The server speaks the
**streamable HTTP** transport supported by [Smithery](https://smithery.ai/) and
can therefore be deployed as a remote MCP to power AI agents or other
applications that need structured financial data.

### Features

- **List ETFs** – Returns the complete list of ETF funds available on
  TuShare.  You may filter by market via a query parameter.  The response
  stream consists of JSON objects, one per line.
- **Historic NAV** – Fetch historical net‑asset‑value (NAV) quotes for a
  given ETF between two dates.
- **Interval performance** – Compute the percentage change in NAV for
  *all* ETFs over a user–supplied interval.  The server streams the results
  progressively so you can begin consuming data immediately rather than
  waiting for the entire calculation to complete.
- **Holdings / components** – Retrieve the latest reported holdings (constituent
  stocks) of a specific ETF.
- **Top ETFs by period** – Get top N ETFs ranked by gain/loss for a specific
  time period (day/week/month). Uses fast AkShare API for daily data (2-3s),
  Tushare for weekly/monthly data (20-40s).

### Running locally

1. Install the dependencies.  At minimum you'll need Python 3.9+.

```bash
pip install -r requirements.txt
```

2. Obtain a TuShare API token from [tushare.pro](https://tushare.pro/)
   (registration is free for basic usage) and set it as an environment
   variable:

```bash
export TUSHARE_TOKEN="your‑token‑string"
```

3. Start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

4. Open your browser at `http://localhost:8000` to see the available
   endpoints.  The API is self‑documenting via FastAPI’s OpenAPI UI.

### Smithery deployment

The server is built on top of FastAPI and uses `StreamingResponse` for all
methods.  Smithery’s streamable HTTP transport understands standard HTTP
streaming – there is no dependency on WebSockets – so you can deploy this
repository as a remote MCP on platforms supported by Smithery (e.g. Apify,
Vercel or your own infrastructure).

To deploy on Smithery, create a new server in your Smithery account and
provide it with the URL of your running service.  You may need to create a
reverse proxy or set up environment variables (including `TUSHARE_TOKEN`)
depending on your hosting environment.  Once deployed, Smithery will
automatically discover the available tools and expose them to your agent.

### API overview

| Endpoint | Method | Query parameters | Description |
|---------|--------|-----------------|-------------|
| `/etfs` | GET | `market` (optional, default `E`) | Stream the list of ETF funds. |
| `/etf/{ts_code}/history` | GET | `start_date`, `end_date` (`YYYYMMDD`) | Stream historical NAV data for an ETF. |
| `/etf_performance` | GET | `start_date`, `end_date`, `market` (optional) | Stream the interval percentage change for all ETFs. |
| `/etf/{ts_code}/holdings` | GET | `start_date`, `end_date` (optional) | Stream the component holdings of an ETF. |

All date parameters should be in `YYYYMMDD` format (e.g. `20250101`).  If
`start_date` is omitted the beginning of the dataset will be used; if
`end_date` is omitted the current date is assumed.

### Note on TuShare data

TuShare’s ETF endpoints are subject to API limits and may return different
fields depending on your subscription level.  This server assumes the
presence of the following fields:

- For **fund_basic**: `ts_code` and `name` among others.  See
  [`pro.fund_basic` documentation](https://tushare.pro/document/2) for
  details.
- For **fund_nav**: either `unit_nav` or `nav` to compute price changes.
- For **fund_portfolio**: constituent names (`name`), stock codes
  (`stk_code`) and weights (`weight`).

If TuShare returns different field names in your environment you may need to
modify the code accordingly.
