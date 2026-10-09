"""API-only scheduled-session view. The trading bot's hours are unchanged."""
from datetime import timedelta
import pandas as pd
from intraday import IntradayError
from intraday.session import BistCalendar, TZ
from .models import SessionInfo


class MarketCalendar:
    def __init__(self):
        self.calendar = BistCalendar()

    def close_time(self, day):
        session = self.calendar.session(day)
        # Equity closing-price phase ends ten minutes after continuous trading.
        # BIST Equity Market Procedure (revision 21 Sep 2026), full/half-day tables.
        return session.end + pd.Timedelta(minutes=10) if session.open else None

    def previous_session(self, day, include=False):
        candidate = day if include else day - timedelta(days=1)
        for _ in range(20):
            if self.calendar.session(candidate).open:
                return candidate
            candidate -= timedelta(days=1)
        raise IntradayError('No supported session within calendar search window')

    def info(self, now):
        now = pd.Timestamp(now).tz_convert(TZ)
        try:
            session = self.calendar.session(now.date())
            status = 'closed'
            if session.closure_reason == 'official_holiday':
                status = 'holiday'
            elif session.open:
                if session.start <= now < session.end:
                    status = 'open'
                elif session.start - pd.Timedelta(minutes=20) <= now < session.start or session.end <= now < self.close_time(now.date()):
                    status = 'pre_market_or_auction'
            expected = self.previous_session(now.date(), include=session.open and now >= self.close_time(now.date()))
            return SessionInfo(status=status, as_of=now.isoformat(), calendar_version=self.calendar.version,
                               half_day=session.half_day, expected_completed_session=expected.isoformat())
        except IntradayError:
            return SessionInfo(status='unknown', as_of=now.isoformat(), calendar_version=self.calendar.version,
                               note='Date outside supported official calendar; explicit calendar update required.')

    def completed(self, timestamp, now):
        try:
            stamp = pd.Timestamp(timestamp).tz_convert(TZ)
            close = self.close_time(stamp.date())
            return close is not None and close <= now and stamp <= now
        except IntradayError:
            return False

    def freshness(self, timestamp, now, *, completed_close=False, guarantee=False):
        info = self.info(now)
        if timestamp is None or info.status == 'unknown':
            return 'unknown'
        stamp = pd.Timestamp(timestamp).tz_convert(TZ)
        if stamp > now:
            return 'unknown'
        expected = info.expected_completed_session
        if expected and stamp.date().isoformat() < expected:
            return 'stale'
        if info.status in ('open', 'pre_market_or_auction'):
            if completed_close:
                return 'delayed'
            age = (now-stamp).total_seconds()
            if age > 20*60:
                return 'stale'
            return 'fresh' if guarantee and age <= 120 else 'delayed'
        if expected and stamp.date().isoformat() == expected:
            if not completed_close:
                close = self.close_time(stamp.date())
                if close is None or stamp < close-pd.Timedelta(minutes=20):
                    return 'stale'
            return 'market_closed'
        return 'unknown'
