"""V2 qualification from operator-trusted, independently reviewed evidence.

Signatures bind a reconciled submission to one job and one evidence snapshot.
HMAC authenticates possession of distinct operator-provisioned keys; it does
not prove a person's identity, independence, or the truth of source excerpts.
No browser data, model scores or candidate metadata can grant qualification.
"""
from __future__ import annotations
import hashlib,hmac,json,math,os,re
from pathlib import Path
from datetime import date
from .adjudication import build,validate,nonempty,evidence,number
from .review_opportunity import date_bounds
from .evidence_metrics import composite_score
from .gates import final_discovery_decision
from scimed_scout.verification.coverage import DEFINITIVE,evaluate_coverage
from scimed_scout.verification.policy import policy_for_question_type

VERSION="SCIENTIFIC_VERIFICATION_V2_PHASE1"
MIN_RCTS=7
def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def snapshot(ledger,candidate):
    rows={k:ledger.list_external_evidence(candidate.candidate_id,k) for k in ("PRIMARY_STUDY","PUBLISHED_REVIEW","REGISTRATION","OTHER","ONGOING_STUDY")}
    other=[r for r in rows["OTHER"] if (r.get("payload") or {}).get("originally_requested_evidence_type") in ("PUBLISHED_REVIEW","REGISTRATION")]
    packet=build(candidate,rows["PRIMARY_STUDY"],rows["PUBLISHED_REVIEW"],rows["REGISTRATION"],ambiguous=other)
    # Bind all actual retrieved source data, not just titles/identifiers.
    # Exclude changing semantic inference and derived metadata from content hash,
    # but retain raw source metadata including search-date evidence.
    def content(r):
        p=dict(r.get("payload") or {})
        for k in ("discovery_semantic_assessment","discovery_semantic_assessment_input_hash","discovery_search_date_attempts"):
            p.pop(k,None)
        return {"source":r.get("source"),"id":r.get("source_record_id"),"title":r.get("title"),"payload":p}
    latest={(l.source,l.query):l for l in ledger.list_search_log(candidate.candidate_id)}
    log_rows=[{"source":l.source,"query":l.query,"status":l.status.value,"count":l.result_count,"searched_at":l.searched_at} for _,l in sorted(latest.items())]
    raw={k:sorted([digest(content(r)) for r in v]) for k,v in rows.items()}
    binding={"version":VERSION,"project_id":candidate.project_id,"candidate_id":candidate.candidate_id,
        "question":{"title":candidate.title,"question_type":candidate.question_type,"review_question":candidate.review_question,
                    "pico":packet["pico"],"eligible_designs":list(candidate.eligible_designs or [])},
        "source_content_hashes":raw,"search_log":log_rows}
    packet["verification_v2"]={"version":VERSION,"project_id":candidate.project_id,
        "snapshot_sha256":digest(binding),"search_log":log_rows,"eligible_designs":binding["question"]["eligible_designs"],
        "reviewer_submission_template":{"project_id":candidate.project_id,"candidate_id":candidate.candidate_id,
            "snapshot_sha256":digest(binding),"route":"NOVEL","studies":[],"outcomes":[],"competitor_decisions":[],
            "excluded_reports":[],"ratings":{},"ratings_evidence":{},"synthesis_group":{},
            "independent_extraction_and_screening_attested":False,"clinical_scope_evidence":{},"update_or_correction_audits":[]}}
    return packet

def signature(payload,reviewer,key):
    return hmac.new(key,canonical({"version":VERSION,"reviewer":reviewer,"submission":payload}),hashlib.sha256).hexdigest()

def authenticated(bundle,keys):
    if not isinstance(bundle,dict) or not isinstance(bundle.get("submission"),dict):raise ValueError("missing signed submission")
    payload=bundle["submission"];approvals=bundle.get("approvals")
    if not isinstance(approvals,list):raise ValueError("missing independent approvals")
    valid={}
    for a in approvals:
        if not isinstance(a,dict):raise ValueError("invalid approval")
        reviewer=a.get("reviewer");sig=a.get("signature")
        if not isinstance(reviewer,str) or reviewer in valid or not isinstance(sig,str):raise ValueError("invalid or repeated reviewer")
        key=keys.get(reviewer)
        if not isinstance(key,bytes) or len(key)<32 or not hmac.compare_digest(signature(payload,reviewer,key),sig):raise ValueError("untrusted or invalid signature")
        valid[reviewer]=key
    if len({r.strip().casefold() for r in valid})<2 or len(set(valid.values()))<2:raise ValueError("two distinct trusted reviewer keys required")
    if payload.get("independent_extraction_and_screening_attested") is not True:raise ValueError("independent review not attested")
    return payload,sorted(valid)

