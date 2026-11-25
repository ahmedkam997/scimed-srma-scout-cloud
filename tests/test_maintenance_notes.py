import io
import json
import zipfile
from scimed_scout import maintenance_notes as m

REPO="owner/repo"
RUN={"id":42,"head_branch":"main","status":"completed","head_repository":{"full_name":REPO},
     "name":"comparative-validation","event":"push","conclusion":"success","head_sha":"a"*40}

def test_untrusted_fork_or_pr_is_rejected():
    assert m.trusted_run(RUN,REPO)
    assert not m.trusted_run({**RUN,"event":"pull_request"},REPO)
    assert not m.trusted_run({**RUN,"head_repository":{"full_name":"fork/repo"}},REPO)

def test_untrusted_artifact_fields_never_become_issue_text():
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("diagnostics-report.json",json.dumps({"version":"DIAGNOSTICS_V1","findings":[
            {"code":"UPSTREAM_UNAVAILABLE","action":"malicious raw content"},
            {"code":"unknown-secret"},{"code":"UPSTREAM_UNAVAILABLE"}]}))
        z.writestr("../../bad.sh","not executed")
    assert m.parse_diagnostics_zip(b.getvalue())==["UPSTREAM_UNAVAILABLE"]
    assert "malicious" not in m.note(REPO,RUN,"UPSTREAM_UNAVAILABLE")["body"]

def test_dedup_and_update_preserve_comments(monkeypatch):
    calls=[]
    def fake(repo,endpoint,**kwargs):
        calls.append((endpoint,kwargs))
        return {"number":7,"body":kwargs["payload"]["body"],"user":{"login":"github-actions[bot]"}}
    monkeypatch.setattr(m,"api",fake)
    issues=[]
    assert m.publish(REPO,RUN,"UPSTREAM_UNAVAILABLE",issues)=="CREATED"
    assert m.publish(REPO,RUN,"UPSTREAM_UNAVAILABLE",issues)=="UNCHANGED"
    assert m.publish(REPO,{**RUN,"id":43},"UPSTREAM_UNAVAILABLE",issues)=="UPDATED"
    assert [c[0] for c in calls]==["issues","issues/7"]

def test_workflow_success_can_still_have_inconclusive_diagnostic(monkeypatch):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("diagnostics-report.json",json.dumps({"version":"DIAGNOSTICS_V1","findings":[{"code":"COMPARISON_INCONCLUSIVE"}]}))
    monkeypatch.setattr(m,"api",lambda repo,path,**kwargs: b.getvalue() if kwargs.get("binary") else {"artifacts":[{"name":"paired-discovery-pilot","id":1,"size_in_bytes":100}]})
    assert m.run_findings(REPO,RUN)==["COMPARISON_INCONCLUSIVE"]
