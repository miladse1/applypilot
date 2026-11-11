"""Polite HTTP access for job sources.

One shared client, an honest User-Agent, per-host pacing, and errors mapped to
ProviderError. Sources are only ever read through their public listing APIs or
feeds. Nothing here logs in, solves challenges, or rotates identities.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import httpx

USER_AGENT = "ApplyPilot/0.2 (personal job-search assistant; listing reader)"

# Minimum seconds between requests to one host. Job Bank asks for a 5 second crawl delay.
HOST_DELAY = {
    "www.jobbank.gc.ca": 5.0,
    "careers.amd.com": 5.0,
    "www.amazon.jobs": 1.0,
    "remotive.com": 2.0,
    "jobicy.com": 2.0,
    "himalayas.app": 1.0,
}
DEFAULT_DELAY = 0.25


class ProviderError(Exception):
    def __init__(self, message: str, *, rate_limited: bool = False, status: int | None = None):
        super().__init__(message)
        self.rate_limited = rate_limited
        self.status = status


class Http:
    """Thin wrapper so adapters can share pacing and a test double can stand in for httpx."""

    def __init__(self, client=None, timeout: float = 20.0):
        self._owns = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, text/html;q=0.8, */*;q=0.5"},
        )
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _pace(self, url: str) -> None:
        host = urlparse(url).netloc
        delay = HOST_DELAY.get(host, DEFAULT_DELAY)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + delay
        wait = slot - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _send(self, method: str, url: str, **kwargs):
        if self._owns:
            self._pace(url)
        response = None
        for attempt in range(2):
            try:
                if method == "GET":
                    response = self.client.get(url)
                else:
                    response = self.client.post(url, **kwargs)
                break
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
                # A dropped connection is usually transient. Try once more after a pause.
                if attempt == 1:
                    raise ProviderError(f"Request failed ({exc.__class__.__name__}).") from exc
                time.sleep(2.0)
            except httpx.HTTPError as exc:
                raise ProviderError(f"Request failed ({exc.__class__.__name__}).") from exc
        status = getattr(response, "status_code", 200)
        if status == 429:
            raise ProviderError("Rate limit reached. Try again later.", rate_limited=True, status=429)
        if status in {401, 403}:
            raise ProviderError(f"The source refused access (HTTP {status}). ApplyPilot does not bypass access controls.", status=status)
        if status >= 400:
            raise ProviderError(f"The source returned HTTP {status}.", status=status)
        return response

    def get_json(self, url: str):
        response = self._send("GET", url)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("The source returned an unreadable response.") from exc

    def post_json(self, url: str, payload: dict):
        response = self._send("POST", url, json=payload)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("The source returned an unreadable response.") from exc

    def get_text(self, url: str) -> str:
        response = self._send("GET", url)
        text = getattr(response, "text", None)
        if text is None:
            content = getattr(response, "content", b"")
            text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        return text


def as_http(client) -> Http:
    if isinstance(client, Http):
        return client
    return Http(client)
