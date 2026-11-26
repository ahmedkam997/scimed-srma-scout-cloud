import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { randomUUID } from 'node:crypto';
import { runInNewContext } from 'node:vm';

const source = readFileSync('web/gap-verification.js', 'utf8');
const appSource = readFileSync('web/app.js', 'utf8');
const indexSource = readFileSync('web/index.html', 'utf8');
const swSource = readFileSync('web/sw.js', 'utf8');

function setup() {
  const values = new Map();
  const localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, val) => values.set(key, String(val)),
  };
  const window = {};
  runInNewContext(source, {window, localStorage, URL, Date, Set, Map, crypto:{randomUUID}});
  return {gap:window.SCIMED_GAP, values};
}

const job = {id:'JOB-13'};
const topic = {
  candidate_id:'TOPIC-A',
  title:'SGLT2 inhibitors in HFpEF',
  qualification_status:'PROVISIONAL_BACKUP',
  research_dossier:{
    scientific_question:{
      review_question:'Are SGLT2 inhibitors superior to DPP-4 inhibitors in HFpEF?',
      population:'Adults with heart failure with preserved ejection fraction',
      intervention_exposure_index_test:'SGLT2 inhibitors',
      comparator_reference:'DPP-4 inhibitors',
      outcomes:['hospitalization','cardiovascular mortality'],
    },
    verification_and_quality:{
      source_statuses:{PubMed:'SEARCHED_POSITIVE',PROSPERO:'PARTIAL', 'OSF Registries':'SEARCHED_POSITIVE'},
      pending_verifications:['TYPE-A: competing published reviews are not fully assessed'],
      competing_review_screening:{
        published_review_records_discovered:37,
        registration_records_discovered:24,
        unassessed_published_review_count:25,
        unassessed_registration_count:18,
        unassessed_review_queue:[
          {record_id:'unrelated1',title:'NSAID use in dogs: a systematic review',source:'Crossref',url:'https://doi.org/10.1/unrelated'},
          {record_id:'REV2',title:'SGLT2 inhibitors in HFpEF: systematic review',source:'PubMed',url:'https://pubmed.ncbi.nlm.nih.gov/123/'},
        ],
        unassessed_registration_queue:[
          {record_id:'REG3',title:'DPP-4 inhibitors in HFpEF systematic review protocol',source:'PROSPERO',url:'https://www.crd.york.ac.uk/PROSPERO/view/CRD111'},
        ],
      },
    },
    published_review_evidence:[
      {record_id:'REV2',title:'SGLT2 inhibitors in HFpEF: systematic review',source:'PubMed',url:'https://pubmed.ncbi.nlm.nih.gov/123/',year:2025,
        overlap_assessment:{overall_overlap:'UNRESOLVED'}},
    ],
    evidence_search_audit:[{database:'PROSPERO',status:'PARTIAL',query_used:'SGLT2 HFpEF'}],
    next_actions:['Check last search dates of published reviews','Screen independent trial populations'],
  },
};

test('Research Gap Verification is loaded into the installed mobile PWA', () => {
  assert.match(indexSource, /gap-verification\.js\?v=/);
  assert.match(swSource, /gap-verification\.js\?v=/);
  assert.match(appSource, /SCIMED_GAP\?\.render/);
  assert.match(appSource, /data-gap-save/);
  assert.match(appSource, /data-gap-export/);
  assert.match(appSource, /document\.activeElement\?\.closest/);
});

test('PICO-related reviews are prioritized without declaring others excluded', () => {
  const {gap} = setup();
  const records = gap.evidenceOf(topic);
  const reviews = records.filter(item => item.kind === 'review');
  assert.equal(reviews.length, 2);
  assert.match(reviews[0].title, /SGLT2/);
  assert.equal(reviews[0].source_status, 'PREVIOUS_SEMANTIC_CUE');
  assert.match(reviews[1].title, /NSAID/);
  const html = gap.render(job,topic);
  assert.match(html, /Research Gap Verification/);
  assert.match(html, /Review backlog: 25/);
  assert.match(html, /PROSPERO: PARTIAL/);
  assert.match(html, /Not yet assessed/);
});

