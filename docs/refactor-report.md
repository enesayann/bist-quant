# Refactor report

The supplied workspace contained one 1,345-line `bot.py` and no Git repository, tests, dependency manifest, documentation or state files. The complete source was inspected before modification; credential assignments were redacted from all inspection output. No old credential was copied into the resulting files.

## Files and structure

Modified: `bot.py` is now a compatibility launcher. Created: `.env.example`, `.gitignore`, `requirements.txt`, `README.md`, `bot/`, `tests/`, and the three documents in `docs/`. The original function names and core calculations remain recognizable inside the responsible modules.

```text
BIST_BOT/
  bot.py
  .env.example
  .gitignore
  requirements.txt
  README.md
  bot/
    __init__.py
    __main__.py
    config.py
    storage.py
    http_client.py
    indicators.py
    scoring.py
    news.py
    market_data.py
    portfolio.py
    telegram_api.py
    telegram_bot.py
    analysis.py
    scheduler.py
    main.py
  docs/
    architecture.md
    strategy-notes.md
    refactor-report.md
  tests/
    __init__.py
    helpers.py
    test_indicators.py
    test_scoring.py
    test_news.py
    test_storage.py
    test_portfolio.py
    test_telegram.py
    test_market_data.py
    test_startup.py
    test_concurrency.py
```

The ignored `.test-deps/` directory contains missing dependencies downloaded for local verification using the bundled Python runtime. It is not application source. No `.env` was created, no real Telegram/Google/Yahoo call was made, no real order was placed, and no commit/push was performed.

## Security and reliability

Credentials come exclusively from the process environment; startup rejects missing/placeholder configuration. The dispatcher independently authorizes chat IDs. Telegram transport validates HTTP/API JSON success and discards credential-bearing exception chains; logging masks credentials and Telegram token paths. Manual ticker/price/quantity validation blocks malformed and non-finite inputs.

JSON writes are atomic and checked; corrupt or incompatible state cannot reset the portfolio or falsely report persistence success. Shared worker list replacement is serialized, while the original scan/manual transaction lock is retained. Per-thread sessions avoid shared requests session state; overlapping scans/cache refreshes are protected. Yahoo/RSS/Telegram structures are validated, scheduled failures are logged without losing job registrations, and repeated API failures are rate-limited.

## Bugs and preserved behavior

Fixed: embedded secrets, silent exception swallowing, partial-file writes, worker lost updates, fabricated manual exits on missing data, incorrect TP1 trailing P&L/win labels, zero profit factor shown as infinity, first-loss drawdown omission, permanently NaN SuperTrend bands, invalid nested numeric Yahoo values, false delivered-summary/cooldown markers, naive/aware date arithmetic, substring negation false matches, and the reduced-loss “zarar düştü” case. Missing-fundamental comparison and chart-monitoring behavior were made explicit and corrected.

The original ticker universe, category weights/caps, thresholds, signal branch ordering, market-hours predicate, schedule frequencies, ATR coefficients, sizing formula and chat commands remain. Existing daily-candle execution order, TP1 milestone/full quantity, global headline hashes and paper-only workflow are documented instead of redesigned. Behavioral effects of the actual fixes and unresolved strategy issues are enumerated in [strategy-notes.md](strategy-notes.md).

## Verification

- 78 standard unittest tests passed with network blocking, mocked external APIs and temporary JSON state.
- The suite includes a mocked startup smoke test exercising initial RSS caching, Yahoo chart/fundamentals parsing, signal send/cooldown, unchanged paper-position state and listener startup; schedule frequencies/timezones are checked separately.
- Concurrency tests cover two worker position transitions and scheduled scan transactions versus both `/al` and `/sat`.
- Python syntax and all package-module imports were checked without starting the bot.
- `git diff --check` is unavailable as a normal working-tree check because the workspace is not a Git repository. A Git `--no-index --check` comparison of the resulting source/docs/tests against an empty directory provides the equivalent added-file whitespace check.
- A source-only security audit verifies no token-shaped credential literal, hardcoded credential assignment, bare `except`, or `except Exception: pass` remains. It reports counts/results without printing credential values.

## Remaining risks

The previously exposed token still requires external revocation. Historical copies/backups/Git history outside this workspace were not changed. Chat authorization does not distinguish members of an authorized group. JSON replacement is per-file and locking per-process; Telegram delivery/state changes are not exactly-once transactions. Missing files are considered first-run defaults, so accidental file deletion requires restoration from backups.

Daily-candle chronology, stale quotes, lack of slippage/cash/risk aggregation, keyword/source heuristics and unauthenticated RSS/KAP labels remain. Blocking scans/retries can delay commands and scheduled jobs. There is no message outbox, failed-delivery replay, Markdown normalization, or automatic message splitting. Existing closed records are not retroactively recalculated. Paper outcomes and score weights need empirical validation; passing tests is not evidence of trading profitability.
