"""Route-aware discovery and non-compensatory assessment, not a validated instrument.

No AI calls. Citation signals guide exploration, not confirmed eligibility,
novelty, treatment effects, or publication probability. Human ratings require
rationale and source references; the module does not authenticate adjudication.
"""
from __future__ import annotations
import math
import re
from datetime import date
from urllib.parse import urlsplit
from .pico_matching import _groups
from .review_opportunity import date_bounds, _publication_bounds, _correction_cues

VERSION="SCIMED_OPPORTUNITY_MCDA_V2"
WEIGHTS={"clinical_importance":15,"research_gap_novelty":20,"information_gain":20,
         "evidence_readiness":15,"methodological_feasibility":15,"timeliness":5,
         "operational_feasibility":5,"editorial_relevance":5}
SCENARIOS={"balanced":WEIGHTS,"novelty_information":dict(zip(WEIGHTS,(10,25,25,10,15,5,5,5))),
           "readiness_feasibility":dict(zip(WEIGHTS,(10,15,15,25,20,5,5,5))),
           "equal":{k:12.5 for k in WEIGHTS}}
GAP_PATTERNS={
    "IMPRECISION_OR_INSUFFICIENT_INFORMATION":r"\b(?:insufficient evidence|limited evidence|imprecise estimates?|wide confidence intervals?|evidence (?:is|remains|was) (?:uncertain|inconclusive|limited|insufficient))\b",
    "INCONSISTENCY":r"\b(?:conflicting (?:evidence|results|findings)|inconsistent (?:results|findings|evidence)|substantial heterogeneity)\b",
    "MISSING_RELEVANT_INFORMATION":r"\b(?:long.term (?:outcomes?|effects?|safety|follow.up)|safety (?:data|outcomes?)|underrepresented|under.reported|not (?:reported|assessed|evaluated))\b",
    "POTENTIAL_BIAS_OR_METHODS_LIMITATION":r"\b(?:risk of bias|publication bias|methodological limitations?|low quality evidence)\b",
}
PROMPT="""RCT-first independent scientific adjudication: verify at least seven independent RCTs with the exact comparison and extractable relevant outcomes; do not count citation cues. Distinguish primary-research gaps from synthesis gaps. For novel, update, corrective, outcome and long-term routes, assess the difference from existing syntheses on its own merits. An identical PICO can be valuable if meaningful new evidence or a verified material correction exists. For updates compare actual search dates AND included-trial lists; new reports are not automatically new trials.
Use eight weighted domains (0–5): clinical importance 15, route-specific research gap/novelty 20, incremental knowledge 20, evidence readiness 15, methodological feasibility 15, scientific timeliness 5, operational feasibility 5, editorial relevance 5. For each give original-source URLs, rationale, counterevidence and uncertainty; missing evidence = UNKNOWN, not 0. Do not double-count a single advantage. Calculate lower and upper weighted bounds without redistributing unknown weights. Compare balanced, novelty/information, readiness/feasibility and equal-weight scenarios. These local weights are not a validated instrument. Full score >=75, clinical importance >=4, information gain >=4, route-specific and overall novelty >=3, publication potential >=4, strong-moderate or high feasibility, grade A/B/corrected C and all scientific gates are mandatory. A score never clears unresolved eligibility, coverage, registry overlap, or fatal flaws. Only recommend registration after independently documenting all gates."""
def number(v):
    return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=5 else None
def link(v):
    try:
        u=urlsplit(str(v or ""))
        return u.scheme in ("http","https") and bool(u.hostname) and not u.username and not u.password
    except ValueError:return False
def ref(record):
    p=record.get("payload") or {}
    return {"source":record.get("source"),"record_id":str(record.get("source_record_id") or ""),
            "title":record.get("title"),"url":p.get("url"),"doi":p.get("doi")}
