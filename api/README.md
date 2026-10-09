# Analysis API v1

[Analysis Explanation v1](explanations/README.md) additively supplies deterministic observations/evidence on the existing completed analysis snapshot. Scores/signals/providers remain unchanged; no LLM or advice is added.

The additive [Market Data Layer v1](market/README.md) now supplies quote/history/scanner endpoints. Analysis API request/response/strategy behavior remains unchanged. The updated dashboard separates provider prices from on-demand Quant Analysis.

Independent, read-only FastAPI layer. No bot runtime, Telegram polling, position tracking, persistence, messages, Strategy v2, brokerage or LLM is started. Original trading/backtest/intraday/research code remains byte-identical; only API entry-point market-route wiring is additive. Market monitoring now polls the fixed ten-ticker basket independently of strategy; see its separate documentation.

## Startup

From the repository root, use a separate environment:

```powershell
python -m venv .venv-api
.\.venv-api\Scripts\python.exe -m pip install -r requirements-api.txt
.\.venv-api\Scripts\python.exe -m api.main
```

API: `http://127.0.0.1:8000`. Optional reload:

```powershell
.\.venv-api\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

No Telegram credentials or root `.env` loading are needed. HTTPX is included for offline API tests. The temporary validation dependency directory is not required for normal use.

Frontend, in a second terminal:

```powershell
cd web
npm.cmd install
# Optional: copy .env.example to .env.local to customize the API URL.
npm.cmd run dev
```

Default `VITE_API_BASE_URL=http://127.0.0.1:8000`; UI `http://127.0.0.1:5173`. CORS allows only localhost/127.0.0.1 port 5173, GET/POST and Content-Type, without credentials or wildcards. Both servers default to loopback; this is a local research API, not an authenticated deployment.

## Endpoints and errors

- `GET /api/v1/health`: API process health, not Yahoo availability.
- `GET /api/v1/strategies/status`: Daily v1 available, intraday data contract ready, **Intraday Strategy v2 not_implemented**.
- `POST /api/v1/analyze`: `{"ticker":"ASELS"}`. Accepts ASELS/ASELS.IS/lowercase/trimmed forms. Rejects non-ASCII, non-letter-leading, overlong, path-like and foreign-exchange symbols and unexpected fields.

Success uses `AnalysisResponse` in `models.py`. Errors are `{"error":{"code":"...","message":"..."}}`, without tracebacks/provider exception details: invalid request/no data/insufficient data 422; provider/invalid candles 502; busy 503; timeout 504; unexpected error 500.

## Architecture and exact reuse

```text
api/main.py                       Routes, CORS, sanitized errors, lifespan
api/models.py                     Finite request/response contract
api/errors.py                     Public error type
api/adapters/daily_strategy_adapter.py
                                  Thin existing provider/engine adapter
api/services/analysis_service.py   Workers, single-flight, TTL/LRU cache
api/services/strategy_service.py   Capability status
```

Directly reused, without copying formulas:

- `backtest.data.normalize_ticker`, `YahooProvider.fetch`, `clean_history` and its `validate_frame` boundary. YahooProvider uses `bot.market_data.chart_quote` internally.
- `backtest.signals.prepare_indicators`, which orchestrates the original `bot.indicators.hesapla_*` functions.
- `bot.scoring.trend_puani_hesapla`, `momentum_puani_hesapla`, `hacim_puani_hesapla`, `volatilite_puani_hesapla`, `destek_direnc_ayarlamasi`, `toplam_skorlar`.
- `backtest.signals.support_resistance`, `signal_from_history`; classification remains its existing `bot.scoring.siniflandirma_etiketi` result.
- Original `bot.config` category maxima, minimum history, timezone and EMA200/Ichimoku eligibility constants.

`bot.analysis.analiz_et` is not invoked because it manages cooldowns, positions, fundamentals/news and Telegram sends. `bot.scheduler.piyasa_acik_mi` is a weekday clock, not a holiday-aware exchange calendar; its coupled runtime modules need not be imported. Market status is **unknown**, rather than an invented open/closed exchange status.

## Data and score semantics

Two years of Yahoo raw daily OHLCV through **yesterday**, Istanbul time, using the existing completed-bar-only provider. Today's bar is excluded even after today's close. Price is the latest usable completed close, not regularMarketPrice. Change compares the last two usable closes; removed candles may make it span multiple sessions. UI labels this basis.

Existing cleaning is unchanged: missing OHLC/Volume drops the candle; infinity, nonnumeric/boolean values, nonpositive prices, negative volume and inconsistent OHLC fail. Explicit numeric conversion, stable sorting, first-source duplicate selection and the 5% removed-row limit are reused. No filling, interpolation or artificial candles. Counts and dated warnings are returned; insufficient history fails. Recent chart closes come from the same cleaned frame.

