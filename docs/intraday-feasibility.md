# Short-Term Momentum Strategy v2 — feasibility audit

**Decision: the project can support an isolated intraday research prototype,
but the daily engine and raw Yahoo candles are not yet a reliable intraday
backtest contract.** No v2 strategy, execution engine, broker integration or
live behavior was implemented. Daily Strategy v1 and existing backtests remain
unchanged.

Audit anchor: 2026-10-09 19:52:44 Europe/Istanbul. Evidence is saved in
`backtest_results/intraday_data_audit/diagnosis.json` with original raw responses
and SHA256 fingerprints. The fixed basket was ASELS, THYAO, GARAN, TUPRS, BIMAS,
KCHOL, FROTO, TCELL, EREGL and SISE (all `.IS`). There were **39 controlled
requests**: 30 short ticker/interval probes, one hourly alias check, six retention
boundary probes, and two corporate-action reference probes. Four initial ASELS
responses were reused within this same audit. Final analysis replayed saved
responses offline; no repeat downloads or full-universe run occurred.

## Yahoo history: observed limits, not a service guarantee

| Interval | Successful bounded history probe | Oldest returned timestamp, Istanbul | Raw rows | Outside-limit result |
| --- | --- | --- | ---: | --- |
| 15m | Just inside the rolling 60-calendar-day boundary | 2026-08-11 09:45+03:00 | 1,496 | Start 61 days ago rejected; Yahoo explicitly requires the last 60 days. |
| 30m | Just inside the rolling 60-calendar-day boundary | 2026-08-11 09:30+03:00 | 749 | Start 61 days ago rejected with the same 60-day condition. |
| 60m / 1h | Just inside the rolling 730-calendar-day boundary | 2024-10-10 09:30+03:00 | 4,519 | Start 731 days ago rejected; Yahoo calls the interval `1h` and requires the last 730 days. |

The successful requests used a one-hour safety margin inside each boundary.
Oldest returned ages were approximately 59.42/59.43/729.43 calendar days; weekends
and session boundaries explain why the oldest candle is younger than the API
limit. Limits were actually probed on ASELS, not inferred from `validRanges`.
That metadata lists long ranges even for intervals that cannot retrieve them.
60m and 1h gave identical OHLCV/timestamps in the short alias sample.

