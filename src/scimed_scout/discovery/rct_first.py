"""Evidence-first RCT discovery. Bounded search samples, not verified eligibility.

Rotating P/I search anchors define the retrieval space, NOT novel questions.
A question is constructed only from observed own-trial comparison cues.
No model-generated topics, hard exclusions or fabricated trial counts.
"""
from __future__ import annotations
import hashlib,re
from collections import defaultdict
from datetime import datetime,timezone
from .pico_matching import _groups,_normalize,_passages,NONPRIMARY,PROTOCOL_TYPE,NEGATED_RCT,OBS
from .trial_family import audit_trial_families,registration_signals
from .evidence_first import _record
from .evidence_seed import _NONPRIMARY_SEED_TITLE
from .topic_memory import is_recently_checked
from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.pubmed_abstracts import enrich_rows
from scimed_scout.domain import SourceStatus

VERSION="RCT_FIRST_V1"
MIN_FAMILIES=7
MAX_PAIRS=6
MAX_DEEP=3
MAX_SEED_RECORDS=60
MAX_EUROPE_SUPPLEMENTS=2
MAX_REVIEW_PREFLIGHTS=4
MAX_REVIEW_COMPARISON_RECOVERIES=2
MAX_REVIEW_TITLE_RECOVERIES=2
MAX_COMPARISON_RECOVERIES=3
MAX_CITATION_CELLS=2
# Clinical search vocabulary; no claim that any pair is novel or eligible.
# Each tuple has a population phrase, intervention phrase and optional aliases.
ANCHORS={
 "cardiology":(
 ("hypertension","renal denervation",("resistant hypertension","high blood pressure"),("renal sympathetic denervation",)),
 ("heart failure","intravenous iron",("heart failure",),("ferric carboxymaltose","ferric derisomaltose")),
 ("atrial fibrillation","catheter ablation",(),("radiofrequency ablation",)),
 ("coronary artery disease","colchicine",("myocardial infarction","coronary disease"),()),
 ("heart failure","empagliflozin",(),()),("heart failure","dapagliflozin",(),()),
 ("dyslipidemia","bempedoic acid",("hypercholesterolemia","hyperlipidemia"),()),
 ("coronary artery disease","intravascular ultrasound",("percutaneous coronary intervention","PCI"),("IVUS",)),
 ("atrial fibrillation","left atrial appendage occlusion",(),("left atrial appendage closure",)),
 ("myocardial infarction","remote ischemic conditioning",("STEMI",),("remote ischaemic conditioning",)),
 ("heart failure","spironolactone",(),()),
 ("peripheral artery disease","rivaroxaban",(),()),
 ("cardiac rehabilitation","exercise training",(),("exercise rehabilitation",)),
 ("coronary artery bypass grafting","endoscopic vein harvesting",("CABG",),("endoscopic saphenous vein harvesting",)),
 ("aortic stenosis","transcatheter aortic valve replacement",(),("TAVR","TAVI")),
 ("coronary artery disease","ticagrelor",("percutaneous coronary intervention",),()),
 ("heart failure","sacubitril valsartan",(),("sacubitril/valsartan",)),
 ("atrial fibrillation","pulsed field ablation",(),()),
 ),
 "general surgery":(
 ("appendicitis","antibiotics",(),("antibiotic treatment",)),
 ("inguinal hernia","laparoscopic repair",(),("laparoscopic hernia repair",)),
 ("colorectal surgery","mechanical bowel preparation",(),("bowel preparation",)),
 ("cholecystectomy","indocyanine green",(),("fluorescence cholangiography",)),
 ("abdominal surgery","negative pressure wound therapy",(),("negative pressure wound dressing",)),
 ("hemorrhoids","stapled hemorrhoidopexy",("haemorrhoids",),("stapled haemorrhoidopexy",)),
 ("colorectal surgery","early oral feeding",(),("early feeding",)),
 ("appendectomy","laparoscopic appendectomy",("appendicectomy",),("laparoscopic appendicectomy",)),
 ),
 "orthopedics":(
 ("distal tibial fracture","fibular fixation",("distal tibia fracture",),()),
 ("total knee arthroplasty","tranexamic acid",("knee replacement",),()),
 ("hip fracture","hemiarthroplasty",(),()),
 ("rotator cuff tear","arthroscopic repair",(),()),
 ("distal radius fracture","volar locking plate",(),()),
 ("anterior cruciate ligament reconstruction","hamstring graft",("ACL reconstruction",),()),
 ),
 "neurology":(
 ("ischemic stroke","mechanical thrombectomy",("ischaemic stroke",),("endovascular thrombectomy",)),
 ("multiple sclerosis","ocrelizumab",(),()),
 ("migraine","erenumab",(),()),("epilepsy","levetiracetam",(),()),
 ("parkinson disease","deep brain stimulation",("parkinson's disease",),()),
 ("stroke","robot assisted rehabilitation",(),("robotic rehabilitation",)),
 ),
 "neurosurgery":(
 ("subdural hematoma","middle meningeal artery embolization",("subdural haematoma",),()),
 ("intracerebral hemorrhage","minimally invasive surgery",("intracerebral haemorrhage",),()),
 ("glioblastoma","tumor treating fields",("glioblastoma multiforme",),("tumour treating fields",)),
 ("lumbar spinal stenosis","decompression",(),()),
 ),
 "radiology":(
 ("breast cancer","digital breast tomosynthesis",(),("tomosynthesis",)),
 ("colorectal cancer","computed tomography colonography",(),("CT colonography",)),
 ("ischemic stroke","mechanical thrombectomy",("ischaemic stroke",),("endovascular thrombectomy",)),
 ("hepatocellular carcinoma","radiofrequency ablation",(),()),
 ),
 "endocrinology":(
 ("type 1 diabetes","continuous glucose monitoring",("type 1 diabetes mellitus",),("CGM",)),
 ("type 2 diabetes","semaglutide",(),()),
 ("type 2 diabetes","tirzepatide",(),()),
 ("obesity","liraglutide",(),()),
 ),
 "anesthesiology":(
 ("general anesthesia","dexmedetomidine",("general anaesthesia",),()),
 ("postoperative pain","lidocaine",(),()),
 ("postoperative nausea and vomiting","dexamethasone",(),()),
 ("tracheal extubation","propofol",(),()),
 ),
 "obstetrics and gynecology":(
 ("postpartum hemorrhage","tranexamic acid",("postpartum haemorrhage",),()),
 ("preterm birth","vaginal progesterone",(),()),
 ("preeclampsia","aspirin",("pre-eclampsia",),()),
 ("gestational diabetes","metformin",(),()),
 ),
 "nephrology":(
 ("acute kidney injury","renal replacement therapy",("AKI","acute renal failure"),("kidney replacement therapy",)),
 ("chronic kidney disease","dapagliflozin",("CKD",),()),
 ("hemodialysis","intravenous iron",("haemodialysis",),()),
 ("chronic kidney disease","finerenone",("CKD",),()),
 ),
}
# Explicit comparator cues. Distinct active arms and usual/standard care
# remain separate; we never invent the comparator from a generic trial title.
CONTROLS=("placebo","sham","usual care","standard care","open surgery","open repair",
          "open vein harvesting","open saphenous vein harvesting","medical therapy",
          "self monitoring of blood glucose","fingerstick glucose monitoring","insulin","mammography","conventional mammography","usual glucose monitoring",
          "aspirin","clopidogrel","warfarin","enalapril","metoprolol",
          "radiofrequency ablation","cryoballoon ablation","early treatment","delayed treatment",
          "appendectomy","appendicectomy","saline","no treatment",
          "surgical aortic valve replacement","open saphenous vein harvesting")
