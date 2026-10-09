# BIST Quant — Market Data Layer v1

**Analysis Explanation v1:** Quant Analysis now also shows deterministic Trend/Momentum/Volume/Risk cards and Quant Summary, with expandable metric evidence and stale/missing-input notes. Numeric analysis remains visible; explanation uses its completed candle rather than the independent quote. Missing/legacy explanation is graceful, and no LLM or recommendation is generated. See [rules, boundaries and replay verification](../api/explanations/README.md). Latest checks: 369 Python tests (35 new), TypeScript/build and 24 explanation browser checks passed.

Provider-backed Overview status/scanner, Market Scanner and stock quote/history, with separate on-demand Quant Analysis. Portfolio/P&L/risk/positions/equity/activity remain explicitly **Demo**. No strategy changes, orders or Telegram actions.

## Run

Start the API using [API setup](../api/README.md), then:

```powershell
cd C:\Users\ayann\Desktop\BIST_BOT\web
npm.cmd install
npm.cmd run dev
```

Node 22.12+ (or 20.19+). Defaults: API http://127.0.0.1:8000, UI http://127.0.0.1:5173; loopback only. Public configuration in `.env.example`, copied to `.env.local` if needed:

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DATA_MODE=api
```

Explicit `VITE_DATA_MODE=demo` enables offline fixtures, disables market calls and hides real Analyze. API errors never switch to demo. `?demo=1` stock views remain visibly explicit. Restart Vite after environment changes. No secrets in Vite variables.

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run preview
```

Use `npm` on macOS/Linux. Production `dist/` needs SPA fallback. Local API CORS permits port 5173 only; another API-mode origin needs explicit configuration. No new frontend dependencies.

## Structure and behavior

- `src/market/`: normalized types/client, shared polling, explicit mode.
- `src/api/`: preserved Analysis API client/types and successful snapshots.
- `src/components/`: MarketData, RealAnalysis, charts/tables/shell/UI primitives.
- `src/pages/`: Overview, Scanner, MarketStockDetail and demo/scaffolds.
- `src/data/`: preserved central mock fixtures.
- `src/index.css`: graphite/bronze tokens and responsive layouts.

Overview and Scanner share GET `/api/v1/market/scanner`: ten symbols, quote/change/volume/session/freshness/time, provider and errors. No fake scores or automatic analysis. Detail fetches separate quote and daily history GETs. Charts use actual closes with no synthetic sessions; quote/bar/retrieval timestamps are distinct from Quant Analysis.

Analyze retains POST `/api/v1/analyze`, stores results and navigates to detail. Prior results appear separately; navigation/polling never recalculates strategy. Detail offers an explicit Analyze action. Failures never substitute mock values; failed refreshes may retain a visibly identified old provider snapshot with stale/unknown labels.

All HTTP is centralized, never directly to Yahoo. Shared resources avoid per-render/duplicate/overlapping calls. Scanner **60s**, quote **45s**, history **300s**; hidden-tab pause, visibility resume, failure backoff up to five minutes and unsubscribe cleanup. Manual refresh respects backend TTLs.

Yahoo is never labeled LIVE; latency/finality are unverified. Quote metadata can be valid while latest daily Close is missing, so history and quote freshness differ. Scheduled session status does not detect halts/exceptional closures. See [Market Data documentation](../api/market/README.md) for provider replacement, cache/calendar rules and limitations. No actual position JSON is read.

## Verification — 10 Oct 2026

334 Python tests passed (existing 306 + 28 new); TypeScript/build passed. 45 offline browser checks covered rendering, failures/staleness/no fallback, separate analysis, mobile and virtual-time polling; zero external calls/page errors. Explicit demo mode passed five checks with zero API requests.

Controlled real validation: one ASELS/GARAN quote/history pass, then one scanner GET; **10 Yahoo GETs** through reuse. All responses HTTP 200. Quotes 9 Oct 18:09 (`market_closed`); all ten daily arrays had a null 9 Oct Close, so history ended 8 Oct (`stale`). No filling, repeated polling/analysis, messages or position changes. Exact URLs/timestamps/anomalies: linked report.

67 Python baseline files: **66 unchanged**, sole additive change `api/main.py` router/service lifecycle registration. Trading logic and Analyze schema/behavior unchanged. Screenshots: ignored `artifacts/market-*`. Existing user frontend server preserved.
