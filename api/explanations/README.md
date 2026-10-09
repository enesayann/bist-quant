# Analysis Explanation v1

Pure deterministic explanations from an existing **completed-candle analysis snapshot**. No indicators, scores, signals, provider behavior, trading thresholds or positions are changed. No network, wall clock, news/fundamental lookup, LLM or investment advice.

## Architecture and additive API contract

```text
Existing AnalysisResponse
  -> generate_explanation(snapshot)
  -> central rules + typed evidence
  -> optional/additive response.explanation
  -> validated frontend -> Analysis Explanation / Quant Summary
```

`models.py` defines Pydantic components, numeric Evidence (rule_id/inputs/observation/derived), summary, source timestamps, warnings and rules version. It is independent of strategy models to avoid import cycles. `rules.py` centralizes descriptive policy; `service.py` assembles components without I/O or scoring calls.

The only existing backend file changed is `api/models.py`: the optional `explanation` field and after-validation generation from already-calculated values. The adapter, analysis/cache service, endpoints and all market provider modules remain byte-identical. Existing response fields are unchanged, and explanation is cached alongside its source snapshot. Legacy responses can omit it; the frontend still renders valid numeric analysis. Malformed/unrecognized/wrong-snapshot explanation is ignored with an unavailable state rather than hiding numbers or inventing prose.

Response addition:

```text
explanation:
  rules_version: analysis-explanation-v1
  analysis_as_of / analysis_last_bar / market_status / scope
  trend, momentum, volume, risk:
    state / headline / points
    evidence: rule_id, finite inputs, observation, derived
    missing_inputs
  summary: headline / text
  warnings
```

## Descriptive policy — independent of scoring

These labels observe values, not entry/exit gates or score contributions. The engine's RSI healthy-point band, history-dependent crossovers, pivots, relative volume and other conditions are **not recreated**. Numeric scores/strategy state remain authoritative; the prose explicitly warns it cannot explain every scoring point from this scalar response.

| Component | Rule / boundaries |
| --- | --- |
| Trend state | Bullish if close > EMA20 > EMA50; bearish if close < EMA20 < EMA50; neutral if all equal; other complete arrangements mixed; missing core input unknown/partial. |
| Trend observations | Close vs each EMA; EMA20 vs EMA50. ADX <20 weak, 20–25 moderate, >25 strong. Strong threshold reads original `ADX_ESIK`; ADX strength is not direction. SuperTrend ±1 is direction only, never a stop price. |
| RSI | [0,30) low/weak; [30,45) weak; [45,55) neutral; [55,60) positive; [60,70) strong; [70,100] overextended. These are descriptive regions, not changed strategy RSI thresholds. |
| MACD | Compare current MACD with current signal. Above/below/equal yields positive/weak/neutral when RSI is missing; opposing RSI/MACD observations are mixed. A single snapshot never establishes a crossover. High RSI stays overextended. |
| MFI | <=20 low; 20<MFI<80 central; >=80 high. Observation only, no standalone component direction. |
| Volume state | CMF >0.05 positive, <-0.05 negative, [-0.05,0.05] moderate/limited magnitude. Reads original positive `CMF_ESIK`; symmetric negative band is descriptive only. |
| Other volume observations | Close vs actual daily VWAP approximation; supplied MFI and OBV level. No OBV direction without earlier OBV; no fabricated absolute/relative volume or ratio from an unrelated live quote. |
| ATR / close | <2% low; [2,4)% moderate; [4,6)% elevated; >=6% high. Existing API ATR% takes precedence. If absent, safely derive ATR/positive analysis close ×100 and mark the evidence derived. |
| Historical volatility | <20% low; [20,40)% moderate; [40,65]% elevated; >65% high. Reads original 20/65 bounds; 40 is descriptive policy. Existing indicator is annualized 20-day log-return volatility. |
| Risk state | Higher descriptive severity of available ATR% and historical volatility; unknown if neither usable. Market volatility only, not portfolio/personalized risk or safety. |

All comparisons use full precision; text display uses eight significant digits and evidence retains exact floats (frontend value tooltip shows full value). NaN/Infinity/bools/invalid indicator domains become unavailable **only for explanation**; original response fields are never mutated. No missing values are zero-filled. Safe ratio overflow is excluded.

Summary is assembled from the four known states. Unknown/partial context remains unknown. No price targets, future-price claims, recommendations, fresh crossover or directional-OBV claims. News/fundamentals are not narrated when null; existing UI marks them unavailable.

## Freshness and provenance