OUTCOMES=("all cause mortality","mortality","cardiovascular death","hospitalization","heart failure hospitalization",
          "blood pressure","stroke","myocardial infarction","major adverse cardiovascular events",
          "bleeding","quality of life","exercise capacity","pain","infection","wound infection",
          "length of stay","functional outcome","fracture union","nonunion","reoperation",
          "recurrence","renal function","kidney function","adverse events","treatment failure")
# Sensitive RCT search *cue*, not a validated standalone search strategy.
RCT_FILTER='(randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR randomised[tiab] OR randomly[tiab] OR placebo[tiab] OR trial[tiab]) NOT (animals[mh] NOT humans[mh])'
REVIEW_FILTER='(systematic[sb] OR meta-analysis[pt] OR systematic review[tiab])'
# Ratios are removed from an allocation passage only, not from clinical terms.
ALLOCATION=r"(?:randomi[sz]ed|randomly (?:assigned|allocated))(?:\s*\(\s*\d+\s*:\s*\d+\s*\))?(?:\s+in\s+(?:a\s+)?\d+\s*:\s*\d+\s+ratio)?(?:\s+(?:(?:\d+[\s,]+)?(?:patients|participants|subjects|individuals|adults|children|women|men|people|infants)|\d+)(?:\s+[\w-]+){0,12}?)?\s+(?:to|into)\s+"
OWN_ASSIGN=re.compile(r"\b(?:randomi[sz]ed(?:\s*,\s*[\w-]+){0,4}\s+(?:controlled )?(?:trial|study)|placebo.controlled|sham.controlled|"+ALLOCATION+r")",re.I)
SECONDARY=re.compile(r"\b(?:secondary analysis|post.hoc|subgroup analysis|sub.study|subanalysis|pooled analysis|individual patient data|insights from|rationale and design|trial protocol|study protocol|retracted publication|extended follow.up|author correction|erratum)\b",re.I)
COMPARE=re.compile(r"\b(?:versus|vs\.?|compared (?:with|to)|randomi[sz]ed (?:to|into)|randomly (?:assigned|allocated)|placebo.controlled|sham.controlled)\b",re.I)
BACKGROUND=re.compile(r"^(?:background|introduction|rationale|objective|aim)\s*[:：]",re.I)

def supported(specialty):
    return str(specialty).strip().casefold() in ANCHORS
def should_route(specialty,question_type):
    return str(question_type).strip().upper() in ("ALL","EFFECTIVENESS")

def has(text,term):
    target=_normalize(term)
    return bool(target and re.search(r"(?<![a-z0-9])"+re.escape(target)+r"(?![a-z0-9])",_normalize(text)))
