# Intraday Data Contract & Session Replay v0

This is an isolated data/replay milestone for ordinary BIST equities using
native Yahoo 1h bars. It implements no Strategy v2, signals, entry/exit simulator,
profitability test, broker, leverage or live integration. Daily Strategy v1,
its indicators/risk model and the existing backtest/validation engines are
unchanged. See [the feasibility audit](intraday-feasibility.md) for evidence.

## Modules and schema

| File | Responsibility |
| --- | --- |
| `intraday/session.py` | Explicit versioned exchange dates/phases, native hourly grid and completion helpers. |
| `intraday/data.py` | Range/schema/session validation, deterministic row diagnostics, gap and action-risk checks. |
| `intraday/cache.py` | Immutable normalized CSV snapshots, integrity checks, exclusive writer and atomic manifest. |
| `intraday/provider.py` | Yahoo, offline cache and standalone CSV providers with the same normalized contract. |
| `intraday/replay.py` | Completed-candle prefix iterator and JSON/CSV/Markdown audits. |
| `intraday/cli.py` | Single-ticker data replay audit, with strict defaults and offline options. |

Canonical candles are a DataFrame indexed by `timestamp`, a unique, strictly
increasing timezone-aware `DatetimeIndex` in **Europe/Istanbul**. Columns are
exactly `open, high, low, close, volume`, stored as numeric values. CSV schema:

```csv
timestamp,open,high,low,close,volume
2026-10-06T10:30:00+03:00,100.0,102.0,99.0,101.0,1000.0
```

Required invariants: finite positive OHLC; high >= max(open, close, low);
low <= min(open, close, high); finite nonnegative Volume. No forward/back fill,
interpolation, fabricated empty bars, relabeling or partial-bar truncation.
Dates are never substituted for timestamps.

Yahoo epoch seconds are parsed explicitly as UTC, then converted to Istanbul.
Request bounds/as-of must be aware; naive values are rejected. Standalone CSV
can normalize naive candle timestamps only with explicit `source_timezone`.
This does not make naive request bounds acceptable. Yahoo ticker, `EQUITY`
instrument type, 1h/60m granularity and Istanbul exchange timezone are verified.

## Local requested-range and completion gates

Every raw timestamp is parsed before candle acceptance. Provider response
metadata is not trusted to bound the result. Locally enforce:

```text
start <= timestamp < end
timestamp + 1h <= end
timestamp + 1h <= as_of
```

The second condition is deliberately stronger than a start-label check: a
candle beginning before end but containing prices after end cannot enter the
historical segment. It is excluded as `incomplete_candle/crosses_requested_end`.
`end` remains exclusive for bar starts; a full candle ending exactly at end or
as-of is included. A candle starting exactly at end is excluded. Out-of-range
rows are filtered before inspecting their prices, so an appended current/future
row with malformed/extreme OHLC cannot taint the historical dataset.

`is_complete(timestamp, replay_timestamp)` is true at exact nominal bar end,
false immediately before it. The data contract assumes nominal completed-bar
availability at its end for historical research; actual vendor publishing/order
latency is **not measured or guaranteed** and is a later execution requirement.

## Session policy and calendar

