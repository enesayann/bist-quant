# Strategy and paper-execution notes

The existing weights are **engineering heuristics**, not estimates calibrated in this task. No backtest, weight optimization or evidence of predictive accuracy was added. Preserve the current forward/paper-test workflow, record outcomes, and validate weights empirically with reproducible backtests and forward tests before relying on signals. Test success validates implementation behavior, not investment performance. Signals are not guaranteed and this code should not be treated as automatic investment advice.

## Original scoring retained

| Category | Cap | Notes |
| --- | ---: | --- |
| Trend | 25 | EMA alignment, SuperTrend, ADX, HH/HL and Ichimoku. Raw points can reach 30; saturation at 25 is intentional existing behavior. |
| Momentum | 20 | RSI band/direction, mutually exclusive fresh/continuing MACD branches, StochRSI and Bollinger rebound. |
| Volume | 15 | OBV, volume spike/recent increase, MFI, CMF and approximate rolling VWAP. |
| Volatility | 10 | Donchian proximity and historical-volatility band. |
| Fundamentals | 10 | P/E, PEG, P/B, forward P/E improvement and dividend. Missing values earn no credit. |
| News | 20 | Positive net keywords, KAP source suffix, patron keywords and signed event weights; clamp to 0–20. Event and keyword/source points can overlap before saturation. |

Final score is the sum of these categories plus the existing support/resistance adjustment, clamped to 0–100. The technical score includes the first **five** categories (including fundamentals), divides by their 80-point maximum, multiplies by 100, then adds the support/resistance adjustment and clamps to 0–100. Confidence begins at `int(technical_score / 10)`. The displayed final score is not the same as the signal-decision technical score.

The original decision order and thresholds are retained:

1. Patron/buyback headline: confidence +3 (cap 10), bypass normal confidence threshold.
2. Rising price with at least 3× normal volume: confidence +2, another +1 for positive news; bypass threshold.
3. Positive news and technical score ≥60: confidence +1; normal minimum confidence 7 applies.
4. Positive news with weaker technicals: confidence at least 6; bypass threshold.
5. Confirmed technical trend and technical score ≥60: normal minimum confidence 7 applies.
6. Otherwise no signal. Cooldown is four hours after a confirmed successful send.

Labels remain LONG ≥8, EARLY ≥6, WATCHLIST ≥4, otherwise RISKY. Resistance within 2% subtracts 10; support within 2% adds 10. Resistance takes precedence if both match. Trend confirmation keeps the last three closes above SMA20, current price above SMA50 and EMA20 above EMA50 below price.

No accidental duplicate MACD fresh/continuing points were found. Trend saturation, overlapping trend/momentum factors, news event/source/keyword overlap, fundamentals inside the “technical” score, and ADX awarding strength without direction are design considerations retained for empirical review. Missing MFI/StochRSI/flat-series RSI or ADX earns no corresponding condition points; the original warmup and zero-denominator NaN semantics are retained. RSI/ATR still use the original pandas EWM seed, which need not match a library using a simple-average initial Wilder seed.

## Paper-position rules and ambiguities retained

Only `/al` opens a paper position. Entry is the user's supplied finite positive price; ATR is from the latest available daily data. Initial stop = entry −1.5×ATR; TP1 = entry +2×ATR; TP2 = entry +3×ATR. Suggested lot size remains floor(100,000 TL ×1% / per-share risk). This does not cap notional exposure to cash, aggregate risk across positions, or add leverage/live execution.

Each check first raises the highest observed **close** and, when appropriate, raises the stop to close −1.5×current ATR. It then evaluates the latest daily candle in this order:

1. Low ≤ updated stop: close at that stop.
2. Otherwise high ≥TP2: close the full paper quantity at TP2.
3. Otherwise, first high ≥TP1: mark TP1, raise stop to at least entry, send an alert and keep the full quantity open.