The [yfinance maintainer source](https://raw.githubusercontent.com/ranaroussi/yfinance/main/yfinance/scrapers/history.py)
also uses 60/730-day bounds and includes a 30m-to-15m/resampling workaround for
a Yahoo interval bug. This project uses the raw chart endpoint, not yfinance;
native 30m worked in the observed sample, but its granularity must still be
validated on every fetch. No dependency was added for this audit.

Yahoo is therefore unsuitable for rebuilding several past years of 15m/30m
data now. An immutable prospective local cache or a suitably licensed historical
source is needed for longer subhour research. Hourly data currently offers a
much longer exploration window, but no availability/SLA/point-in-time guarantee.

## Recent basket observations

All 30 short probes returned data for 2026-10-05 through 2026-10-09. The following
counts apply **per ticker**, consistently across the ten-stock sample:

| Interval | Raw rows / five sessions | Full-interval continuous-session candidates | Null rows | Duplicate timestamps | Missing interior timestamps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15m | 170 | 160 (32/session) | 4, all 09:30 outside continuous trading | 0 | 0 |
| 30m | 86 | 80 (16/session) | 0 | 0 | 0 |
| 60m | 46 | 35 (7/session with native :30 alignment) | 0 | 0 | 0 |

Interior candidates had finite, internally consistent positive OHLC and
positive volume in this short sample. This is evidence of recent basket
availability, **not proof of long-history completeness for every ticker**.
The full-limit history was tested only on ASELS. Raw nulls were retained for
diagnosis; no prices, volume or missing candles were invented.

Native ASELS 30m interior bars matched aggregates of their two real 15m child
bars (80 comparisons); native 60m interiors matched four real children (35).
Incomplete child groups are never manufactured. This checks the observed bar
basis; it does not establish reliable auction mapping or future feed stability.

## Timezone and trading sessions

Yahoo returned UTC epoch seconds, `exchangeTimezoneName=Europe/Istanbul`,
`timezone=TRT`, and `gmtoffset=10800`. The diagnostic converts epoch seconds from
UTC to a timezone-aware Istanbul index and preserves hours/minutes. Naive CSV
timestamps require an explicit source timezone; no silent UTC/local inference.

For these ordinary equities, current exchange phases are: opening order
collection from 09:40, opening uncrossing around 09:55, continuous trading
10:00–18:00, then closing phases through 18:10. Half-day continuous trading ends
12:30, with closing-price activity through 12:40. These phase boundaries come
from the [BIST Equity Market Procedure, session-flow tables](https://www.borsaistanbul.com/files/equity-market-procedure.pdf),
not the bot's scan-hours constants. The [closing-session description](https://www.borsaistanbul.com/en/closing-session)
separates the closing auction and closing-price trades. The live bot's existing
09:30–18:10 scan window is **not** a continuous-trading calendar and was not changed.

The [official holiday calendar](https://www.borsaistanbul.com/en/official-holidays)
identifies closures and half-days. Its general "until 13:00" half-day label is
not a substitute for the equity procedure's 12:30 continuous-phase cutoff.
The long probe spans five relevant half-days: 2024-10-28, 2025-06-05,
2025-10-28, 2026-03-19 and 2026-05-26. Audit calendar evidence is linked in JSON;
this is not an implemented, production-maintained calendar service.

Observed Yahoo boundary behavior matters:

- 15m emits all-null 09:30 rows and flat zero-volume 09:45 rows; 30m emits flat
  zero-volume 09:30 rows. These are vendor pre-open/auction-adjacent labels, not
  verified ordinary executable bars. No tick-level phase classification exists.
- Native 1h starts at 09:30, 10:30, ... 17:30. Its 09:30 bar contains first-half-hour
  regular price movement but has zero volume in the short sample. For ASELS on
  2026-10-05, that bar high was 384.25 and close 377.75 with Volume=0; its two
  10:00/10:15 child bars had combined volume 10,768,180. Boundary volume cannot
  be trusted just because OHLC moves.
- The final native 17:30 hourly slot is a session-edge/partial interval, not an
  ordinary full hour through 18:30. Older history also has long clusters of null
  17:30 slots. Do not infer duration/completeness from the label alone.
- All intervals appended an 18:00 flat, zero-volume last-price row for the latest
  day. It is not a normal post-18:00 trading candle or a guaranteed executable
  closing-auction fill.
- Yahoo's historic `tradingPeriods` metadata says 09:30–18:00 even on the known
  2024-10-28 half-day. It cannot replace the official session calendar.

The audit's conservative full-day filter keeps only **whole nominal bars**
inside 10:00–18:00. For native hourly alignment this retains starts
10:30–16:30, excludes 09:30 and 17:30, and does not relabel or truncate them.
On a half-day it retains only complete bars before 12:30. This is a candidate
filter, not proof that every vendor bar contains exactly those ticks. Actual
bar duration and auction contamination remain data-contract acceptance gates.

## Long-history holes and corporate-action evidence

The 730-day ASELS response had 141 all-null rows, mostly closing-edge placeholders
and half-day afternoon slots. Under the naive full-day candidate filter, 21 null
rows remained. Applying explicit holiday and half-day dates gives 502 observed
sessions, no entirely missing scheduled sessions, 3,489 expected interior slots,
and **one unusable slot: 2026-04-20 10:30+03:00** (all OHLCV null), leaving 3,488
finite candidates. The cause is unresolved; it is not an official holiday or
half-day in the checked schedule. A halt/feed issue/no-data episode cannot be
distinguished here. Timestamp presence alone is not usable-candle completeness.
No forward-fill, interpolation or fake survival through that gap is acceptable.

A particularly important no-lookahead risk was directly observed: a historical
FROTO hourly request covering a small May 2025 split window also returned
**2026-10-09 18:00+03:00**, a current-price row outside its requested end. Any future
provider must enforce `start <= bar_start < end` and completed/available-at rules
before indicators or signals; raw result length/end metadata is insufficient.

Yahoo reported FROTO's 2025-05-07 split as `1000:100` (10:1). Captured hourly and
daily pre/post prices are both around 88, consistent with retrospectively
split-adjusted price units rather than a raw 10x discontinuity. That is an
observation of this retrieved vintage, not a point-in-time adjustment guarantee.
Intraday output had only `quote`; the daily reference had `quote` plus `adjclose`,
dividend/split events, and adjusted-close/close ratios from about 0.87985 to 1.
Do not assume intraday OHLC includes dividend total returns or apply a daily
adjustment factor again without an explicit basis contract.

Volume basis requires additional validation: FROTO hourly summed volume and
daily reference volume differ around the split. On 2025-05-06 they were
1,162,760 versus 14,615,020; on 2025-05-08, 15,664,313 versus 9,947,869. Auction
coverage, vendor adjustments or feed aggregation may contribute; this audit
does not choose a correction factor. Snapshot OHLCV/events/retrieval timestamps
must be versioned, and price/volume adjustment status labeled **unknown unless
verified**. Original raw responses are preserved for follow-up.

## Code reuse and daily assumptions

| Existing piece | Reuse assessment |
| --- | --- |
| `bot.indicators`: EMA, Wilder RSI/ATR/TR/ADX, MACD, Bollinger, StochRSI, OBV, MFI, CMF, Donchian, forward SuperTrend | Bar-based causal math is reusable on ordered, validated bars. Periods mean bars, not days; daily parameters are not an established v2 specification. Overnight TR and session resets need explicit policy. |
| HH/HL and support/resistance | Centered live pivots must remain prefix-only/confirmation-delayed. Backtest confirmed-pivot math is reusable after preserving full timestamps. Breakout levels must be already known, rather than comparing against a current-bar-inclusive resistance. |
| Ichimoku | Positive-shift implementation is causal; availability and warmup are bar-based. Not required for the first minimal v2 research setup. |
| Approximate VWAP | Existing rolling 20-bar approximation is not session-cumulative VWAP. A true intraday/session version needs separate adaptation. |
| Historical volatility | Hardcoded sqrt(252) assumes daily observations; do not apply it to intraday returns without a new explicitly documented annualization basis. |
| `bot.scoring` / `backtest.signals` | Numerical comparisons/components are inspectable, but daily weights, thresholds, minimum lengths, confidence rules, 80-point denominator and whale-volume rolling mean are a Daily v1 strategy, not an intraday strategy. Leave untouched; no automatic v2 reuse of those decisions. |
| `backtest.execution.position_quantity` | Stop-distance risk math and cash/commission cap are reusable; smaller ATR can produce large notionals. Keep 1% cap and reserved cash, adding independent portfolio/day/week risk gates later. |
| `process_candle` and pure fill/cost math | Stop-first/target-first ambiguity, gap fills, TP1 state and next-candle trailing timing are useful tested primitives. A timestamp/session-aware adapter and duration-aware position state are needed before intraday replay. |
| `backtest.data` | Unsafe as an intraday loader: index is normalized to date, timezone removed, `interval=1d` fixed, and same-day rows become duplicate dates. Do not modify Daily v1; propose a separate intraday provider. |
| `backtest.engine` | Daily timeline and `.date().isoformat()` decision/entry/exit values collapse time. No session close/overnight policy or bar publication cutoff. Daily engine cannot be used unchanged. |
| `close_position` / holding fields | Calendar `date.fromisoformat()` is not an intraday timestamp model. Add elapsed minutes, session count and held bars without reporting every intraday trade as zero days. |
| `backtest.metrics` / reporting | CSV/JSON/Markdown/chart utilities are reusable. Daily equity, sqrt(252) Sharpe and observation gates require session-close aggregation; do not annualize every 15m observation as if it were a day. |
| Multi-ticker ranking/cash ledger | Stored-score ranking and deterministic ticker ties are useful patterns. Intraday must process all tickers on a shared bar-event clock, reserve opening cash before intrabar exit proceeds, and expose missing/stale timestamps. |

## Intraday execution and no-lookahead risks

The future signal from a completed bar t may enter only a subsequent executable
bar Open; changing the word "day" to "bar" is not enough. Reject unfinished
bars and appended out-of-range prices. Store `bar_start`, `bar_end`, signal time
and availability time. No signal can use the entry bar's High/Low/Close, a future
confirmed pivot, or an unfinished higher-timeframe candle.

Stop/target touches remain ambiguous inside a 15m/30m/1h OHLC bar. Keep explicit
conservative stop-first as baseline; a finer candle is not tick execution proof.
Close-derived ATR trailing updates activate only after that bar completes, on
the next bar. TP1 has no partial sale in current v1; any v2 change needs its own
future specification, not a hidden adaptation here.

Do not allow a generic next-available-bar loop to carry an entry across an
overnight gap, a data hole, or the closing auction without a declared policy.
First research version should specify flat-at-session-end versus overnight
holding explicitly. A flat policy needs a real eligible liquidation price and
entry cutoff before the close, not an 18:00 zero-volume snapshot. Gaps can exceed
nominal stop risk; price limits, halts, tick-size/queue effects and limited volume
make guaranteed OHLC fills unrealistic. Timestamp-level P&L/cash and session
daily-equity reporting must be distinguished.

## Proposed provider and module shape — not implemented

Keep a small synchronous interface:

```python
fetch(ticker, interval, start, end, *, as_of) -> (bars, audit_metadata)
```

All arguments are timezone-aware; end is exclusive. `bars` preserves an Istanbul
`bar_start` index and OHLCV, with explicit bar-end/availability/session identifiers.
Audit metadata records requested versus returned bounds, source/interval, raw
snapshot hash and retrieval time, discarded/invalid/duplicate records, phase,
adjustment status and known gaps. Transport failures are explicit, not empty
"valid" histories. Use immutable raw JSON plus local ISO-offset CSV snapshots
for deterministic offline research; never request Yahoo inside a backtest loop.

Proposed future files only:

```text
intraday/data.py       Yahoo/CSV boundary, range and completion checks, audit
intraday/session.py    versioned exchange dates/phases, full and half-days
intraday/strategy.py   later fixed research setup; causal bar/MTF interfaces
intraday/execution.py  timestamp/session adapter around reusable tested math
intraday/backtest.py   bar-event orchestration, risk gates and session equity
```

No database, queue, async system or web framework is needed. Do not fork daily
scoring into a renamed v2 engine or duplicate all indicators. The current change
adds only `research/intraday_audit.py`, offline helper tests, this document, and
ignored diagnostic artifacts; it does not create those proposed strategy files.

## Setup families and timeframe choice

| Family | Needed information | Additional controls before research |
| --- | --- | --- |
| A: trend breakout | EMA/trend context, already-known rolling/confirmed resistance, ATR/range, expanding volume, momentum confirmation | Exclude current bar from reference resistance; validate volume basis and time-of-day seasonality; confirm any higher-timeframe bar before use. |
| B: pullback continuation | Established EMA20/EMA50 context, price/ATR pullback geometry, RSI/MACD or causal momentum resumption | Define setup/confirmation before examining P&L; fewer dependencies on fragile auction volume or multi-timeframe joins. |
| C: volume momentum breakout | Reliable volume, comparable same-time-of-day history, price expansion/ATR, momentum | Current rolling daily whale heuristic is not an intraday volume-seasonality model. Split/auction volume inconsistencies are blockers. |

| Candidate | Data feasibility | Assessment |
| --- | --- | --- |
| 15m entry + 1h trend | Entry history caps the paired dataset at ~60 calendar days, despite longer hourly availability. | Feasible for a recent smoke test/prospective cache; limited regime coverage and added bar-close join risk. |
| 30m entry + 1h trend | Same ~60-day overlap; fewer bars and less noise/complexity than 15m, but native hourly :30 anchors differ from a session-aligned 10:00 hourly grid. | Practical second target after a validated cache and completed-bar joins. Do not silently combine grids. |
| 1h standalone | ~730-day access; approximately seven nominal full interior slots per ordinary session and thousands of candidates. | Preferred first isolated prototype, conditional on data/session acceptance gates. Simpler single-timeframe chronology and longer sample. |

**Recommended first research target: 1h standalone, family B (pullback
continuation), restricted to verified continuous-session interior bars.** This
choice is based on observed history depth, manageable chronology and reusable
causal trend/momentum math, not expected returns. Actual trade frequency is
unknown until a fixed setup is specified; seven candidates/session is bar
availability, not seven trades. The first/last native hourly slots, historical
duration/completeness, known null bar and corporate-action/volume basis must be
resolved or explicitly excluded with gap rules before a trustworthy backtest.

A later 15m/30m + 1h implementation must align on **completed** higher bars.
For example, a native 10:30–11:30 hourly bar is unavailable to an 11:15 entry
decision. Derived 10:00-anchored hourly bars require all real child candles and
must be kept distinct from the native :30 series. Do not synthesize lower
frequency detail from hourly OHLC or interpolate missing children.

## Risk and cost requirements before any live consideration

Reuse the current 1% risk-per-trade ceiling, stop-distance sizing, cash reservation
and maximum-position control without increasing risk. Five positions can imply
up to five nominal risk units; intraday churn and correlated BIST exposures need
an explicit total open-risk budget including estimated exit costs/gap exposure.

Before live usage, specify and test: daily and weekly realized-plus-marked loss
limits; maximum trades per session/ticker; cooldown after consecutive losses;
no new entries near the session/half-day close; explicit overnight policy;
halt/data-stale circuit breakers; quantity/notional/liquidity participation
limits; duplicate-signal/order protection; and deterministic kill/stop behavior.
Exact budgets/cutoffs should be an approved research specification, not selected
after a profitable backtest. None were implemented in this audit.

Intraday OHLC has no bid/ask quotes. Costs must separately identify commission,
adverse execution slippage, spread proxy, and any applicable actual fee/tax
schedule. No exact broker fee is asserted here. Current v1's 0.10% commission
plus 0.10% slippage each way implies roughly **40 basis points round trip** for
an unchanged reference price, before additional costs; that is a configurable
research assumption, not a broker quote. If slippage already includes half-spread,
do not add the same spread again. Alternatively expose spread basis points and
residual slippage separately, documenting adverse buy/sell treatment and minimum
fees from an actual quoted schedule. Stress assumptions should be predeclared,
not tuned to increase return. Small stops/targets need cost-aware acceptance.

## Next milestone and remaining blockers

Next: **Intraday Data Contract & Session Replay v0**, still before strategy
optimization. Implement isolated Yahoo/CSV snapshots, explicit official session
calendar, full aware timestamps/completion/availability gates, range enforcement,
phase classification and versioned adjustment flags. Verify historical bar
durations, volumes/actions and the 2026-04-20 hole against an independent source
or fail unsafe segments. Add timestamp-based next-bar/session/overnight fixtures,
hold duration, shared cash and configurable cost/spread accounting tests.

Acceptance gates: deterministic offline replay; no current-price append leakage;
no fill/interpolation; no unclassified conflicting duplicates/data gaps; no
unfinished higher-bar joins; certified half-day behavior; explicit entry/exit
cutoffs; and unchanged Daily v1 hashes/tests. Only after those gates define one
fixed pullback setup and measure its selectivity and costs. Yahoo alone cannot
provide a multi-year 15m/30m regime validation or execution-quality/spread proof.

## Verification

```powershell
python -m unittest tests.test_intraday_audit -v
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest research tests
python -c "import research.intraday_audit, backtest.engine, bot.main; print('imports OK')"
```

The diagnostic-only helpers cover timezone preservation, explicit full/half-day
filtering, duplicate conflicts, missing slots/whole sessions/holidays, complete
real-child aggregation, out-of-range/partial/null bars, bounded network failure,
rate-limit stopping and successful export. All tests are offline. Existing
strategy/backtest files are hash-checked and the full project suite is rerun.
No commit or push is part of this audit.
