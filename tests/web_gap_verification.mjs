import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
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
  runInNewContext(source, {window, localStorage, URL, Date, Set, Map});
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
