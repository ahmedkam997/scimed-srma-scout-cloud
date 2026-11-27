import asyncio,json
import pytest
pytest.importorskip("ldp.agent")
from aviary.core import ToolCall,ToolRequestMessage
from scripts.v2_adaptive_gym import SequentialGym,rollout,CASES,save_policy,load_policy,SURG_REF,SURG_STRATEGIES
def cache(ratio=10):
    return {"probe":(set(),[{"total":100,"complete_bounded":True},{"total":100*ratio,"complete_bounded":True}]),
            "top":({"16899775"},[{"complete_bounded":True}]),
            "expanded":({"16899775","20048204"},[{"complete":True}])}
def test_real_ldp_agent_changes_action_based_on_observed_counts():
    for ratio,expected in [(10,["probe","narrow_top","expand","finish"]),(1,["probe","narrow_top","finish"])]:
        result=asyncio.run(rollout(SequentialGym(None,CASES[0],cache(ratio)),5))
        assert result["resolved"] and [r["action"] for r in result["actions"]]==expected
        assert result["recall"]==(2/12 if ratio==10 else 1/12)
def test_unresolved_probe_does_not_become_success():
    c=cache();c["probe"][1][0]["complete_bounded"]=False
    result=asyncio.run(rollout(SequentialGym(None,CASES[0],c),5))
    assert not result["resolved"] and result["recall"] is None
def test_invalid_action_cannot_skip_probe():
    async def go():
        env=SequentialGym(None,CASES[0],cache())
        await env.reset()
        _,reward,done,truncated=await env.step(ToolRequestMessage(tool_calls=[ToolCall.from_name("finish")]))
        assert reward==-1 and not done and truncated
    asyncio.run(go())
def test_persistent_policy_and_no_qualification(tmp_path):
    p=tmp_path/"p.json";save_policy(p,5,["statins","sglt2_hf"],{5:1})
    assert load_policy(p)==5 and not json.loads(p.read_text())["qualification_granted"]
def test_transfer_queries_have_no_reference_identifiers():
    for routes in SURG_STRATEGIES.values():
        for q,_ in routes:
            assert all(i not in q for i in SURG_REF["linked_reports"])
            assert SURG_REF["review_pmid"] not in q

def test_failed_transfer_rejects_policy_even_when_source_resolved():
    from scripts.v2_adaptive_gym import assess_transfer
    result=assess_transfer({"resolved":True,"recall":.3},{"resolved":True,"recall":1})
    assert not result["passed"] and result["fallback"]=="always_expand"
    assert not result["production_approved"] and not result["scientific_search_complete"]
    result=assess_transfer({"resolved":True,"recall":1},{"resolved":True,"recall":1})
    assert result["passed"] and not result["production_approved"]
    assert not assess_transfer({"resolved":False,"recall":None},{"resolved":True,"recall":1})["passed"]


def test_unresolved_development_persists_diagnostics_without_policy(tmp_path, monkeypatch):
    from scripts import v2_adaptive_gym as gym

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gym, "PubMedSource", lambda **_: None)

    def unavailable(_client, routes):
        return set(), [
            {"complete_bounded": False, "error_type": "HTTPError"} for _ in routes
        ]

    monkeypatch.setattr(gym, "bounded_ids", unavailable)
    with pytest.raises(SystemExit, match="development unresolved"):
        gym.main()
    report = json.loads((tmp_path / "adaptive-gym-report.json").read_text())
    assert not report["all_resolved"]
    assert not report["policy_written"]
    assert not report["qualification_granted"]
    assert not (tmp_path / "adaptive-policy.json").exists()
    trace = report["development"]["statins"][0]["actions"][0]
    assert trace["source_audits"][0]["error_type"] == "HTTPError"


def test_report_curriculum_persists_source_access_failure(tmp_path, monkeypatch):
    from urllib.error import URLError

    from scripts import v2_report_gym as gym

    monkeypatch.chdir(tmp_path)

    def unavailable(_client, _ids):
        raise URLError("network unavailable")

    monkeypatch.setattr(gym, "_fetch", unavailable)
    with pytest.raises(SystemExit, match="ACCESS_FAILED"):
        asyncio.run(gym.main_async())
    report = json.loads((tmp_path / "report-gym.json").read_text())
    assert report["source_diagnostics"] == {"status": "ACCESS_FAILED", "error_type": "URLError"}
    assert report["reports"] == []
    assert not report["qualification_granted"]
