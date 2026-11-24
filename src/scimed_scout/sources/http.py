from __future__ import annotations

import json
import time
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


JsonLoader = Callable[[str], dict[str, Any]]

# Process-wide pacing by service, including separate seed/preflight clients.
_pace_lock = threading.Lock()
_next_request: dict[str, float] = {}


def _retry_seconds(value: str) -> float:
    if not value:
        return 3.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 3.0


def _pace(service: str, interval: float, max_wait: float) -> None:
    if not service:
        return
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_request.get(service, now))
        pause = slot - now
        if pause > max_wait:
            raise RuntimeError("HTTP Error 429: service cooldown active; retry deferred")
        _next_request[service] = slot + interval
    if pause > 0:
        time.sleep(pause)


def _cooldown(service: str, seconds: float) -> None:
    if service:
        with _pace_lock:
            _next_request[service] = max(_next_request.get(service, 0), time.monotonic() + seconds)



@dataclass(slots=True)
class JsonHttpClient:
    user_agent: str = "SciMed-SRMA-Scout-Cloud/0.3"
    timeout: float = 20.0
    retries: int = 2
    delay: float = 0.35
    loader: JsonLoader | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    service: str = ""
    min_interval: float = 0.0
    retry_rate_limit: bool = False
    max_rate_wait: float = 8.0

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if params:
            encoded = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = url + ("&" if "?" in url else "?") + encoded

        if self.loader is not None:
            return self.loader(url)

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            **self.default_headers,
            **(headers or {}),
        }

        last_error: Exception | None = None
        rate_retried = False
        for attempt in range(self.retries + 1):
            _pace(self.service, self.min_interval, self.max_rate_wait)
            try:
                req = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Do NOT hammer an exhausted shared quota. The caller
                    # records 429 as ACCESS_FAILED and defers remaining
                    # query variants rather than silently trying 3 times.
                    retry_after = (exc.headers.get("Retry-After","")
                                   if exc.headers else "")
                    seconds = max(2.0, _retry_seconds(retry_after)) + 0.2
                    _cooldown(self.service, seconds)
                    if (self.retry_rate_limit and self.service and not rate_retried
                            and attempt < self.retries and seconds <= self.max_rate_wait):
                        rate_retried = True
                        continue  # _pace honors the provider cooldown before retrying
                    raise RuntimeError(
                        "HTTP Error 429: rate limit reached; no immediate retry"
                        + (f"; Retry-After={str(retry_after)[:40]}" if retry_after else "")
                    ) from exc
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.delay * (2 ** attempt))
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"HTTP request failed: {last_error}")
