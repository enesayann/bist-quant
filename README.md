# BIST scanning and paper-trading bot

An existing Turkish-language BIST analysis bot, refactored into a small synchronous Python package. It scans the original 153 Yahoo Finance tickers, scores technical/fundamental/news conditions, sends Telegram alerts, and tracks manually entered **paper** positions. It has no brokerage connection and submits no real orders. A scan sends an alert; it does **not** open a position automatically.

Features include Wilder RSI/ATR/ADX, EMA, MACD, Bollinger, volume indicators, SuperTrend, Ichimoku, support/resistance, weighted scores, cached Google News RSS keyword analysis, live negative-news checks for open positions, TP1/TP2/stop monitoring, ATR trailing stops, and performance/market/position summaries.

## Setup

Use Python 3.10 or newer. From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:TELEGRAM_TOKEN = 'replace_with_new_bot_token'
$env:TELEGRAM_CHAT_ID = 'replace_with_authorized_chat_id'
python bot.py
```

Replace both placeholders with your own environment values. `TELEGRAM_CHAT_ID` must be the numeric ID of the authorized private chat or group. Both variables are required; startup fails before API requests if either is missing. **Revoke the previously embedded Telegram token through BotFather and issue a new one.** This refactor cannot revoke it or clean historical copies outside this project.

`.env.example` documents variable names only. The bot reads the process environment and does not automatically load a `.env` file. If you use your own environment loader, keep the real `.env` out of version control; `.gitignore` excludes it. Do not paste credentials into source, logs, screenshots, or commits.

`python -m bot` is an equivalent launcher. Run from the same directory as your existing JSON files. Do not run multiple bot processes against the same state directory. Dependencies are NumPy, pandas, requests, schedule, tzdata (including Windows timezone support), and pytz (schedule's wall-clock timezone support).

## Telegram commands

| Command | Behavior |
| --- | --- |
| `/al ASELS 132.40 [500]` | Add a paper position using the supplied entry price, optional quantity, and current ATR targets. Comma decimals are also accepted. |
| `/sat ASELS` | Close the paper position at the latest available daily candle close; fail without closing if market data is unavailable. |
| `/pozisyonlar` | List paper positions, current prices, P&L, stops, targets, and hold/reduce/exit scores. |
| `/durum ASELS` | Detailed position report and news status. |
| `/yardim`, `/help`, `/start` | Show help. |

Ticker inputs accept an optional `.IS` suffix. Command suffixes such as `/al@bot_name` retain their existing behavior. Other chats are ignored, including direct calls to the dispatcher. Authorization is **chat-based**: anyone able to send messages in an authorized group can issue these commands; use a private chat if this is undesirable.

## Scheduling

Startup validates state and checks market hours. When open, it runs one slow news scan and one technical scan before registering jobs and starting the Telegram listener. When closed, it skips both initial scans and starts the scheduler and Telegram listener normally, keeping manual commands available. Scheduled jobs run synchronously in the main loop; the Telegram long-poll listener runs in a background thread. Technical scans use four workers; market summaries use five.

| Job | Timing |
| --- | --- |
| Technical scan and position monitoring | Every 15 minutes; only weekdays, 09:30–18:10 Istanbul time inclusive. |
| Bulk news scan | 09:15, 13:30, 17:45 Istanbul time, plus startup when the market is open. |
| Market summary | 18:10 Istanbul time. |
| Open-position summary | 18:15 Istanbul time. |
| Paper P&L report | Every 3 hours while the market-hours check is true. |
| Closed-position performance summary | At most once per Istanbul date, after a market-open scan, when there are closed positions. |

The original news/summary jobs also run on weekends; there is no holiday calendar. The loop checks jobs every 60 seconds. Long RSS scans and GET retries can delay jobs and startup command availability. The Google scan retains its 2.5-second pause per ticker; Yahoo scan jitter and retry limits are retained. Daily wall-clock jobs now explicitly use Istanbul time even on a host in another timezone.

## Generated files

All paths are relative to the working directory. Existing JSON layouts are retained.

| File | Contents |
| --- | --- |
| `pozisyon_takip.json` | `acik` and `kapanan` position lists. |
| `son_sinyaller.json` | Ticker → last successfully sent signal timestamp; four-hour cooldown. |
| `gorulmus_haberler.json` | Headline hash → seen timestamp; seven-day retention. |
| `haber_cache.json` | Ticker → selected news headline/flags/KAP score for the Istanbul date. |
| `telegram_offset.json` | Last processed polling offset. |
| `son_performans_ozeti.json` | Last successfully sent performance-summary date. |
| `son_pozisyon_ozeti.json` | Last successfully sent position-summary date. |
| `son_piyasa_ozeti.json` | Last successfully sent market-summary date. |
| `borsa_bot.log` | Operational errors and summaries; credentials are redacted. |

Missing files initialize the original empty defaults. Invalid JSON or invalid state schemas raise `StorageError`; startup stops, commands report failure, and scheduled jobs log the error instead of resetting state. Inspect/repair a damaged file from a trusted backup before restarting. Writes use a same-directory temporary file, flush, fsync, close, and atomic replace. Individual files are atomic; multiple files and Telegram sends are not a single transaction. Keep backups of state files.

## Historical backtesting

Backtest v1 runs the existing technical scoring in a separate historical layer.
It uses completed daily candles, next-session Open entries, a conservative
`stop_first` policy, risk sizing with reserved cash, and configurable costs.
News and unavailable historical fundamentals receive zero points. Live bot
behavior is unchanged. Start with one ticker and a limited period:

```powershell
python -m backtest.cli --help
python -m backtest.cli --ticker ASELS.IS --start 2025-01-01 --end 2025-03-31
python -m backtest.cli --ticker ASELS.IS --ticker THYAO.IS --start 2023-01-01 --end 2025-12-31
python -m backtest.cli --universe current --start 2023-01-01 --end 2025-12-31
```

CSV/JSON trade and signal logs, daily equity, and `summary.md` are saved under
ignored `backtest_results/`. Optional charts use matplotlib:
`python -m pip install -r requirements-backtest.txt`. Existing dependencies
suffice for core backtests; `--no-charts` skips plotting. Local data works with
`--csv-dir historical_csv`. See [backtesting methodology](docs/backtesting.md)
for cost units, execution choices, the look-ahead audit, and limitations.

Historical ingestion reports every discarded candle in `data_validation.json`
and the summary, including downloaded/removed/usable row counts. Missing OHLC
or Volume drops the whole candle without filling prices or volume. Infinity,
negative volume and inconsistent OHLC fail clearly. Removal above 5% fails in
either downloaded history or the requested trading range. Known removed
sessions cannot defer an entry or be silently crossed by an open position.

Multi-Ticker Validation v1 runs the fixed 10-stock basket through independent
replays and one shared portfolio (100,000 TL, up to five positions). A single
command fetches data once and compares zero costs with 0.10% commission plus
0.10% slippage per side:

```powershell
python -m backtest.validation_cli --start 2025-01-01 --end 2025-12-31
```

The validation shared portfolio ranks pending entries using existing confidence
and scores, with ticker ties. Ordinary backtests retain alphabetical allocation.
Both scenarios, every ticker (including zero/failed ones), contribution and
selectivity tables, and optional charts share one result directory. Read
[multi-ticker validation methodology](docs/multi-ticker-validation.md) for
ranking, data-failure handling, cost units and report definitions. This adds
measurement only; it does not optimize the strategy or change the live bot.

Multi-Year Validation v1 compares 2023, 2024 and 2025 with the same fixed basket.
Each year starts independently at 100,000 TL, with the preserved 1% risk and
five-position limit. Realism (0.10% commission + 0.10% slippage per side) is the
primary scenario; zero costs are retained as reference:

```powershell
python -m backtest.multi_year_cli
```

One run directory contains three annual reports, a combined comparison,
multi-year ticker tables and combined trade logs. The optional chained-capital
chart links annual returns for illustration only; it does not change annual
capital, trades or risk sizing. See [multi-year methodology](docs/multi-year-validation.md)
for pooled statistics, cost-drag denominators, failure handling and limitations.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall -q bot.py bot backtest tests
python -c "import bot.main, bot.analysis, bot.telegram_bot; print('imports OK')"
git diff --check
```