The calendar is explicit, versioned as
`bist-equities-2024-2026-native-1h-v0-20261009`, covering 2024, 2025 and 2026.
Unsupported years fail before retrieval, rather than inventing weekday sessions.
Weekend, full holiday and half-day definitions come from the
[official holiday calendar](https://www.borsaistanbul.com/en/official-holidays),
[2024 schedule](https://www.borsaistanbul.com/files/duyuru-22379_ENG.pdf),
[2025 schedule](https://www.borsaistanbul.com/files/equity-market-2025-holiday-schedule.pdf),
and [2026 announcement](https://borsaistanbul.com/files/41625-sayili-duyurumuz-ingilizce-04122025.pdf).

The [equity-market procedure](https://www.borsaistanbul.com/files/equity-market-procedure.pdf)
defines continuous trading as 10:00–18:00 on full days and 10:00–12:30 on half-days.
Opening/closing auctions and closing-price phases are not accepted. The general
holiday page's "until 13:00" half-day label does not define the continuous phase.
The live bot's 09:30–18:10 scanner window is not reused as a session calendar.

Native hourly labels are anchored at :30. Accepted **full nominal hours**:

- Full day: starts 10:30, 11:30, 12:30, 13:30, 14:30, 15:30, 16:30.
- Half-day: starts 10:30 and 11:30, ending by 12:30.
- 09:30, 17:30 on full days, the half-day 12:30 edge, and an 18:00 latest-price
  snapshot are excluded. :00/seconds/fractional misalignments are explicitly
  rejected as `outside_session/misaligned_native_hourly_timestamp`.

`Session` exposes date, continuous start/end, open/half-day state and accepted
starts. `Candle.tradable` means session/schema eligibility under this contract,
not proof of liquidity, tick ownership or a guaranteed executable price. No
10:00 hourly bar is synthesized. This sacrifices opening/closing fragments to
avoid silently using auction/partial intervals. Yahoo's historic session metadata
does not override official full/half days.

The calendar is a pinned research schedule, not an automatically maintained
future calendar or intraday halt feed. Unscheduled closures/halts and actual
vendor bar duration/auction contamination still require independent validation.
An official calendar change needs a new calendar/cache version; old snapshots
are not silently reinterpreted.

## Validation and duplicate policy

Bounds, completion and session classification precede numeric acceptance.
Structured records include ticker, normalized timestamp, session date, source
row, reason/detail, removal flag and original OHLCV evidence. Reasons include:

| Reason | Policy |
| --- | --- |
| `outside_requested_range` | Remove timestamp < start or >= end, including appended current/future prices. |
| `incomplete_candle` | Remove bars crossing requested end or unfinished at as-of. |
| `outside_session` | Remove closed-day, misaligned, auction/partial-boundary bars. |
| `zero_volume_boundary` | Remove zero-volume rows outside accepted whole continuous intervals. |
| `missing_ohlcv` | Remove any required NaN/null candle; later gap detection diagnoses its expected slot. |
| `invalid_ohlc` | Remove nonnumeric/boolean/infinite fields or nonpositive/inconsistent OHLC. |
| `invalid_volume` | Remove negative volume. |
| `duplicate_timestamp` | Normalize first; identical valid duplicates keep the first valid source row, then sort. |
| `valid_zero_volume` | Keep a valid full interior candle with zero volume, explicitly flag it as no-volume data. |

First malformed and later valid copies of a timestamp keep the first **valid**
copy. Differing valid source duplicates are ambiguous and refuse the request
under both policies; `warn` relaxes gaps, not quote conflicts. Source timestamp
or array/schema corruption that prevents reliable bounding rejects the input.
No data is silently filled or repaired.

Zero volume is not universally invalid. A flat/nonflat zero-volume interior bar
can be a legitimate no-trade/no-volume observation; it remains usable history
but does not authorize a fill. Boundary rows cannot reliably be classified as
auction prints versus snapshots using OHLC alone, so they are conservatively
excluded. Reasons and counts remain visible.

## Expected gaps: strict versus warn

Expected native slots are generated from every calendar session in the requested
range, limited to whole bars completed by `min(end, as_of)`. This detects internal,
leading/trailing and completely absent session gaps. Weekends/holidays and
future/unfinished slots are not gaps. Every missing record contains ticker,
`missing_timestamp` and `session_date`.

Default `strict`: provider raises `GapError` with full diagnostics if any expected
completed slot is absent. Valid rows and explicit attempted-range coverage can
still be cached, so the same failure is reproducible offline without repeated
network calls. `warn` returns available candles with the same gap diagnostics;
no placeholder is inserted. Future strategies must not treat warn-mode gaps as
continuous price paths.

If a warn dataset is passed to strict replay, safe earlier prefixes may replay,
but iteration stops before a snapshot whose history crosses the first missing
completed slot. A trailing gap raises rather than silently ending. To research
a different segment, request its explicit bounds; this does not repair the
missing market interval. No strategy, fill or gap survival is assumed.

## Cache and offline provider

Default ignored layout:

```text
data/intraday_cache/1h/ASELS.IS/
    manifest.json
    <sha256>.csv
    <previous-sha256>.csv
```

The cache stores normalized **validated** candles only, plus contract/calendar
version, source identity, source audits, attempted completed-range coverage and
CSV checksum. CSV files are immutable content-addressed snapshots. Write the
new CSV first and replace only the manifest atomically; previous revisions remain
recoverable. Checksums, path confinement, ticker/timeframe/timezone/calendar
version and the candle contract are verified on load. A per-ticker exclusive
writer lock prevents silent concurrent lost updates. A stale crash lock causes
a clear failure and needs manual verification/removal; it is not auto-deleted.

First uncovered Yahoo fetch is a cache miss. A second covered identical request
is a hit and makes no API call. `CacheProvider` never uses the network and fails
uncovered segments explicitly. Coverage stops at `min(end, as_of)`; an incomplete
fetch cannot claim future rows. Missing known slots remain gaps on cache hits.
Use a separate cache root to obtain a deliberate new source vintage.

Range extension merges sorted timestamps. Equal valid overlaps deduplicate;
malformed incoming rows cannot replace an existing valid historical candle.
Only the exact previously validated cached timestamp can be reused, not a
neighbor or interpolated/future value. Reuse is recorded separately. Conflicting
valid cache/provider revisions fail **without changing the cache**, avoiding a
silent mix of price vintages. A different source/basis identity also requires a
separate cache root. Adjustment status remains unverified, not magically known
because a CSV has a checksum. Nonoverlapping unknown-basis data needs further
corporate-action checks before strategy research.

Standalone `CSVProvider` enforces the same schema/bounds/completion/session/gap
contract. It is distinct from trusted immutable cache coverage. User-supplied
CSV adjustment/provenance is unverified and naive timestamps require an explicit
source timezone.

Standalone CSV is declared **native 1h** input. Six OHLCV fields cannot prove
the real aggregation duration; passing shorter bars with matching labels is
not supported and must be ruled out by source provenance. This provider does
not resample, infer another timeframe, or certify tick-level bar ownership.

## API and deterministic replay

```python
from intraday.cache import IntradayCache
from intraday.provider import YahooProvider, CacheProvider
from intraday.replay import SessionReplay
import pandas as pd

cache = IntradayCache('data/intraday_cache')
provider = YahooProvider(cache=cache)
data = provider.fetch(
    'FROTO.IS', '2025-05-05T00:00:00+03:00', '2025-05-10T00:00:00+03:00',
    as_of='2026-10-09T20:00:00+03:00', gap_policy='strict')
for snapshot in SessionReplay(data):
    candle = snapshot.current_candle
    history = snapshot.history
    assert (history.index + pd.Timedelta(hours=1)
            <= snapshot.replay_timestamp).all()

offline = CacheProvider(cache).fetch(
    'FROTO.IS', '2025-05-05T00:00:00+03:00', '2025-05-10T00:00:00+03:00')
```

Each snapshot exposes a frozen current `Candle` (aware timestamp/bar_end, OHLCV,
session date, eligibility flag), replay timestamp at nominal bar end, and a new
deep-copy history prefix. No future row, incomplete row, view into remaining
data or mutable shared history is passed to the consumer. Replay may use an
earlier as-of cutoff; it cannot extend beyond the provider's declared as-of.
Corporate events beyond that cutoff are excluded from the replay's event list.
Raw audit/provenance metadata can contain evidence of excluded future rows and
later retrieval vintages; it is **diagnostics, never strategy input**.

## Corporate actions and future execution contract

Yahoo's `quote` OHLCV is stored without using `adjclose`, auto-adjusting prices,
inventing adjusted volume or guessing a split factor. The payload cannot prove
raw versus retrospectively split-adjusted price or volume basis; both are labeled
**unverified**. In-range split/dividend events are recorded with uncertainty,
not used as point-in-time features. A diagnostic >20% adjacent close-to-open
discontinuity is flagged as suspicious, not identified automatically as a split
and not corrected. It is not a strategy threshold or parameter optimization.

Before v2 execution, specify: signals only from completed/available bars; earliest
entry at a next tradable bar, with publication/order latency considered; explicit
conservative same-bar stop/target ambiguity; overnight permitted or prohibited;
no-new-entry cutoff relative to actual full/half-day session close; real eligible
flat-at-close pricing; commission/slippage/spread conventions and no double
counting. None of those entry/exit or risk rules are implemented here. The live
bot's current risk percentages and strategy behavior remain unchanged.

## CLI, reports and validation

```powershell
python -m intraday.cli --help
python -m intraday.cli --ticker FROTO.IS --start 2025-05-05T00:00:00+03:00 --end 2025-05-10T00:00:00+03:00
python -m intraday.cli --offline --ticker FROTO.IS --start 2025-05-05T00:00:00+03:00 --end 2025-05-10T00:00:00+03:00
python -m intraday.cli --ticker ASELS.IS --start 2026-04-20T00:00:00+03:00 --end 2026-04-21T00:00:00+03:00 --gap-policy warn
```

The last command is explicit diagnostic warn mode, not approval to ignore gaps
in research/backtests. CLI operates on one ticker only and generates no trades.
Audits are saved to exclusive directories under
`backtest_results/intraday_replay_audit/`, with `diagnostics.json`, `summary.md`
and normalized `candles.csv` when data is available. Yahoo payload evidence is
stored separately by hash. Failures also produce audit records; unknown counts
on transport/schema failures remain unknown.

Required metadata includes requested/actual first/last bounds, ticker, interval,
timezone, source, input/downloaded/removed/duplicate/outside-range/outside-session/
incomplete/usable counts, exact gaps and cache hit/miss. Cache-hit `downloaded_rows`
is zero; original download counts/source audits are separate. Final usable rows
can exceed new valid rows when exact validated cache rows are reused, and this
is explicitly counted. Provider/cache request bounds are enforced again on load.

Tests are synthetic/offline and block real requests/socket connections. They
cover future/current append exclusion, pre-start/exact-end/full-bar bounds,
UTC/naive rules, invalid OHLCV, duplicates, full/half/closed days, zero volume,
all gap positions, complete-as-of boundaries, growing immutable replay prefixes,
cache misses/hits/merge/revision/integrity/lock/coverage safety, CSV parity,
corporate-event bounds and known-null regressions.

```powershell
python -m unittest tests.test_intraday_contract -v
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest research intraday tests
python -c "import intraday.provider, intraday.replay, bot.main; print('imports OK')"
```

Controlled real validation uses ASELS and FROTO only, limited 1h ranges, verifies
the FROTO current-price append cannot enter May 2025 replay, and diagnoses the
known 2026-04-20 10:30 ASELS slot. If vendor data has revised the slot, that is
reported separately from the archived real-response regression, never fabricated
to force a failure. Remaining blockers: actual historical bar duration/auction
ownership, split/volume basis, unresolved gaps/halts, publishing latency, liquidity/
execution quality and later risk/session execution specifications.

## Controlled validation result (2026-10-09)

Exactly three limited Yahoo 1h requests were made, for ASELS/FROTO only.
FROTO 2025-05-05 through exclusive 2025-05-10 returned 46 raw rows: ten
session-boundary rows and the appended 2026-10-09 18:00 current-price row were
excluded, leaving 35 completed historical candles. Second identical fetch was
a cache hit with no additional request; offline candles matched exactly.

The live ASELS 2026-04-20 response omitted the 10:30 timestamp entirely. The
original archived real response contains an all-null candle at that same slot.
Both map to one `missing_expected_candle` and strict provider/replay rejection.
Explicit warn mode returns six existing valid candles without a replacement.
A separately requested segment starting 11:30 is valid, without claiming the
missing prior hour was continuous. A healthy ASELS range 2026-10-05 through
exclusive 2026-10-08 replays 21 completed candles with no gaps.

Full evidence is under
`backtest_results/intraday_replay_audit/20261009_211020_controlled_bebebb8a/`.
Failures with transport/schema errors still record required metadata keys;
unavailable counts are null and gap detection is marked not performed, rather
than inventing zero usable rows or zero gaps.