Category scales remain **25 / 20 / 15 / 10**, shown with their actual maxima. `overall` is the existing final formula; `technical` is the existing normalized formula with its unchanged **80-point denominator** and support/resistance adjustment. Progress bars visualize category completion only, without reweighting.

News/fundamentals are **null/unavailable**. No quoteSummary, news service or bot cache is called. Formulas receive zero missing contributions, matching the existing neutral backtest convention; scope/warnings explicitly disclose this. This is not a full current-news/fundamental live-bot evaluation. State/signal/classification come from the existing neutral technical decision, without a new classifier or changed thresholds.

Indicator fields include RSI, EMAs, ATR, ADX, MACD/signal, MFI, CMF, OBV, approximate daily VWAP, historical volatility and **SuperTrend direction (+1/-1), not a stop price**. Undefined/non-finite optional indicators become null; critical scores/prices reject non-finite values. JSON never contains NaN/Infinity. ATR% is ATR/close; unavailable volatility classification remains null.

`as_of` is calculation time. Freshness compares last usable bar with the preceding weekday; holidays are not modeled. A stale flag may reflect provider delays, rejected latest candles or holidays. Yahoo may retrospectively revise/split-adjust history; it is not point-in-time data. No streaming/websocket is added.

## Timeouts and cache

API-owned Requests sessions: no bot session/cache sharing, no retries/redirects, 3-second connection / 12-second read timeout. HTTP analysis deadline 25 seconds; frontend deadline 30 seconds. Read timeout is an inactivity limit; running synchronous work cannot be forcibly cancelled. Two bounded workers, no queued unique analyses; excess distinct work returns 503, identical in-flight requests share a computation. Failed/over-deadline computations are not cached.

Thread-safe, process-local in-memory cache: **60-second TTL, maximum 128 entries**, LRU eviction, normalized symbol + analysis type/scope key. Response copies expose cache hit, age and TTL. No persistence.

## Frontend flow

Overview Analyze → centralized `web/src/api/analysis.ts`/`client.ts` → POST → existing provider/engine → response validation → in-memory `AnalysisProvider` → `/stocks/ASELS`.

Loading disables duplicate submit; invalid input stays local; failure shows an error, **never mock fallback**. With Market Data Layer v1, direct stock URLs fetch quote/history and request strategy analysis only on explicit action. Prior Analyze results remain visible in a separate Quant Analysis section. Refresh uses backend TTL; failed refresh explicitly retains the previous successful snapshot/as-of time. Navigation aborts the waiter, although shared backend work may finish.

Mock fixtures are retained for explicit demo mode. Default market scanner uses fixed-universe quote data, without running strategy; portfolio/activity remain Demo. Real detail never mixes mock levels/statistics into market or analysis values. See the Market Data Layer documentation for mode, polling and provider provenance.

## Validation — 10 Oct 2026

```powershell
.\.venv-api\Scripts\python.exe -m pip install -r requirements-backtest.txt
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -v
cd web
npm.cmd run typecheck
npm.cmd run build
```

**306 Python tests passed, none skipped**, including 25 new offline API tests; existing optional Matplotlib enabled three chart tests. Tests block external calls and inject synthetic providers. TypeScript/build passed. **63 offline browser checks passed**: 24 Analyze-flow checks plus 39 preserved-dashboard checks for navigation, scanner search/filter/sort, sidebar, charts and responsive layouts. No unexpected page errors or external calls. Upstream Starlette TestClient emits an HTTPX compatibility deprecation notice; tests still pass.

Controlled real validation: local GET health, GET strategy status, CORS OPTIONS analyze and one browser POST Analyze ASELS. Only external market request:

```text
GET https://query1.finance.yahoo.com/v8/finance/chart/ASELS.IS?interval=1d&period1=1728421200&period2=1791579600
```

No retries, redirects, second ticker, fundamentals/news calls, scans, messages or position changes.

HTTP 200: **503 downloaded / 1 removed / 502 usable**. Yahoo source row **502 / 2026-10-09** had missing **Close**. Latest usable bar **2026-10-08**, close **₺348.75**, previous usable close **₺348.75**, change **0.00%**. Final **11**, technical **13.75**, **no_setup**, signal null. Response/UI marked stale versus expected 2026-10-09. These are descriptive outputs, not profitability evidence.

SHA-256: all **57 pre-existing protected Python files unchanged**. No live bot, commit or push. Temporary audited API server is stopped after validation; the existing frontend server is left alone.

