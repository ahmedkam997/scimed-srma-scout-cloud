"""Paired, bounded live ablation of the evidence-first discovery strategy.

Same frozen seed context, fixed model, proposal budget, common evaluation
code and source limits. Pilot only: no independent gold-standard labels.
Separate from production jobs; no Supabase mutations.
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from scimed_scout.ai.discovery import SYSTEM_PROMPT, build_discovery_prompt, parse_candidate_proposals, _recover_complete_candidate_proposals
from scimed_scout.ai.models import AIRequest
from scimed_scout.ai.providers import FreeProviderFallback
from scimed_scout.diagnostics import classify_failure, comparison_diagnostic
from scimed_scout.cloud.worker import _within_specialty
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.domain import SourceStatus
from scimed_scout.sources import build_default_source_clients
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.queries import build_search_plan
from .constants import MIN_DISCOVERY_STUDIES
from .evidence_seed import recent_pubmed_cues, recent_review_gap_cues, cue_prompt, review_gap_prompt
from .evidence_first import collect_evidence_map, evidence_map_prompt, link_candidate
from .pico_matching import assess_pico
from .evidence_classification import classify_review_search_hit
from .topic_diversity import same_clinical_question, same_discovery_family
from .novelty import DiscoveryNoveltyService
from .open_access_dates import OpenAccessSearchDateResolver
from .scoring import DiscoveryScoringService
from .orchestrator import ReviewDiscoveryOrchestrator

VERSION = "PAIRED_DISCOVERY_PILOT_V1"
TARGET = 4
LIMIT = 12
DEEP_LIMIT = 12
DEEP_AI_BUDGET = 8
ARMS = ("A_title_seed_baseline", "B_evidence_first")


def fixed_providers(config):
    """Yield fixed configured free routes; never use dynamic model routing."""
    queue = [config]
    while queue:
        item = queue.pop(0)
        if item is None:
            continue
        if isinstance(item, FreeProviderFallback):
            queue[0:0] = [item.primary, item.backup]
            continue
        if getattr(item, "model", "") != "openrouter/free" and getattr(item, "api_key", ""):
            yield item


def choose_fixed_provider(config):
    return next(fixed_providers(config), None)


def probe_fixed_provider(config, *, excluded_provider=""):
    """Select a healthy route BEFORE both arms; never switch mid-experiment."""
    probes = []
    for item in [p for p in fixed_providers(config) if p.name != excluded_provider][:3]:
        meter = MeteredProvider(item, 1)
        try:
            response = meter.complete(AIRequest(system='Return only JSON.',
                prompt='Return {"ready":true}', temperature=0.0, max_tokens=512))
            payload = json.loads(response.text)
            if not isinstance(payload, dict) or payload.get("ready") is not True:
                raise ValueError("unexpected probe response")
            probes.append({"provider":item.name,"model":response.model,"status":"HEALTHY",
                           "calls":meter.calls})
            return item, probes
        except Exception as exc:
            code=getattr(exc,"status_code",None)
            probes.append({"provider":item.name,"model":item.model,"status":"UNAVAILABLE",
                           "http_status":code,"error_type":type(exc).__name__,
                           "diagnosis":classify_failure(code),"calls":meter.calls})
    return None, probes


class MeteredProvider:
    def __init__(self, provider, budget):
        self.provider = provider
        self.name = provider.name
        self.model = provider.model
        self.budget = budget
        self.calls = []
        self.attempts = 0

    def complete(self, request):
        if self.attempts >= self.budget:
            raise RuntimeError("Prespecified pilot AI request budget exhausted")
        self.attempts += 1
        started = time.monotonic()
        try:
            response = self.provider.complete(request)
            usage = response.raw.get("usage") or {}
            self.calls.append({"provider":response.provider,"model":response.model,
                "seconds":round(time.monotonic()-started,3),
                "prompt_tokens":usage.get("prompt_tokens"),"completion_tokens":usage.get("completion_tokens"),
                "total_tokens":usage.get("total_tokens"),"status":"SUCCESS"})
            return response
        except Exception as exc:
            self.calls.append({"status":"FAILED","error_type":type(exc).__name__,
                "http_status":getattr(exc,"status_code",None),"seconds":round(time.monotonic()-started,3)})
            raise


def _serialize_candidate(proposal, arm, index):
    return CandidateRecord(candidate_id=f"{arm}-{index}",project_id=arm,
        title=proposal.title,specialty="Cardiology",question_type=proposal.question_type,
        review_question=proposal.review_question,population=proposal.population,
        intervention_exposure_index_test=proposal.intervention_exposure_index_test,
        comparator_reference=proposal.comparator_reference,outcomes=proposal.outcomes,
        eligible_designs=proposal.eligible_designs,rationale=proposal.rationale,
        novelty_hypothesis=proposal.novelty_hypothesis,search_terms=proposal.search_terms)


def generate_arm(arm, provider, common_context, evidence_map):
    meter=MeteredProvider(provider,1)
    context=common_context
    if arm==ARMS[1]:
        context=evidence_map_prompt(evidence_map)+"\n"+context
    prompt=build_discovery_prompt(specialty="Cardiology",count=TARGET,additional_context=context)
    audit={"requested":TARGET,"returned_proposals":0,"accepted":0,"duplicate_proposals":0,
           "off_scope_or_incomplete":0,"status":"NOT_RUN","calls":[]}
    kept=[]
    try:
        response=meter.complete(AIRequest(system=SYSTEM_PROMPT,prompt=prompt,temperature=0.0,max_tokens=3200))
        try:
            proposals=parse_candidate_proposals(response.text)
        except (ValueError,json.JSONDecodeError):
            proposals=_recover_complete_candidate_proposals(response.text)
            audit["partial_json_recovery"]=True
        audit["returned_proposals"]=len(proposals)
        for index, proposal in enumerate(proposals[:TARGET]):
            candidate=_serialize_candidate(proposal,arm,index)
            if not (_within_specialty(candidate,"Cardiology") and candidate.population and
                    candidate.intervention_exposure_index_test and candidate.eligible_designs):
                audit["off_scope_or_incomplete"]+=1
                continue
            if any(same_clinical_question(candidate,c) or same_discovery_family(candidate,c) for c in kept):
                audit["duplicate_proposals"]+=1
                continue
            kept.append(candidate)
        audit["status"]="COMPLETE" if len(kept)==TARGET else "SHORTFALL"
    except Exception as exc:
        audit["status"]="GENERATION_FAILED"
        audit["error_type"]=type(exc).__name__
    audit["accepted"]=len(kept)
    audit["calls"]=meter.calls
    audit["logical_ai_requests"]=meter.attempts
    return kept,audit


def _record(item):
    return {"source":item.source,"source_record_id":item.record_id,"title":item.title,
            "payload":{"year":item.year,"doi":item.doi,"url":item.url,"metadata":item.metadata}}


def audit_candidate(candidate, clients, cache, evidence_map):
    """Same query planner and cap for both arms; no seed records injected."""
    started=time.monotonic()
    plan=build_search_plan(candidate,max_queries=1)
    primary=[]
    reviews=[]
    logs=[]
    for purpose, queries in (("PRIMARY",plan.primary_queries),("REVIEW",plan.review_queries)):
        for client in clients:
            for query in queries:
                key=(client.name,query,LIMIT)
                cached=key in cache
                if not cached:
                    try:
                        cache[key]=client.search(query,limit=LIMIT)
                    except Exception:
                        from scimed_scout.sources.base import SearchResult
                        cache[key]=SearchResult(client.name,query,SourceStatus.ACCESS_FAILED)
                result=cache[key]
                logs.append({"source":client.name,"query":query,"purpose":purpose,
                             "status":result.status.value,"retrieved":len(result.records),
                             "total_count":result.total_count,"cache_hit":cached})
                if purpose=="PRIMARY":
                    primary.extend(_record(r) for r in result.records
                        if classify_review_search_hit(r)!="CONFIRMED_REVIEW_CUE")
                else:
                    reviews.extend(_record(r) for r in result.records
                        if classify_review_search_hit(r)=="CONFIRMED_REVIEW_CUE")
    pico,_=assess_pico(candidate,primary)
    from .pico_matching import _groups
    # The anchor-link endpoint is intentionally secondary: it favors the
    # treatment by construction. Primary endpoint uses fresh common queries.
    link=link_candidate(candidate,evidence_map)
    source_complete=(len(logs)==4 and all(x["status"] in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE")
                            for x in logs))
    return {"candidate":asdict(candidate),"cluster_link":link,"search_logs":logs,
            "sample_source_access_complete":source_complete,
            "pico_design_report_leads":pico["pico_design_report_leads"],
            "pico_design_family_leads":pico["pico_design_family_leads"],
            "minimum_family_lead_signal":pico["pico_design_family_leads"]>=MIN_DISCOVERY_STUDIES if source_complete else None,
            "distinct_sampled_review_cues":len(_groups(reviews)),
            "pico_audit":pico,"seconds":round(time.monotonic()-started,3),
            "eligible_independent_studies":None,"novelty_confirmed":False}


def summarize_arm(generation, audits):
    complete=[a for a in audits if a["sample_source_access_complete"]]
    positive=sum(a["minimum_family_lead_signal"] is True for a in complete)
    return {"generation":generation,"audited_candidates":len(audits),"complete_source_samples":len(complete),
        "candidates_with_minimum_family_signal":positive,
        "signal_rate_among_complete_samples":positive/len(complete) if complete else None,
        "signal_yield_per_requested_proposal":positive/generation["requested"],
        "unresolved_source_samples":len(audits)-len(complete),
        "cluster_anchored_candidates":sum(bool(a["cluster_link"]["links"]) for a in audits),
        "sum_family_leads_not_independent_studies":sum(a["pico_design_family_leads"] for a in complete),
        "unique_live_source_calls":sum(not l["cache_hit"] for a in audits for l in a["search_logs"]),
        "scientifically_qualified_topics":None,"confirmed_eligible_independent_studies":None}


def choose_deep(audits):
    candidates=[a for a in audits if a["sample_source_access_complete"]]
    if not candidates:
        return None
    # Identical selection rule in both arms; no cluster bonus or model grade.
    return sorted(candidates,key=lambda x:(-x["pico_design_family_leads"],
        -x["pico_design_report_leads"],x["candidate"]["title"].casefold()))[0]


def deep_audit(arm, selected, provider):
    if selected is None:
        return {"status":"NOT_RUN_NO_COMPLETE_SAMPLE","qualified":None}
    meter=MeteredProvider(provider,DEEP_AI_BUDGET)
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteLedger(Path(directory)/"pilot.sqlite3") as ledger:
                ledger.upsert_project(ProjectRecord(arm,"Cardiology",question_type="ALL"))
                raw=selected["candidate"]
                # Preserve generated PICO, not any unrelated saved decisions.
                candidate=CandidateRecord(**raw)
                ledger.upsert_candidate(candidate)
                novelty=DiscoveryNoveltyService(ledger,SemanticCompetitorAssessor(meter),
                    search_date_resolver=OpenAccessSearchDateResolver(),max_reviews=18,max_registrations=12,
                    max_fulltext_reviews=3,batch_size=3)
                scoring=DiscoveryScoringService(meter)
                engine=ReviewDiscoveryOrchestrator(ledger,build_default_source_clients(),
                    novelty_service=novelty,scoring_service=scoring,require_pico_signals=True)
                result=engine.verify_candidate(candidate.candidate_id,limit_per_query=DEEP_LIMIT)
                saved=ledger.get_candidate(candidate.candidate_id)
                return {"status":"COMPLETED","title":candidate.title,"decision":result.decision,
                        "candidate_status":result.candidate_status.value,"qualified":result.candidate_status.value=="QUALIFIED",
                        "pending":result.pending,"source_statuses":{k:v.value for k,v in result.coverage.source_statuses.items()},
                        "pico_design_family_leads":result.evidence.pico_audit.get("pico_design_family_leads"),
                        "review_opportunity":(saved.metadata or {}).get("discovery_review_opportunity",{}),
                        "ai_budget":DEEP_AI_BUDGET,"logical_ai_requests":meter.attempts,"calls":meter.calls,
                        "seconds":round(time.monotonic()-started,3),"confirmed_independent_eligible_studies":None}
    except Exception as exc:
        return {"status":"FAILED","error_type":type(exc).__name__,"qualified":None,
                "logical_ai_requests":meter.attempts,"calls":meter.calls,
                "seconds":round(time.monotonic()-started,3)}


def _write(path, report):
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    temp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--rotation",type=int,default=0)
    parser.add_argument("--deep",action="store_true")
    parser.add_argument("--seed-report",type=Path)
    parser.add_argument("--avoid-previous-provider",action="store_true")
    args=parser.parse_args()
    start=time.monotonic()
    order=list(ARMS)
    random.Random(20261125+args.rotation).shuffle(order)
    report={"version":VERSION,"started_at":datetime.now(timezone.utc).isoformat(),
            "rotation":args.rotation,"order":order,"target_per_arm":TARGET,"sample_limit":LIMIT,
            "deep_limit":DEEP_LIMIT,"deep_ai_budget_per_arm":DEEP_AI_BUDGET,
            "status":"STARTED","arms":{},"clinical_accuracy_validated":False,
            "limitations":["Single paired pilot, no independent reference judgments or confidence interval.",
                "Same current verification engine, not a historical binary comparison.",
                "Common queries are bounded samples, not exhaustive searches.",
                "Cluster anchor linkage favors intervention by construction and is secondary.",
                "No full-text inclusion, extractability or publication-probability validation.",
                "Model token usage is provider-reported; logical requests exclude internal bounded HTTP retries."]}
    _write(args.output,report)
    try:
        excluded_provider=""
        if args.avoid_previous_provider:
            # A short probe passed last time, but full requests failed.
            # Require an independent fixed route for this new paired trial.
            if not args.seed_report or not args.seed_report.is_file() or args.seed_report.stat().st_size>2_000_000:
                raise RuntimeError("Previous paired report unavailable")
            previous=json.loads(args.seed_report.read_text(encoding="utf-8"))
            if previous.get("version")!=VERSION or previous.get("status")!="PILOT_INCONCLUSIVE":
                raise RuntimeError("Previous paired report is not inconclusive")
            excluded_provider=previous.get("configured_provider") or ""
            if excluded_provider not in ("gemini-free","groq-free-backup","openrouter-free"):
                raise RuntimeError("Previous fixed provider not identifiable")
        report["excluded_previous_provider"]=excluded_provider or None
        provider, probes=probe_fixed_provider(FreeProviderFallback.from_env(),excluded_provider=excluded_provider)
        report["provider_probes"]=probes
        if provider is None:
            raise RuntimeError("No healthy fixed free model")
    except Exception as exc:
        report.update(status="FIXED_MODEL_UNAVAILABLE",error_type=type(exc).__name__)
        _write(args.output,report)
        print(json.dumps({"status":report["status"]}))
        return 1
    report["configured_provider"]=provider.name
    report["configured_model"]=provider.model
    prior = None
    if args.seed_report and args.seed_report.is_file():
        try:
            if args.seed_report.stat().st_size > 2_000_000:
                raise ValueError("Oversized seed report")
            old=json.loads(args.seed_report.read_text(encoding="utf-8"))
            frozen=old["frozen_seed"]
            if old["version"]!=VERSION or old["rotation"]!=args.rotation or not isinstance(frozen["pubmed_cues"],list) or not isinstance(frozen["review_gap_cues"],list) or not isinstance(frozen["evidence_map"],dict):
                raise ValueError("Seed report scope mismatch")
            if frozen["evidence_map"].get("specialty")!="Cardiology" or frozen["evidence_map"].get("question_type")!="ALL":
                raise ValueError("Seed report question scope mismatch")
            prior=frozen
        except (ValueError,KeyError,TypeError,OSError):
            report["seed_reuse_warning"]="Invalid prior seed snapshot; collect fresh bounded sample"
    if prior:
        seed=prior["pubmed_cues"]
        gaps=prior["review_gap_cues"]
        evidence=prior["evidence_map"]
        report["seed_origin"]="REUSED_FROZEN_SNAPSHOT"
    else:
        seed=[]
        gaps=[]
        for i in (args.rotation,args.rotation+3,args.rotation+6):
            seed.extend(recent_pubmed_cues("Cardiology","ALL",max_records=6,rotation_index=i))
            gaps.extend(recent_review_gap_cues("Cardiology","ALL",max_records=2,rotation_index=i))
        seed=list({str(x.get("pmid") or x.get("title")):x for x in seed}.values())
        gaps=list({str(x.get("pmid") or x.get("title")):x for x in gaps}.values())
        evidence=collect_evidence_map("Cardiology","ALL",rotation_index=args.rotation)
        report["seed_origin"]="FRESH_BOUNDED_SAMPLE"
    common=(cue_prompt(seed)+"\n"+review_gap_prompt(gaps)).strip()
    report["frozen_seed"]={"pubmed_cues":seed,"review_gap_cues":gaps,"evidence_map":evidence}
    report["status"]="SEEDS_SAVED"
    _write(args.output,report)
    print(json.dumps({"status":"SEEDS_SAVED","clusters":len(evidence.get("clusters",[]))}),flush=True)
    clients=[PubMedSource(),EuropePMCSource()]
    cache={}
    generated={}
    for arm in order:
        candidates,audit=generate_arm(arm,provider,common,evidence)
        generated[arm]=candidates
        report["arms"][arm]={"generation":audit,"audits":[]}
        _write(args.output,report)
    # Interleave arms to mitigate time/order effects and share exact-query
    # cache. No cross-arm learning or generated-context carryover.
    for i in range(TARGET):
        for arm in order:
            if i>=len(generated[arm]):
                continue
            item=audit_candidate(generated[arm][i],clients,cache,evidence)
            report["arms"][arm]["audits"].append(item)
            _write(args.output,report)
    for arm in ARMS:
        entry=report["arms"][arm]
        entry["summary"]=summarize_arm(entry["generation"],entry["audits"])
    models={(c.get("provider"),c.get("model")) for arm in ARMS
            for c in report["arms"][arm]["generation"]["calls"] if c.get("status")=="SUCCESS"}
    comparable=(len(models)==1 and all(report["arms"][arm]["generation"]["status"]=="COMPLETE" for arm in ARMS)
                and all(report["arms"][arm]["summary"]["complete_source_samples"]==TARGET for arm in ARMS)
                and evidence.get("status")=="SAMPLED" and bool(evidence.get("clusters")) and bool(seed))
    report["strict_generation_comparability"]=comparable
    a,b=(report["arms"][arm]["summary"] for arm in ARMS)
    report["descriptive_difference_yield_per_requested_proposal"]=round(
        b["signal_yield_per_requested_proposal"]-a["signal_yield_per_requested_proposal"],4) if comparable else None
    report["status"]="GENERATION_AND_PREFLIGHT_COMPLETE"
    _write(args.output,report)
    print(json.dumps({"status":report["status"],"comparable":comparable,
        "arms":{arm:report["arms"][arm]["summary"] for arm in ARMS}},default=str),flush=True)
    if args.deep:
        if comparable:
            for arm in reversed(order):
                entry=report["arms"][arm]
                entry["deep_audit"]=deep_audit(arm,choose_deep(entry["audits"]),provider)
                _write(args.output,report)
                deep=entry["deep_audit"]
                print(json.dumps({"arm":arm,"deep_status":deep["status"],"qualified":deep.get("qualified"),
                                  "logical_ai_requests":deep.get("logical_ai_requests")}),flush=True)
        else:
            for arm in ARMS:
                report["arms"][arm]["deep_audit"]={"status":"NOT_RUN_INCOMPARABLE_PILOT","qualified":None}
    report["status"]="PILOT_FINISHED" if comparable else "PILOT_INCONCLUSIVE"
    report["diagnostics"]=comparison_diagnostic(report)
    report["seconds"]=round(time.monotonic()-start,3)
    _write(args.output,report)
    print(json.dumps({"status":report["status"],"comparable":comparable,
                      "difference":report["descriptive_difference_yield_per_requested_proposal"]}),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
