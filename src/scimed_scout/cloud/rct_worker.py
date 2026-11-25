"""Bounded RCT-only cloud workflow using existing verifier and durable audit."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
from scimed_scout.discovery.rct_first import collect,MIN_FAMILIES,MAX_DEEP,VERSION
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.discovery.models import DiscoveryRunResult
from scimed_scout.discovery.review_package import build_discovery_review_package
from scimed_scout.discovery.novelty import DiscoveryNoveltyService
from scimed_scout.discovery.scoring import DiscoveryScoringService
from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver
from scimed_scout.discovery.topic_memory import recent_topic_memory
from scimed_scout.ai.adaptive_router import AdaptiveFreeRouter
from scimed_scout.ai.providers import ProviderFailure
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.run_telemetry import MeteredDiscoveryProvider
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.sources import build_default_source_clients
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.ranking import RankingResult
from scimed_scout.domain import CandidateStatus
from .checkpoints import audit_snapshot,restore_audit

SEED="rct-first:seed:v1"
AUDIT="rct-first:audit:v1:"
BUDGET=18
PER_TOPIC=6

class BoundedProvider(MeteredDiscoveryProvider):
    def __init__(self,provider,*,limit=BUDGET,per_topic=PER_TOPIC):
        super().__init__(provider);self.limit=limit;self.per_topic=per_topic;self.start=0;self.deferred=0;self.reserved=0;self.topic=""
    def begin(self,topic):
        self.topic=topic;self.start=self.requests;self.reserved=0
    def available(self):
        routes=self.configured_free_route
        return self.requests<self.limit and self.requests-self.start<self.per_topic-self.reserved and bool(set(routes)-set(self.unavailable_free_providers))
    def complete(self,request):
        if not self.available():
            self.deferred+=1
            raise ProviderFailure("scimed-rct-budget",429,"AI assessment deferred: bounded budget or all free routes unavailable",error_category="route_deferred")
        return super().complete(request)
    def snapshot(self):
        return {**super().snapshot(),"logical_call_cap":self.limit,"per_topic_cap":self.per_topic,"budget_deferred_calls":self.deferred}

def _draft(c):
    info=c.metadata["rct_first"]
    return {"candidate_id":c.candidate_id,"title":c.title,"specialty":c.specialty,"question_type":c.question_type,
        "population":c.population,"intervention_exposure_index_test":c.intervention_exposure_index_test,
        "comparator_reference":c.comparator_reference,"outcomes":c.outcomes,"eligible_designs":c.eligible_designs,
        "qualification_status":"RCT_SEED_CUES_NOT_DEEP_VERIFIED","provisional_only":True,
        "evidence_first_link":info,"preflight_bibliographic_evidence":c.metadata.get("evidence_preflight"),
        "research_dossier":{"candidate_id":c.candidate_id,"title":c.title,"scientific_question":{"population":c.population,
        "intervention_exposure_index_test":c.intervention_exposure_index_test,"comparator_reference":c.comparator_reference,
        "outcomes":c.outcomes,"eligible_designs":c.eligible_designs},"qualification_label":"RCT_SEED_CUES_NOT_DEEP_VERIFIED",
        "rct_first":info,"eligible_independent_studies_confirmed":None,"independent_literature_confirmation_required":True,
        "next_actions":["Verify complete PICO, exact comparison arms, trial independence and extractable outcomes.",
        "Search published reviews and registrations; verify actual search cutoffs."]}}

def _candidate(row,job):
    fields=dict(row);fields["project_id"]=job.id;fields["status"]=CandidateStatus.DISCOVERED
    return CandidateRecord(**fields)

def process_rct_job(job,store,*,collector=collect,clients=None,router_factory=AdaptiveFreeRouter.from_env):
    check=lambda:store.ensure_active(job.id)
    check()
    history=store.recent_completed_jobs(client_token_hash=job.client_token_hash,revisit_days=job.revisit_days)
    prior=recent_topic_memory(history,revisit_days=job.revisit_days)
    seed=store.load_step(job.id,SEED)
    if seed:
        if seed.get("version")!=VERSION or seed.get("job_id")!=job.id:raise RuntimeError("RCT seed checkpoint scope mismatch")
        seed=seed["report"]
    else:
        store.update_job(job.id,stage="RCT_EVIDENCE_FIRST",progress=5,message="Searching actual randomized trial reports before proposing review questions")
        seed=collector(job.specialty,len(history),check=check,prior=prior)
        store.save_step(job.id,SEED,{"version":VERSION,"job_id":job.id,"report":seed})
    candidates=[_candidate(row,job) for row in seed.get("candidates",[])]
    drafts=[_draft(c) for c in candidates]
    store.update_job(job.id,stage="RCT_EVIDENCE_TRIAGE",progress=20,message=f"Found {len(candidates)} source-linked comparison question(s); selecting up to three for deep verification",
        result_json={"checkpoint":{"stage":"RCT_EVIDENCE_TRIAGE","verified":False,"candidates":drafts,"rct_first":seed}})
    try:provider=BoundedProvider(router_factory())
    except (RuntimeError,ValueError):provider=None
    clients=clients if clients is not None else build_default_source_clients()
    # Only one comparison per population/intervention cell at deep stage;
    # all others remain exported, not declared scientifically rejected.
    selected=[];seen=set()
    for c in candidates:
        info=c.metadata["rct_first"]
        if not info["shortlist_eligible"]:continue
        cell=tuple(info["pair"][:2])
        if cell in seen:continue
        seen.add(cell);selected.append(c)
        if len(selected)>=MAX_DEEP:break
    audits=[];ranked=[];checked=[];qualified=[]
    with TemporaryDirectory(prefix="scimed-rct-first-") as d:
        with SQLiteLedger(Path(d)/"rct.sqlite3") as ledger:
            ledger.upsert_project(ProjectRecord(job.id,job.specialty,"EFFECTIVENESS"))
            for c in candidates:ledger.upsert_candidate(c)
            for i,c in enumerate(selected,1):
                check()
                store.update_job(job.id,stage="RCT_DEEP_VERIFY",progress=20+int(65*i/max(1,len(selected))),message=f"Checking evidence-backed RCT topic {i}/{len(selected)}: {c.title}")
                rank=RankingResult(c.candidate_id,float(c.metadata["rct_first"]["family_leads"]),("Observed comparison-family lead count; not eligible trial count",));ranked.append(rank)
                previous=store.load_step(job.id,AUDIT+c.candidate_id)
                if previous:
                    result=restore_audit(ledger,previous,job.id,c.candidate_id)
                    # Retry restores source records and cached assessments rather
                    # than regenerating questions or repeating successful queries.
                    if result.candidate_status==CandidateStatus.QUALIFIED:checked.append(result);qualified.append(c.candidate_id);continue
                else:
                    for row in c.metadata["rct_first"]["comparison_records"]:
                        ledger.upsert_external_evidence(c.candidate_id,"PRIMARY_STUDY",row["source_record_id"],source=row["source"],title=row["title"],payload=row["payload"])
                if provider:provider.begin(c.candidate_id)
                novelty=DiscoveryNoveltyService(ledger,SemanticCompetitorAssessor(provider),max_reviews=12,max_registrations=8,batch_size=5,
                    search_date_resolver=OpenAccessSearchDateResolver(),max_fulltext_reviews=2,enrichment_client=EuropePMCSource(),max_enrichment_lookups=1) if provider else None
                scoring=DiscoveryScoringService(provider) if provider else None
                engine=ReviewDiscoveryOrchestrator(ledger,clients,novelty_service=novelty,scoring_service=scoring,
                    cancellation_check=check,require_pico_signals=True,optimize_literature_queries=True,adaptive_search=True,
                    adaptive_retrieval=True,strict_rct_minimum=MIN_FAMILIES)
                result=engine.verify_candidate(c.candidate_id,ranking_score=rank.score,limit_per_query=min(12,job.limit_per_query),recover_only=bool(previous))
                checked.append(result)
                if result.candidate_status==CandidateStatus.QUALIFIED:qualified.append(c.candidate_id)
                store.save_step(job.id,AUDIT+c.candidate_id,audit_snapshot(ledger,result))
            for item in checked:
                c=ledger.get_candidate(item.candidate_id);m=c.metadata or {};a=m.get("rct_first_final_audit") or {}
                audits.append({"candidate_id":c.candidate_id,"title":c.title,"status":item.candidate_status.value,"decision":item.decision,"pending":list(item.pending),
                    "source_statuses":{k:v.value for k,v in item.coverage.source_statuses.items()},"coverage_blockers":list(item.coverage.blockers),
                    "pico_design_family_leads":item.evidence.pico_audit.get("pico_design_family_leads"),
                    "rct_first_final_audit":a,"review_opportunity":m.get("discovery_review_opportunity") or {},
                    "competitor_audit":{"published_reviews_discovered":m.get("discovery_competitor_records_discovered",0),
                    "unassessed_reviews":m.get("discovery_unassessed_review_count",0),"unassessed_registrations":m.get("discovery_unassessed_registration_count",0)},
                    "scorecard":m.get("discovery_gate_inputs") or {}})
            desired=min(3,job.final_options)
            run=DiscoveryRunResult(job.id,ranked,checked,qualified[:desired],qualified,desired)
            package=build_discovery_review_package(ledger,run)
            ids={x.candidate_id for x in checked}
            package["unverified_generated_options"]=[_draft(c) for c in candidates if c.candidate_id not in ids]
            package["unverified_generated_options_are_not_qualified"]=True
            package["rct_first"]={"version":VERSION,"minimum_comparison_family_leads":MIN_FAMILIES,"seed_status":seed["status"],
                "seed_queries":seed["queries"],"cells":[{k:v for k,v in x.items() if k!="source_records"} for x in seed.get("cells",[])],
                "deep_limit":MAX_DEEP,"confirmed_independent_eligible_trials":None,"novelty_confirmed_by_seed":False}
            counts={}
            for x in checked:counts[x.candidate_status.value]=counts.get(x.candidate_status.value,0)+1
            return {"package":package,"run_summary":{"mode":VERSION,"requested_candidates":job.candidate_count,"generated_candidates":len(candidates),
                "verified_candidates":len(checked),"unverified_generated_candidates":len(candidates)-len(checked),"status_counts":counts,
                "qualified_candidate_ids":qualified,"desired_options":desired,"candidate_audits":audits,
                "ai_telemetry":provider.snapshot() if provider else {"logical_requests":0,"logical_call_cap":BUDGET,"provider_available":False},
                "generation_shortfall":0,"generation_warnings":["Evidence-first mode: no AI-generated topics; bounded source samples, not systematic review eligibility."],
                "rct_first":package["rct_first"],"topic_history":[{**{k:getattr(c,k) for k in ("candidate_id","title","specialty","question_type","population","intervention_exposure_index_test","comparator_reference","outcomes","eligible_designs")},"status":x.candidate_status.value,"checked_at":datetime.now(timezone.utc).isoformat()} for x in checked if (c:=ledger.get_candidate(x.candidate_id))],
                "generated_topic_history":[{k:getattr(c,k) for k in ("candidate_id","title","specialty","question_type","population","intervention_exposure_index_test","comparator_reference","outcomes","eligible_designs")} for c in candidates],
                "recent_topics_skipped":seed.get("skipped_recent",[]),"recent_topics_skipped_count":len(seed.get("skipped_recent",[]))}}
