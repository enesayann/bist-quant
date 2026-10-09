"""Telegram transport. Errors never include the credential-bearing request URL."""
import requests

from .config import api_warning, telegram_credentials
from .http_client import session


class TelegramError(RuntimeError):
    """The Telegram response was unsuccessful or structurally invalid."""


def _result(response):
    if response.status_code != 200:
        raise TelegramError("Telegram HTTP status " + str(response.status_code))
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("ok") is not True or "result" not in payload:
        raise TelegramError("Telegram API returned an invalid or unsuccessful response")
    return payload["result"]


def basit_mesaj_gonder(mesaj: str) -> bool:
    token, chat_id = telegram_credentials()
    try:
        response = session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                data={"chat_id": chat_id, "text": mesaj, "parse_mode": "Markdown"}, timeout=8)
        if not isinstance(_result(response), dict):
            raise TelegramError("Invalid sendMessage result")
        return True
    except (requests.RequestException, ValueError, TelegramError) as error:
        api_warning("Telegram send", error, "Telegram message failed: %s", type(error).__name__)
        return False


def telegram_guncellemelerini_al(offset: int) -> list:
    token, _ = telegram_credentials()
    try:
        # Separate request: do not apply the market-data retry policy to long polling.
        response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                params={"offset": offset, "timeout": 25}, timeout=(10, 30),
                                headers={"User-Agent": "Mozilla/5.0"})
        updates = _result(response)
        if not isinstance(updates, list) or any(
                not isinstance(item, dict) or type(item.get("update_id")) is not int
                or item["update_id"] < 0 or ("message" in item and not isinstance(item["message"], dict))
                for item in updates):
            raise TelegramError("Invalid getUpdates result")
        return updates
    except (requests.RequestException, ValueError, TelegramError) as error:
        # Remove request/response objects from the exposed exception chain.
        raise TelegramError("Telegram polling failed: " + type(error).__name__) from None