def weighted_assessment(ratings=None):
    """Unknown domains retain their full weight as uncertainty, never renormalized."""
    ratings=ratings or {};domains={}
    for k,w in WEIGHTS.items():
        row=ratings.get(k) or {};v=number(row.get("rating"))
        refs=[u for u in row.get("source_urls",[]) if link(u)] if isinstance(row.get("source_urls"),list) else []
        documented=bool(v is not None and row.get("status")=="ADJUDICATED" and refs and str(row.get("rationale") or "").strip())
        preliminary=bool(v is not None and row.get("status")=="PRELIMINARY")
        domains[k]={"weight":w,"rating":v if documented or preliminary else None,
                    "status":"ADJUDICATED_INPUT" if documented else "PRELIMINARY" if preliminary else "UNKNOWN",
                    "rationale":str(row.get("rationale") or "")[:1000],"source_urls":refs,
                    "counterevidence":str(row.get("counterevidence") or "")[:1000],
                    "weighted_contribution":round(w*v/5,2) if documented else None}
    def bounds(weights,allow_preliminary=False):
        known={"ADJUDICATED_INPUT","PRELIMINARY"} if allow_preliminary else {"ADJUDICATED_INPUT"}
        low=sum(weights[k]*d["rating"]/5 for k,d in domains.items() if d["status"] in known)
        missing=sum(weights[k] for k,d in domains.items() if d["status"] not in known)
        return [round(low,2),round(low+missing,2)]
    scenarios={k:{"documented_bounds":bounds(w),"exploratory_bounds":bounds(w,True),"weights":dict(w)} for k,w in SCENARIOS.items()}
    complete=all(d["status"]=="ADJUDICATED_INPUT" for d in domains.values())
    return {"version":VERSION,"domains":domains,"scenarios":scenarios,"status":"COMPLETE_ADJUDICATED_INPUTS_NOT_AUTHENTICATED" if complete else "INCOMPLETE",
            "publication_oriented_score":scenarios["balanced"]["documented_bounds"][0] if complete else None,
            "documented_score_bounds":scenarios["balanced"]["documented_bounds"],
            "exploratory_score_bounds":scenarios["balanced"]["exploratory_bounds"],
            "validated_instrument":False,"qualification_granted":False,
            "note":"Preliminary ratings and bibliographic cues never satisfy scientific gates. Local weights; documented inputs require independent verification."}
def compare_assessments(items):
    """Interval dominance, not optimistic imputation. Incomplete rankings may be indeterminate."""
    out={}
    for scenario in SCENARIOS:
        rows=[]
        for cid,a in items:
            lo,hi=a["scenarios"][scenario]["documented_bounds"]
            rows.append({"candidate_id":cid,"lower":lo,"upper":hi})
        winners=[r["candidate_id"] for r in rows if len(rows)>1 and all(r["lower"]>s["upper"] for s in rows if s["candidate_id"]!=r["candidate_id"])]
        out[scenario]={"intervals":rows,"strict_dominance_winner":winners[0] if len(winners)==1 else None}
    winners=[x["strict_dominance_winner"] for x in out.values()]
    return {"scenarios":out,"robust_winner":winners[0] if winners and winners[0] and len(set(winners))==1 else None,
            "status":"ROBUST_INTERVAL_DOMINANCE" if winners and winners[0] and len(set(winners))==1 else "INDETERMINATE_OR_WEIGHT_SENSITIVE",
            "qualification_granted":False}