The unittest suite blocks unmocked requests/socket connections and uses temporary state directories. Yahoo, Google News, and Telegram are mocked. It includes a mocked startup smoke test and deterministic scan/command and worker concurrency tests. Importing package modules does not start services, configure logging, or require credentials.

No Git repository existed in the supplied workspace. See [the refactor report](docs/refactor-report.md) for the verification results and equivalent whitespace check performed here.

## Limitations

Scores and keyword sentiment are engineering heuristics. Paper results depend on daily-candle execution assumptions; TP1 does not sell a partial quantity. There are no fees, slippage, cash ledger, total portfolio-risk cap, corporate-action handling, exchange holiday calendar, or live brokerage execution. Yahoo data may be stale or incomplete. Google News source labels do not authenticate official KAP disclosures. API failures are logged; repeated failures of the same service/error are suppressed at WARNING for five minutes and retained at DEBUG.

Telegram delivery can fail because of rate limits, legacy Markdown content, or oversized messages; messages are not automatically split or queued. The bot reports failures and does not mark unsuccessful summaries/alerts as delivered. There is no exactly-once guarantee between Telegram updates, state files, and outbound notifications.

Read [architecture](docs/architecture.md), [strategy and execution notes](docs/strategy-notes.md), and [the change report](docs/refactor-report.md) before interpreting results. Signals are not guaranteed and this system should not be treated as automatic investment advice.

## Read-only web analysis

The isolated React dashboard supports provider-backed market monitoring and on-demand completed-daily stock analysis through an independently runnable FastAPI layer. See [Market Data Layer](api/market/README.md), [Analysis API startup](api/README.md) and [dashboard setup](web/README.md). Market quotes/history/scanner are separate from technical indicators/scoring; no trading runtime or strategy behavior changes. Portfolio/positions/activity remain Demo; failed real endpoints never fall back to mock data.