def phrases(anchor,aliases):
    return tuple(dict.fromkeys((anchor,*aliases)))
def any_term(text,terms):
    return any(has(text,t) for t in terms)
def _query(terms,field="[tiab]"):
    return "("+" OR ".join('"'+s.replace('"','')+'"'+field for s in terms)+")"
def query_pair(pair,review=False):
    pop,inter,pa,ia=pair
    return _query(phrases(pop,pa))+" AND "+_query(phrases(inter,ia))+" AND "+(REVIEW_FILTER if review else RCT_FILTER)
CONTROL_ALIASES={"surgical aortic valve replacement":("SAVR","surgical valve replacement"),
                 "open vein harvesting":("OVH","open saphenous vein harvesting","traditional vein harvesting"),
                 "open saphenous vein harvesting":("OVH","open vein harvesting"),
                 "medical therapy":("medical treatment","drug therapy"),
                 "usual care":("routine care",)}

def control_terms(control):
    return phrases(control,CONTROL_ALIASES.get(control,()))

# Bibliographic variants are supplementary retrieval terms, not arm-equivalence rules.
REVIEW_INTERVENTION_ALIASES={"pulsed field ablation":("pulse field ablation","pulsed-field ablation")}
REVIEW_COMPARATOR_GROUPS=(("thermal ablation","conventional thermal ablation","conventional thermal techniques","thermal techniques","radiofrequency ablation","cryoablation","thermal energy"),)

def review_control_terms(comparator):
    """Retrieval-only variants; never used to establish clinical arm equivalence."""
    normalized=_normalize(comparator)
    extra=next((group for group in REVIEW_COMPARATOR_GROUPS if normalized in {_normalize(x) for x in group}),())
    return phrases(comparator,(*control_terms(comparator),*extra))

def review_title_query(pair, comparator):
    _,inter,_,aliases=pair
    i=phrases(inter,(*aliases,*REVIEW_INTERVENTION_ALIASES.get(inter.casefold(),())))
    c=review_control_terms(comparator)
    # Omit mandatory population only in this supplementary route. Every hit
    # remains a review lead requiring original PICO assessment.
    return _query(i,"[ti]")+" AND "+_query(c,"[tiab]")+" AND "+REVIEW_FILTER

def comparison_query(pair, comparator):
    # Supplemental only: preserve the broader P+I sample.
    return query_pair(pair)+" AND "+_query(control_terms(comparator))

def ep_query(pair):
    pop,inter,pa,ia=pair
    q=lambda ts:"("+" OR ".join('TITLE_ABS:"'+t.replace('"','')+'"' for t in ts)+")"
    return q(phrases(pop,pa))+" AND "+q(phrases(inter,ia))+' AND (PUB_TYPE:"randomized controlled trial" OR TITLE_ABS:"randomized trial" OR TITLE_ABS:"randomised trial" OR TITLE_ABS:"placebo controlled" OR TITLE_ABS:"sham controlled")'

def own_rct(variants):
    passages,types=_passages(variants)
    title=[p[3] for p in passages if p[0]=="title"]
    labels=[p[3] for p in types]
    if any(NONPRIMARY.search(t) or _NONPRIMARY_SEED_TITLE.search(t) or SECONDARY.search(t) or OBS.search(t) or NEGATED_RCT.search(t) for t in title):return False
    if any(PROTOCOL_TYPE.search(t) or "retract" in t.casefold() for t in labels):return False
    indexed=any(re.search(r"\brandomi[sz]ed controlled trial\b",t,re.I) for t in labels)
    explicit=any(OWN_ASSIGN.search(t) and not NEGATED_RCT.search(t) for t in title)
    methods=any(OWN_ASSIGN.search(p[3]) and not NEGATED_RCT.search(p[3]) and re.search(r"\b(?:we|patients|participants|subjects|individuals)\b",p[3],re.I) and not BACKGROUND.search(p[3]) for p in passages if p[0]!="title")
    return indexed or explicit or methods

def representative(variants):
    rep=max(variants,key=lambda x:(bool((x.get("payload") or {}).get("metadata",{}).get("abstractText")),bool((x.get("payload") or {}).get("url")),len(str(x.get("title") or ""))))
    payload=dict(rep.get("payload") or {});meta=dict(payload.get("metadata") or {})
    meta["trial_registration_ids"]=sorted({i for r in variants for i in registration_signals(r)})
    return {**rep,"payload":{**payload,"metadata":meta}}

def eligible_groups(pair,rows,year=None):
    year=year or datetime.now(timezone.utc).year
    pop,inter,pa,ia=pair
    for group in _groups(rows):
        variants=group["records"]
        if not own_rct(variants):continue
        passages,_=_passages(variants)
        valid_year=any(str((r.get("payload") or {}).get("year") or "").isdigit() and 1900<=int(r["payload"]["year"])<=year for r in variants)
        if not valid_year:continue
        # Both concepts must appear in the title or in own-study Methods/
        # allocation text, not merely in unrelated background sentences.
        eligible=[clean_passage(p[3]) for p in passages if p[0]=="title" or ((OWN_ASSIGN.search(clean_passage(p[3])) or re.match(r"^(?:METHODS?|DESIGN(?:, SETTING, AND PARTICIPANTS)?)\s*:",clean_passage(p[3]),re.I)) and not BACKGROUND.search(clean_passage(p[3])) and not SECONDARY.search(clean_passage(p[3])) and not re.search(r"\b(?:previous|prior)\b",p[3],re.I))]
        # The condition may be stated in the title or another own-method
        # passage, while randomization arms are described separately.
        if not (any(any_term(t,phrases(pop,pa)) for t in eligible) and any(any_term(t,phrases(inter,ia)) for t in eligible)):continue
        yield variants,eligible

