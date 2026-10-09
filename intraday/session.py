"""Versioned BIST continuous-session calendar and native Yahoo :30 hourly grid."""
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import IntradayError


TZ = ZoneInfo('Europe/Istanbul')
HOUR = pd.Timedelta(hours=1)
CALENDAR_VERSION = 'bist-equities-2024-2026-native-1h-v0-20261009'
SOURCES = [
    'https://www.borsaistanbul.com/files/equity-market-procedure.pdf',
    'https://www.borsaistanbul.com/en/official-holidays',
    'https://www.borsaistanbul.com/files/duyuru-22379_ENG.pdf',
    'https://www.borsaistanbul.com/files/equity-market-2025-holiday-schedule.pdf',
    'https://borsaistanbul.com/files/41625-sayili-duyurumuz-ingilizce-04122025.pdf',
]
CLOSED = {
    2024: {'01-01', '04-10', '04-11', '04-12', '04-23', '05-01', '05-19', '06-15',
           '06-16', '06-17', '06-18', '06-19', '07-15', '08-30', '10-29'},
    2025: {'01-01', '03-29', '03-30', '03-31', '04-01', '04-23', '05-01', '05-19',
           '06-06', '06-07', '06-08', '06-09', '07-15', '08-30', '10-29'},
    2026: {'01-01', '03-20', '03-21', '03-22', '04-23', '05-01', '05-19', '05-27',
           '05-28', '05-29', '05-30', '07-15', '08-30', '10-29'},
}
HALF_DAYS = {2024: {'04-09', '10-28'}, 2025: {'06-05', '10-28'}, 2026: {'03-19', '05-26', '10-28'}}


def aware_timestamp(value, source_timezone=None):
    if value is None or isinstance(value, (bool, int, float)):
        raise IntradayError('Expected a valid timezone-aware timestamp, not an implicit epoch')
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError('NaT')
        if stamp.tz is None:
            if source_timezone is None:
                raise IntradayError('Naive timestamp requires explicit source_timezone')
            stamp = stamp.tz_localize(source_timezone, ambiguous='raise', nonexistent='raise')
        return stamp.tz_convert(TZ)
    except (ValueError, TypeError) as error:
        raise IntradayError(f'Invalid intraday timestamp: {value!r}') from error


def request_times(start, end, as_of=None):
    first, last = aware_timestamp(start), aware_timestamp(end)
    now = aware_timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz=TZ)
    if first >= last:
        raise IntradayError('Requested start must precede exclusive end')
    return first, last, now


def is_complete(timestamp, replay_timestamp):
    return aware_timestamp(timestamp) + HOUR <= aware_timestamp(replay_timestamp)


@dataclass(frozen=True)
class Session:
    session_date: date
    start: pd.Timestamp
    end: pd.Timestamp
    open: bool
    half_day: bool
    closure_reason: str | None

    def accepted_starts(self):
        if not self.open:
            return pd.DatetimeIndex([], tz=TZ)
        return pd.date_range(self.start + pd.Timedelta(minutes=30), self.end - HOUR, freq='1h')


class BistCalendar:
    version = CALENDAR_VERSION
    sources = SOURCES

    def session(self, day):
        if isinstance(day, (pd.Timestamp, datetime)):
            day = aware_timestamp(day).date()
        elif not isinstance(day, date):
            day = date.fromisoformat(str(day))
        if day.year not in CLOSED:
            raise IntradayError(f'Unsupported BIST calendar year {day.year}; explicit official calendar update required')
        key = day.strftime('%m-%d')
        weekend, holiday = day.weekday() >= 5, key in CLOSED[day.year]
        half = key in HALF_DAYS[day.year] and not weekend and not holiday
        start = pd.Timestamp(f'{day} 10:00', tz=TZ)
        end = pd.Timestamp(f'{day} ' + ('12:30' if half else '18:00'), tz=TZ)
        return Session(day, start, end, not (weekend or holiday), half,
                       'weekend' if weekend else 'official_holiday' if holiday else None)

    def ensure_range(self, start, end):
        for year in range(start.year, (end - pd.Timedelta(nanoseconds=1)).year + 1):
            if year not in CLOSED:
                raise IntradayError(f'Unsupported BIST calendar year {year}; explicit official calendar update required')

    def classify(self, timestamp, zero_volume=False):
        stamp = aware_timestamp(timestamp)
        session = self.session(stamp.date())
        if not session.open:
            return False, 'zero_volume_boundary' if zero_volume else 'outside_session', session.closure_reason
        if stamp < session.start or stamp + HOUR > session.end:
            return False, 'zero_volume_boundary' if zero_volume else 'outside_session', 'auction_or_partial_boundary'
        if stamp.second or stamp.microsecond or stamp.nanosecond or stamp.minute != 30:
            return False, 'outside_session', 'misaligned_native_hourly_timestamp'
        return True, 'valid_zero_volume' if zero_volume else 'valid_session', None

    def expected(self, start, end, as_of):
        self.ensure_range(start, end)
        cutoff = min(end, as_of)
        if cutoff <= start:
            return pd.DatetimeIndex([], tz=TZ)
        timestamps = []
        for day in pd.date_range(start.normalize(), (cutoff - pd.Timedelta(nanoseconds=1)).normalize(), freq='D'):
            for stamp in self.session(day.date()).accepted_starts():
                if start <= stamp < end and stamp + HOUR <= cutoff:
                    timestamps.append(stamp)
        return pd.DatetimeIndex(timestamps, tz=TZ, name='timestamp')
