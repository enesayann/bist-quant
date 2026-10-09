# Architecture and data flow

The refactor retains the original Turkish function names, indicator expressions, ticker list, message text, synchronous execution, and JSON records. Modules are ordinary functions with explicit imports; no framework or database is introduced.

| Module | Responsibility |
| --- | --- |
| `bot.py`, `bot/__main__.py` | Compatibility and package launchers. |
| `bot/config.py` | Original constants/tickers/locks, required environment validation, Istanbul timestamp normalization, redacted logging, API warning suppression. |
| `bot/storage.py` | JSON read/schema validation, original persistence helpers, atomic commits, signal cooldown. |
| `bot/http_client.py` | Lazy per-thread requests sessions and the original GET retry/timeout infrastructure. |
| `bot/indicators.py` | Original numeric indicator helpers and safe-number validation. |
| `bot/scoring.py` | Original capped categories, final/technical formulas, labels, hold/reduce/exit score. |
| `bot/market_data.py` | Yahoo response validation, light position data, fundamentals, daily changes. |
| `bot/news.py` | RSS parsing, headline hashes/retention, keyword/negation/KAP heuristic, slow news cache writer and fast reader, live negative-news checks. |
| `bot/portfolio.py` | Paper-position creation, sizing, TP/stop/trailing transitions, risk alerts, P&L and statistics. |
| `bot/telegram_api.py` | Environment-backed send/poll transport, HTTP and API-success validation, credential-safe errors. |
| `bot/telegram_bot.py` | Authorized command dispatch, input validation, paper /al and /sat transactions, reports, backoff listener. |
| `bot/analysis.py` | Original per-ticker technical analysis, category scoring, signal decision branches and successful-send cooldown. |
| `bot/scheduler.py` | Market-hours guard, scan coordination and periodic/daily reports. |
| `bot/main.py` | Startup validation, initial scans, Istanbul wall-clock job registration and main loop. |

## Scan and command flow

1. Startup checks required environment variables, configures redacted logging, and validates all existing state files before making an API request. It uses the existing market-hours check to run the initial news/technical scans only when open; closed-market startup skips both scans and starts the listener and scheduler normally. Scheduled jobs retain their existing timing and behavior.
2. The slow Google News job reads the cache/seen hashes, fetches the first five RSS items per ticker, filters to today's Istanbul date, applies the existing keyword rules and preserves the existing headline-selection priority. It writes the news cache before seen hashes so a failed cache commit cannot mark undelivered headlines as consumed.
3. `ana_tarama` checks market hours, reads cooldown state, acquires the original position transaction lock, and loads a position snapshot. Four workers fetch/validate Yahoo data, calculate indicators, monitor relevant open positions, read cached news, and apply the unchanged signal branches. Signals do not create positions. A confirmed Telegram send updates the signal cooldown.
4. The coordinator waits for every worker and commits position and cooldown files. Workers use a separate state lock when reading/writing the shared position lists or cooldown dictionary; the coordinator's transaction lock cannot be acquired from workers without deadlocking.
5. The Telegram listener uses a separate non-retrying GET request for long polling, checks the response structure, and hands updates to the chat-authorized dispatcher. `/al` and `/sat` hold the same original transaction lock across load, market-data validation, mutation and save. Read-only commands consume atomic file snapshots.
6. Summaries call the same Telegram transport and save their sent-date marker only on confirmed API success. Listener backoff remains 5, 10, 20, 40, 80, then 120 seconds; healthy polling resets it. Operational state errors are explicit.

Telegram responses must indicate API success in addition to an HTTP success response; see the [official Bot API request/response contract](https://core.telegram.org/bots/api#making-requests). Daily timezone registration follows [schedule's timezone documentation](https://schedule.readthedocs.io/en/stable/timezones.html).

## Concurrency and persistence boundaries

- `pozisyon_kilidi` protects complete scan/manual position transactions. It is intentionally held during the scan as in the original; manual commands may wait for a slow scan.
- `tarama_durum_kilidi` serializes worker position transitions. Previously multiple workers constructed and replaced the entire shared `acik` list independently, allowing a closed position to be resurrected or another worker's updates to disappear. The new lock also guards worker cooldown access.
- `tarama_kilidi` skips overlapping complete scans; `haber_kilidi` serializes full cache read/modify/write jobs. API-warning bookkeeping has its own short lock.
- Each worker/listener thread owns its requests session. Headers and cookie jars are not shared across workers. GET retries remain five attempts with backoff factor two and statuses 429/500/502/503/504. POST sends are not automatically retried.
- JSON replacement is atomic per file. A serialization, fsync or replace failure propagates as `StorageError` and keeps the old target. Missing files receive independent default objects; malformed/incompatible files never become empty portfolios.
- Locking is in-process only. Two separate bot processes, external writers, power loss during multi-file commits, and Telegram-send/state-commit ordering require operator supervision/backups. Atomic replacement is not a cross-file transaction or a guarantee of filesystem directory durability.

## Error semantics

Invalid/insufficient Yahoo arrays, non-finite values, API errors, malformed RSS and unsuccessful Telegram JSON are detected before deep indexing or mutation. Optional unavailable fundamentals receive no fundamental credit and an explicit warning. Live news failure carries `kullanilabilir=False`; reports display unknown rather than no negative news, and the original news-neutral risk factor remains unchanged.

Repeated API errors are rate-limited at WARNING by service/error type for five minutes, with individual details at DEBUG. Bulk news scans additionally report failed-ticker counts. Unexpected exceptions at scheduling/listener/analysis boundaries are logged with operation/type, and startup/storage failures remain visible. Logs do not include raw Telegram response bodies, credential-bearing URLs or request exception chains.

Existing naive timestamps are read as Istanbul local times; new cooldown timestamps include the timezone. Cache expiry and RSS dates use the Istanbul calendar date. Hosts that previously wrote naive timestamps in another timezone should review those historical records before migration.