def family_summary(rows):
    a=audit_trial_families(rows)
    return {"distinct_report_leads":len(rows),"family_leads":a["conservative_family_lead_count"]-len(a["ambiguous_reports"]),
            "registry_linked_families":a["registry_linked_families"],"unlinked_reports":len(a["unlinked_reports"]),
            "ambiguous_reports":len(a["ambiguous_reports"]),"confirmed_independent_eligible_trials":None}

# Context and arm-composition markers: a treatment received by all
# participants is not the randomized intervention. Fail closed on unclear arms.
CONTEXT=re.compile(r"\b(?:in patients|in adults|in children|among|after|following|before|during|undergoing|admitted for|beyond|on background|as an add-on to|in addition to|each in combination with|both receiving|with concomitant|regardless of)\b",re.I)
PAIR_SPLIT=re.compile(r"\b(?:versus|vs\.?|compared (?:with|to))\b",re.I)
def clean_passage(text):
    from html import unescape
    return re.sub(r"\s+"," ",unescape(re.sub(r"<[^>]*>"," ",str(text or "")))).strip()

def arm_segment(text):
    # Strip contextual population/procedure tail and shared concomitant care.
    return CONTEXT.split(text,maxsplit=1)[0].strip()

def exact_arms(left,right,interventions,control):
    left,right=arm_segment(left),arm_segment(right)
    ct=control_terms(control)
    li,ri=any_term(left,interventions),any_term(right,interventions)
    lc,rc=any_term(left,ct),any_term(right,ct)
    # A vs A+B, or A+B vs C, is not A vs B. Other arm components still
    # need screening; this guard only rejects explicit same-agent crossover.
    return (li and not lc and rc and not ri) or (lc and not li and ri and not rc)

def explicit_comparison(text,interventions,control):
    """Conservative direct-arm clues, not confirmed randomization or eligibility."""
    text=clean_passage(text)
    # Coordinated title ellipsis: e.g. "X or Y ablation". Expand only a
    # shared final noun explicitly present in both requested arm names.
    # No inferred head if the phrase is absent or ambiguous.
    for inter in interventions:
        iw=str(inter).split();cw=str(control).split()
        if len(iw)>=2 and len(cw)>=2 and iw[-1].casefold()==cw[-1].casefold():
            left=" ".join(iw[:-1]);right=str(control)
            pattern=r"^"+re.escape(left)+r"\s+or\s+"+re.escape(right)+r"(?=\s|[:.,]|$)"
            if re.search(pattern,text,re.I):return True
    if not any_term(text,interventions) or not any_term(text,control_terms(control)):return False
    # Prefer explicit allocation. The initial population/procedure cannot
    # leak into either arm. Shared-agent/composition ambiguity is withheld.
    m=re.search(r"\b"+ALLOCATION,text,re.I)
    if m:
        arms=re.split(r"\b(?:or|and|versus|vs\.?)\b",text[m.end():],maxsplit=1,flags=re.I)
        if len(arms)==2:
            return exact_arms(" ".join(arms[0].split()[:16])," ".join(arms[1].split()[:16]),interventions,control)
    for m in PAIR_SPLIT.finditer(text):
        left=" ".join(text[:m.start()].split()[-12:])
        right=" ".join(text[m.end():].split()[:12])
        if exact_arms(left,right,interventions,control):return True
    if PAIR_SPLIT.search(text):return False
    # Implicit placebo/sham-controlled title cues are accepted only if
    # the intervention is in the pre-context subject of the passage and
    # not merely a procedure in which an unrelated drug is tested.
    if control in ("placebo","sham") and re.search(r"\b"+control+r"[- ]controlled\b",text,re.I):
        subject=arm_segment(text)
        if not any_term(subject,interventions):return False
        if re.search(r"\b(?:evaluat(?:e|ed|ing)|investigat(?:e|ed|ing)|assess(?:ed|ing)?|efficacy of|effect of)\b",text,re.I):
            focus=re.split(r"\b(?:efficacy of|effect of|effects of|evaluate|evaluated|investigate|investigated|assess|assessed)\b",text,maxsplit=1,flags=re.I)
            if len(focus)==2 and not any_term(arm_segment(focus[1]),interventions):return False
        return True
    return False

