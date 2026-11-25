import json
import urllib.error
import pytest
from scimed_scout.ai.models import AIRequest,AIResponse
from scimed_scout.ai.providers import FreeProviderFallback,ProviderFailure,OpenAICompatibleProvider
from scimed_scout.ai.adaptive_router import AdaptiveFreeRouter
from scimed_scout.run_telemetry import MeteredDiscoveryProvider

REQUEST=AIRequest(system="JSON only",prompt="Return a JSON object")
class Stub:
    def __init__(self,name,reply):
        self.name=name
        self.model=name
        self.reply=reply
        self.calls=0
    def complete(self,request):
        self.calls+=1
        if isinstance(self.reply,Exception):
            raise self.reply
        return AIResponse(self.reply,self.name,self.model,{})

def test_repeated_503_sticky_success_reduces_attempts_in_24_call_simulation():
    a=Stub("gemini-free",ProviderFailure("gemini-free",503,"unavailable"))
    b=Stub("openrouter-free",ProviderFailure("openrouter-free",503,"unavailable"))
    c=Stub("groq-free-backup",'{"ok":true}')
    r=AdaptiveFreeRouter(FreeProviderFallback(a,FreeProviderFallback(b,c)),clock=lambda:0)
    for _ in range(24):
        assert r.complete(REQUEST).provider==c.name
    assert (a.calls,b.calls,c.calls)==(1,1,24)
    s=r.routing_snapshot()
    assert s["provider_attempts"]==26 and s["fallback_attempts"]==2
    assert s["preferred_provider"]==c.name and s["http_attempts"] is None

def test_rate_limit_honors_retry_after_and_all_routes_defer_without_http_calls():
    now=[0]
    a=Stub("groq-free-backup",ProviderFailure("groq-free-backup",429,"quota",remaining_daily_requests=0))
    b=Stub("gemini-free",ProviderFailure("gemini-free",429,"quota",retry_after_seconds=300))
    r=AdaptiveFreeRouter(FreeProviderFallback(a,b),clock=lambda:now[0])
    with pytest.raises(ProviderFailure):r.complete(REQUEST)
    now[0]=299
    with pytest.raises(ProviderFailure) as e:r.complete(REQUEST)
    assert e.value.retry_after_seconds==1 and (a.calls,b.calls)==(1,1)
    now[0]=300
    b.reply='{"ready":true}'
    assert r.complete(REQUEST).provider==b.name
    assert a.calls==1 and b.calls==2

def test_recovered_route_only_tried_when_needed_after_cooldown():
    now=[0]
    a=Stub("gemini-free",ProviderFailure("gemini-free",503,"unavailable"))
    b=Stub("groq-free-backup",'{"ok":true}')
    r=AdaptiveFreeRouter(FreeProviderFallback(a,b),clock=lambda:now[0])
    assert r.complete(REQUEST).provider==b.name
    now[0]=61
    a.reply='{"ok":true}'
    assert r.complete(REQUEST).provider==b.name
    assert a.calls==1
    b.reply=ProviderFailure(b.name,503,"unavailable")
    assert r.complete(REQUEST).provider==a.name
    assert r.routing_snapshot()["provider_switches"]==1

def test_safety_and_programming_failure_not_masked_by_fallback():
    b=Stub("groq-free-backup",'{"ok":true}')
    for error in (ProviderFailure("gemini-free",403,"blocked",error_category="content_policy_violation"),
                  ProviderFailure("gemini-free",403,"unknown"),
                  RuntimeError("internal logic bug")):
        r=AdaptiveFreeRouter(FreeProviderFallback(Stub("gemini-free",error),b))
        with pytest.raises(RuntimeError):r.complete(REQUEST)
    assert b.calls==0

def test_partial_json_recovery_is_not_counted_as_complete():
    a=Stub("gemini-free",'{"candidates":[{"title":"a"}],')
    b=Stub("groq-free-backup",ProviderFailure("groq-free-backup",503,"unavailable"))
    r=AdaptiveFreeRouter(FreeProviderFallback(a,b),clock=lambda:0)
    assert r.complete(REQUEST).text==a.reply
    s=r.routing_snapshot()
    assert s["partial_responses_returned"]==1
    assert sum(x["complete_json_responses"] for x in s["providers"])==0

def test_transport_http_attempts_include_bounded_internal_retry_and_no_secret():
    calls=[]
    def requester(req,timeout):
        calls.append(req)
        if len(calls)==1:
            raise urllib.error.HTTPError(req.full_url,429,"rate",{"retry-after":"1","x-ratelimit-remaining-requests":"10"},None)
        return json.dumps({"choices":[{"message":{"content":'{"ok":true}'}}]}).encode()
    p=OpenAICompatibleProvider(endpoint="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b",name="groq-free-backup",api_key="SECRET",
        requester=requester,rate_limit_sleeper=lambda _:None,empty_retries=1)
    r=MeteredDiscoveryProvider(AdaptiveFreeRouter(FreeProviderFallback(p)))
    r.complete(REQUEST)
    s=r.snapshot()
    assert s["logical_requests"]==1 and s["routing"]["provider_attempts"]==1
    assert s["http_attempts_known"] and s["routing"]["http_attempts"]==2
    assert "SECRET" not in json.dumps(s)
