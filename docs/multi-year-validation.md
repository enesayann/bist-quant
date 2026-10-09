# Multi-Year Validation v1

This validation layer calls the existing `run_validation` and `run_backtest`
functions separately for 2023, 2024 and 2025. It adds orchestration, aggregation
and reporting only. Live bot files, weights, thresholds, indicators, execution,
risk sizing, ranking and ingestion rules remain unchanged.

## Fixed experiment

Basket: ASELS.IS, THYAO.IS, TUPRS.IS, BIMAS.IS, EREGL.IS, KCHOL.IS, GARAN.IS,
SISE.IS, FROTO.IS and TCELL.IS. Each calendar year runs from January 1 through
December 31 inclusive. Each year's shared portfolio starts independently with
100,000 TL, 1% risk per trade and a maximum of five concurrent positions.
Positions, capital and risk budgets are not carried between years.

Primary scenario B (`realism`): 0.10% commission plus 0.10% adverse slippage on
entry and exit. Secondary scenario A (`baseline`): zero costs. Technical-only
scoring, neutral historical news/fundamentals, next-open entry, `stop_first`,
TP1/TP2/stop logic, ATR trailing and confirmed-prefix decisions are preserved.
Both scenarios use the same fetched input within each year. Current stored
confidence/technical/final scores rank shared entries, with ticker ties.

```powershell
python -m backtest.multi_year_cli --help
python -m backtest.multi_year_cli
python -m backtest.multi_year_cli --csv-dir historical_csv --no-charts
python -m backtest.multi_year_cli --no-chained-view
```

The CLI fixes years, basket, capital, risk, position limit and costs for this
milestone. It does not expose optimization or alternate strategy parameters.
`--output-dir` changes the output parent. `--no-chained-view` omits only the
secondary illustration; primary results remain identical.

## Historical isolation and data quality

Each year independently requests the existing 730-calendar-day warmup before
its own January 1, with data ending at that year's December 31. It does not use
one future-enriched full-history indicator frame to seed all years. Pre-start
rows initialize indicators but cannot generate trades. Adding/changing a later
year's input cannot change an earlier year's signals or capital.

Yahoo numeric validation, missing-row removal, corruption rejection, stable
sorting/duplicate policy and 5% limits are unchanged. A known removed session
cannot defer an entry or be crossed by an open position with unknown exits.
The existing multi-ticker prequalification and explicit failure reporting are
reused. Failed tickers stay in tables with N/A. Annual qualification may differ;
partial baskets and failed aggregates are labeled, never silently treated as
full 10-ticker years. Downloaded/removed/usable counts are per year and ticker;
overlapping warmup windows are separate downloads, not unique market sessions.

Per-ticker totals require a valid result in every requested year. When coverage
is incomplete, full totals are N/A; known observed subtotals and observed-year
counts are separate. Zero-trade valid years are explicit zero, distinct from
failure. Combined portfolio statistics identify available years and coverage.
The CLI returns nonzero for incomplete coverage while still saving reports.

## Independent-year and pooled descriptive metrics

Annual comparison includes all existing portfolio metrics plus valid signals,
executed entries and all skipped signal dispositions. Executed entries include
unclosed positions; closed trade count is separate. Skip reasons remain in each
year's existing decision log. Per-ticker shared counts describe executed entries;
the independent single-ticker mode is separately labeled in the CSV.

The combined comparison presents Scenario B first and Scenario A as reference.
Summed annual net P&L describes three independently funded trials. With complete
coverage, total allocated capital is 300,000 TL; return on that allocated capital
is summed annual P&L / 300,000, equivalent to average yearly return for equal
100,000 TL starts. It is not a compounded three-year portfolio return. Annual
ending equities are not presented as one continuous final account balance.

Descriptive stability includes positive/negative/flat year counts, best/worst
year by return, mean/median annual return, sample standard deviation in percentage
points (`ddof=1`), and observed return range. Pooled closed-trade counts, net
win/loss statistics, profit factor, expectancy and mean/median trade return are
also reported. They do not create a continuous equity curve. Worst annual
drawdown is the maximum of annual drawdowns, not a chained portfolio drawdown.
No combined Sharpe or CAGR is fabricated; existing annual gates remain intact.

Every ticker has annual trade/P&L fields, total entries, summed net P&L,
positive/negative year counts and explicit zero-trade years. Both shared and
independent modes, and both scenarios, are exported. Shared ticker P&L includes
the existing marked unclosed positions/entry-fee treatment and reconciles to
observed annual portfolio P&L.