def comparison_rows(pair,rows,comparator=None,year=None,extra_controls=()):
    buckets=defaultdict(list);all_rows=[]
    pop,inter,pa,ia=pair
    for variants,eligible in eligible_groups(pair,rows,year):
        r=representative(variants);all_rows.append(r)
        # Require observed intervention + comparator in same comparison title/
        # allocation passage. This is an explicit cue, not proof of exact arms.
        # Equivalent vocabulary must not create duplicate candidate questions.
        for control in ((comparator,) if comparator else tuple(dict.fromkeys(c for c in (*CONTROLS,*extra_controls) if c!="open saphenous vein harvesting"))):
            if any_term(control,phrases(inter,ia)):continue
            matches=[t for t in eligible if explicit_comparison(t,phrases(inter,ia),control)]
            if matches:
                buckets[control].append({**r,"comparison_excerpt":matches[0][:500]})
    return all_rows,buckets

def strict_candidate_audit(candidate,rows):
    info=(candidate.metadata or {}).get("rct_first") or {}
    raw=info.get("pair")
    if not isinstance(raw,(tuple,list)) or len(raw)!=4:return {"family_leads":0,"confirmed_independent_eligible_trials":None}
    all_rows,buckets=comparison_rows(raw,rows,candidate.comparator_reference)
    exact=buckets.get(candidate.comparator_reference,[])
    return {**family_summary(exact),"population_intervention_family_leads":family_summary(all_rows)["family_leads"],
            "comparison_cues":[{"title":r["title"],"source":r["source"],"record_id":r["source_record_id"],
            "excerpt":r["comparison_excerpt"],"url":r["payload"].get("url"),"registration_ids":sorted(registration_signals(r))} for r in exact],
            "minimum":MIN_FAMILIES,"scope":"BIBLIOGRAPHIC_COMPARISON_CUES_ONLY"}

def _search(client,query,cap,stage,audits,check):
    if check:check()
    try:r=client.search(query,limit=cap)
    except Exception as e:
        audits.append({"source":client.name,"query":query,"stage":stage,"status":"ACCESS_FAILED","error_type":type(e).__name__,"retrieved":0});return []
    audits.append({"source":client.name,"query":query,"stage":stage,"status":r.status.value,"total":r.total_count,"retrieved":len(r.records),"message":str(r.message or "")[:240]})
    return [_record(x) for x in r.records if x.title.strip()]

