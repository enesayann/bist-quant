# Backtest v1

Backtest v1 measures the existing technical strategy on historical daily OHLCV.
It is separate from the live bot: no Telegram, news requests, live state files,
credentials, broker connection, parameter optimization, or real orders.
The live strategy source is unchanged.

## Commands

Run from the project directory using the existing Python environment:

```powershell
python -m backtest.cli --help
python -m backtest.cli --ticker ASELS.IS --start 2025-01-01 --end 2025-03-31
python -m backtest.cli --ticker ASELS.IS --ticker THYAO.IS --start 2023-01-01 --end 2025-12-31
python -m backtest.cli --universe current --start 2023-01-01 --end 2025-12-31
```

Start with the one-ticker, three-month example. Yahoo is only contacted by
manual provider runs. End dates are inclusive and must precede today for Yahoo,
so today's unfinished candle cannot enter a historical test. Unavailable or
malformed ticker data fails the run explicitly rather than silently selecting
the successful tickers. No real-data run is part of the offline tests.

Costs and capital controls:

```powershell
python -m backtest.cli --ticker ASELS.IS --start 2025-01-01 --end 2025-03-31 --initial-capital 100000 --risk-per-trade 0.01 --max-concurrent-positions 5 --commission-pct 0.1 --slippage-pct 0.1 --intrabar-policy stop_first
```

`--risk-per-trade` is a fraction (`0.01` = 1%). Commission and slippage arguments
are percentage points (`0.1` = 0.1%) per entry and per exit. Both default to zero.
`--execution-model signal_close` explicitly enables a same-close comparison;
the default is `next_open`. `--intrabar-policy target_first` provides the alternate
daily-candle ordering. Every report records these settings.

## Architecture and data

| Module | Responsibility |
| --- | --- |
| `backtest/data.py` | Provider protocol, Yahoo chart data, local CSV, ticker/date/OHLCV validation. |
| `backtest/signals.py` | Existing causal indicators/scoring, prefix-only decisions, confirmed pivots and support/resistance. |
| `backtest/execution.py` | Configuration, risk quantity, fills/costs, stop/targets and position transitions. |
| `backtest/engine.py` | Synchronous portfolio timeline: opening orders, intraday exits, close signals and equity. |
| `backtest/metrics.py` | Net trade statistics, portfolio drawdown, sample-gated annualized measures. |
| `backtest/report.py` | CSV/JSON/Markdown exports and optional equity/drawdown plots. |
| `backtest/cli.py` | Date/universe/options, provider loading and report creation. |

Yahoo uses the existing HTTP client and chart endpoint with `period1`, `period2`
and `interval=1d`. The live `chart_frame` cannot be reused as a historical loader:
it omits Open and dated indexing. The new loader validates timestamp and array
lengths, positive/internally consistent OHLC, nonnegative volume, finite numbers,
and strictly increasing unique session dates in Istanbul time. It never reads
Yahoo's current `regularMarketPrice`, quoteSummary fundamentals, or news cache.
Providers normalize OHLCV numerically and remove an entire candle if any required
OHLC value or Volume is missing. No price or volume is filled/interpolated.
Infinity, negative volume, nonpositive prices, nonnumeric values, invalid dates,
and inconsistent OHLC fail with ticker/date/column diagnostics. Dates are stably
sorted; duplicate dates keep the first source row and report discarded rows.
The generic engine validator remains strict, including its missing-Open entry
test behavior; provider cleaning is a separate boundary.

Every removed row logs its ticker, date, source-row index, and reason. Audit JSON
preserves the numeric values (missing fields as null), downloaded/removed/usable
counts, and warnings. The default removal limit is 5%, checked separately for
all downloaded data (including warmup) and for the requested trading period.
An empty usable dataset or excess removal fails rather than silently accepting
a badly damaged sample. Structural errors and genuine corruption fail even when
only one row is affected; duplicates do not hide corrupt values.

Known removed dates also affect execution: an order whose next source candle
was removed expires and cannot enter at a later good Open. If an open position
would cross a removed candle, the run fails because a stop/target outcome would
be unknown. This includes candles with valid prices but missing Volume, since
v1 treats that whole candle as unusable. A real exit before the missing candle
is allowed; a missing final session cannot cause an earlier reporting exit.
No artificial candle or assumed survival fills the gap. Completely absent
source dates still require an exchange calendar/coverage audit to distinguish
missing sessions from holidays.

The engine accepts a mapping of ticker to validated DataFrame and is independent
of retrieval. `DataProvider.fetch(ticker, start, end)` isolates retrieval. CSV
files are named `ASELS.IS.csv` and contain:

```csv
Date,Open,High,Low,Close,Volume
2023-01-02,100,102,99,101,1000000
2023-01-03,101,104,100,103,1200000
```

```powershell
python -m backtest.cli --ticker ASELS.IS --start 2025-01-01 --end 2025-03-31 --csv-dir historical_csv
```

