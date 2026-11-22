from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


JsonLoader = Callable[[str], dict[str, Any]]


@dataclass(slots=True)
class JsonHttpClient:
    user_agent: str = "SciMed-SRMA-Scout-Cloud/0.3"
    timeout: float = 20.0
    retries: int = 2
    delay: float = 0.35
    loader: JsonLoader | None = None
    default_headers: dict[str, str] = field(default_factory=dict)

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
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"HTTP request failed: {last_error}")