def profile(candidate, reviews=None, *, opportunity=None, scorecard=None):
    from .rct_first import explicit_comparison, any_term, phrases, has, family_summary, MIN_FAMILIES
    from .evidence_classification import classify_review_search_hit
    from scimed_scout.sources.base import SearchRecord
    info=(candidate.metadata or {}).get("rct_first") or {}
    pair=info.get("pair") or ()
    records=info.get("comparison_records") or []
    seed=info.get("competing_review_preflight") or {}
    review_rows=seed.get("records",[]) if reviews is None else reviews
    findings=[];related=[];cutoffs=[];outcome_hypotheses=[]
    if len(pair)==4:
        pop,inter,pa,ia=pair
        for group in _groups(review_rows):
            for row in group["records"]:
                p=row.get("payload") or {};meta=p.get("metadata") or {}
                if classify_review_search_hit(SearchRecord(row.get("source",""),str(row.get("source_record_id","")),str(row.get("title","")),metadata=meta))!="CONFIRMED_REVIEW_CUE":continue
                title=str(row.get("title") or "")
                abstract=str(meta.get("abstractText") or meta.get("abstract") or "")
                if not any_term(title+" "+abstract,phrases(pop,pa)):continue
                if not (explicit_comparison(title,phrases(inter,ia),candidate.comparator_reference) or any(explicit_comparison(s,phrases(inter,ia),candidate.comparator_reference) for s in re.split(r"(?<=[.!?])\s+|\n+",abstract) if re.match(r"(?i)^(?:methods?|objective|aim)\s*:",s))):continue
                citation=ref(row)
                if not (link(citation["url"]) or citation["doi"]):continue
                related.append(citation)
                for sentence in re.split(r"(?<=[.!?])\s+|\n+",abstract):
                    for code,pattern in GAP_PATTERNS.items():
                        if re.search(pattern,sentence,re.I):
                            findings.append({**citation,"kind":code,"excerpt":sentence[:400],
                                "status":"REVIEW_ABSTRACT_GAP_CUE_NOT_SYNTHESIS_GAP_CONFIRMED",
                                "next_action":"Check whether eligible RCTs and existing synthesis answer this specific uncertainty, or new primary research is required."})
                            for outcome in candidate.outcomes:
                                if has(sentence,outcome):
                                    matched=[r for r in records if has(str(r.get("title") or "")+" "+str((r.get("payload") or {}).get("metadata",{}).get("abstractText") or ""),outcome)]
                                    n=family_summary(matched)["family_leads"]
                                    if n>=MIN_FAMILIES:
                                        outcome_hypotheses.append({"outcome":outcome,"comparison_family_cues":n,"review":citation,
                                            "status":"OUTCOME_SPECIFIC_PICO_HYPOTHESIS_NOT_ELIGIBILITY_OR_NOVELTY_VERIFIED",
                                            "next_action":"Verify exact outcome definitions, extractability, prior synthesis and independent trial families before refining PICO."})
                # A methods abstract date is a lead for full-text verification.
                from .open_access_dates import extract_search_date
                methods=[s for s in abstract.splitlines() if re.match(r"(?i)^methods?\s*:",s)]
                for passage in methods:
                    if d:=extract_search_date(passage):
                        b=date_bounds(d["date"])
                        if b and b[0]<=date.today():cutoffs.append({**citation,"date":d["date"],"end":b[1].isoformat(),"excerpt":d["quote"],"status":"ABSTRACT_SEARCH_DATE_CUE_VERIFY_FULLTEXT"})
                break
    latest=max((c["end"] for c in cutoffs),default=None)
    post=[]
    if latest:
        for row in records:
            b=_publication_bounds(row)
            if b and b[0]>date.fromisoformat(latest) and b[0]<=date.today():
                post.append(ref(row))
    opportunity=opportunity or {};scorecard=scorecard or {}
    correction=opportunity.get("correction_method_cues") or []
    routes=[]
    if findings:routes.append("REVIEW_GAP_SIGNAL")
    if post or opportunity.get("route") in ("UPDATE_SIGNAL","UPDATE_AND_CORRECTIVE_SIGNAL"):routes.append("UPDATE_SIGNAL")
    if correction or opportunity.get("route") in ("CORRECTIVE_SIGNAL","UPDATE_AND_CORRECTIVE_SIGNAL"):routes.append("CORRECTIVE_SIGNAL")
    if outcome_hypotheses:routes.append("OUTCOME_SPECIFIC_SIGNAL")
    if not routes:routes=["EXPLORATORY_SYNTHESIS_UNCERTAIN"]
    n=int(info.get("family_leads") or 0)
    # Operational priority only: evidence floor, source-linked actionable gaps,
    # and capped count rather than reward for the largest saturated topic.
    priority=(int(n>=MIN_FAMILIES),int(bool(post or correction)),int(bool(findings)),min(n,14))
    ratings={}
    if n:
        ratings["evidence_readiness"]={"rating":min(5,round(n/MIN_FAMILIES*3,2)),"status":"PRELIMINARY",
            "rationale":"Comparison-linked bibliography family cues only, not independent eligible trials.",
            "source_urls":[r.get("payload",{}).get("url") for r in records[:5]]}
    opinions=scorecard.get("model_domain_opinions") or {}
    for k,v in opinions.items():
        if k in WEIGHTS and number(v) is not None:
            ratings[k]={"rating":v,"status":"PRELIMINARY","rationale":"Model-only judgment; requires source-backed independent assessment."}
    return {"version":VERSION,"routes":routes,"priority_key":list(priority),
            "source_linked_gap_cues":findings[:12],"direct_comparison_review_sample":related[:15],
            "abstract_search_date_cues":cutoffs[:15],"post_cutoff_report_cues":post[:15],
            "outcome_specific_hypotheses":outcome_hypotheses[:8],"verified_review_opportunity":opportunity,
            "review_preflight_status":seed.get("status","NOT_SEARCHED"),"confirmed_independent_eligible_trials":None,
            "assessment":weighted_assessment(ratings),
            "scope":"DISCOVERY_SIGNALS_NOT_CONFIRMED_RESEARCH_GAPS_OR_PUBLICATION_PROBABILITY"}