The CLI requests 730 calendar days before start for indicator warmup. Override
with `--warmup-days`. Pre-start candles initialize indicators but generate no
orders. CSV history is not invented; fewer than 200 candles at start produces a
warning. The existing 60-candle signal minimum, 200-candle EMA200 gate and
78-candle Ichimoku gate are retained. Indicators use expanding available history;
this can differ slightly from the live bot's repeatedly reset two-year EWM seeds.

## Technical-only scoring

Reuse `bot.indicators` and `bot.scoring`: trend/momentum/volume/volatility caps
remain 25/20/15/10. Support/resistance adjustment remains +/-10 with its original
2% distance rule and resistance-first priority. No weight/threshold is optimized.

Historical news is disabled: zero points, no positive/negative news or buyback
flags, no historical scraping and no present-day cache. Historical fundamentals
are unavailable in daily OHLCV, so they also receive zero points. Current P/E,
PEG, P/B or dividends would leak present information and are never requested.
The original technical score denominator remains 80, including the 10-point
fundamental allowance; the four technical categories are not rescaled to 100.

Both `final_score` (raw categories + adjustment, clipped 0..100) and
`technical_score` (categories / 80 * 100 + adjustment) are exported. Live
confidence uses `int(technical_score / 10)`. The normal technical branch requires
trend confirmation, technical score >=60 and confidence >=7. Trend confirmation
requires the last three closes above SMA20, current Close above SMA50, and
Close > EMA20 > EMA50. The live volume exception is preserved: rising Close
with Volume >=3 * rolling 20-candle average adds two confidence points and
bypasses the normal confidence bar. Classification remains LONG >=8, EARLY >=6,
WATCHLIST >=4, RISKY otherwise. News-dependent branches are absent.

Live alerts require a human to open paper positions. Backtesting assumes every
eligible technical/volume signal is an entry instruction when flat; this is an
explicit measurement convention, not a change to live trading behavior.

## Look-ahead bias audit

| Existing helper | Review and historical handling |
| --- | --- |
| EMA, Wilder RSI/ATR/ADX, MACD | Trailing EWM, previous-row changes; causal. |
| Bollinger, MFI, CMF, StochRSI, VWAP, Donchian, historical volatility | Trailing rolling windows; causal. Donchian includes today's completed candle, as live does. |
| OBV, SuperTrend | Cumulative or forward-only updates; causal. |
| Ichimoku | Trailing 9/26/52 windows and positive shift(26); earlier information is shifted forward. No future/negative-shift series. |
| HH/HL | Live uses centered 11-candle windows. Never calculate this over full history for historical decisions. The existing trend scorer receives only rows through t, so pivots need five already observed right-hand candles. Tests prove equivalence to trailing-window confirmation. |
| Support/resistance | Same centered-window hazard. A backtest-only trailing 11-candle comparison emits the middle candle on its confirmation date. Use the live last-60-candle scope, min/max confirmed pivots and fallback extremes. Tests check live-prefix parity. |
| ATR trailing | Live raises a stop using today's Close/ATR before checking today's Low. Historical replay must not assume this close-derived stop existed earlier that day. Check the active stop first; close-derived updates start next candle. |
| Reference price/news/fundamentals | Historical Close replaces today's meta price; present news and fundamentals are never read. |

Only proven causal indicator series may be calculated once over all loaded data.
Every decision receives a prefix ending at that completed candle. Centered
pivots are never precomputed across the full dataset. Public `evaluate_signal`
also truncates raw data before calculating anything. Tests append/alter future
candles and require identical earlier indicators and a nonempty earlier signal.
All adaptations stay inside `backtest`; live modules are untouched.

## Entry, exits and intrabar ambiguity

A signal from completed candle t enters the next available ticker session's
Open. This avoids buying at a price whose closing indicators were not yet known.
No next candle within the range, missing Open, full portfolio, or zero affordable
quantity skips the order; rejected orders are not deferred to a favorable price.
Without an exchange calendar, an entirely absent session cannot be distinguished
from a holiday: audit source coverage. Signal-close mode executes after all
intraday processing and never replays the elapsed signal candle's high/low.

Buy slippage increases the fill price. Signal-date ATR sets stop at fill -1.5 ATR,
TP1 at fill +2 ATR and TP2 at fill +3 ATR. Levels are rebased to actual entry,
retaining the live ATR distances rather than holding stale signal-close levels.
TP1 marks the milestone and raises stop to entry without a partial sale.
TP2 closes the whole position. The highest observed Close, not High, advances
the trailing stop to Close -1.5 * that candle's ATR; stops never move down.

Daily highs/lows reveal touches but cannot establish their chronological order:

- `stop_first` (default): the active stop wins over a target on the same candle.
  If only TP1 is touched, break-even starts next candle. A low preceding TP1
  must not trigger a stop that did not yet exist.
- `target_first`: TP2 wins over an ambiguous stop; otherwise TP1 happens before
  the low, including a possible same-candle break-even exit.
- Opening gaps are known earlier than subsequent extremes under either policy.
  An open below stop exits at Open; an open above TP2 exits at Open. A gap above
  TP1 activates break-even before that session's low. Missing Open on an existing
  position uses high/low checks without claiming to know gap precedence.