def collect(specialty,rotation=0,*,pubmed=None,europe=None,check=None,prior=(),year=None,max_pairs=MAX_PAIRS,abstract_enricher=None,dynamic=None,registry_lookup=None,citation=None):
    key=str(specialty).strip().casefold()
    year=year or datetime.now(timezone.utc).year
    if key=="all":key=tuple(ANCHORS)[rotation%len(ANCHORS)]
    report={"version":VERSION,"specialty":key,"queries":[],"cells":[],"candidates":[],"skipped_recent":[],"new_ai_requests":0,"minimum_family_leads":MIN_FAMILIES,"scientific_accuracy_validated":False}
    if key not in ANCHORS:return {**report,"status":"UNSUPPORTED_SPECIALTY"}
    pubmed=pubmed or PubMedSource(sort="relevance");europe=europe or EuropePMCSource()
    if abstract_enricher is None and isinstance(pubmed,PubMedSource) and pubmed.http.loader is None:
        abstract_enricher=lambda rows:enrich_rows(pubmed,rows)
    from .dynamic_anchors import query as dynamic_query,derive,VERSION as DYNAMIC_VERSION
    anchors=ANCHORS[key];start=(int(rotation)*5)%len(anchors)
    pairs=[anchors[(start+i)%len(anchors)] for i in range(min(max_pairs,len(anchors),MAX_PAIRS))]
    dynamic_enabled=bool(abstract_enricher and isinstance(pubmed,PubMedSource) and pubmed.http.loader is None) if dynamic is None else bool(dynamic)
    report["dynamic_discovery"]={"version":DYNAMIC_VERSION,"status":"NOT_SEARCHED","anchors":[],"qualification_granted":False}
    dynamic_controls={}
    if dynamic_enabled and abstract_enricher and (dq:=dynamic_query(key,year)):
        discovery_source=PubMedSource(http=pubmed.http,sort="mixed") if isinstance(pubmed,PubMedSource) and pubmed.http.loader is None else pubmed
        recent=_search(discovery_source,dq,MAX_SEED_RECORDS,"DYNAMIC_SPECIALTY_SAMPLE",report["queries"],check)
        status=report["queries"][-1]["status"]
        if recent:
            if check:check()
            recent,diag=abstract_enricher(recent);report["queries"].append({**diag,"stage":"DYNAMIC_MESH_ENRICHMENT"})
            if diag["status"] not in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE"):status="PARTIAL"
        diagnostic={}
        proposed=derive(recent,anchors,year=year,allow_single=True,specialty=key,diagnostic=diagnostic)
        report["dynamic_discovery"].update(status=status,anchors=proposed,retrieved=len(recent),diagnostic=diagnostic,anchor_status="ANCHORS_RETRIEVED" if proposed else "NO_ANCHORS_IN_BOUNDED_SAMPLE")
        from .registry_anchors import derive_registry
        # An indexed title alone may not reveal treatment arms. Consult only
        # exact NCTs already linked to retrieved reports, with a hard budget.
        if len(proposed)<2 and (registry_lookup is not None or isinstance(pubmed,PubMedSource) and pubmed.http.loader is None):
            registry_proposed,registry_audit=derive_registry(recent,[*anchors,*(x["pair"] for x in proposed)],check=check,lookup=registry_lookup,limit=2-len(proposed))
            report["dynamic_discovery"]["registry_anchor_audit"]=registry_audit
            proposed.extend(registry_proposed)
            for x in registry_proposed:dynamic_controls[tuple(x["pair"][:2])]=(x["comparator"],)
        report["dynamic_discovery"]["anchors"]=proposed
        report["dynamic_discovery"]["anchor_status"]="ANCHORS_RETRIEVED" if proposed else "NO_ANCHORS_IN_BOUNDED_SAMPLE"
        pairs.extend(tuple(x["pair"]) for x in proposed)
    citation_enabled=(isinstance(europe,EuropePMCSource) and europe.http.loader is None) if citation is None else bool(citation)
    report["citation_recovery"]={"status":"NOT_SEARCHED","cells":[],"source_calls":0,"coverage_clearance_allowed":False}
    graph_reviews={}
    samples=[]
    for pair in pairs:
        rows=_search(pubmed,query_pair(pair),MAX_SEED_RECORDS,"RCT_SEED",report["queries"],check)
        if rows and abstract_enricher:
            if check:check()
            rows,abstract_audit=abstract_enricher(rows)
            report["queries"].append(abstract_audit)
        all_rows,buckets=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
        samples.append((pair,rows,family_summary(all_rows)["family_leads"]))
    # Recover only the strongest sampled cells; don't spend all time on a slow
    # second provider. PubMed metadata remains preserved if Europe PMC fails.
    strongest=sorted(range(len(samples)),key=lambda i:(-samples[i][2],i))[:MAX_EUROPE_SUPPLEMENTS]
    for i in strongest:
        pair,rows,n=samples[i]
        if n<2:continue
        rows+=_search(europe,ep_query(pair),MAX_SEED_RECORDS,"ABSTRACT_SUPPLEMENT",report["queries"],check)
    # Recover near-threshold comparisons before spending AI requests.
    recovery=[]
    for i,(pair,rows,_) in enumerate(samples):
        matched_rows,buckets=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
        for control,exact in buckets.items():
            n=family_summary(exact)["family_leads"]
            if 4<=n<MIN_FAMILIES or (2<=n<4 and family_summary(matched_rows)["family_leads"]>=MIN_FAMILIES):recovery.append((n,i,control))
    recovered_cells=set()
    for before,i,control in sorted(recovery,key=lambda x:(-x[0],x[1],x[2])):
        if len(recovered_cells)>=MAX_COMPARISON_RECOVERIES:break
        if i in recovered_cells:continue
        recovered_cells.add(i)
        pair,rows,_=samples[i]
        additional=_search(pubmed,comparison_query(pair,control),MAX_SEED_RECORDS,"COMPARISON_RECOVERY",report["queries"],check)
        if additional and abstract_enricher:
            if check:check()
            additional,abstract_audit=abstract_enricher(additional)
            report["queries"].append(abstract_audit)
        rows.extend(additional)
        _,updated=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
        report.setdefault("comparison_recovery",[]).append({"population":pair[0],"intervention":pair[1],"comparator":control,"before_family_cues":before,"after_family_cues":family_summary(updated.get(control,[]))["family_leads"],"confirmed_independent_eligible_trials":None})
    # A single bounded citation hop supplements keyword retrieval before
    # shortlist selection. Prioritize dynamic and near-threshold cells.
    if citation_enabled:
        from .adaptive_search import citation_neighbors,_pmid
        from .evidence_classification import classify_review_search_hit
        ranked_cells=[]
        for i,(pair,rows,_) in enumerate(samples):
            matched,buckets=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
            if matched:
                best=max(buckets.values(),key=lambda x:family_summary(x)["family_leads"],default=[])
                n=family_summary(best)["family_leads"]
                seed=next((_pmid(x) for x in [*best,*matched] if _pmid(x)),"")
                if seed:ranked_cells.append((i,seed,n))
        ranked_cells.sort(key=lambda x:(not (x[0]>=len(pairs)-len(report["dynamic_discovery"]["anchors"])),not (2<=x[2]<MIN_FAMILIES),-x[2],x[0]))
        for i,seed,n in ranked_cells[:MAX_CITATION_CELLS]:
            pair,rows,_=samples[i]
            audit,records=citation_neighbors(europe,[seed],rows,check=check)
            linked=[_record(x) for x in records]
            rows.extend(linked)
            graph_reviews[tuple(pair[:2])]=[_record(x) for x in records if classify_review_search_hit(x)=="CONFIRMED_REVIEW_CUE" and any_term(x.title+" "+str(x.metadata.get("abstractText") or ""),phrases(pair[0],pair[2])) and any_term(x.title+" "+str(x.metadata.get("abstractText") or ""),phrases(pair[1],pair[3]))]
            _,updated=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
            report["citation_recovery"]["cells"].append({"population":pair[0],"intervention":pair[1],"before_max_comparison_cues":n,"after_max_comparison_cues":max((family_summary(v)["family_leads"] for v in updated.values()),default=0),"review_leads":len(graph_reviews[tuple(pair[:2])]),**audit})
            report["citation_recovery"]["source_calls"]+=audit["source_calls"]
            if any(e.get("rate_limited") for e in audit["citation_search"]):break
        report["citation_recovery"]["status"]="BOUNDED_ATTEMPT" if report["citation_recovery"]["cells"] else "NO_SOURCE_LINKED_SEED"
    for pair,rows,_ in samples:
        all_rows,buckets=comparison_rows(pair,rows,year=year,extra_controls=dynamic_controls.get(tuple(pair[:2]),()))
        primary=family_summary(all_rows)
        report["cells"].append({"population":pair[0],"intervention":pair[1],**primary,
            "observed_comparators":{k:family_summary(v) for k,v in buckets.items()},
            "source_records":all_rows})
        for comp,exact in sorted(buckets.items(),key=lambda x:(-family_summary(x[1])["family_leads"],x[0])):
            if family_summary(exact)["family_leads"]<2:continue
            # Outcomes are observed citation terms, never invented results.
            text=" ".join(r["title"]+" "+str((r["payload"].get("metadata") or {}).get("abstractText") or "") for r in exact)
            outcomes=[o for o in OUTCOMES if has(text,o)][:5]
            if not outcomes:outcomes=["Clinical outcomes reported in eligible trials (verify before protocol)"]
            ident=hashlib.sha256(("|".join((key,pair[0],pair[1],comp))).encode()).hexdigest()[:16].upper()
            title=f"{pair[1].capitalize()} versus {comp} in {pair[0]}: systematic review of randomized trials"
            info={"version":VERSION,"pair":pair,**family_summary(exact),"population_intervention_family_leads":primary["family_leads"],
                  "observed_outcome_terms":outcomes,"comparison_records":exact,"minimum":MIN_FAMILIES,
                  "shortlist_eligible":family_summary(exact)["family_leads"]>=MIN_FAMILIES,
                  "novelty_confirmed":False,"confirmed_independent_eligible_trials":None}
            candidate=CandidateRecord("RCT-"+ident,"",title,key.title(),"EFFECTIVENESS",
                review_question=title,population=pair[0],intervention_exposure_index_test=pair[1],comparator_reference=comp,
                outcomes=outcomes,eligible_designs=["Randomized controlled trial"],
                rationale="Observed randomized-report comparison cues; independent eligibility and extractable outcomes remain unverified.",
                novelty_hypothesis="Check existing reviews and actual search dates; neither novelty nor update value is confirmed.",
                search_terms=[pair[0],pair[1],comp],metadata={"rct_first":info,"evidence_preflight":{"priority_signal":family_summary(exact)["family_leads"],"eligibility_confirmed":False,"novelty_confirmed":False}})
            if any(is_recently_checked(candidate,x) for x in prior):
                report["skipped_recent"].append({"candidate_id":candidate.candidate_id,"title":title,"reason":"RECENTLY_CHECKED_PICO"});continue
            from dataclasses import asdict
            report["candidates"].append(asdict(candidate))
    # Prioritize exact comparison families, then screen the highest-ranked
    # distinct cells for competing reviews BEFORE model calls. Publication
    # chronology is not a search cutoff and never clears novelty.
    report["candidates"].sort(key=lambda c:(-c["metadata"]["rct_first"]["family_leads"],-c["metadata"]["rct_first"]["population_intervention_family_leads"],c["candidate_id"]))
    seen={}
    from .evidence_classification import classify_review_search_hit
    from scimed_scout.sources.base import SearchRecord
    for c in report["candidates"]:
        info=c["metadata"]["rct_first"];pair=info["pair"];key2=tuple(pair[:2])
        if not info["shortlist_eligible"]:continue
        if key2 not in seen:
            if len(seen)>=MAX_REVIEW_PREFLIGHTS:continue
            reviews=_search(pubmed,query_pair(pair,review=True),15,"REVIEW_PREFLIGHT",report["queries"],check)
            review_status=report["queries"][-1]["status"]
            if reviews and abstract_enricher:
                if check:check()
                reviews,abstract_audit=abstract_enricher(reviews)
                report["queries"].append({**abstract_audit,"stage":"REVIEW_ABSTRACT_ENRICHMENT"})
            # Keep keyword records and exact citation discoveries; one source
            # query per cell, independent mutable lists for each comparator.
            seen[key2]=(review_status,[*reviews,*graph_reviews.get(key2,[])])
        review_status,reviews=seen[key2]
        reviews=list(reviews)
        info["competing_review_preflight"]={"status":review_status,"records":reviews,"actual_search_dates_verified":False,"novelty_confirmed":False}
        dates=[r["payload"]["year"] for r in reviews if isinstance(r["payload"].get("year"),int) and classify_review_search_hit(SearchRecord(r["source"],r["source_record_id"],r["title"],metadata=r["payload"].get("metadata") or {}))=="CONFIRMED_REVIEW_CUE"]
        info["latest_sampled_review_publication_year"]=max(dates,default=None)
        info["newer_publication_report_cues"]=sum(isinstance(r["payload"].get("year"),int) and bool(dates) and r["payload"]["year"]>max(dates) for r in info["comparison_records"])
    from .opportunity_mcda import profile
    # All questions receive a transparent profile; unsampled competitor cells
    # stay UNKNOWN, not "no competing reviews".
    for row in report["candidates"]:
        candidate=CandidateRecord(**row)
        row["metadata"]["opportunity_mcda"]=profile(candidate)
    # Broad P+I review retrieval is sensitive but may obscure exact comparisons.
    # Run a bounded supplemental query only for top evidence-backed questions
    # where no direct review or gap cue was retrieved. Preserve both searches.
    review_recoveries=0
    for row in report["candidates"]:
        info=row["metadata"]["rct_first"];p=row["metadata"]["opportunity_mcda"]
        pre=info.get("competing_review_preflight")
        if not pre or pre.get("status") not in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE","PARTIAL"):continue
        if p["direct_comparison_review_sample"]:continue
        if review_recoveries>=MAX_REVIEW_COMPARISON_RECOVERIES:break
        pair=info["pair"];control=row["comparator_reference"];before=len(p["direct_comparison_review_sample"])
        query=query_pair(pair,review=True)+" AND "+_query(review_control_terms(control))
        extra=_search(pubmed,query,15,"REVIEW_COMPARISON_RECOVERY",report["queries"],check)
        supplement_status=report["queries"][-1]["status"]
        if extra and abstract_enricher:
            if check:check()
            extra,abstract_audit=abstract_enricher(extra)
            report["queries"].append({**abstract_audit,"stage":"REVIEW_COMPARISON_ABSTRACT_ENRICHMENT"})
        pre["records"].extend(extra)
        pre["comparison_recovery_status"]=supplement_status
        p=profile(CandidateRecord(**row));row["metadata"]["opportunity_mcda"]=p
        report.setdefault("review_comparison_recovery",[]).append({"candidate_id":row["candidate_id"],"before_direct_review_cues":before,"after_direct_review_cues":len(p["direct_comparison_review_sample"]),"gap_cues":len(p["source_linked_gap_cues"]),"novelty_confirmed":False,"status":supplement_status})
        review_recoveries+=1
    if citation_enabled:
        # Run even when one competing review was found: one hit cannot
        # establish complete retrieval. Keep independent caps and audit.
        recovered=set()
        for row in report["candidates"]:
            info=row["metadata"]["rct_first"];pre=info.get("competing_review_preflight")
            if not pre:continue
            pair=info["pair"];control=row["comparator_reference"];key2=(*pair[:2],control)
            if key2 in recovered:continue
            if len(recovered)>=MAX_REVIEW_TITLE_RECOVERIES:break
            recovered.add(key2)
            extra=_search(pubmed,review_title_query(pair,control),30,"REVIEW_TITLE_RECOVERY",report["queries"],check)
            status=report["queries"][-1]["status"]
            if extra and abstract_enricher:
                if check:check()
                extra,diag=abstract_enricher(extra)
                report["queries"].append({**diag,"stage":"REVIEW_TITLE_ABSTRACT_ENRICHMENT"})
            before={str(x["source_record_id"]) for x in pre["records"]}
            pre["records"].extend(x for x in extra if str(x["source_record_id"]) not in before)
            pre["title_recovery_status"]=status
            row["metadata"]["opportunity_mcda"]=profile(CandidateRecord(**row))
            report.setdefault("review_title_recovery",[]).append({"candidate_id":row["candidate_id"],"new_bibliographic_records":len({str(x["source_record_id"]) for x in extra}-before),"status":status,"novelty_confirmed":False})
    report["candidates"].sort(key=lambda row: (tuple(-x for x in row["metadata"]["opportunity_mcda"]["priority_key"]),row["candidate_id"]))
    report["status"]="SAMPLED" if report["queries"] and all(q["status"] in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE") for q in report["queries"]) else "PARTIAL_SAMPLE" if any(q["retrieved"] for q in report["queries"]) else "ACCESS_UNRESOLVED"
    return report

def main():
    import argparse,json
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--rotation",type=int,default=0);p.add_argument("--specialty",default="Cardiology");args=p.parse_args()
    r=collect(args.specialty,args.rotation);args.output.write_text(json.dumps(r,indent=2,default=str)+"\n")
    print(json.dumps({"status":r["status"],"queries":r["queries"],"cells":[{k:v for k,v in c.items() if k!="source_records"} for c in r["cells"]],"candidates":[{"title":c["title"],"family_leads":c["metadata"]["rct_first"]["family_leads"],"pi_families":c["metadata"]["rct_first"]["population_intervention_family_leads"],"shortlist_eligible":c["metadata"]["rct_first"]["shortlist_eligible"],"opportunity_routes":c["metadata"].get("opportunity_mcda",{}).get("routes",[]),"gap_cue_count":len(c["metadata"].get("opportunity_mcda",{}).get("source_linked_gap_cues",[]))} for c in r["candidates"]],"dynamic_discovery":r.get("dynamic_discovery",{}),"comparison_recovery":r.get("comparison_recovery",[]),"review_comparison_recovery":r.get("review_comparison_recovery",[]),"new_ai_requests":0}),flush=True)
if __name__=="__main__":main()
