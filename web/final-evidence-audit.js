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
      && study?.targeted_fit === 'DIRECT_DOAC_COMPARATOR_VERIFIED'
      && !!study?.url;
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
    const directReports=(curated?.study_reports||[])
      .filter(s=>s.targeted_fit==='DIRECT_DOAC_COMPARATOR_REPORT').length;
    const verifiedIndependent=(curated?.study_reports||[]).filter(verifiedIndependence);
    const familyOverlapFlags=(curated?.study_reports||[]).filter(
      s=>Array.isArray(s.possible_overlaps) && s.possible_overlaps.length
    ).length;
    const gates=[
      {
        gate:'COMPREHENSIVE_SOURCE_SEARCH',
        status:'UNRESOLVED',
        reason:sourceProblems.length ?
          'Original search still reports incomplete access or partial coverage. Targeted rechecks do not erase those flags.' :
          'Original source status alone does not prove a systematic comprehensive and updated search.',
      },
      {
        gate:'REGISTRATION_AND_PUBLISHED_REVIEW_OVERLAP',
        status:'UNRESOLVED',
        reason:curated?.registrations?.length ?
          'High-priority registry titles were identified, but full protocols and their chronology were not independently inspected.' :
          'No completed, source-linked audit of all competing reviews and registrations was provided.',
      },
      {
        gate:'FOUR_INDEPENDENT_ELIGIBLE_STUDY_POPULATIONS',
        status:'UNRESOLVED',
        reason:'No complete validated list of independent original study populations screened to full-text criteria. Bibliographic leads are not eligible studies.',
      },
      {
        gate:'DOAC_ONLY_DIALYSIS_COMPARATIVE_OUTCOMES',
        status:'UNRESOLVED',
        reason:'Dialysis-only DOAC comparator arms and outcome-specific extractable estimates remain unverified for the full evidence base.',
      },
      {
        gate:'RISK_OF_BIAS_AND_SYNTHESIS_FEASIBILITY',
        status:'UNRESOLVED',
        reason:'Study-level design, confounding, time horizon, endpoint availability and duplicate populations require independent assessment.',
      },
    ];
    const recommendation=curated?.review_decision === 'REFINE' ? 'REFINE' : 'UNRESOLVED';
    return {
      schema:'SCIMED_FINAL_EVIDENCE_AUDIT_V1',
      created_at_utc:new Date().toISOString(),
      job_id:String(job.id),candidate_id:String(topic.candidate_id),
      title:String(topic.title||''),
      original_qualification_status:String(topic.qualification_status ||
        topic.research_dossier?.qualification_label || 'UNRESOLVED'),
      evidence_basis:curated?.evidence_grade || 'UNVERIFIED_SAVED_DISCOVERY_DOSSIER_ONLY',
      external_research_curated_as_of:curated?.as_of || null,
      recommendation,
      registration_recommendation:curated?.registration_recommendation || 'DO_NOT_REGISTER_WITHOUT_VERIFICATION',
      scientific_gates_satisfied:0,
      scientific_gates_unresolved:gates,
      eligible_independent_study_count: null, // Never replace unknown with 0.
      studied_full_text_eligible_independent_populations_verified_in_this_audit:verifiedIndependent.length,
      count_is_not_exhaustive:true,
      direct_comparator_reports_identified_in_curated_audit:directReports,
      potential_study_family_overlap_flags:familyOverlapFlags,
      published_review_source_hits:reviewHits,
      registration_source_hits:registrationHits,
      source_coverage_problems_preserved:sourceProblems,
      targeted_search_technical_results:targetedResults,
      saved_manual_review_decisions:manualDecisions,
      prioritized_registrations:curated?.registrations || [],
      prioritized_published_reviews:curated?.published_reviews || [],
      study_family_screening_ledger:curated?.study_reports || [],
      evidence_methods:curated?.sources_and_methods || [],
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
      '</span><span>Curated direct-comparator REPORTS: '+audit.direct_comparator_reports_identified_in_curated_audit+
      '</span><span>Verified independent eligible populations: UNKNOWN</span><span>Possible study-family overlaps: '+
      audit.potential_study_family_overlap_flags+'</span></div>'+
      recordSet(audit.prioritized_registrations,'PROSPERO registrations','registration')+
      recordSet(audit.prioritized_published_reviews,'Published competing reviews','review')+
      recordSet(audit.study_family_screening_ledger,'Primary study family ledger','study')+
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