- Close-based trailing updates always start next candle, under either policy.

These are reproducible scenarios, not proof of actual tick execution. At the
portfolio's last observed candle, positions with a candle that day are liquidated
at Close for reporting, with exit costs. A ticker missing that boundary candle
remains open at its last known Close and is exported/warned separately. The
engine never uses knowledge of missing future rows to close it early and free
cash. This avoids fabricating stale executions or a portfolio look-ahead effect.

## Capital, costs and metrics

One long position per ticker, no pyramiding, shorts or leverage. Risk quantity is
`floor(initial_capital * risk_fraction / (entry - stop))`, matching the live fixed
portfolio-size formula. Available cash including entry commission further caps
the quantity. Capital is reserved until exit; intraday exit proceeds cannot
fund that same session's opening orders. Simultaneous orders allocate in ticker
alphabetical order. Live has no cash ledger; this ledger is a documented v1
portfolio assumption. Risk is not automatically compounded or portfolio-wide
risk-limited beyond cash and maximum concurrent positions.

Commission applies to each actual fill's notional; adverse slippage applies to
each fill. Gross P&L includes slippage but excludes commission; net P&L subtracts
both commissions. Gross return divides by entry fill notional; net return divides
by total entry cash including fee. Stop-based risk sizing excludes fees/slippage
loss on exits, and opening gaps can exceed planned risk.

Daily equity is cash plus shares marked at the last available Close; missing
ticker dates carry the last known mark. Equity CSV includes an `initial` baseline
row, possibly sharing a date with the first `close` row. This captures first-day
fees and losses in maximum drawdown. Ending capital is final marked equity; when
positions remain open it differs from cash and from realized closed-trade P&L.

Wins/losses use net TL P&L, with net-zero trades separate. Profit factor uses
sum winning TL P&L / absolute sum losing TL P&L. Expectancy is mean net TL P&L
and mean net return separately. Average winner/loser and best/worst are net
percentages; holding period is calendar days with held candle count also exported.
Losing streak follows exit date/ticker order; zero P&L breaks a losing streak.
Maximum drawdown is the largest percentage decline from a prior equity peak,
including initial capital, not a sum of trade return percentages.

Sharpe uses net daily equity simple returns, zero risk-free rate, sample standard
deviation and sqrt(252). It requires at least 60 daily observations and nonzero
volatility. CAGR needs >=365 calendar days and >=252 daily close observations.
Undefined/small-sample values are JSON null and Markdown N/A; profit factor
without losses also includes an explanatory status. Sparse/incomplete union
session data makes annualized statistics less reliable.

## Outputs, charts and verification

Each run creates an exclusive `backtest_results/<timestamp>_<id>/` directory:

- `signals.csv` / `signals.json`: every eligible signal, even when already in a
  position; signal date/reference price, all component scores, both totals,
  confidence/classification, initial reference stop/TP1/TP2 and signal-date ATR.
- `trades.csv` / `trades.json`: actual entries/exits, initial/final stop, targets,
  TP1 flag, quantity, holding dates/days/bars, fees, gross/net TL and percent P&L,
  entry scores/classification and intrabar policy.
- `equity.csv`: daily cash, market value, equity, open count and drawdown.
- `open_positions.json`: unclosed positions when a final candle is unavailable.
- `data_validation.json`: per-ticker downloaded/removed/usable counts, separate
  requested-period counts, exact discarded dates/values/reasons, and warnings.
- `results.json`: configuration, date range, tickers, data source, warnings,
  metrics, signals, trades, open positions and data-validation audit.
- `summary.md`: capital, costs, execution policy, metrics, warnings, full
  look-ahead audit and assumptions/limitations.
- `equity.png` and `drawdown.png` when matplotlib is installed.

The directory is ignored by Git. Reports never overwrite an existing run.
Install optional chart support or disable charts explicitly:

```powershell
python -m pip install -r requirements-backtest.txt
python -m backtest.cli --ticker ASELS.IS --start 2025-01-01 --end 2025-03-31 --no-charts
python -m unittest tests.test_backtest_signals tests.test_backtest_execution tests.test_backtest_outputs -v
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest tests
python -c "import backtest.cli, backtest.engine, bot.main; print('imports OK')"
git diff --check
```

Tests use synthetic candles, mocked Yahoo responses, temporary directories, and
network blockers. No test accesses the internet. Source hashes can verify live
files remain unchanged. This supplied workspace has no `.git` repository, so use
a trailing-whitespace/conflict-marker check as the `git diff --check` equivalent.

## Remaining limitations

Yahoo history may be revised or split-adjusted retrospectively; quote OHLC is
used like live, without a separate point-in-time corporate-action model.
Dividends, delistings, symbol changes, limit-up/down queues, liquidity/market
impact, bid/ask spreads, taxes and financing are unmodeled. The current universe
has 153 tickers and survivorship bias; it is not historical index membership.
Daily policy scenarios, indicator warmup, data gaps, stale marks and endpoint
liquidations can materially affect reported performance. No historical news,
fundamentals, strategy optimization, machine learning or broker execution is
included in this milestone.
