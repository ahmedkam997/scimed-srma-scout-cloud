import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const seeds=readFileSync('web/final-audit-evidence.js','utf8');
const moduleCode=readFileSync('web/final-evidence-audit.js','utf8');
const gapSource=readFileSync('web/gap-verification.js','utf8');
const appSource=readFileSync('web/app.js','utf8');
const index=readFileSync('web/index.html','utf8');
const sw=readFileSync('web/sw.js','utf8');
const jobId='4d10637b-b367-474c-b588-770b5834764b';
const candidateId='CAND-BCD199B816F41CFC';

function setup() {
  const window={};
  const sandbox={window,URL,Date,Set,Map};
  runInNewContext(seeds,sandbox);
  runInNewContext(moduleCode,sandbox);
  const gap={
    read:()=>({decisions:{
      'review|manual1':{
        record_key:'review|manual1',
        decision:'POTENTIAL_OVERLAP',
        evidence_url:'https://pubmed.ncbi.nlm.nih.gov/41085503/',
        source:'PubMed',rationale:'Full text not available',
        recorded_at_utc:'2026-11-24T13:00:00Z',
      },
    }}),
    rechecksOf:()=>[{
      id:'recheck01',status:'COMPLETED',
      result_json:{source_reports:[
        {source:'PROSPERO',previous_status:'PARTIAL',
         targeted_search_status:'TARGETED_QUERIES_COMPLETED_NOT_FULL_SEARCH_CLEARANCE'},
      ]},
    }],
  };
  return {final:window.SCIMED_FINAL,window,gap};
}
const job={id:jobId,status:'COMPLETED'};
const topic={
  candidate_id:candidateId,
  title:'LAAO vs DOACs in dialysis-dependent ESRD',
  qualification_status:'PROVISIONAL_BACKUP',
  discovered_primary_study_candidates:91,
  research_dossier:{
    scientific_question:{
      population:'Dialysis-dependent ESRD and AF',
      intervention_exposure_index_test:'Percutaneous LAAO',
      comparator_reference:'DOACs only',
      outcomes:['stroke','bleeding','mortality'],
    },
    verification_and_quality:{
      source_statuses:{
        PROSPERO:'PARTIAL',OpenAlex:'ACCESS_FAILED',
        'Europe PMC':'PARTIAL',
      },
      competing_review_screening:{
        published_review_records_discovered:36,
        registration_records_discovered:113,
      },
    },
  },
};

test('Current case returns REFINE and DO_NOT_REGISTER_NOW with all gates unresolved',()=>{
  const {final,gap}=setup();
  const r=final.build(job,topic,gap);
  assert.equal(r.schema,'SCIMED_FINAL_EVIDENCE_AUDIT_V1');
  assert.equal(r.recommendation,'REFINE');
  assert.equal(r.registration_recommendation,'DO_NOT_REGISTER_NOW');
  assert.equal(r.eligible_independent_study_count,null);
  assert.equal(r.studied_full_text_eligible_independent_populations_verified_in_this_audit,0);
  assert.equal(r.count_is_not_exhaustive,true);
  assert.equal(r.direct_comparator_reports_identified_in_curated_audit,1);
  assert.equal(r.study_family_screening_ledger.length,4);
  assert.equal(r.prioritized_registrations.length,3);
  assert.equal(r.prioritized_published_reviews.length,3);
  assert.equal(r.scientific_gates_unresolved.length,5);
  assert.ok(r.scientific_gates_unresolved.every(x=>x.status==='UNRESOLVED'));
  assert.equal(r.original_qualification_status,'PROVISIONAL_BACKUP');
  assert.equal(r.source_search_reexecuted,false);
  assert.equal(r.original_discovery_and_qualification_modified,false);
  assert.equal(topic.qualification_status,'PROVISIONAL_BACKUP');
  assert.equal(r.primary_study_count_from_bibliography_NOT_ELIGIBLE,91);
  assert.equal(r.saved_manual_review_decisions.length,1);
});

