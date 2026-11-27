import json
from urllib.error import HTTPError
import pytest
from scripts.scimed_autonomous_worker import initial,plan,advance,load,write,run,advise,provider_configs

def lead(n=7):
    return {"candidate_id":"RCT-TEST","title":"Test comparison","metadata":{"rct_first":{"family_leads":n,"shortlist_eligible":n>=7}}}

def test_resume_and_rotate(tmp_path):
    s=initial()
    advance(s,"ACCESS_UNRESOLVED");assert plan(s)==("Cardiology",0)
    advance(s,"ACCESS_UNRESOLVED");assert plan(s)==("General Surgery",0)
    advance(s,"PARTIAL_SAMPLE");assert plan(s)==("Cardiology",1)
    p=tmp_path/"state.json";write(p,s);assert load(p)==s
    p.write_text('{"schema":99}')
    with pytest.raises(ValueError):load(p)

def test_partial_never_qualifies_and_preserves_cues():
    s=initial()
    result,_=run(s,lambda *a,**kw:{"status":"PARTIAL_SAMPLE","candidates":[lead()]},lambda x:{"status":"TEST_ONLY"})
    assert result["first_choice_count"]==0 and not result["qualification_granted"]
    assert s["ledger"]["RCT-TEST"]["confirmed_independent_eligible_trials"] is None
    assert result["selected"]["id"]=="RCT-TEST"
    result,_=run(s,lambda *a,**kw:{"status":"ACCESS_UNRESOLVED","candidates":[]},lambda x:None)
    assert "RCT-TEST" in s["ledger"] and result["coverage"]=="ACCESS_UNRESOLVED"

def test_free_guard():
    assert provider_configs({"GROQ_API_KEY":"paid","GEMINI_API_KEY":"paid","OPENROUTER_API_KEY":"paid"})==[]
    assert provider_configs({"SCIMED_FREE_GROQ_API_KEY":"key"})==[]
    env={"SCIMED_FREE_OPENROUTER_API_KEY":"key","SCIMED_FREE_GROQ_API_KEY":"key","SCIMED_FREE_GROQ_ATTESTED":"true"}
    assert [p[0] for p in provider_configs(env)]==["openrouter","groq"]

def test_fallback_on_quota_and_invalid_advice():
    seen=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"choices":[{"message":{"content":"RCT-TEST"}}]}'
    def transport(req,timeout):
        body=json.loads(req.data);seen.append(body)
        if len(seen)==1:raise HTTPError(req.full_url,429,"quota",{},None)
        return Response()
    env={"SCIMED_FREE_OPENROUTER_API_KEY":"key","SCIMED_FREE_GROQ_API_KEY":"key","SCIMED_FREE_GROQ_ATTESTED":"true"}
    result=advise([{"id":"RCT-TEST","title":"test","family_leads":7}],env,transport)
    assert result["provider"]=="groq" and result["attempts"][0]["status"]=="HTTP_429"
    assert seen[0]["model"]=="openrouter/free" and seen[0]["provider"]["max_price"]=={"prompt":0,"completion":0}
    assert advise([{"id":"RCT-TEST","title":"test","family_leads":7}],{},transport)["status"]=="DETERMINISTIC_FALLBACK"

def test_no_arbitrary_model_output():
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"choices":[{"message":{"content":"unknown candidate"}}]}'
    result=advise([{"id":"RCT-TEST","title":"test","family_leads":7}],{"SCIMED_FREE_OPENROUTER_API_KEY":"key"},lambda *a,**kw:Response())
    assert result["status"]=="DETERMINISTIC_FALLBACK"
