# Market Data Layer v1

Read-only market monitoring, separate from Daily Strategy v1, Analysis API cache, bot runtime, positions and persistence. No strategy calls during scanner refresh, no Telegram, execution or WebSockets. Yahoo is **not labeled LIVE or guaranteed real-time**.

## Startup and endpoints

Existing commands are unchanged; install `requirements-api.txt` in your separate API environment, then run from repository root:

```powershell
.\.venv-api\Scripts\python.exe -m api.main
# or, with the API environment active:
python -m api.main
```

No new backend/frontend dependencies. Existing [API setup](../README.md) documents environment creation. Frontend:

```powershell
cd web
npm.cmd run dev
```

Loopback API port 8000; frontend port 5173. Existing local CORS/Analysis API endpoints remain compatible.

- `GET /api/v1/market/quote/ASELS`
- `GET /api/v1/market/history/ASELS?interval=1d&range=1mo`
- `GET /api/v1/market/scanner`

History accepts **1d × 1mo/3mo/6mo/1y** only. Unsupported combinations return 422; **1h is pending integration with the existing intraday data contract**, never bypassed. Invalid symbols, no data, provider failures and timeouts return sanitized error codes/messages, without tracebacks. Scanner retains all ten symbols even on partial failure, with null measurements and per-ticker errors.

## Provider abstraction

```text
MarketDataProvider.fetch_snapshot(symbol, as_of)
        -> ProviderSnapshot(normalized Quote, completed HistoryPoints, Quality)
YahooMarketDataProvider
        -> MarketDataService (quote / ranged history / fixed-universe scanner)
        -> FastAPI router -> centralized frontend client -> shared polling resources
```

`provider.py` is a provider-neutral Python Protocol. Quote/history/scanner contracts live in `models.py`; no Yahoo-shaped JSON reaches frontend components. The snapshot boundary shares quote metadata and one year of completed daily bars, so three service operations reuse one download. A future licensed provider implements `fetch_snapshot` and normalized provenance/latency semantics, then is injected as `MarketDataService(provider=...)` into `create_app(market_service=...)`. No component, route or strategy rewrite is needed. A licensed provider may truthfully set `real_time_guaranteed`; Yahoo never does. Batch transport can be implemented behind the boundary later.

Yahoo v1 uses one `v8/finance/chart/<symbol>?interval=1d&range=1y` request per source snapshot, not quoteSummary, intraday downloads or strategy analysis. Service scans only ASELS, THYAO, TUPRS, BIMAS, EREGL, KCHOL, GARAN, SISE, FROTO, TCELL. Provider requests use API-owned sessions, no redirects/retries, 3-second connect / 8-second read timeouts. At most **two provider downloads** run concurrently, no unbounded executor queue, and a **24-second deadline** bounds scanner work. Pending symbols become timeout rows. Identical source requests and concurrent scanner callers share work. Sync downloads cannot be forcibly interrupted and may finish/cache after a waiter times out.

## Quote versus completed history

Quote price/time come from Yahoo `regularMarketPrice`/`regularMarketTime` when usable. This is provider data with unverified latency. `quote_time` is separate from `last_bar_time`, which is the last usable completed daily candle's original provider timestamp. A raw daily timestamp is the candle label/start, not its close time; it is preserved, not shifted. `fetched_at` is retrieval time, not trade time.

If metadata price is unusable, an actual last completed close can be returned with `price_basis=last_completed_close`, never a fabricated quote. Missing quote timestamp yields unknown freshness. A future quote timestamp rejects its associated price. Future daily rows are excluded before price inspection, reported and never used. Unknown calendar/session completion is not guessed. Current daily bars before the closing-price phase ends are excluded from completed history.

Daily previous close is the preceding scheduled session's usable close. If that candle is missing, change is null; it does not jump over the missing session. Yahoo `chartPreviousClose` is a **range-start reference**, and is deliberately not used as yesterday's close. Nullable day fields use finite metadata or available same-day raw OHLCV, with invalid values/ranges excluded and warnings. Currency stays null if unknown. No OHLCV filling, artificial points, score interpolation or future-row use.