test('Indexed PROSPERO titles cannot count as inspected protocols',()=>{
  const {final,gap}=setup();
  const r=final.build(job,topic,gap);
  assert.ok(r.prioritized_registrations.every(x=>x.full_protocol_accessed===false));
  assert.ok(r.prioritized_registrations.every(x=>x.last_search_date===null));
  assert.ok(r.prioritized_registrations.every(x=>x.evidence_level==='SAVED_PROSPERO_SEARCH_RESULT_TITLE_ONLY'));
  assert.match(final.render(job,topic,gap),/Full PROSPERO protocol NOT independently examined/);
});

test('New November 2026 published review is included as a competitor with no invented dialysis effect',()=>{
  const {final,gap}=setup();
  const r=final.build(job,topic,gap);
  const paper=r.prioritized_published_reviews.find(x=>x.id==='10.1097/crd.0000000000001561');
  assert.equal(paper.published,'2026-11-19');
  assert.equal(paper.last_search_date,null);
  assert.equal(paper.evidence_level,'PUBLISHED_ABSTRACT_ONLY');
  assert.match(paper.note,/No dialysis-only DOAC estimate verified/);
});

test('Generic question without independent research never gets fabricated NO-GO or GO',()=>{
  const {final,gap}=setup();
  const another={
    candidate_id:'TOPIC-NEW',title:'Unknown treatment A vs B',
    qualification_status:'PROVISIONAL_BACKUP',
    research_dossier:{scientific_question:{population:'Adults'}},
  };
  const r=final.build({id:'OTHER-JOB',status:'COMPLETED'},another,gap);
  assert.equal(r.recommendation,'UNRESOLVED');
  assert.equal(r.eligible_independent_study_count,null);
  assert.equal(r.direct_comparator_reports_identified_in_curated_audit,0);
  assert.equal(r.external_research_curated_as_of,null);
  assert.equal(r.prioritized_registrations.length,0);
  assert.equal(r.scientific_gates_satisfied,0);
  assert.match(final.render({id:'OTHER-JOB'},another,gap),/missing evidence, not a negative search result/);
});

test('Study-family flags never convert overlapping publications into independent studies',()=>{
  const {final,gap}=setup();
  const r=final.build(job,topic,gap);
  const usrds=r.study_family_screening_ledger.filter(x=>x.family.startsWith('USRDS_'));
  assert.equal(usrds.length,2);
  assert.ok(usrds.every(x=>x.independent_population_verified===false));
  assert.ok(usrds[0].possible_overlaps.includes('USRDS_DHAR'));
  assert.ok(usrds[1].possible_overlaps.includes('USRDS_AL_ABCHA'));
  assert.ok(r.study_family_screening_ledger.every(x=>x.endpoint_extraction_verified===false));
});

test('Malicious text is escaped and arbitrary links are not opened',()=>{
  const {final,gap,window}=setup();
  const data=window.SCIMED_AUDIT_SEEDS[jobId+':'+candidateId];
  const item=data.study_reports[0];
  const oldTitle=item.title, oldUrl=item.url;
  item.title='<img src=x onerror=alert(1)>';
  item.url='javascript:alert(2)';
  try {
    const html=final.render(job,topic,gap);
    assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
    assert.ok(!html.includes('<img src=x'));
    assert.ok(!html.includes('href="javascript:'));
  } finally {
    item.title=oldTitle;
    item.url=oldUrl;
  }
});

test('PWA loads source seeds and final audit module before app and includes export action',()=>{
  const idx=index.indexOf('final-audit-evidence.js?v=');
  const moduleIdx=index.indexOf('final-evidence-audit.js?v=');
  const appIdx=index.indexOf('type="module" src="app.js');
  assert.ok(idx>0 && moduleIdx>idx && appIdx>moduleIdx);
  assert.match(sw,/final-audit-evidence\.js\?v=/);
  assert.match(sw,/final-evidence-audit\.js\?v=/);
  assert.match(gapSource,/SCIMED_FINAL\?\.render/);
  assert.match(appSource,/data-final-audit-export/);
  assert.match(appSource,/SCIMED_FINAL\.build/);
  assert.match(index,/Final Evidence Audit/);
});
