from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable


TextLoader = Callable[[str], str]


class TextHTTPError(RuntimeError):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class TextHttpClient:
    user_agent: str = "SciMed-SRMA-Scout-Cloud/0.4"
    timeout: float = 30.0
    retries: int = 2
    delay: float = 0.35
    loader: TextLoader | None = None

    def get_text(self, url: str, *, accept: str = "application/xml,text/xml,text/plain") -> str:
        if self.loader is not None:
            return self.loader(url)

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept": accept},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code in {403, 404}:
                    raise TextHTTPError(exc.code, f"HTTP {exc.code} for {url}") from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(self.delay * (2 ** attempt))

        raise TextHTTPError(None, f"HTTP request failed: {last_error}")
