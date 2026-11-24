from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from scimed_scout.sources.http import JsonHttpClient


def test_http_429_is_not_retried_even_with_standard_retry_budget(monkeypatch):
    calls = []
    def blocked(request, timeout=None):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url,429,"Too Many Requests",
                                     {"Retry-After":"23"},io.BytesIO(b"quota"))
    monkeypatch.setattr(urllib.request,"urlopen",blocked)
    client=JsonHttpClient(retries=4,delay=0)
    with pytest.raises(RuntimeError,match="HTTP Error 429.*Retry-After=23"):
        client.get_json("https://api.semanticscholar.org/graph/v1/paper/search",
                        {"query":"dialysis"})
    assert len(calls)==1


def test_temporary_non429_transport_error_still_respects_standard_retry(monkeypatch):
    calls=[]
    def occasionally_broken(request, timeout=None):
        calls.append(1)
        if len(calls)==1:
            raise urllib.error.URLError("transient")
        return FakeResponse()
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def read(self): return b'{"total":0}'
    monkeypatch.setattr(urllib.request,"urlopen",occasionally_broken)
    client=JsonHttpClient(retries=1,delay=0)
    assert client.get_json("https://api.semanticscholar.org/test")=={"total":0}
    assert len(calls)==2
