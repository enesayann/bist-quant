# Multi-Ticker Validation v1

This milestone observes the existing technical strategy on a fixed 2025 basket.
It does not optimize strategy weights/thresholds, change the live bot or change
the bot's current universe. It calls the existing `run_backtest` engine for both
independent and shared portfolio replay; there is no second execution engine.

## Fixed basket and commands

ASELS.IS, THYAO.IS, TUPRS.IS, BIMAS.IS, EREGL.IS, KCHOL.IS, GARAN.IS,
SISE.IS, FROTO.IS, TCELL.IS; 2025-01-01 through 2025-12-31, inclusive.

```powershell
python -m backtest.validation_cli --help
python -m backtest.validation_cli --start 2025-01-01 --end 2025-12-31
```

The second command downloads each ticker once (730 calendar days of pre-start
warmup), then runs exactly two cost scenarios on that same input. Scenario A
`baseline` uses zero commission/slippage. Scenario B `realism` uses 0.10%
commission and 0.10% adverse slippage, each on entry and exit. No full-universe
mode or basket parameter optimization is part of this CLI. Input CSV hashes are
included in the result JSON to identify the data used for both scenarios.

Independent replay: each ticker starts with its own 100,000 TL. Shared replay:
all safely qualified tickers share a single 100,000 TL cash ledger. Shared
maximum concurrent positions defaults to five; risk per trade is the existing
default 0.01 of initial capital. Independent P&Ls/returns are not summed to claim
a shared portfolio return. Both kinds of result are explicitly labeled.

Options support cash/risk/max-position controls, optional chart suppression,
local CSV, and explicit realism costs. Example (the same defaults):

```powershell
python -m backtest.validation_cli --start 2025-01-01 --end 2025-12-31 --initial-capital 100000 --risk-per-trade 0.01 --max-concurrent-positions 5 --realism-commission-pct 0.10 --realism-slippage-pct 0.10
python -m backtest.validation_cli --csv-dir historical_csv --no-charts
```

Commission `0.10` is 0.10%, or 0.001 times each actual fill's notional. Slippage
`0.10` increases buy fills to `reference * 1.001` and reduces sell fills to
`reference * 0.999`. Fill prices and both commissions are logged; gross P&L
includes slippage but excludes commission, while net P&L includes both fees.
Cost-induced changes to fills, ATR target rebasing, lot affordability and
exit/holding outcomes follow the existing Backtest v1 model. Costs are not
merely subtracted from an unchanged list of trades.

## Preserved assumptions and ranked allocation

Both scenarios retain neutral/zero historical news and fundamentals; original
weights, thresholds, categories, classification and whale exception; next-open
entry; stop-first daily ambiguity; stop/TP1/TP2 ATR distances; no partial TP1
sale; highest-Close ATR trailing effective on the next candle; fixed initial
capital risk sizing; reserved cash; one long per ticker; no leverage/pyramiding.
Validation v1 rejects attempts to use signal-close or target-first settings.
See [Backtest v1 methodology](backtesting.md) for the detailed model.

In the shared validation portfolio, simultaneous pending entries rank by:

1. Signal confidence, descending.
2. Existing technical score, descending.
3. Existing final score, descending.
4. Ticker symbol, ascending.

Every ranking value comes from the completed **signal** candle, stored before
the next Open. Today's High/Low/Volume, future candles, future P&L and ticker
performance never participate. Ranking does not create a new score or rescale
the current one. It is applied to cash allocation even with fewer than five
candidates. Opening entries reserve cash before intraday exits, and rejected
orders expire. The regular Backtest v1 keeps its original alphabetical default;
only validation calls its optional `score_confidence` allocation mode.

## Data failures and coverage

The ingestion policy is unchanged: explicit numeric conversion; complete-row
removal for missing OHLC or Volume without fill/interpolation; hard rejection
of infinity, negative volume, nonpositive or inconsistent prices; stable dates;
first-source-row duplicate selection; 5% removal limit separately in loaded
history and the requested period. Failure exceptions now carry available audit
counts/reasons for reporting, without weakening validation.

Every requested ticker remains in each scenario's per-ticker table, including
zero-trade tickers and failed tickers. Unavailable metrics are N/A, not invented
zeros. Failed-ticker stages/errors and known data counts/removal reasons are
exported. Unknown counts from transport/schema failure remain N/A.