Concentration uses signed cumulative ticker P&L / total observed net P&L. Offset
losses can produce negative or >100% shares. Zero net total yields N/A. Share of
positive contribution is reported separately. Largest positive/negative ticker
and each year's largest positive contributor are explicit; absence of either
sign is reported as None.

## Cost drag

Per year: baseline ending equity minus realism ending equity; baseline return
minus realism return in percentage points; and that capital difference divided
by baseline gross profit. The **gross profit denominator is the sum of positive
gross P&L from baseline closed trades**, not net P&L or the sum including losses.
A zero denominator gives N/A. This definition is written in every report.

Combined capital difference sums matched independently funded annual ending
differences. Combined return difference sums annual percentage-point differences,
not compounded returns. Combined drag/gross-profit divides summed drag by summed
baseline gross profit, not the average of yearly ratios. Available matched-year
coverage is recorded when a year is unavailable.

The return difference on total allocated capital is also reported separately:
summed capital drag / (100,000 TL * matched-year count) * 100. With three full
years this compares returns on 300,000 TL and equals the mean yearly return drag,
not the sum of the three annual percentage-point differences.

Cost drag includes commissions, adverse fills and any existing quantity/target/
execution-path differences caused by costs. It need not equal paid commissions.
Realism commissions paid are reported separately. Negative drag, if it occurs,
is not clamped or hidden. Costs do not trigger parameter changes or reruns.

## Optional chained view

`chained_capital.csv` and its chart link independently observed annual returns:
start at 100,000 TL, multiply by the 2023 net-return factor, use that illustrative
ending value as 2024's illustrative start, and then link 2025. Both scenarios
are shown. A failed or partial year breaks the illustration rather than inventing
the missing return.

This is a **secondary visualization only**, not a chained trade replay. It does
not rerun position sizing, integer lot rounding, reserved cash or fees at changed
capital. It cannot be treated as an executed account balance or replace the
primary independent-year analysis. Disabling it leaves annual trades and metrics
unchanged.

## Result directory

One exclusive `backtest_results/<run_id>/` contains:

- `summary.md`: primary 2023/2024/2025 comparison, zero-cost reference, stability,
  per-ticker annual tables, concentration, costs, data quality and warnings.
- `years/2023/summary.md`, `years/2024/summary.md`, `years/2025/summary.md`: full
  existing annual basket reports, annual trade/equity/audit exports and optional
  charts. Primary realism and independent annual starting capital are labeled.
- `year_comparison.csv`: one row per year/scenario, annual metrics and signal
  disposition counts, with coverage/failure status.
- `per_ticker_multi_year.csv`: one row per ticker/scenario/portfolio mode with
  annual and cumulative fields, zero-trade years and completeness/subtotals.
- `combined_trades.csv`: shared closed trades with year and scenario.
- `independent_combined_trades.csv`: separately funded single-ticker closed trades.
- `equity_curves.csv`: annual reset equity curves identified by year/scenario.
- `data_quality.csv`: every year/ticker's counts and failure/removal reasons.
- `cost_drag.csv`, optional `chained_capital.csv`, and `multi_year.json` containing
  comparison, stability, contribution, provenance hashes and annual report links.
- When plotting is available: yearly returns/drawdown, cumulative ticker P&L and
  optional secondary chained illustration. Missing results are not plotted as zero.

Warnings cover fewer than 30 pooled trades, >50% concentration, only one positive
year, zero-trade years, tickers with fewer than three observed trades, undefined
profit factor, incomplete coverage, and the existing annual sample/quality
warnings. Warnings do not alter results. Three annual observations are not
called statistically significant or proof of strategy profitability.

## Verification

```powershell
python -m unittest tests.test_backtest_multi_year -v
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest tests
python -c "import backtest.multi_year, backtest.multi_year_cli, backtest.multi_year_report, bot.main; print('imports OK')"
git diff --check
```

Tests use synthetic candles, mocked providers, temporary directories and the
existing network blockers. They cover independent resets, combined comparisons,
annual-window isolation, chained illustrations, ticker aggregation, positive/
negative year counts, concentration, warnings, cost denominators, failures and
artifact exports. Existing no-lookahead tests remain part of the full suite.
The supplied workspace has no Git repository; whitespace/conflict-marker checks
are used as the equivalent. No commit or push is part of this milestone.
