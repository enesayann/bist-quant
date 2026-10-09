"""Validated startup and the original synchronous scheduling loop."""
import threading

import schedule

from .config import (
    ConfigurationError,
    PNL_RAPOR_SIKLIGI_SAAT,
    configure_logging,
    log,
    telegram_credentials,
)
from .news import toplu_haber_taramasi_yap
from .scheduler import (
    ana_tarama,
    gun_sonu_piyasa_ozeti_gonder,
    gun_sonu_pozisyon_ozeti_gonder,
    periyodik_kar_zarar_raporu_gonder,
    piyasa_acik_mi,
)
from .storage import StorageError, _json_yukle
from .telegram_bot import telegram_komut_dinleyicisi_baslat


def validate_state() -> None:
    # Detect unusable state before any API request or background thread.
    files = {
        "pozisyon_takip.json": {"acik": [], "kapanan": []},
        "son_sinyaller.json": {}, "gorulmus_haberler.json": {}, "haber_cache.json": {},
        "telegram_offset.json": {"offset": 0}, "son_performans_ozeti.json": {"tarih": ""},
        "son_pozisyon_ozeti.json": {"tarih": ""}, "son_piyasa_ozeti.json": {"tarih": ""},
    }
    for filename, default in files.items():
        _json_yukle(filename, default)


def run_job(job):
    """Report a failed scheduled job; the next scheduled run remains registered."""
    try:
        job()
    except StorageError:
        log.error("Scheduled job %s aborted: state file could not be read or saved", job.__name__)
    except Exception as error:
        log.error("Scheduled job %s failed: %s", job.__name__, type(error).__name__)


def configure_jobs(scheduler):
    scheduler.every(15).minutes.do(run_job, ana_tarama)
    for at in ("09:15", "13:30", "17:45"):
        scheduler.every().day.at(at, "Europe/Istanbul").do(run_job, toplu_haber_taramasi_yap)
    scheduler.every().day.at("18:10", "Europe/Istanbul").do(run_job, gun_sonu_piyasa_ozeti_gonder)
    scheduler.every().day.at("18:15", "Europe/Istanbul").do(run_job, gun_sonu_pozisyon_ozeti_gonder)
    scheduler.every(PNL_RAPOR_SIKLIGI_SAAT).hours.do(run_job, periyodik_kar_zarar_raporu_gonder)


def main(stop_event=None) -> int:
    try:
        telegram_credentials()
    except ConfigurationError as error:
        print("Startup configuration error: " + str(error))
        return 1
    configure_logging()
    try:
        validate_state()
        if piyasa_acik_mi():
            log.info("Bot starting; building initial news cache")
            toplu_haber_taramasi_yap()
            ana_tarama()
        else:
            log.info("Market closed; skipping initial news and technical scans. Telegram commands remain active.")
    except StorageError:
        log.error("Startup aborted: state file could not be read or saved. Inspect and repair the file; it was not reset.")
        return 1
    stop_event = stop_event or threading.Event()
    scheduler = schedule.Scheduler()
    configure_jobs(scheduler)
    threading.Thread(target=telegram_komut_dinleyicisi_baslat, args=(stop_event,), daemon=True).start()
    log.info("Bot running; scheduled jobs and manual paper-trading commands active")
    try:
        while not stop_event.is_set():
            scheduler.run_pending()
            stop_event.wait(60)
    except KeyboardInterrupt:
        log.info("Bot stopped")
    finally:
        stop_event.set()
    return 0