Independent replays qualify data before shared replay. If a ticker fails fetch,
data validation or either independent scenario's safe replay, it is explicitly
excluded from **both** shared scenarios. Both aggregate scenarios therefore use
the same qualified subset. Successful independent evidence can still be shown
for the counterpart scenario; shared status is `excluded`. The summary warns
that this is an incomplete basket, not the requested full basket. Exclusion is
based solely on data/simulation safety, never on P&L or signal selectivity.

If a shared replay itself would cross a removed candle while a position is open,
that aggregate stops and is reported as failed. The validator does not rerun
after pruning an inconvenient ticker, invent a missing candle, free cash via a
retroactive exit, or present a partial curve as a complete portfolio. Other
independent results remain reportable. The CLI returns nonzero if either shared
scenario is unavailable and still writes the failure report. Safe partial
basket runs print ticker failures explicitly.

## Report definitions

The exclusive run directory contains both scenarios:

- `summary.md`: configuration, shared metrics, independent per-ticker tables,
  shared concentration, selectivity, data-quality failures/warnings, and the
  existing look-ahead audit.
- `per_ticker.csv`: one row for each ticker **per scenario** (20 for the full
  basket). Unprefixed performance columns describe independent replay; `shared_`
  columns describe actual entries and P&L contribution in the shared portfolio.
- `trades.csv`: shared closed trades, identified by scenario; fill prices and
  entry/exit commissions retain the existing trade-log fields.
- `independent_trades.csv`: independent closed trades, separately labeled.
- `equity_curve.csv`: long-format shared cash/market-value/equity/open-count data,
  with scenario and phase. The initial baseline row is retained.
- `drawdown.csv`: shared daily drawdown by scenario/date/phase.
- `entry_decisions.csv`: every signal disposition with stored ranking values,
  attempted entry date, executed/skipped status, skip reason, fill and quantity.
- `validation.json`: both full independent/shared results, configurations,
  input hashes, signals, decisions, audits, failures, concentration and warnings.
- `data_validation.json`: downloaded/removed/usable counts and exact known
  removed-row dates, values, reasons and limits for each ticker.
- When matplotlib is present: `aggregate_equity.png`, `drawdown.png`,
  `per_ticker_net_pnl.png`, `per_ticker_trade_count.png`. Bars describe shared
  contributions/entries, not independently funded results. Failed values remain
  missing rather than being plotted as zero trades/profit.

Shared per-ticker net P&L includes closed net trades plus marked unclosed shares,
less their entry commission. Contributions reconcile with ending equity minus
initial capital. Percentage of total P&L is signed ticker P&L / total net P&L;
offsetting losses can make shares negative or greater than 100%. A near-zero
total gives N/A. JSON additionally reports share of positive P&L to preserve
denominator context. Largest positive/negative contributors are selected only
from tickers of that sign; a missing sign is explicitly `None`. A >50% signed
contribution is a descriptive concentration flag, not statistical significance.

Ticker-days evaluated counts usable in-range candles passed to the signal
generator; signal-ready days additionally meet the existing 60-candle minimum.
Valid signals include signals while a position is already open. Executed entry
counts include unclosed positions; closed trade counts are separate. Capital
and concurrency skips refer to attempted entries, while already-open,
missing-open, removed-candle, invalid-level/risk-lot and no-next-candle skips
are separate. Average entries per requested ticker and per qualified ticker
are both reported so failures do not hide the denominator.

## Warnings and verification

Warnings cover fewer than 30 aggregate closed trades, fewer than three
independent trades per ticker, zero-trade tickers, no losses, undefined profit
factor, dominant P&L contribution, too-small Sharpe/CAGR interpretation samples,
stale open marks, incomplete basket and data/simulation errors. They do not
alter scores, trades, ratios or replay assumptions. Existing Sharpe and CAGR
gates remain in `metrics.py`; a computed Sharpe is still descriptive.

```powershell
python -m unittest tests.test_backtest_validation -v
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest tests
python -c "import backtest.validation, backtest.validation_cli, backtest.validation_report, bot.main; print('imports OK')"
git diff --check
```

Tests use synthetic fixtures, temporary output directories, mocked providers,
and the existing network blockers. They cover ranking/ties, concurrency,
reserved cash, costs, aggregate reconciliation, zero/failed tickers, contribution
denominators, stale position fees, warnings, reports and CSV CLI. A multi-ticker
regression appends future candles to one ticker and proves that another ticker's
already-generated historical signal is identical. Original no-lookahead tests
are rerun. No test uses a real network.

All outputs stay in ignored `backtest_results/`. Live bot source, strategy,
position execution, market hours and universe are unchanged. This is a small
fixed-basket observation, without a profitability conclusion or parameter advice.