test('Source links and supporting explanations are required before storing any human finding', () => {
  const {gap} = setup();
  const record = gap.evidenceOf(topic).find(x => x.kind === 'review');
  const bare = gap.saveDecision(job,topic,record,{
    decision:'DOCUMENTED_NON_OVERLAP',evidence_url:'',rationale:'I looked at the article',
  });
  assert.equal(bare.ok,false);
  const poisoned = gap.saveDecision(job,topic,record,{
    decision:'DOCUMENTED_NON_OVERLAP',evidence_url:'javascript:alert(1)',
    rationale:'Full methods show a different population',
  });
  assert.equal(poisoned.ok,false);
  const accepted = gap.saveDecision(job,topic,record,{
    decision:'NEEDS_FULL_TEXT',evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    rationale:'Only the abstract is available, full text needed for outcome overlap',
  });
  assert.equal(accepted.ok,true);
  assert.equal(Object.keys(gap.read(job,topic).decisions).length,1);
  const second = gap.saveDecision(job,topic,record,{
    decision:'POTENTIAL_OVERLAP',evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    search_date:'2024-05-13',
    rationale:'The full text reports an actual search cutoff and similar PICO terms',
  });
  assert.equal(second.ok,true);
  assert.equal(gap.read(job,topic).history.length,2);
  assert.equal(gap.read(job,topic).decisions[record.key].documented_last_search_date,'2024-05-13');
  assert.equal(topic.qualification_status,'PROVISIONAL_BACKUP');
});

test('The exported ledger retains unresolved source coverage and original bibliography', () => {
  const {gap} = setup();
  const record = gap.evidenceOf(topic)[0];
  gap.saveDecision(job,topic,record,{
    decision:'NEEDS_FULL_TEXT',evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    rationale:'Detailed review protocol is not available through the citation',
  });
  const ledger = gap.exportLedger(job,topic);
  assert.equal(ledger.schema,'SCIMED_RESEARCH_GAP_VERIFICATION_V1');
  assert.equal(ledger.manual_review_does_not_override_gates,true);
  assert.equal(ledger.qualification_automatically_modified,false);
  assert.equal(ledger.history_is_not_cryptographically_immutable_or_authenticated,true);
  assert.equal(ledger.original_status,'PROVISIONAL_BACKUP');
  assert.equal(ledger.saved_source_statuses.PROSPERO,'PARTIAL');
  assert.equal(ledger.source_search_audit[0].status,'PARTIAL');
  assert.equal(ledger.bibliographic_candidates_ordered_for_manual_review.length,3);
  assert.equal(ledger.append_only_local_adjudication_history.length,1);
});

test('HTML-escaped titles and non-whitelisted links cannot inject markup', () => {
  const {gap} = setup();
  const poisonedTopic = structuredClone(topic);
  poisonedTopic.research_dossier.published_review_evidence[0].title = '<img src=x onerror=alert(1)>';
  poisonedTopic.research_dossier.published_review_evidence[0].url = 'https://example-attacker.org/phish';
  const html = gap.render(job,poisonedTopic);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!html.includes('<img src=x'));
  assert.ok(!html.includes('href="https://example-attacker.org/phish"'));
});

test('Cloud events for one browser-scoped job merge with locally unsent notes', () => {
  const {gap} = setup();
  const record = gap.evidenceOf(topic)[0];
  const local = gap.saveDecision(job,topic,record,{
    decision:'NEEDS_FULL_TEXT', evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    rationale:'Need full-text review methods before deciding on comparator',
  });
  assert.equal(local.ok,true);
  assert.equal(gap.assignPendingIds(job,topic).length,1);
  const remoteId = randomUUID();
  gap.setCloudEvents([{
    id:remoteId,job_id:job.id,candidate_id:topic.candidate_id,
    record_key:record.key,record_type:'review',
    title_at_adjudication:record.title,source:record.source,
    decision:'DOCUMENTED_OVERLAP',
    evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    documented_last_search_date:'2024-08-30',
    rationale:'Published methods show matching PICO with a dated search',
    created_at:new Date(Date.now()+60000).toISOString(),
  },{
    id:randomUUID(),job_id:'ANOTHER-JOB',candidate_id:topic.candidate_id,
    record_key:'review|unrelated',decision:'DOCUMENTED_NON_OVERLAP',
    rationale:'Other browser scoped job',created_at:'2026-11-24T14:00:00Z',
  }]);
  const result = gap.read(job,topic);
  assert.equal(result.history.length,2);
  assert.equal(result.decisions[record.key].decision,'DOCUMENTED_OVERLAP');
  const pending = gap.assignPendingIds(job,topic);
  gap.markCloudSynced(job,topic,pending[0].id);
  assert.equal(gap.assignPendingIds(job,topic).length,0);
  assert.equal(gap.read(job,topic).history.length,2);
  assert.equal(topic.qualification_status,'PROVISIONAL_BACKUP');
});

test('Cached reassessment never clears unresolved sources or qualifies a topic', () => {
  const {gap} = setup();
  const candidate = structuredClone(topic);
  const evidence = gap.evidenceOf(candidate);
  for(const record of evidence) {
    assert.equal(gap.saveDecision(job,candidate,record,{
      decision:'DOCUMENTED_NON_OVERLAP',
      evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
      rationale:'Manual source review suggests no overlap for this PICO',
    }).ok,true);
  }
  const result = gap.reassess(job,candidate);
  assert.equal(result.status,'SOURCE_COVERAGE_INCOMPLETE');
  assert.equal(result.scientific_qualification_changed,false);
  assert.equal(result.search_queries_reexecuted,false);
  assert.equal(result.full_text_eligible_independent_studies,'NOT_VERIFIED');
  assert.ok(result.unresolved_citations.review > 0);
  assert.ok(result.unresolved_citations.registration > 0);
  assert.match(gap.reassessmentHtml(result),/Original source blockers/);
  const output = gap.exportLedger(job,candidate);
  assert.equal(output.cached_reassessment.status,'SOURCE_COVERAGE_INCOMPLETE');
});