Rules use `market.price` from the analysis snapshot, **not the independently polled quote**. Explanation carries the exact analysis timestamp/bar and is bound to those fields by the frontend. Stale analysis warns: “Analysis is based on the latest completed available candle and may not represent the current session.” Missing inputs are listed in each card; only usable values produce observations/evidence.

If an input snapshot explicitly reports closed/holiday, the explanation says so. Current Analysis API v1 reports `market_status=unknown`; it stays unknown here, even though the separate Market Data Layer can report a scheduled closed/open session. No calendar/provider request or session inference is added to explanation generation. The stock page keeps both provenances separate.

## Frontend

`src/api/explanation.ts` supplies typed optional validation, including finite evidence and timestamp binding. `AnalysisExplanation.tsx` adds four graphite/bronze cards, Quant Summary, stale/partial notes and keyboard-accessible native evidence disclosure. Numeric cards and all existing indicators remain visible. No prose is generated in JSX or used to replace failed real analysis. Legacy/malformed explanation shows an unavailable card; failed Analyze still shows its real API error without mock fallback.

## Tests / verification — 10 Oct 2026

**35 new offline tests**, **369 total Python tests passed**, none skipped. Cases include EMA structures/missing/equal/mixed, RSI regions, MACD conflicts, ADX boundaries, SuperTrend, CMF signs/bounds, VWAP, OBV limitations, ATR derivation/overflow, volatility composition, all-missing/domain-invalid/non-finite values, stale/closed/unknown context, summary, deterministic repeatability/no mutation/no scoring/provider calls, unchanged legacy fields and cached endpoint explanations.

TypeScript and production build passed. **24 offline browser checks**: Analyze flow, four cards/summary, numeric preservation, metric evidence, missing/malformed/wrong-snapshot explanation, partial input, stale warning, desktop/390px/320px layouts and failed Analyze without fallback. No page errors/external calls.

Standard verification:

```powershell
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -v
cd web
npm.cmd run typecheck
npm.cmd run build
```

Use the existing API/backtest requirements to enable all tests. No new dependencies. Startup is unchanged (`python -m api.main`, frontend `npm.cmd run dev`).

## Real ASELS validation — recorded snapshot replay, zero new requests

Reused the already-saved successful real ASELS response from **2026-10-10 00:28:03.703517 TRT**, analysis bar **2026-10-08**. This is **not a newly downloaded/current analysis**. Explanation replay ran with Requests blocked and proved every pre-existing response field identical. No scanner, Yahoo, Telegram or position operation occurred.

| Actual metric from saved response | Value | Observation |
| --- | ---: | --- |
| Analysis close | 348.75 | Below both EMAs and VWAP |
| EMA20 / EMA50 | 366.80067558479334 / 372.9603651719748 | Bearish EMA structure |
| ADX | 25.77995702345507 | Strong strength, not bullish direction |
| SuperTrend | -1 | Negative direction |
| RSI | 42.29112163645962 | Weak descriptive region |
| MACD / signal | -6.784692866280523 / -5.5500834940795585 | MACD below signal; no crossover claim |
| MFI | 39.65082005675782 | Central 20–80 region |
| CMF | -0.14134795613960158 | Negative flow observation |
| VWAP approximation | 365.88307082495317 | Close below calculated approximation |
| OBV | 2618703375 | Level only; trend unavailable |
| ATR / ATR% | 17.952383056031692 / 5.147636718575396% | Elevated ATR variability |
| Historical volatility | 65.71514463010568% | High band; composite volatility label high |

Generated summary: “EMA structure is negative; momentum observations are weak. CMF flow is negative, while observed market volatility is high. This describes the analysis candle, not a forecast or an action recommendation.”

Stale warning present, market/session unknown; missing absolute/relative volume explicitly listed. Final score **11**, technical **13.75**, state **no_setup** stayed unchanged. Raw replay/evidence: ignored `.test-deps/explanation-asels-replay.json`; browser screenshots: ignored `web/artifacts/explanation-*`.

## Protected files and future boundary

All original trading/backtest/intraday/research/provider code remains byte-identical. SHA-256 baseline covers 76 existing Python files; **75 unchanged**, only `api/models.py` has additive explanation typing/validation. No commit/push.

Limits: scalar snapshots cannot prove trajectories, OBV trend, relative volume, crossings or all score conditions. Descriptive regions are broad labels, not statistically validated forecasts. A future LLM could only render this validated, versioned evidence into alternate prose, without fetching facts or changing scores/states; deterministic facts and missing-data policy would remain authoritative. No external LLM is integrated now. Recommended next milestone: expose existing per-condition score evidence read-only, with parity tests, before considering a narrative renderer.
