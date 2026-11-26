"""Bounded RCT-only cloud workflow using existing verifier and durable audit."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
from scimed_scout.discovery.rct_first import collect,MIN_FAMILIES,MAX_DEEP,VERSION
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.discovery.opportunity_mcda import profile,compare_assessments,PROMPT
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
SELECTION="rct-first:selection:v1"
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

class ReservedScoring(DiscoveryScoringService):
    def score(self,*args,**kwargs):
        self.provider.reserved=0
        return super().score(*args,**kwargs)

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
        "rct_first":info,"opportunity_mcda":c.metadata.get("opportunity_mcda"),"eligible_independent_studies_confirmed":None,"independent_literature_confirmation_required":True,
        "next_actions":["Verify complete PICO, exact comparison arms, trial independence and extractable outcomes.",
        "Search published reviews and registrations; verify actual search cutoffs."]}}

def _candidate(row,job):
    fields=dict(row);fields["project_id"]=job.id;fields["status"]=CandidateStatus.DISCOVERED
    return CandidateRecord(**fields)

def recovery_reasons(result,metadata):
    """Machine-actionable recovery only; independent human adjudication is separate."""
    if result.candidate_status not in (CandidateStatus.PROVISIONAL_BACKUP,CandidateStatus.DEEP_VERIFYING):
        return []
    if not result.coverage.complete:
        return ["MANDATORY_SOURCE_COVERAGE"]
    strict=metadata.get("rct_first_final_audit") or {}
    if strict.get("family_leads",0)<MIN_FAMILIES or result.evidence.pico_audit.get("pico_design_family_leads",0)<MIN_FAMILIES:
        # Disagreement is actionable, not scientific exclusion. Avoid endless
        # retries: one bounded recovery pass after the initial adaptive audit.
        if strict.get("family_leads",0)>=MIN_FAMILIES and not metadata.get("v2_disagreement_recovery_attempted"):
            return ["PICO_COMPARISON_DISAGREEMENT"]
        return []
    reasons=[]
    if any("competing published reviews are not fully assessed" in p or "competing review registrations are not fully assessed" in p or "limited competitor assessment scope" in p for p in result.pending):
        reasons.append("COMPETITOR_BACKLOG")
    if not metadata.get("discovery_gate_inputs") or metadata.get("discovery_scoring_deferred"):
        reasons.append("SCORING_UNFINISHED")
    return reasons

def process_rct_job(job,store,*,collector=collect,clients=None,router_factory=AdaptiveFreeRouter.from_env):
    import time
    from .supabase import SupabaseJobStore
    last_heartbeat=[time.monotonic()]
    def check():
        store.ensure_active(job.id)
        now=time.monotonic()
        if isinstance(store,SupabaseJobStore) and now-last_heartbeat[0]>=30:
            store.update_job(job.id)
            last_heartbeat[0]=now
    check()
    history=store.recent_completed_jobs(client_token_hash=job.client_token_hash,revisit_days=job.revisit_days)
    prior=recent_topic_memory(history,revisit_days=job.revisit_days)
    seed=store.load_step(job.id,SEED)
    reused_seed=bool(seed)
    if seed:
        if seed.get("version")!=VERSION or seed.get("job_id")!=job.id:raise RuntimeError("RCT seed checkpoint scope mismatch")
        seed=seed["report"]
    else:
        store.update_job(job.id,stage="RCT_EVIDENCE_FIRST",progress=5,message="Searching actual randomized trial reports before proposing review questions")
        seed=collector(job.specialty,len(history),check=check,prior=prior)
        store.save_step(job.id,SEED,{"version":VERSION,"job_id":job.id,"report":seed})
    candidates=[_candidate(row,job) for row in seed.get("candidates",[])]
    for c in candidates:
        c.metadata["opportunity_mcda"]=profile(c)
    candidates.sort(key=lambda c:(tuple(-x for x in c.metadata["opportunity_mcda"]["priority_key"]),c.candidate_id))
    drafts=[_draft(c) for c in candidates]
    if reused_seed:
        # Keep the last completed cloud report intact until a replacement is
        # successfully built. Evidence snapshots are worker-only.
        store.update_job(job.id,stage="RCT_EVIDENCE_TRIAGE",progress=20,message="Reusing saved evidence and candidate plan; checking unresolved work only")
    else:
        store.update_job(job.id,stage="RCT_EVIDENCE_TRIAGE",progress=20,message=f"Found {len(candidates)} source-linked comparison question(s); selecting up to three for deep verification",
            result_json={"checkpoint":{"stage":"RCT_EVIDENCE_TRIAGE","verified":False,"candidates":drafts,"rct_first":seed}})
    from scimed_scout.discovery.scientific_verification_v2 import TrustedDirectory
    try:trusted_verifier=TrustedDirectory.from_env()
    except (OSError,ValueError,TypeError):trusted_verifier=None
    try:provider=BoundedProvider(router_factory())
    except (RuntimeError,ValueError):provider=None
    clients=clients if clients is not None else build_default_source_clients()
    # Only one comparison per population/intervention cell at deep stage;
    # all others remain exported, not declared scientifically rejected.
    selected=[];seen=set()
    for c in candidates:
        info=c.metadata["rct_first"]
        if not info.get("shortlist_eligible") or info.get("family_leads",0)<MIN_FAMILIES:continue
        cell=tuple(info["pair"][:2])
        if cell in seen:continue
        seen.add(cell);selected.append(c)
        if len(selected)>=MAX_DEEP:break
    saved_selection=store.load_step(job.id,SELECTION)
    if saved_selection:
        ids=saved_selection.get("candidate_ids")
        by_id={c.candidate_id:c for c in candidates}
        if saved_selection.get("job_id")!=job.id or saved_selection.get("version")!=1 or not isinstance(ids,list) or len(ids)>MAX_DEEP or len(set(ids))!=len(ids) or any(i not in by_id for i in ids):
            raise ValueError("Invalid saved RCT selection scope")
        selected=[by_id[i] for i in ids]
    else:
        store.save_step(job.id,SELECTION,{"version":1,"job_id":job.id,"candidate_ids":[c.candidate_id for c in selected]})
    audits=[];ranked=[];checked=[];qualified=[];restored_count=0;recovery_count=0;reused_without_recheck=0
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
                    restored_count+=1
                    restored=ledger.get_candidate(c.candidate_id)
                    if trusted_verifier is None and result.candidate_status!=CandidateStatus.QUALIFIED and not recovery_reasons(result,restored.metadata or {}):
                        checked.append(result);reused_without_recheck+=1;continue
                    recovery_count+=1
                    # Retry restores source records and cached assessments rather
                    # than regenerating questions or repeating successful queries.
                    # A legacy discovery-only QUALIFIED label cannot establish seven independent eligible trials.
                else:
                    for row in c.metadata["rct_first"]["comparison_records"]:
                        ledger.upsert_external_evidence(c.candidate_id,"PRIMARY_STUDY",row["source_record_id"],source=row["source"],title=row["title"],payload=row["payload"])
                    from scimed_scout.sources.base import SearchRecord
                    from scimed_scout.discovery.evidence_classification import classify_review_search_hit
                    for row in (c.metadata["rct_first"].get("competing_review_preflight") or {}).get("records",[]):
                        cue=classify_review_search_hit(SearchRecord(row["source"],row["source_record_id"],row["title"],metadata=row["payload"].get("metadata") or {}))
                        if cue=="CONFIRMED_REVIEW_CUE":
                            ledger.upsert_external_evidence(c.candidate_id,"PUBLISHED_REVIEW",row["source_record_id"],source=row["source"],title=row["title"],payload=row["payload"])
                if provider:
                    provider.begin(c.candidate_id)
                    provider.reserved=1
                novelty=DiscoveryNoveltyService(ledger,SemanticCompetitorAssessor(provider) if provider else None,max_reviews=12,max_registrations=8,batch_size=5,
                    search_date_resolver=OpenAccessSearchDateResolver(),max_fulltext_reviews=2,enrichment_client=EuropePMCSource(),max_enrichment_lookups=1,bounded_recovery=True)
                scoring=ReservedScoring(provider) if provider else None
                engine=ReviewDiscoveryOrchestrator(ledger,clients,novelty_service=novelty,scoring_service=scoring,
                    cancellation_check=check,progress_callback=lambda pct,stage,msg:store.update_job(job.id,message=f"Topic {i}/{len(selected)}: {msg}") if pct==-1 else None,require_pico_signals=True,optimize_literature_queries=True,adaptive_search=True,
                    adaptive_retrieval=True,strict_rct_minimum=MIN_FAMILIES,scientific_verifier=trusted_verifier)
                result=engine.verify_candidate(c.candidate_id,ranking_score=rank.score,limit_per_query=min(12,job.limit_per_query),recover_only=bool(previous))
                assessed=ledger.get_candidate(c.candidate_id)
                if previous and "PICO_COMPARISON_DISAGREEMENT" in recovery_reasons(result,assessed.metadata or {}):
                    assessed.metadata["v2_disagreement_recovery_attempted"]=True
                assessed.metadata["opportunity_mcda"]=profile(assessed,ledger.list_external_evidence(c.candidate_id,"PUBLISHED_REVIEW"),opportunity=assessed.metadata.get("discovery_review_opportunity"),scorecard=assessed.metadata.get("discovery_gate_inputs"),primary_records=ledger.list_external_evidence(c.candidate_id,"PRIMARY_STUDY"))
                ledger.upsert_candidate(assessed)
                checked.append(result)
                if result.candidate_status==CandidateStatus.QUALIFIED:qualified.append(c.candidate_id)
                store.save_step(job.id,AUDIT+c.candidate_id,audit_snapshot(ledger,result))
            for item in checked:
                c=ledger.get_candidate(item.candidate_id);m=c.metadata or {};a=m.get("rct_first_final_audit") or {}
                audits.append({"candidate_id":c.candidate_id,"title":c.title,"status":item.candidate_status.value,"decision":item.decision,"pending":list(item.pending),
                    "source_statuses":{k:v.value for k,v in item.coverage.source_statuses.items()},"coverage_blockers":list(item.coverage.blockers),
                    "pico_design_family_leads":item.evidence.pico_audit.get("pico_design_family_leads"),
                    "rct_first_final_audit":a,"review_opportunity":m.get("discovery_review_opportunity") or {},
                    "adaptive_retrieval_audit":m.get("adaptive_retrieval_audit") or [],"adaptive_search_audit":m.get("adaptive_search_audit") or {},"fulltext_search_date_resolutions":m.get("discovery_fulltext_search_date_resolutions") or [],
                    "competitor_audit":{"published_reviews_discovered":m.get("discovery_competitor_records_discovered",0),
                    "unassessed_reviews":m.get("discovery_unassessed_review_count"),"unassessed_registrations":m.get("discovery_unassessed_registration_count"),"total_pending_reviews":m.get("discovery_pending_review_count"),"total_pending_registrations":m.get("discovery_pending_registration_count")},
                    "scientific_verification_v2":m.get("scientific_verification_v2") or {},
                    "scorecard":m.get("discovery_gate_inputs") or {},"scoring_deferred_reason":m.get("discovery_scoring_deferred_reason",""),"registry_result_reference_audit":m.get("registry_result_reference_audit") or {},"registration_enrichment_audit":m.get("registration_enrichment_audit") or {},"opportunity_mcda":m.get("opportunity_mcda") or {}})
            recovery_queue=[{"candidate_id":x.candidate_id,"reasons":recovery_reasons(x,ledger.get_candidate(x.candidate_id).metadata or {})} for x in checked]
            recovery_queue=[x for x in recovery_queue if x["reasons"]]
            desired=min(3,job.final_options)
            run=DiscoveryRunResult(job.id,ranked,checked,qualified[:desired],qualified,desired)
            package=build_discovery_review_package(ledger,run)
            package["topic_review_prompt"] += "\n\n"+PROMPT
            package["review_instructions"]="RCT evidence-first discovery shortlist: no automatically confirmed independent trials. Assess the dossiers independently before registration.\n"+PROMPT
            package["weighted_assessment_comparison"]=compare_assessments([(c.candidate_id,(ledger.get_candidate(c.candidate_id).metadata or {})["opportunity_mcda"]["assessment"]) for c in candidates])
            ids={x.candidate_id for x in checked}
            package["unverified_generated_options"]=[_draft(c) for c in candidates if c.candidate_id not in ids]
            package["unverified_generated_options_are_not_qualified"]=True
            package["rct_first"]={"version":VERSION,"minimum_comparison_family_leads":MIN_FAMILIES,"seed_status":seed["status"],
                "seed_queries":seed["queries"],"stratified_seed_recovery":seed.get("stratified_seed_recovery",{}),"citation_recovery":seed.get("citation_recovery",{}),"dynamic_discovery":seed.get("dynamic_discovery",{}),"comparison_recovery":seed.get("comparison_recovery",[]),"review_comparison_recovery":seed.get("review_comparison_recovery",[]),"review_title_recovery":seed.get("review_title_recovery",[]),"cells":[{k:v for k,v in x.items() if k!="source_records"} for x in seed.get("cells",[])],
                "deep_limit":MAX_DEEP,"confirmed_independent_eligible_trials":None,"novelty_confirmed_by_seed":False,
                "scope_note":"Unsupported specialties return explicit diagnostic instead of switching to mixed-design AI generation. Bounded samples do not establish absence.",
                "selected_for_deep_verification":len(selected),"source_linked_candidates":len(candidates)}
            counts={}
            for x in checked:counts[x.candidate_status.value]=counts.get(x.candidate_status.value,0)+1
            return {"package":package,"run_summary":{"mode":VERSION,"requested_candidates":job.candidate_count,"generated_candidates":len(candidates),
                "resume_eligible":bool(recovery_queue),"resume_queue":recovery_queue,"resume_audit":{"reused_seed":reused_seed,"restored_candidate_audits":restored_count,"rechecked_candidates":recovery_count,"reused_without_recheck":reused_without_recheck},
                "verified_candidates":len(checked),"unverified_generated_candidates":len(candidates)-len(checked),"status_counts":counts,
                "qualified_candidate_ids":qualified,"desired_options":desired,"candidate_audits":audits,
                "ai_telemetry":provider.snapshot() if provider else {"logical_requests":0,"logical_call_cap":BUDGET,"provider_available":False},
                "generation_shortfall":max(0,job.candidate_count-len(candidates)),"generation_warnings":["Evidence-first mode: no AI-generated topics; bounded source samples, not systematic review eligibility."],
                "rct_first":package["rct_first"],"weighted_assessment_comparison":package["weighted_assessment_comparison"],"topic_history":[{**{k:getattr(c,k) for k in ("candidate_id","title","specialty","question_type","population","intervention_exposure_index_test","comparator_reference","outcomes","eligible_designs")},"status":x.candidate_status.value,"checked_at":datetime.now(timezone.utc).isoformat()} for x in checked if (c:=ledger.get_candidate(x.candidate_id))],
                "generated_topic_history":[{k:getattr(c,k) for k in ("candidate_id","title","specialty","question_type","population","intervention_exposure_index_test","comparator_reference","outcomes","eligible_designs")} for c in candidates],
                "recent_topics_skipped":seed.get("skipped_recent",[]),"recent_topics_skipped_count":len(seed.get("skipped_recent",[]))}}
