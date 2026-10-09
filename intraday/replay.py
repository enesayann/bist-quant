"""One-ticker completed-candle snapshots; no signals or execution logic."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from . import GapError, IntradayError
from .data import finalize_diagnostics, validate_contract
from .session import HOUR, TZ, aware_timestamp


@dataclass(frozen=True)
class Candle:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_end: pd.Timestamp
    session_date: str
    tradable: bool = True


@dataclass(frozen=True)
class Snapshot:
    replay_timestamp: pd.Timestamp
    current_candle: Candle
    history: pd.DataFrame


class SessionReplay:
    def __init__(self, dataset, *, as_of=None, gap_policy='strict'):
        if gap_policy not in ('strict', 'warn'):
            raise IntradayError('Gap policy must be strict or warn')
        self.dataset = dataset
        self.as_of = min(aware_timestamp(as_of) if as_of is not None else dataset.as_of, dataset.as_of)
        self.gap_policy = gap_policy
        frame = dataset.candles.copy(deep=True)
        validate_contract(frame, dataset.calendar)
        self._frame = frame[(frame.index >= dataset.start) & (frame.index < dataset.end)
                            & (frame.index + HOUR <= dataset.end) & (frame.index + HOUR <= self.as_of)].copy()
        self.diagnostics = finalize_diagnostics(self._frame, dataset.diagnostics, dataset.calendar,
                                                dataset.start, dataset.end, self.as_of)
        self.diagnostics['replay_gap_policy'] = gap_policy
        self.diagnostics['source_as_of'] = dataset.as_of.isoformat()
        self.diagnostics['replay_as_of'] = self.as_of.isoformat()
        self.diagnostics['corporate_action_events'] = [e for e in self.diagnostics.get('corporate_action_events', [])
                                                       if aware_timestamp(e['timestamp']) <= self.as_of]
        if self.diagnostics.get('duplicate_conflicts'):
            raise IntradayError('Ambiguous duplicate candles cannot enter replay', self.diagnostics)

    def __iter__(self):
        gaps = self.diagnostics['missing_candle_gaps']
        for number, (stamp, values) in enumerate(self._frame.iterrows()):
            now = stamp + HOUR
            if self.gap_policy == 'strict':
                due = [g for g in gaps if aware_timestamp(g['missing_timestamp']) + HOUR <= now]
                if due:
                    raise GapError('Replay segment blocked at missing completed candle: ' + due[0]['missing_timestamp'], self.diagnostics)
            candle = Candle(stamp, *(float(values[c]) for c in ('open', 'high', 'low', 'close', 'volume')),
                            now, str(stamp.date()))
            # Fresh deep copy per step: a consumer cannot mutate the replay's
            # remaining data or gain access to any future row via a view.
            yield Snapshot(now, candle, self._frame.iloc[:number + 1].copy(deep=True))
        if self.gap_policy == 'strict' and gaps:
            raise GapError('Replay segment ends with missing completed candle: ' + gaps[0]['missing_timestamp'], self.diagnostics)


def save_replay_audit(diagnostics, *, candles=None, output='backtest_results/intraday_replay_audit', run_id=None, status='ok', error=None):
    run_id = run_id or datetime.now(TZ).strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    if Path(run_id).name != run_id or run_id in ('.', '..') or '/' in run_id or '\\' in run_id:
        raise IntradayError('run_id must be a single directory name')
    directory = Path(output) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    result = deepcopy(diagnostics)
    defaults = {'ticker': None, 'requested_start': None, 'requested_end': None,
                'actual_first_candle': None, 'actual_last_candle': None,
                'timezone': 'Europe/Istanbul', 'interval': '1h', 'downloaded_rows': None,
                'removed_rows': None, 'duplicates': None, 'outside_range_rows': None,
                'outside_session_rows': None, 'missing_candle_gaps': None,
                'final_usable_rows': None, 'provider_source': None, 'cache_hit': None,
                'gap_detection_performed': False}
    for key, value in defaults.items():
        result.setdefault(key, value)
    result.update(status=status, error=str(error) if error else None)
    (directory / 'diagnostics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if candles is not None:
        from .cache import csv_bytes
        (directory / 'candles.csv').write_bytes(csv_bytes(candles))
    gaps = result.get('missing_candle_gaps') or []
    lines = ['# Intraday Data Contract & Session Replay v0', '', f'Status: {status}.',
             f'Ticker: {result.get("ticker", "unknown")}. Interval: 1h. Timezone: Europe/Istanbul.',
             f'Requested: {result.get("requested_start")} <= timestamp < {result.get("requested_end")}.',
             'Full bar_end must also be <= requested end and as_of; incomplete/boundary bars are excluded.',
             f'Actual first/last: {result.get("actual_first_candle")} / {result.get("actual_last_candle")}.',
             f'Provider: {result.get("provider_source")}. Cache hit: {result.get("cache_hit")}.', '',
             '| Field | Value |', '| --- | ---: |']
    for key in ('downloaded_rows', 'source_downloaded_rows', 'input_rows', 'removed_rows', 'duplicates',
                'outside_range_rows', 'outside_session_rows', 'incomplete_rows', 'valid_zero_volume_rows',
                'expected_completed_candles', 'final_usable_rows'):
        lines.append(f'| {key} | {result.get(key, "N/A")} |')
    gap_count = str(len(gaps)) if result['gap_detection_performed'] else 'N/A (not evaluated)'
    lines += ['', f'Gap policy: {result.get("replay_gap_policy", result.get("gap_policy", "unknown"))}. Known gaps: {gap_count}.',
              '', '## Missing expected candles', '']
    lines += ['- ' + g['missing_timestamp'] + ' (' + g['session_date'] + ')' for g in gaps] or ['None.']
    if error:
        lines += ['', 'Error: ' + str(error)]
    lines += ['', '## Corporate-action and execution limitations', '',
              'Yahoo quote price/volume adjustment basis remains unverified; no adjustment, fill or interpolation was applied.',
              'Tradable means accepted under the nominal native :30 hourly session contract, not proof of tick/auction ownership or guaranteed execution.',
              'Future signal: completed bar only; earliest entry next tradable bar. Intrabar stop/target order, overnight policy, entry cutoff and costs require a later execution specification.',
              'No strategy, order, profit calculation, risk change or live-bot integration exists in this replay.']
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return directory
