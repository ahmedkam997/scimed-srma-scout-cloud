import json
from pathlib import Path
from scimed_scout.discovery.end_to_end_benchmark import audit
from scimed_scout.sources.base import SearchResult
from scimed_scout.domain import SourceStatus

class MissingSource:
    name="PubMed"
    def search(self,q,*,limit):
        return SearchResult(self.name,q,SourceStatus.ACCESS_FAILED,message="test outage")

def test_real_orchestrator_without_sources_never_qualifies(tmp_path):
    case=json.loads(Path("benchmarks/scientific_v1.json").read_text())["cases"][0]
    report=audit(case,[MissingSource()],None,tmp_path/"report.json")
    assert report["status"]=="COMPLETED"
    assert report["candidate_status"]!="QUALIFIED"
    assert report["coverage_complete"] is False
    assert report["human_go_label"] is None and report["logical_ai_requests"]==0
