import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source=readFileSync('web/app.js','utf8');
const start=source.indexOf('function clinicalWords(');
const end=source.indexOf('function renderJobs()',start);
assert.ok(start>=0 && end>start);
const uniqueProvisionalTopics=runInNewContext(
  source.slice(start,end)+'\nuniqueProvisionalTopics;', {}
);

function sample(id,title,population,intervention,comparator,outcomes,question_type) {
  return {candidate_id:id,title,population,intervention_exposure_index_test:intervention,
    comparator_reference:comparator,outcomes,question_type};
}

test('Group the two AF and ketone pairs from the actual Cardiology report',()=>{
  const afA=sample('af-a',
    'Effectiveness of adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation',
    'Adults with persistent atrial fibrillation undergoing catheter ablation',
    'Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation',
    'Pulmonary-vein isolation alone',
    ['Freedom from atrial fibrillation at 12 months','Procedure-related complications','Quality of life scores'],
    'Systematic review/meta-analysis');
  const afB=sample('af-b',
    'Adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation',
    'Adults with persistent atrial fibrillation undergoing catheter ablation',
    'Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation',
    'Pulmonary-vein isolation alone',
    ['Freedom from atrial fibrillation at 12 months','Procedural complications','Quality of life'],
    'Intervention');
  const ketoneA=sample('k-a',
    'Ketone Monoester Ingestion and Cardiovascular Response During Heat Stress Exercise in Endurance Athletes',
    'Endurance athletes (male or female) performing exercise in heat',
    'Ketone monoester ingestion','Placebo or no supplementation',
    ['Heart rate','Blood pressure','Cardiac output'],'Systematic Review / Meta-Analysis');
  const ketoneB=sample('k-b',
    'Impact of ketone monoester ingestion on cardiovascular response during heat-stress exercise in endurance athletes',
    'Endurance athletes performing heat-stress exercise',
    'Ketone monoester ingestion','Placebo',
    ['Heart rate','Blood pressure','Core temperature'],'Meta-analysis of RCTs');
  const other=sample('other','Inclisiran versus statin therapy for secondary prevention',
    'Adults with atherosclerotic cardiovascular disease',
    'Inclisiran','High intensity statin therapy',
    ['Major adverse cardiovascular events'],'Intervention');
  const rows=[afA,other,afB,ketoneA,ketoneB];
  const distinct=uniqueProvisionalTopics(rows);
  assert.equal(distinct.length,3);
  assert.deepEqual(Array.from(distinct,x=>x.candidate_id),['af-a','other','k-a']);
});

test('A clinically different comparator remains a distinct PICO',()=>{
  const base=sample('a','Drug X versus placebo for heart failure',
    'Adults with heart failure','Drug X','Placebo',['Mortality'],'Intervention');
  const changed=sample('b','Drug X versus standard therapy for heart failure',
    'Adults with heart failure','Drug X','Standard therapy',['Mortality'],'Intervention');
  assert.equal(uniqueProvisionalTopics([base,changed]).length,2);
});


const registrationDisplayRelevance=runInNewContext(
  source.slice(start,end)+'\nregistrationDisplayRelevance;', {}
);

test('Unrelated dental implant and breastfeeding PROSPERO hits are not presented as direct ketone competitors',()=>{
  const topic={title:'Ketone monoester supplementation and cardiovascular heat stress',
    intervention_exposure_index_test:'Ketone Monoester Supplementation',
    population:'Endurance athletes'};
  const unrelated=[
    'Effect of Vitamin D Supplementation versus No Supplementation on Dental Implant Stability',
    'In breastfeeding mothers what is the effect of herbal supplementation on milk supply',
    'Effects of protein and amino acid supplementation in chronic heart failure',
  ];
  unrelated.forEach(title=>{
    const match=registrationDisplayRelevance(topic,{title});
    assert.equal(match.kind,'BROAD_SEARCH_HIT');
    assert.ok(match.anchor.includes('ketone'));
    assert.ok(match.anchor.includes('monoester'));
  });
  const related=registrationDisplayRelevance(topic,{
    title:'Ketone monoester ingestion during heat stress exercise in endurance runners'
  });
  assert.equal(related.kind,'INTERVENTION_ANCHOR_MATCH');
});

test('Generic interventions remain uncertain rather than being excluded',()=>{
  const topic={intervention_exposure_index_test:'Standard care'};
  const match=registrationDisplayRelevance(topic,{
    title:'Standard care in surgical randomized trials'
  });
  assert.equal(match.kind,'UNCERTAIN');
});