def effect(row):
    """Conservative common-effect pilot. No invented continuity correction."""
    m=row["measure"]
    if m=="LOG_HR":return float(row["effect"]),float(row["se"])**2
    if m=="MD":
        return row["intervention_mean"]-row["comparator_mean"],row["intervention_sd"]**2/row["intervention_n"]+row["comparator_sd"]**2/row["comparator_n"]
    if m in ("RR","OR"):
        a,c=row["intervention_events"],row["comparator_events"];n,t=row["intervention_n"],row["comparator_n"]
        if not (0<a<n and 0<c<t):raise ValueError("sparse or boundary events need separately validated method")
        if m=="RR":return math.log((a/n)/(c/t)),1/a-1/n+1/c-1/t
        return math.log(a/(n-a)/(c/(t-c))),1/a+1/(n-a)+1/c+1/(t-c)
    raise ValueError("measure not supported by V2 pilot")

def pool(rows):
    if len(rows)<2:raise ValueError("fewer than two compatible outcome rows")
    pairs=[effect(r) for r in rows]
    if any(not math.isfinite(y) or not math.isfinite(v) or v<=0 for y,v in pairs):raise ValueError("invalid or zero variance")
    weights=[1/v for _,v in pairs];total=math.fsum(weights)
    mean=math.fsum(y*w for (y,_),w in zip(pairs,weights))/total
    se=math.sqrt(1/total);q=math.fsum(w*(y-mean)**2 for (y,_),w in zip(pairs,weights))
    return {"k":len(rows),"effect":mean,"se":se,"ci95":[mean-1.95996398454*se,mean+1.95996398454*se],
        "q":q,"i2":max(0,1-(len(rows)-1)/q)*100 if q else 0.0,"method":"COMMON_EFFECT_INVERSE_VARIANCE_PILOT"}

