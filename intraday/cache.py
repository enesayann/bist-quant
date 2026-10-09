"""Immutable CSV snapshots with an atomic manifest; no database or repair fill."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

import pandas as pd

from . import CacheError
from .data import COLUMNS, CONTRACT_VERSION, empty_candles, ticker_name, validate_contract
from .session import BistCalendar, TZ, aware_timestamp


def atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def csv_bytes(frame):
    output = frame.copy()
    output.insert(0, 'timestamp', [t.isoformat() for t in frame.index])
    return output.to_csv(index=False, lineterminator='\n').encode('utf-8')


def read_csv_candles(path, source_timezone=None):
    frame = pd.read_csv(path, float_precision='round_trip')
    if list(frame.columns) != ['timestamp'] + COLUMNS:
        raise CacheError('CSV schema must be timestamp,open,high,low,close,volume')
    frame.index = pd.DatetimeIndex([aware_timestamp(t, source_timezone) for t in frame.pop('timestamp')],
                                   tz=TZ, name='timestamp').as_unit('ns')
    return frame


class IntradayCache:
    def __init__(self, root='data/intraday_cache', calendar=None):
        self.root = Path(root).resolve()
        self.calendar = calendar or BistCalendar()

    def directory(self, ticker):
        folder = self.root / '1h' / ticker_name(ticker)
        if not folder.resolve().is_relative_to(self.root):
            raise CacheError('Cache directory escaped the configured root')
        return folder

    def load(self, ticker):
        folder = self.directory(ticker)
        manifest = folder / 'manifest.json'
        if not manifest.exists():
            return empty_candles(), None
        try:
            metadata = json.loads(manifest.read_text('utf-8'))
            if metadata['contract_version'] != CONTRACT_VERSION or metadata['calendar_version'] != self.calendar.version:
                raise CacheError('Cache contract/calendar version mismatch; use a separate cache revision')
            if metadata['ticker'] != ticker_name(ticker) or metadata['interval'] != '1h' or metadata['timezone'] != 'Europe/Istanbul':
                raise CacheError('Cache ticker/interval/timezone mismatch')
            digest = metadata['csv_sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise CacheError('Invalid cache snapshot digest')
            snapshot = folder / f'{digest}.csv'
            if snapshot.resolve().parent != folder.resolve() or sha256(snapshot.read_bytes()).hexdigest() != digest:
                raise CacheError('Cache CSV integrity/path check failed')
            frame = read_csv_candles(snapshot)
            validate_contract(frame, self.calendar)
            for coverage in metadata['coverage']:
                if aware_timestamp(coverage['start']) >= aware_timestamp(coverage['end']):
                    raise CacheError('Invalid cache coverage interval')
            return frame, metadata
        except (OSError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, CacheError):
                raise
            raise CacheError(f'Invalid intraday cache for {ticker}: {error}') from error

    def covers(self, metadata, start, end, as_of):
        target = min(end, as_of)
        if metadata is None:
            return False
        if target <= start:
            return True
        cursor = start
        for interval in sorted(metadata['coverage'], key=lambda row: row['start']):
            left, right = aware_timestamp(interval['start']), aware_timestamp(interval['end'])
            if right <= cursor:
                continue
            if left > cursor:
                return False
            cursor = max(cursor, right)
            if cursor >= target:
                return True
        return False

    def merge(self, ticker, incoming, start, end, as_of, audit, *, source_identity='yahoo_chart_quote_unverified'):
        folder = self.directory(ticker)
        folder.mkdir(parents=True, exist_ok=True)
        lock = folder / '.write.lock'
        try:
            with lock.open('x', encoding='utf-8') as handle:
                handle.write(str(os.getpid()))
        except FileExistsError as error:
            raise CacheError('Another cache writer or stale lock exists; merge refused') from error
        try:
            return self._merge(ticker, incoming, start, end, as_of, audit, source_identity=source_identity)
        finally:
            lock.unlink()

    def _merge(self, ticker, incoming, start, end, as_of, audit, *, source_identity):
        """Valid first snapshots stay immutable; conflicting valid revisions fail.

        Malformed provider rows must already have been explicitly removed by
        the contract. Existing valid candles can fill their SAME known cache
        timestamps, never via interpolation. Overlapping equal rows are deduped.
        """
        validate_contract(incoming, self.calendar)
        old, manifest = self.load(ticker)
        if manifest is not None and manifest['source_identity'] != source_identity:
            raise CacheError('Cache source/price-basis identity mismatch; use a separate cache root', audit)
        common = old.index.intersection(incoming.index)
        conflicts = [t for t in common if tuple(old.loc[t]) != tuple(incoming.loc[t])]
        if conflicts:
            diagnostics = deepcopy(audit)
            diagnostics['cache_conflicts_preserved'] = [t.isoformat() for t in conflicts]
            raise CacheError('Conflicting valid cache/provider candle(s); cache unchanged: '
                             + ', '.join(t.isoformat() for t in conflicts), diagnostics)
        merged = pd.concat([old, incoming.loc[~incoming.index.isin(old.index)]]).sort_index(kind='stable')
        merged.index = pd.DatetimeIndex(merged.index, tz=TZ, name='timestamp')
        validate_contract(merged, self.calendar)
        content = csv_bytes(merged)
        digest = sha256(content).hexdigest()
        folder = self.directory(ticker)
        snapshot = folder / f'{digest}.csv'
        if not snapshot.exists():
            atomic_bytes(snapshot, content)
        elif sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise CacheError('Existing content-addressed snapshot is corrupted')
        metadata = deepcopy(manifest) if manifest else {
            'ticker': ticker_name(ticker), 'interval': '1h', 'timezone': 'Europe/Istanbul',
            'contract_version': CONTRACT_VERSION, 'calendar_version': self.calendar.version,
            'source_identity': source_identity, 'price_basis': 'unverified', 'volume_adjustment_basis': 'unverified',
            'coverage': [], 'source_audits': []}
        sealed = min(end, as_of)
        if start < sealed:
            metadata['coverage'].append({'start': start.isoformat(), 'end': sealed.isoformat()})
        metadata['coverage'] = [dict(t) for t in sorted({tuple(sorted(row.items())) for row in metadata['coverage']})]
        metadata['source_audits'].append(deepcopy(audit))
        metadata['csv_sha256'] = digest
        metadata['rows'] = len(merged)
        # CSV written first, manifest last. Old CSV revisions remain recoverable
        # even if an interruption occurs before the atomic pointer update.
        atomic_bytes(folder / 'manifest.json', json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))
        return merged, metadata, len(common)
