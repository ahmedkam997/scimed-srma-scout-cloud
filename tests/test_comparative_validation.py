from scimed_scout.discovery.comparative_validation import summarize_arm, choose_deep, MeteredProvider, generate_arm, ARMS, TARGET
from scimed_scout.ai.models import AIResponse
import pytest


def test_missing_source_sample_is_not_negative_or_scientific_qualification():
    generation={"requested":4}
    audits=[{"sample_source_access_complete":True,"minimum_family_lead_signal":True,
             "pico_design_family_leads":5,"cluster_link":{"links":[]},"search_logs":[]},
            {"sample_source_access_complete":False,"minimum_family_lead_signal":None,
             "pico_design_family_leads":8,"cluster_link":{"links":[]},"search_logs":[]}]
    out=summarize_arm(generation,audits)
    assert out["signal_rate_among_complete_samples"]==1
    assert out["signal_yield_per_requested_proposal"]==.25
    assert out["unresolved_source_samples"]==1
    assert out["scientifically_qualified_topics"] is None
    assert out["confirmed_eligible_independent_studies"] is None
    assert out["sum_family_leads_not_independent_studies"]==5


def test_equal_selection_no_cluster_bonus():
    rows=[{"sample_source_access_complete":True,"pico_design_family_leads":2,
            "pico_design_report_leads":2,"candidate":{"title":"A"},"cluster_link":{"links":[1]}},
          {"sample_source_access_complete":True,"pico_design_family_leads":4,
            "pico_design_report_leads":4,"candidate":{"title":"B"},"cluster_link":{"links":[]}},
          {"sample_source_access_complete":False,"pico_design_family_leads":9,
            "pico_design_report_leads":9,"candidate":{"title":"C"}}]
    assert choose_deep(rows)["candidate"]["title"]=="B"


def test_fixed_budget_and_usage_accounting():
    class Stub:
        name="stub"
        model="fixed"
        def complete(self,request):
            return AIResponse("{}",self.name,self.model,{"usage":{"total_tokens":100}})
    p=MeteredProvider(Stub(),1)
    assert p.complete(None).model=="fixed"
    assert p.calls[0]["total_tokens"]==100
    with pytest.raises(RuntimeError,match="budget exhausted"):
        p.complete(None)
    assert p.attempts==1


def test_failed_generation_not_a_zero_quality_verdict():
    class Stub:
        name="stub"
        model="fixed"
        def complete(self,request):
            raise RuntimeError("provider unavailable")
    rows,audit=generate_arm(ARMS[0],Stub(),"shared",{})
    assert rows==[]
    assert audit["status"]=="GENERATION_FAILED"
    assert audit["logical_ai_requests"]==1
    assert audit["requested"]==TARGET


def test_fixed_probe_failover_before_comparison_only():
    from scimed_scout.discovery.comparative_validation import probe_fixed_provider
    from scimed_scout.ai.providers import FreeProviderFallback, ProviderFailure
    class Stub:
        api_key="test"
        def __init__(self,name,fail):
            self.name=name
            self.model=name+"-fixed"
            self.fail=fail
            self.calls=0
        def complete(self,request):
            self.calls+=1
            if self.fail:
                raise ProviderFailure(self.name,503,"unavailable")
            return AIResponse('{"ready":true}',self.name,self.model)
    a,b=Stub("first",True),Stub("second",False)
    selected,probes=probe_fixed_provider(FreeProviderFallback(a,b))
    assert selected is b
    assert [p["status"] for p in probes]==["UNAVAILABLE","HEALTHY"]
    assert a.calls==b.calls==1


def test_new_pair_excludes_prior_failed_fixed_provider():
    from scimed_scout.discovery.comparative_validation import probe_fixed_provider
    from scimed_scout.ai.providers import FreeProviderFallback
    class Stub:
        api_key="test"
        def __init__(self,name):
            self.name=name
            self.model=name+"-fixed"
            self.calls=0
        def complete(self,request):
            self.calls+=1
            return AIResponse('{"ready":true}',self.name,self.model)
    previous,alternate=Stub("gemini-free"),Stub("groq-free-backup")
    selected,probes=probe_fixed_provider(FreeProviderFallback(previous,alternate),excluded_provider="gemini-free")
    assert selected is alternate
    assert previous.calls==0 and alternate.calls==1
    selected,probes=probe_fixed_provider(FreeProviderFallback(previous),excluded_provider="gemini-free")
    assert selected is None and probes==[]