RATINGS=("clinical_question_novelty","overall_novelty","new_information_gain","clinical_importance","publication_potential")
FLAGS=("design_framework_defined","meaningful_synthesis_plausible","question_framework_coherent")
def evaluate(packet,bundle,keys,coverage,policy):
    """Return fail-closed result. Ratings are dual-reviewer judgments, not validated instruments."""
    errors=[]
    def fail(msg):errors.append(msg)
    try:
        data,reviewers=authenticated(bundle,keys)
        binding=packet["verification_v2"]
        if any(data.get(k)!=v for k,v in (("project_id",binding["project_id"]),("candidate_id",packet["candidate_id"]),("snapshot_sha256",binding["snapshot_sha256"]))):
            raise ValueError("submission scope or evidence snapshot changed")
        # Bind all rows to actual approving reviewers, not arbitrary display names.
        for name in ("studies","outcomes","competitor_decisions","excluded_reports"):
            if not isinstance(data.get(name),list):raise ValueError("missing "+name)
            for row in data[name]:
                if not isinstance(row,dict) or not isinstance(row.get("reviewers"),list) or set(row["reviewers"])!=set(reviewers):
                    raise ValueError("row approval identity mismatch")
        structural=validate(packet,data)
        errors.extend(structural["errors"])
        if not coverage.complete:fail("mandatory source coverage incomplete")
        if structural["valid_study_rows"]<MIN_RCTS:fail("fewer than seven independently adjudicated RCTs")
        if structural["competitors_pending"]:fail("unresolved competitor records")
        if not evidence(data.get("clinical_scope_evidence")):fail("missing source-backed scope justification")
        if any(s.get("full_text_checked") is not True or s.get("pico_eligible") is not True or s.get("randomization_confirmed") is not True or s.get("independent_population_confirmed") is not True for s in data["studies"]):
            fail("full-text PICO, randomization or population independence not confirmed")
        primary={r["id"]:r for r in packet["primary_report_index"]}
        covered={rid for s in data["studies"] for rid in s.get("report_ids",[])}
        excluded=set()
        for r in data["excluded_reports"]:
            rid=r.get("report_id")
            if rid not in primary or rid in covered or rid in excluded or not nonempty(r.get("reason")) or not evidence(r.get("evidence")):
                fail("invalid or duplicate report exclusion")
            else:excluded.add(rid)
        if covered|excluded != set(primary):fail("primary report inventory not fully screened")
        ratings=data.get("ratings") or {};reasons=data.get("ratings_evidence") or {}
        for k in RATINGS:
            if not number(ratings.get(k)) or not 0<=ratings[k]<=5 or not evidence(reasons.get(k)):fail("missing bounded evidence-backed rating: "+k)
        for k in (*FLAGS,"fatal_methodological_flaw","fatal_redundancy","feasibility","editorial_grade"):
            if not evidence(reasons.get(k)):fail("missing evidence-backed judgment: "+k)
        if any(ratings.get(k) is not True for k in FLAGS) or ratings.get("fatal_methodological_flaw") is not False or ratings.get("fatal_redundancy") is not False:
            fail("required methodological or redundancy judgment not passed")
        if ratings.get("feasibility") not in ("HIGH","STRONG MODERATE") or ratings.get("editorial_grade") not in ("A","B","CORRECTED C"):fail("feasibility or editorial gate not passed")
        group=data.get("synthesis_group") or {}
        fields=("outcome","definition","timepoint","measure")
        if not all(nonempty(group.get(k)) for k in fields) or not evidence(group.get("compatibility_evidence")) or group.get("parallel_individual_randomization") is not True:
            fail("outcome harmonization and unit-of-analysis judgment missing")
        selected=[o for o in data["outcomes"] if all(o.get(k)==group.get(k) for k in fields)]
        # Keep the original seven RCTs with extractable outcomes and require
        # at least two compatible valid rows for the prespecified synthesis.
        if structural["studies_with_valid_outcome_rows"]<MIN_RCTS:fail("fewer than seven trials with extractable outcomes")
        if len({o["study_id"] for o in selected})!=len(selected):fail("duplicate study in synthesis")
        if errors:return {"version":VERSION,"qualification_granted":False,"blockers":errors,"reviewers":reviewers}
        combined=pool(selected)
        route=data.get("route")
        decisions={d["record_id"]:d for d in data["competitor_decisions"]}
        records={r["id"]:r for r in packet["competitor_index"]}
        overlaps=[d for d in decisions.values() if d["decision"]!="NON_OVERLAP"]
        audit=[]
        if route=="NOVEL":
            if overlaps:fail("novel route has overlapping competitor")
        elif route in ("UPDATE","CORRECTIVE"):
            expected="UPDATE_REQUIRED" if route=="UPDATE" else "CORRECTION_REQUIRED"
            if not overlaps or any(d["decision"]!=expected or records[d["record_id"]]["kind"]!="REVIEW" for d in overlaps):
                fail("unresolved or incompatible overlapping competitor, including registrations")
            items=data.get("update_or_correction_audits")
            if not isinstance(items,list):raise ValueError("missing update/correction audits")
            indexed={a["record_id"]:a for a in items}
            if len(indexed)!=len(items) or set(indexed)!={d["record_id"] for d in overlaps}:fail("every overlapping review requires a distinct audit")
            studies={s["study_id"]:s for s in data["studies"]}
            for d in overlaps:
                a=indexed.get(d["record_id"],{})
                if not evidence(a.get("baseline_evidence")) or not evidence(a.get("clinical_threshold_evidence")) or not evidence(a.get("impact_evidence")):
                    fail("missing baseline, clinical threshold or impact evidence");continue
                if a.get("synthesis_group")!={k:group[k] for k in fields}:fail("baseline and new outcome/measure mismatch");continue
                ids=d.get("included_study_ids")
                if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or not set(ids)<=set(studies):
                    fail("baseline study inclusion list unresolved");continue
                cutoff=date_bounds(d.get("last_search_date"))
                if not cutoff or cutoff[1]>date.today():fail("invalid review search cutoff");continue
                baseline=[o for o in selected if o["study_id"] in ids]
                if set(ids)!={o["study_id"] for o in baseline}:fail("baseline outcome inclusion list incomplete");continue
                if route=="UPDATE":
                    added=[o for o in selected if o["study_id"] not in ids]
                    if not added:fail("no additional independent study in update");continue
                    # Exact source-backed first availability, not publication year or follow-up label alone.
                    if any(not evidence(studies[o["study_id"]].get("first_report_date_evidence")) or not (b:=date_bounds(studies[o["study_id"]].get("first_report_date"))) or b[0]<=cutoff[1] or b[1]>date.today() for o in added):
                        fail("new independent trial chronology unresolved");continue
                    old=pool(baseline)
                else:
                    # Corrective baseline must reproduce the erroneous published analysis from signed source rows.
                    # Do not support corrections without a machine-checkable original analysis yet.
                    fail("corrective route needs verified original-analysis reconstruction; not implemented in phase 1");continue
                published=a.get("published_common_effect")
                if not isinstance(published,dict) or not number(published.get("effect")) or not number(published.get("se")) or published["se"]<=0 or abs(old["effect"]-published["effect"])>0.001 or abs(old["se"]-published["se"])>0.001:
                    fail("published baseline not reproduced to 0.001 on declared effect scale");continue
                threshold=a.get("minimum_important_effect_change")
                if not number(threshold) or threshold<=0 or abs(combined["effect"]-old["effect"])<threshold:
                    fail("predeclared clinically important effect change not demonstrated");continue
                audit.append({"record_id":d["record_id"],"route":route,"baseline":old,"new":combined,"effect_change":abs(combined["effect"]-old["effect"]),"threshold":threshold})
        else:fail("unknown qualification route")
        score=composite_score(novelty=ratings["overall_novelty"],information_gain=ratings["new_information_gain"],
            clinical_importance=ratings["clinical_importance"],feasibility=ratings["feasibility"],publication_potential=ratings["publication_potential"])
        names={n for n in policy.literature_sources if coverage.source_statuses.get(n) in DEFINITIVE}
        complete=len(names)
        if policy.require_prospero:names.add("PROSPERO")
        if policy.require_osf:names.add("OSF Registries")
        if policy.require_pipeline_source:names.update(n for n in policy.pipeline_sources if coverage.source_statuses.get(n) in DEFINITIVE)
        gate=final_discovery_decision({**ratings,"publication_oriented_score":score["publication_oriented_score"],
            "unique_primary_study_candidates":structural["valid_study_rows"],"complete_literature_sources":complete,
            "sources":[{"source":n,"status":coverage.source_statuses[n].value} for n in sorted(names) if n in coverage.source_statuses],
            "unresolved_type_a":errors})
        passed=gate["all_discovery_gates_passed"] and not errors
        return {"version":VERSION,"qualification_granted":passed,"blockers":errors,"reviewers":reviewers,"route":route,
            "snapshot_sha256":binding["snapshot_sha256"],"confirmed_independent_rct_count":structural["valid_study_rows"],
            "trials_with_extractable_outcomes":structural["studies_with_valid_outcome_rows"],"synthesis":combined,"update_audits":audit,
            "gate_result":gate,"scorecard":{**ratings,**score},"human_review_attested":True,
            "scientific_accuracy_independently_validated_by_software":False}
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,ZeroDivisionError) as exc:
        return {"version":VERSION,"qualification_granted":False,"blockers":[*errors,"invalid or incomplete V2 evidence: "+type(exc).__name__],"detail":str(exc)[:200]}

class TrustedDirectory:
    """Operator-only adapter. No keys or bundles from browser or ledger metadata."""
    def __init__(self,directory,keys):
        self.directory=Path(directory);self.keys=keys
    def __call__(self,packet,coverage,policy):
        project=packet["verification_v2"]["project_id"];candidate=packet["candidate_id"]
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,100}",x) for x in (project,candidate)):raise ValueError("invalid scope path")
        path=self.directory/project/(candidate+".json")
        if not path.is_file():return {"version":VERSION,"qualification_granted":False,"blockers":["no trusted signed adjudication submitted"]}
        if path.stat().st_size>20_000_000:raise ValueError("adjudication file exceeds limit")
        return evaluate(packet,json.loads(path.read_text()),self.keys,coverage,policy)
    @classmethod
    def from_env(cls):
        directory=os.getenv("SCIMED_TRUSTED_ADJUDICATION_DIR")
        keyfile=os.getenv("SCIMED_TRUSTED_REVIEWER_KEYS_FILE")
        if not directory or not keyfile:return None
        raw=json.loads(Path(keyfile).read_text())
        return cls(directory,{k:bytes.fromhex(v) for k,v in raw.items()})