Completed history reuses `backtest.data.clean_history`/strict validation unchanged. Missing OHLC/Volume drops the candle; infinity, invalid prices/volume and inconsistent OHLC refuse history, with quote/history availability reported separately. Calendar/range exclusions occur before candle cleaning. Quality counts describe the **one-year source snapshot**, not the number of points in a selected month/chart range. A metadata quote may still be usable while the latest daily Close is missing; quote and history freshness must therefore be distinct.

## Scheduled market status and freshness

Uses Europe/Istanbul and the existing versioned `intraday.session.BistCalendar` (2024–2026 holidays/half days), unchanged. Continuous-session boundaries come from that calendar. API-only opening/closing phase overlay uses the [BIST Equity Market Procedure](https://www.borsaistanbul.com/files/equity-market-procedure.pdf), revision 21 Sep 2026: opening auction from 09:40, closing-price phase through 18:10 on full days / 12:40 on half days. [Official holiday reference](https://www.borsaistanbul.com/en/official-holidays).

Statuses: open (continuous), pre_market_or_auction, closed, holiday, unknown. Weekends are closed, official holidays holiday, unsupported calendar years unknown. This is a **scheduled** status; halts/extraordinary closures and individual instruments are not monitored. Original bot market hours and intraday grid remain byte-identical.

Freshness states:

- **fresh**: contract-guaranteed real-time provider and quote age at most two minutes during an active session. Yahoo cannot reach this state.
- **delayed**: reasonably recent provider quote (within 20 minutes) without a live guarantee, or a prior completed close during an active session.
- **stale**: quote precedes the expected session, active-session quote exceeds 20 minutes, or a closed-session quote is earlier than the final 20 minutes of the expected session. Completed history older than the expected completed session is stale.
- **market_closed**: most recent expected completed-session quote/close is present while the scheduled market is closed/holiday.
- **unknown**: missing timestamp, unsupported calendar, or insufficient context.

Stale dominates closed status when expected data is absent. Delay contract status is separate and remains unknown for Yahoo unless an explicit positive delay is supplied; zero/absent delay metadata is not a real-time guarantee. Cached responses recompute session/freshness on access without modifying original quote/history timestamps.

## Cache and frontend polling

Thread-safe, API-owned TTL/LRU cache, maximum 128 entries; independent from existing analysis/bot caches:

- Quote/source bundle: **45 seconds**.
- Scanner: **60 seconds**.
- History per normalized symbol/interval/range: **300 seconds**.

Keys include operation, normalized symbol and range. Responses are copied; cache hit/age/TTL are explicit. Source snapshots reuse data between quote and history, including during scanner. Analysis API still uses its own two-year completed-only provider and 60-second cache; integrating its fetches with market snapshots is intentionally deferred to avoid changing strategy behavior.

Frontend `src/market/useMarket.ts` shares resources across components: scanner **60s**, stock quote **45s**, history **300s**. Requests start on subscription, not rendering; StrictMode does not double initial GETs. No overlapping resource request, duplicate component polls or automatic ten-ticker analysis. Hidden tabs pause timers; visible tabs refresh only due resources. Failed refreshes back off, up to five minutes. On last subscriber removal, timers/listeners are cleaned and the HTTP waiter aborts. Manual refresh respects server TTLs.

API mode is the default: `VITE_DATA_MODE=api`. Errors **never silently switch to demo**. Last successful provider snapshots may be retained with explicit failure text and stale/unknown labels. `VITE_DATA_MODE=demo` is explicit offline development; market GETs and Analyze action are disabled, fixtures retained. `?demo=1` also opens a visibly explicit stock demo view. All fetch calls go through the central API client, never directly to Yahoo.

Overview now uses scanner data for market status/retrieval time and preview. Scanner shows quote/change/volume/session/freshness/time/provider, without fake strategy columns. Stock detail uses separate quote/history GETs; Quant Analysis shows prior Analyze results with a separate as-of/bar time, or waits for an explicit Analyze action. Quote polling never recalculates strategy or overwrites an analysis snapshot. Portfolio value/P&L/risk/positions/equity/activity remain **Demo**; no position JSON is read. Intraday Strategy v2 is still not implemented.

## Validation — 10 Oct 2026

**334 Python tests passed, no skips**, including all existing 306 and 28 new market tests. TypeScript and production build passed. **45 offline browser checks**: 30 rendering/interaction checks, 10 virtual-time polling checks and 5 explicit demo-mode checks, covering quote/scanner/chart, partial errors, stale/offline states, no mock fallback, separate analysis, mobile layouts, 60s/45s/300s timers, hidden-tab pause and no analysis polling. No external calls or page errors in offline checks.

Controlled real validation used an in-process FastAPI TestClient, with **no frontend polling/server**: one quote + one 1mo daily-history GET each for ASELS/GARAN, then **exactly one scanner GET**. All five API responses HTTP 200; scanner had no failed ticker. **Exactly 10 Yahoo GETs**, one per fixed symbol, because the two quote/history pairs and scanner reused snapshots. Every request was:

```text
https://query1.finance.yahoo.com/v8/finance/chart/<TICKER>.IS?interval=1d&range=1y
```

Symbols: ASELS, GARAN, THYAO, TUPRS, BIMAS, EREGL, KCHOL, SISE, FROTO, TCELL. No retries, repeated polling, extra tickers, fundamentals/news calls, Analyze calls, Telegram or position changes.

| Ticker | Provider quote (TRY) | Quote timestamp (TRT, 2026-10-09) | Freshness |
| --- | ---: | --- | --- |
| ASELS | 351.25 | 18:09:58 | market_closed |
| GARAN | 129.30 | 18:09:49 | market_closed |
| THYAO | 287.50 | 18:09:59 | market_closed |
| TUPRS | 386.25 | 18:09:41 | market_closed |
| BIMAS | 402.75 | 18:09:55 | market_closed |
| EREGL | 37.32 | 18:09:45 | market_closed |
| KCHOL | 208.00 | 18:09:54 | market_closed |
| SISE | 38.04 | 18:09:47 | market_closed |
| FROTO | 74.65 | 18:09:46 | market_closed |
| TCELL | 98.55 | 18:09:57 | market_closed |

For **all ten tickers**, raw source row **251**, timestamp **2026-10-09 09:30 TRT**, had `close=null`. It was excluded from history. Last completed usable bar **2026-10-08 09:30 TRT**; histories are **stale**, although independently timestamped metadata quotes reflect Friday's close session. Each source had 252 rows; one first row outside the as-of one-year bound plus the missing latest Close yielded **250 usable / 2 removed**. No future rows or incomplete-session bars at Saturday as-of. No missing price was filled with the metadata quote. This is the principal provider anomaly; observations do not guarantee Yahoo latency or candle finality.

Full exact URLs, response schemas, timestamps and raw-null audit are recorded in ignored `.test-deps/market-real-validation.json`; this report preserves the meaningful results. Screenshots are in ignored `web/artifacts/market-*`.

## Protected-code verification and next milestone

SHA-256 baseline: **67 existing Python files checked; 66 byte-identical**. Sole existing Python change: `api/main.py`, purely additive market-router import/registration, optional market-service injection/app state and lifespan shutdown. Existing Analyze route/body/schema, error handlers and analysis services/adapters are unchanged; all existing 306 tests pass. No trading/backtest/intraday/research/existing-test code changed. No commit/push.

Limits: versioned calendar ends in 2026, exceptional closures are unknown, daily-only history, source revision/adjustment and Yahoo delay are unverified, sync network work may outlive a timeout. Next milestone: controlled open-session freshness/latency validation and a licensed BIST provider adapter, with calendar maintenance; no strategy optimization is implied.

