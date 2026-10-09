"""Lazy per-thread HTTP sessions with the original GET retry policy."""
import threading

import requests
from requests.adapters import HTTPAdapter, Retry


class ThreadLocalSession:
    def __init__(self):
        self._local = threading.local()

    def _session(self):
        if not hasattr(self._local, "session"):
            current = requests.Session()
            retries = Retry(total=5, backoff_factor=2, connect=5, read=5,
                            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
            current.mount("https://", HTTPAdapter(max_retries=retries, pool_maxsize=30, pool_connections=30))
            current.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Connection": "keep-alive",
            })
            self._local.session = current
        return self._local.session

    def get(self, *args, **kwargs):
        return self._session().get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._session().post(*args, **kwargs)


session = ThreadLocalSession()