test('Cached reassessment with missing coverage metadata is unknown, not a zero', () => {
  const {gap} = setup();
  const missing = {candidate_id:'MISSING',title:'Sparse prior topic',qualification_status:'PROVISIONAL_BACKUP'};
  const report = gap.reassess(job,missing);
  assert.equal(report.status,'SOURCE_COVERAGE_INCOMPLETE');
  assert.equal(report.unresolved_citations.review,null);
  assert.equal(report.unresolved_citations.registration,null);
});

test('Existing local event ids are stable across retry and cloud acknowledgement', () => {
  const {gap} = setup();
  const candidate = structuredClone(topic);
  const row = gap.evidenceOf(candidate)[0];
  const saved = gap.saveDecision(job,candidate,row,{
    decision:'NEEDS_FULL_TEXT', evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    rationale:'Clinical decision endpoint is not reported in the citation',
  });
  assert.equal(saved.ok,true);
  const first = gap.assignPendingIds(job,candidate)[0];
  const second = gap.assignPendingIds(job,candidate)[0];
  assert.equal(first.id,second.id);
  assert.match(first.id,/^[0-9a-f-]{36}$/i);
  gap.markCloudSynced(job,candidate,first.id);
  assert.equal(gap.assignPendingIds(job,candidate).length,0);
});

test('Saved citation shortlist never masquerades as complete source inventory', () => {
  const {gap} = setup();
  const example = structuredClone(topic);
  const screening = example.research_dossier.verification_and_quality.competing_review_screening;
  screening.registration_records_discovered = 113;
  screening.unassessed_registration_queue = Array.from({length:40}, (_,i)=>({
    record_id:'REG'+i, title:'Registry protocol '+i,
    source:'OSF Registries', url:'https://osf.io/'+(i+1000),
  }));
  example.research_dossier.registration_evidence = [];
  const html = gap.render(job,example);
  assert.match(html,/PROSPERO and OSF registrations \(40 saved citations; 14 shown\)/);
  assert.match(html,/26 additional saved citations are included in the JSON export/);
  assert.match(html,/exceeds the saved citation list by 73 hits/);
  assert.match(html,/NOT individually available here or in this export/);
  const ledger = gap.exportLedger(job,example);
  assert.equal(ledger.bibliographic_export_inventory.registrations.saved_citations,40);
  assert.equal(ledger.bibliographic_export_inventory.registrations.reported_source_hits,113);
  assert.equal(ledger.bibliographic_export_inventory.registrations.unrepresented_hit_difference,73);
  assert.equal(ledger.qualification_automatically_modified,false);
});

test('Full competitor packet is paginated and remains available in JSON export',()=>{
  const {gap}=setup();
  const t=structuredClone(topic);
  t.research_dossier.study_centric_adjudication={competitor_index:[
    ...Array.from({length:45},(_,i)=>({kind:'REVIEW',source:'PubMed',record_id:'FULL'+i,title:'Full review '+String(i).padStart(2,'0'),url:'https://pubmed.ncbi.nlm.nih.gov/'+(1000+i)+'/',doi:[]})),
    ...Array.from({length:18},(_,i)=>({kind:'REGISTRATION',source:'PROSPERO',record_id:'REGFULL'+i,title:'Protocol '+String(i).padStart(2,'0'),url:'https://www.crd.york.ac.uk/PROSPERO/view/CRD'+(1000+i),doi:[]})),
    {kind:'UNCLASSIFIED',source:'Other',record_id:'UNKNOWN',title:'Unknown record',doi:[]}
  ]};
  const records=gap.evidenceOf(t);
  assert.equal(records.filter(x=>x.kind==='review').length,47);
  assert.equal(records.filter(x=>x.kind==='registration').length,19);
  const first=gap.render(job,t),next=gap.render(job,t,{review:14,registration:14});
  assert.match(first,/data-gap-queue-kind="review"/);
  assert.match(next,/15–28 of 47/);
  assert.match(next,/15–19 of 19/);
  assert.match(next,/data-gap-page="0"/);
  const ledger=gap.exportLedger(job,t);
  assert.equal(ledger.bibliographic_candidates_ordered_for_manual_review.length,66);
  assert.equal(ledger.qualification_automatically_modified,false);
  assert.equal(t.qualification_status,'PROVISIONAL_BACKUP');
});
