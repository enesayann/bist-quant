"""Atomic JSON persistence. Only missing files get defaults; corruption fails closed."""
import copy
import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .config import (
    COOLDOWN_DOSYA,
    COOLDOWN_SAAT,
    GORULMUS_HABERLER_DOSYA,
    HABER_CACHE_DOSYA,
    POZISYON_TAKIP_DOSYA,
    TELEGRAM_OFFSET_DOSYA,
    TR_TZ,
    istanbul_datetime,
    log,
)


class StorageError(RuntimeError):
    """A state file could not be read, validated, or committed."""


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _validate(dosya, data):
    name = Path(dosya).name
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    if name == POZISYON_TAKIP_DOSYA:
        for group in ("acik", "kapanan"):
            if not isinstance(data.get(group), list):
                raise ValueError("Position state requires acik and kapanan lists")
            for poz in data[group]:
                if not isinstance(poz, dict) or not isinstance(poz.get("hisse"), str):
                    raise ValueError("Invalid position entry")
                for key in ("giris_fiyati", "stop", "guncel_stop", "tp1", "tp2", "atr"):
                    if not _finite(poz.get(key)):
                        raise ValueError("Invalid numeric position field: " + key)
                if poz["giris_fiyati"] <= 0 or poz["atr"] <= 0:
                    raise ValueError("Entry price and ATR must be positive")
                if not isinstance(poz.get("tp1_vuruldu"), bool) or not isinstance(poz.get("etiket"), str):
                    raise ValueError("Invalid position metadata")
                istanbul_datetime(poz["acilis_tarihi"])
                if poz.get("adet") is not None and (not _finite(poz["adet"]) or poz["adet"] <= 0):
                    raise ValueError("Invalid position quantity")
                if not _finite(poz.get("en_yuksek_fiyat", poz["giris_fiyati"])):
                    raise ValueError("Invalid highest price")
                for timestamp in poz.get("son_uyarilar", {}).values():
                    istanbul_datetime(timestamp)
                if group == "kapanan":
                    if not _finite(poz.get("pnl_yuzde")) or not _finite(poz.get("kapanis_fiyati")):
                        raise ValueError("Invalid closed position P&L")
                    istanbul_datetime(poz["kapanis_tarihi"])
        symbols = [p["hisse"] for p in data["acik"]]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate open positions")
    elif name in (COOLDOWN_DOSYA, GORULMUS_HABERLER_DOSYA):
        for timestamp in data.values():
            istanbul_datetime(timestamp)
    elif name == HABER_CACHE_DOSYA:
        for item in data.values():
            if not isinstance(item, dict) or not isinstance(item.get("baslik"), str):
                raise ValueError("Invalid news cache entry")
            datetime.fromisoformat(item["tarih"])
            for key in ("pozitif", "patron_aliyor", "kap_kaynakli"):
                if not isinstance(item.get(key), bool):
                    raise ValueError("Invalid news cache flag: " + key)
            if not _finite(item.get("kap_olay_puani")):
                raise ValueError("Invalid KAP event score")
    elif name == TELEGRAM_OFFSET_DOSYA:
        if type(data.get("offset")) is not int or data["offset"] < 0:
            raise ValueError("Invalid Telegram offset")
    elif name in ("son_performans_ozeti.json", "son_pozisyon_ozeti.json", "son_piyasa_ozeti.json"):
        if not isinstance(data.get("tarih"), str):
            raise ValueError("Invalid summary date")
        if data["tarih"]:
            datetime.fromisoformat(data["tarih"])


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _json_yukle(dosya: str, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as handle:
            data = json.load(handle, parse_constant=_reject_constant)
        if not isinstance(data, type(varsayilan)):
            raise ValueError("Unexpected JSON root type")
        _validate(dosya, data)
        return data
    except FileNotFoundError:
        return copy.deepcopy(varsayilan)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        log.error("State read failed (%s): %s", dosya, type(error).__name__)
        raise StorageError("Cannot read state file: " + str(dosya)) from error


def _json_kaydet(dosya: str, veri) -> None:
    temporary = None
    try:
        _validate(dosya, veri)
        target = Path(dosya)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(veri, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        log.error("State write failed (%s): %s", dosya, type(error).__name__)
        raise StorageError("Cannot write state file: " + str(dosya)) from error
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError as error:
                log.warning("Temporary state file cleanup failed: %s", type(error).__name__)


def son_sinyalleri_yukle() -> dict:
    return _json_yukle(COOLDOWN_DOSYA, {})


def son_sinyalleri_kaydet(veri: dict) -> None:
    _json_kaydet(COOLDOWN_DOSYA, veri)


def pozisyon_takip_yukle() -> dict:
    return _json_yukle(POZISYON_TAKIP_DOSYA, {"acik": [], "kapanan": []})


def pozisyon_takip_kaydet(veri: dict) -> None:
    _json_kaydet(POZISYON_TAKIP_DOSYA, veri)


def cooldown_da_mi(hisse: str, son_sinyaller: dict) -> bool:
    timestamp = son_sinyaller.get(hisse)
    return bool(timestamp) and datetime.now(TR_TZ) - istanbul_datetime(timestamp) < timedelta(hours=COOLDOWN_SAAT)
