from types import SimpleNamespace
from urllib.error import HTTPError
import io
import json

from scimed_scout.sources import http
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.discovery.topic_diversity import select_diverse_ranked
from scimed_scout.ranking import RankingResult


def test_paced_client_respects_retry_after_and_recovers(monkeypatch):
    clock = [100.0]
    sleeps = []
    calls = []
    monkeypatch.setattr(http, "_next_request", {})
    monkeypatch.setattr(http.time, "monotonic", lambda: clock[0])
    def advance(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(http.time, "sleep", advance)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"ok": True}).encode()
    def request(req, timeout=None):
        calls.append(clock[0])
        if len(calls) == 1:
            raise HTTPError(req.full_url, 429, "limited", {"Retry-After": "2"}, io.BytesIO())
        return Response()
    monkeypatch.setattr(http.urllib.request, "urlopen", request)
    client = JsonHttpClient(service="test", min_interval=0.5, retry_rate_limit=True, retries=2)
    assert client.get_json("https://example.org") == {"ok": True}
    assert len(calls) == 2 and calls[1] - calls[0] >= 2
    other = JsonHttpClient(service="test", min_interval=0.5)
    assert other.get_json("https://example.org") == {"ok": True}
    assert calls[2] - calls[1] >= 0.5


def test_vexus_cross_design_family_only_uses_one_deep_audit():
    def candidate(cid, qtype, intervention, comparator):
        return SimpleNamespace(
            candidate_id=cid, title="VExUS after TAVR " + cid,
            population="Adults undergoing transcatheter aortic valve replacement",
            intervention_exposure_index_test=intervention,
            comparator_reference=comparator, outcomes=["Acute kidney injury"],
            question_type=qtype,
        )
    a = candidate("a", "PROGNOSIS", "Venous excess ultrasound score", "Clinical assessment")
    b = candidate("b", "DIAGNOSTIC_ACCURACY", "Venous Excess Ultrasound (VExUS) score", "Serum creatinine")
    c = candidate("c", "PROGNOSIS", "Cardiac magnetic resonance", "Clinical assessment")
    by_id = {x.candidate_id:x for x in (a,b,c)}
    selected, skipped = select_diverse_ranked(
        [RankingResult(x.candidate_id, 100-i, ()) for i,x in enumerate((a,b,c))], by_id, limit=3)
    assert [x.candidate_id for x in selected] == ["a", "c"]
    assert skipped[0]["candidate_id"] == "b"
    assert len(by_id) == 3