TP1 is a milestone, not a simulated partial fill: no realized TP1 proceeds or reduced quantity are recorded. TP2 can close without a separate TP1 event. The stop only moves upward. A stop raised at TP1 is not retested within that same call; a later scan of the same daily candle can close it.

The daily candle does not reveal high/low ordering. When stop and target are touched in the same candle, **stop wins**. The close-derived trailing update precedes the low test even if that low occurred earlier in the day. The latest candle can contain price movements before a manual entry, and the implementation does not filter them out. These existing assumptions are documented and covered by tests; no new intraday fill ordering was selected.

Manual `/sat` uses the latest available daily close, which can differ from the quote metadata price used for signal analysis. Gap-through stops still fill at the stop level; no slippage, commissions, taxes, liquidity constraints or corporate-action adjustments are modeled. Stale/in-progress daily candles are not rejected solely by age. Those assumptions can materially bias paper performance.

P&L remains `(exit − entry) / entry ×100`; TL P&L is `(exit − entry) ×quantity` when known. Win rate uses P&L >0; nonpositive outcomes, including break-even, remain in the nonwinning group. The drawdown is the drawdown of cumulative unweighted percentage returns from a zero baseline, not a cash/equity portfolio drawdown. Profit factor uses summed positive versus absolute summed nonpositive percentage returns.

## Keyword news analysis retained

News sentiment is heuristic substring analysis, with a 20-character post-keyword negation window; it is not an LLM, semantic classifier, fact checker, or authenticated official KAP feed. “Zarar azaldı” and its original variants are treated as reduced-loss positives. Negation matching now uses word boundaries, and the existing “zarar düştü” exception correctly suppresses the matching negative “düştü”.

The Google scan considers the first five RSS items, today's Istanbul date, and selects one qualifying positive/event headline per ticker, preferring an existing patron/buyback headline. Exact headline hashes are retained globally for seven days. Identical headlines mentioning multiple stocks can therefore be consumed by the first ticker; title spelling/spacing changes can evade deduplication. Substring false positives (e.g. `kar` within another word), unrelated negation within the window, overlapping phrases and suppression across clauses remain known limitations. Negation boundaries retain common copula forms such as `değildir` and `yoktur`, but are not an exhaustive Turkish morphology parser. A source suffix containing the word KAP is only a source-label heuristic.

Failed bulk requests retain any same-day cache entry and report failures. Cache records retain their existing format without per-ticker refresh-success metadata; an empty cache is not proof of no relevant news. Live negative-news failures are displayed as unknown; the news part of the hold/reduce/exit score stays neutral because no verified positive/negative headline is available.

## Intentional bug fixes with behavioral effects

- SuperTrend previously propagated initial ATR NaNs into both bands indefinitely, leaving direction at its initial +1; the first valid ATR bands now seed the recurrence. This can change trend points/signals, especially on downtrends; periods/multipliers/weights are unchanged.
- TP1-followed-by-stop exits now use the actual current stop, rather than always the entry price. Profitable trailing exits are labeled wins; zero-return exits are explicitly break-even. No partial TP1 sale was invented.
- `/sat` with unavailable Yahoo data keeps the position open instead of fabricating a zero-return exit at entry. Nonpositive/NaN/infinite prices and quantities are rejected before fetching/mutating state.
- Missing trailing P/E no longer fabricates a P/E of 20 for forward-P/E comparison. Quote-summary failures now allow valid chart/position analysis with neutral, visibly unavailable fundamentals; the old network exception could skip stop monitoring entirely.
- Profit factor zero remains zero instead of infinity; drawdown includes the starting zero so the first loss is counted.
- Unsuccessful Telegram messages no longer count as delivered summaries or risk-alert cooldowns. HTTP 200 without API success does not count as a sent signal.
- Daily scheduling now explicitly targets Istanbul; historic naive timestamps are interpreted as Istanbul. The clock times/frequencies and weekday market-hours predicate are unchanged.
