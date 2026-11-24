/* Reusable, deterministic final-evidence audit preview.
 * It makes NO source requests, NEVER counts bibliography leads as eligible,
 * never modifies Supabase qualification, and never auto-issues a GO.
 * Clinically curated inputs belong in final-audit-evidence.js, not here.
 */
(function () {
  'use strict';
  const BAD_SOURCE = new Set(['ACCESS_FAILED','PARTIAL','NOT_SEARCHED','UNKNOWN']);
  const SAFE_HOSTS = new Set([
    'pubmed.ncbi.nlm.nih.gov','pmc.ncbi.nlm.nih.gov','doi.org',
    'www.crd.york.ac.uk','www.cochrane.org','www.3ieimpact.org',
    'www.jacc.org','jamanetwork.com','www.sciencedirect.com',
    'academic.oup.com','www.ebi.ac.uk','europepmc.org',
    'www.semanticscholar.org',
  ]);
  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g,
      ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function link(url, label) {
    try {
      const parsed = new URL(String(url || ''));
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password
          || !SAFE_HOSTS.has(parsed.hostname)) return esc(label);
      return '<a href="' + esc(parsed.href) + '" target="_blank" rel="noopener noreferrer">' +
        esc(label) + '</a>';
    } catch {
      return esc(label);
    }
  }
  function verifiedIndependence(study) {
    return study?.fulltext_eligibility_verified === true
      && study?.independent_population_verified === true
      && study?.endpoint_extraction_verified === true
      && ['DIRECT_DOAC_COMPARATOR_VERIFIED','PICO_ELIGIBLE_VERIFIED'].includes(study?.targeted_fit)
      && !!study?.url;
  }
  function verifiedIndependentFamilies(studies) {
    // A report is not an independent population. Deduplicate explicitly
    // adjudicated family IDs, and withhold any unresolved cross-family overlap.
    const seen=new Set();
    const confirmed=[];
    for (const report of (Array.isArray(studies) ? studies : [])) {
      if (!verifiedIndependence(report) || !String(report.family||'').trim()
          || (report.possible_overlaps||[]).length) continue;
      const id=String(report.family);
      if (seen.has(id)) continue;
      seen.add(id);
      confirmed.push(report);
    }
    return confirmed;
  }
  function questionType(topic) {
    const q=topic?.research_dossier?.scientific_question || {};
    const declared=[topic?.question_type,q.question_type,
      ...(Array.isArray(q.eligible_designs)?q.eligible_designs:[])]
      .filter(Boolean).join(' ').toLowerCase();
    const metrics=(Array.isArray(q.outcomes)?q.outcomes:[])
      .join(' ').toLowerCase();
    if (/diagnostic|test accuracy|\\bdta\\b|index test/.test(declared)
        || (/sensitivity|specificity|diagnostic odds ratio/.test(metrics)
          && (q.comparator_reference || q.reference_standard))) return 'DIAGNOSTIC_TEST_ACCURACY';
    if (/prognos|prediction model|risk prediction/.test(declared)) return 'PROGNOSTIC';
    if (/prevalence|incidence|epidemiolog/.test(declared)) return 'PREVALENCE_INCIDENCE';
    if (/qualitative|scoping/.test(declared)) return 'EVIDENCE_MAPPING';
    return 'COMPARATIVE_INTERVENTION';
  }
  function methodsFor(type) {
    if (type==='DIAGNOSTIC_TEST_ACCURACY') return [
      {name:'Cochrane Handbook for Diagnostic Test Accuracy Reviews',
       url:'https://www.cochrane.org/authors/handbooks-and-manuals/handbook-systematic-reviews-diagnostic-test-accuracy'},
      {name:'PRISMA-DTA reporting checklist',
       url:'https://www.prisma-statement.org/dta'},
      {name:'QUADAS-3 risk of bias and applicability (2026)',
       url:'https://pubmed.ncbi.nlm.nih.gov/41698208/'},
      {name:'MetaDTA diagnostic meta-analysis, open source',
       url:'https://github.com/CRSU-Apps/MetaDTA'},
    ];
    return [
      {name:'Cochrane Handbook, eligibility and study selection',
       url:'https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04'},
      {name:'PRISMA 2020',
       url:'https://pmc.ncbi.nlm.nih.gov/articles/PMC8008539/'},
    ];
  }
  function gatesFor(type,sourceProblems,curated) {
    const common=[
      {gate:'COMPREHENSIVE_SOURCE_SEARCH',status:'UNRESOLVED',
       reason:sourceProblems.length ?
         'Original search still reports incomplete access or partial coverage. Targeted rechecks do not erase those flags.' :
         'Original source status alone does not prove a systematic comprehensive and updated search.'},
      {gate:'REGISTRATION_AND_PUBLISHED_REVIEW_OVERLAP',status:'UNRESOLVED',
       reason:curated?.registrations?.length ?
         'High-priority registry leads exist, but full protocols, review search dates and publication links remain unconfirmed.' :
         'No completed, source-linked assessment of all competing reviews and registrations is available.'},
      {gate:'INDEPENDENT_ELIGIBLE_STUDY_FAMILIES',status:'UNRESOLVED',
       reason:'Independently eligible study populations are not verified. The Scout four-study screening target is a project feasibility target, not a universal minimum required by evidence-synthesis methodology.'},
    ];
    if (type==='DIAGNOSTIC_TEST_ACCURACY') return [...common,
      {gate:'INDEX_TEST_REFERENCE_STANDARD_AND_2X2_DATA',status:'UNRESOLVED',
       reason:'Verify actual target condition and lesion population, CT-derived FFR index test, invasive FFR reference standard, compatible thresholds, unit of analysis (patient/vessel/lesion) and extractable TP/FP/FN/TN. Broad coronary disease results do not establish left-main-specific accuracy.'},
      {gate:'QUADAS_3_AND_DTA_SYNTHESIS_FEASIBILITY',status:'UNRESOLVED',
       reason:'Assess participants, index-test conduct, target-condition reference standard and analysis using QUADAS-3. Check clinical thresholds, verification/selection bias, sparse cells and potential dependence among lesion-level results before considering bivariate/HSROC meta-analysis.'},
    ];
    if (type==='PROGNOSTIC') return [...common,
      {gate:'EXTRACTABLE_PROGNOSTIC_ASSOCIATIONS_AND_TIME_HORIZONS',status:'UNRESOLVED',
       reason:'Verify compatible prognostic outcomes, baseline definitions, follow-up windows, effect measures, adjusted covariates and participant overlap.'},
      {gate:'PROGNOSTIC_RISK_OF_BIAS_AND_SYNTHESIS_FEASIBILITY',status:'UNRESOLVED',
       reason:'Assess selection, attrition, measurement, confounding and model validation as applicable; do not pool incompatible measures or time horizons.'},
    ];
    if (type==='PREVALENCE_INCIDENCE') return [...common,
      {gate:'CASE_DEFINITION_AND_NUMERATOR_DENOMINATOR',status:'UNRESOLVED',
       reason:'Verify condition definitions, population sampling frames, event numerators, denominators, geography and observation period.'},
      {gate:'PREVALENCE_STUDY_BIAS_AND_HETEROGENEITY',status:'UNRESOLVED',
       reason:'Assess selection bias, representativeness, measurement validity, heterogeneity and clustering of populations.'},
    ];
    if (type==='EVIDENCE_MAPPING') return [...common,
      {gate:'MAPPING_SCOPE_AND_CHARTING_FIELDS',status:'UNRESOLVED',
       reason:'Confirm conceptual scope, eligible evidence types, deduplicated study families and charting variables. Numerical quantitative synthesis is not automatically appropriate.'},
      {gate:'TRANSPARENT_MAPPING_AND_REPORTING',status:'UNRESOLVED',
       reason:'Establish reproducible source coverage, charting processes, evidence-gap definitions and appropriate reporting guidance.'},
    ];
    return [...common,
      {gate:'PICO_MATCHED_COMPARATIVE_OUTCOME_EXTRACTION',status:'UNRESOLVED',
       reason:'Verify population, intervention, actual comparator arms, extractable events/denominators or adjusted effects, consistent endpoints and time horizons. Mixed comparators must not be labeled as direct head-to-head evidence.'},
      {gate:'INTERVENTION_RISK_OF_BIAS_AND_SYNTHESIS_FEASIBILITY',status:'UNRESOLVED',
       reason:'Determine randomized versus nonrandomized designs and appropriate RoB 2 or ROBINS-I assessment, confounding, time horizons, outcome definitions and overlapping cohorts.'},
    ];
  }
  function countOrUnknown(raw) {
    if (raw === null || raw === undefined) return null;
    const value=Number(raw);
    return Number.isFinite(value) && value>=0 ? value : null;
  }
  function build(job, topic, gap = window.SCIMED_GAP) {
    if (!job?.id || !topic?.candidate_id)
      throw new Error('A saved completed job and a specific topic are required.');
    const key=String(job.id)+':'+String(topic.candidate_id);
    const curated=(window.SCIMED_AUDIT_SEEDS || {})[key] || null;
    const quality=topic.research_dossier?.verification_and_quality || {};
    const originalStatuses=quality.source_statuses || topic.source_statuses || {};
    const sourceProblems=Object.entries(originalStatuses)
      .filter(([,status])=>BAD_SOURCE.has(String(status)))
      .map(([source,status])=>({source,status}));
    if (!Object.keys(originalStatuses).length)
      sourceProblems.push({source:'Original source audit',status:'UNKNOWN'});
    const rechecks=gap?.rechecksOf?.(job,topic) || [];
    const completedRechecks=rechecks.filter(r=>r.status==='COMPLETED');
    const targetedResults=completedRechecks.flatMap(r=>
      (r.result_json?.source_reports || []).map(s=>({
        source:String(s.source || ''),
        previous_status:String(s.previous_status || ''),
        technical_status:String(s.targeted_search_status || ''),
        request_id:r.id,
        only_query_level:true,
      }))
    );
    const notes=gap?.read?.(job,topic)?.decisions || {};
    const manualDecisions=Object.values(notes).map(item=>({
      record_key:String(item.record_key||''),
      decision:String(item.decision||''),
      source:String(item.source||''),
      evidence_url:String(item.evidence_url||''),
      rationale:String(item.rationale||''),
      recorded_at_utc:item.recorded_at_utc || null,
    }));
    const competitors=quality.competing_review_screening || {};
    const reviewHits=countOrUnknown(competitors.published_review_records_discovered);
    const registrationHits=countOrUnknown(competitors.registration_records_discovered);
    const type=questionType(topic);
    const directReports=(curated?.study_reports||[])
      .filter(s=>['DIRECT_DOAC_COMPARATOR_REPORT','DIRECT_COMPARISON_REPORT',
        'INDEX_TEST_REFERENCE_STANDARD_REPORT'].includes(s.targeted_fit)).length;
    const verifiedIndependent=verifiedIndependentFamilies(curated?.study_reports||[]);
    const familyOverlapFlags=(curated?.study_reports||[]).filter(
      s=>Array.isArray(s.possible_overlaps) && s.possible_overlaps.length
    ).length;
    const gates=gatesFor(type,sourceProblems,curated);
    const recommendation=curated?.review_decision === 'REFINE' ? 'REFINE' : 'UNRESOLVED';
    return {
      schema:'SCIMED_FINAL_EVIDENCE_AUDIT_V1',
      created_at_utc:new Date().toISOString(),
      job_id:String(job.id),candidate_id:String(topic.candidate_id),
      title:String(topic.title||''),
      original_qualification_status:String(topic.qualification_status ||
        topic.research_dossier?.qualification_label || 'UNRESOLVED'),
      evidence_basis:curated?.evidence_grade || 'UNVERIFIED_SAVED_DISCOVERY_DOSSIER_ONLY',
      question_type_verified_from_saved_pico:type,
      method_guidance:methodsFor(type),
      minimum_independent_study_target_for_scout:4,
      minimum_target_is_methodological_requirement:false,
      external_research_curated_as_of:curated?.as_of || null,
      recommendation,
      registration_recommendation:curated?.registration_recommendation || 'DO_NOT_REGISTER_WITHOUT_VERIFICATION',
      scientific_gates_satisfied:0,
      scientific_gates_unresolved:gates,
      eligible_independent_study_count: null, // Never replace unknown with 0.
      studied_full_text_eligible_independent_populations_verified_in_this_audit:verifiedIndependent.length,
      count_is_not_exhaustive:true,
      direct_comparator_reports_identified_in_curated_audit:directReports,
      relevant_comparator_or_index_reference_reports_in_curated_audit:directReports,
      potential_study_family_overlap_flags:familyOverlapFlags,
      published_review_source_hits:reviewHits,
      registration_source_hits:registrationHits,
      source_coverage_problems_preserved:sourceProblems,
      targeted_search_technical_results:targetedResults,
      saved_manual_review_decisions:manualDecisions,
      prioritized_registrations:curated?.registrations || [],
      prioritized_published_reviews:curated?.published_reviews || [],
      study_family_screening_ledger:curated?.study_reports || [],
      evidence_methods:[...methodsFor(type),...(curated?.sources_and_methods||[])],
      clinical_question:topic.research_dossier?.scientific_question || {
        population:topic.population,
        intervention_exposure_index_test:topic.intervention_exposure_index_test,
        comparator_reference:topic.comparator_reference,
        outcomes:topic.outcomes,
      },
      primary_study_count_from_bibliography_NOT_ELIGIBLE:
        countOrUnknown(topic.discovered_primary_study_candidates),
      source_search_reexecuted:false,
      full_text_screening_performed_by_this_feature:false,
      ai_generated_sufficiency_assessment:false,
      original_discovery_and_qualification_modified:false,
      caution:'This is a structured analyst evidence ledger, not an exhaustive systematic review. A numerical GO requires fully independently verified primary studies, full protocol comparisons, exhaustive searches, and eligibility decisions.',
      research_recommendation_note:curated?.note ||
        'Complete a source-linked competing review audit and independent original-study family/endpoint check before deciding on registration.',
    };
  }
  function recordSet(items, title, kind) {
    if (!items?.length) return '<p>No independently researched ' + esc(title.toLowerCase()) +
      ' supplied for this candidate. This is missing evidence, not a negative search result.</p>';
    return '<details class="gap-queue"><summary>' + esc(title) + ' ('+items.length+
      ' prioritized leads)</summary>' +
      '<p class="help">These are selected high-priority sources, not all search hits and not a complete eligibility assessment.</p>' +
      items.map(r=>{
        const label=r.id ? r.id+' — '+r.title : r.title;
        const grade=r.evidence_level || r.targeted_fit || 'NOT_VERIFIED';
        return '<article class="gap-record"><p><b>'+link(r.url,label)+'</b></p>'+
          '<p class="help">Evidence level: '+esc(grade)+
          (r.overlap ? ' | PICO overlap: '+esc(r.overlap) : '')+
          (r.last_search_date ? ' | Reported search cutoff: '+esc(r.last_search_date) : '')+
          '</p><p>'+esc(r.note||'')+'</p>'+
          (kind==='study'?
            '<p class="help">Population: '+esc(r.population||'unknown')+
            '. Comparator: '+esc(r.comparator||'unknown')+
            '. Family: '+esc(r.family||'unresolved')+
            '. Independence and extraction: '+(verifiedIndependence(r)?'VERIFIED':'NOT VERIFIED')+
            '. Potential overlap: '+esc((r.possible_overlaps||[]).join(', ')||'unknown')+
            '</p>':
            (r.full_protocol_accessed===false ?
              '<p class="help">Full PROSPERO protocol NOT independently examined.</p>':''))+
          '</article>';
      }).join('')+'</details>';
  }
  function render(job,topic,gap=window.SCIMED_GAP) {
    if (!job?.id || !topic?.candidate_id) return '';
    const audit=build(job,topic,gap);
    return '<details class="gap-final-audit"><summary>Final Evidence Audit · '+
      esc(audit.recommendation)+' (no automatic GO)</summary>'+
      '<p class="help">Evidence-based, reusable review. Original qualification remains '+esc(audit.original_qualification_status)+
      '. No searches are executed when this panel opens.</p>'+
      '<p><b>Recommendation: '+esc(audit.recommendation)+
      '.</b> Protocol registration: '+esc(audit.registration_recommendation)+'</p>'+
      '<p class="help">Curated research date: '+esc(audit.external_research_curated_as_of||'Not performed for this topic')+
      '. Never treat a record hit, conference abstract, or overlapping publication as an independently eligible population.</p>'+
      '<div class="gap-counts"><span>Source problems: '+audit.source_coverage_problems_preserved.length+
      '</span><span>Curated PICO-matched source REPORTS: '+audit.relevant_comparator_or_index_reference_reports_in_curated_audit+
      '</span><span>Verified independent eligible populations: UNKNOWN</span><span>Possible study-family overlaps: '+
      audit.potential_study_family_overlap_flags+'</span></div>'+
      recordSet(audit.prioritized_registrations,'PROSPERO registrations','registration')+
      recordSet(audit.prioritized_published_reviews,'Published competing reviews','review')+
      recordSet(audit.study_family_screening_ledger,'Primary study family ledger','study')+
      '<p class="help">Audit framework: '+esc(audit.question_type_verified_from_saved_pico)+
      '. The four-study screening target is a SciMed planning criterion, not a universal DTA meta-analysis requirement.</p>'+
      '<details class="gap-queue"><summary>Scientific gates (all unresolved)</summary>'+
      audit.scientific_gates_unresolved.map(g=>'<p><b>'+esc(g.gate)+
      ':</b> '+esc(g.reason)+'</p>').join('')+'</details>'+
      '<details class="gap-queue"><summary>Evidence and methodology references</summary>'+
      (audit.evidence_methods.map(m=>'<p>'+link(m.url,m.name)+'</p>').join('') ||
      '<p>Additional methods research is required for this topic.</p>')+'</details>'+
      '<p class="help">'+esc(audit.research_recommendation_note)+'</p>'+
      '<button type="button" class="secondary small" data-final-audit-export="'+
      esc(job.id)+'" data-gap-topic="'+esc(topic.candidate_id)+
      '">Export Final Evidence Audit (.json)</button>'+
      '</details>';
  }
  window.SCIMED_FINAL = Object.freeze({build,render});
})();
