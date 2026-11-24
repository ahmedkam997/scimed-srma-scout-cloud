import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';

const seedSource=readFileSync('web/final-audit-evidence.js','utf8');
const engineSource=readFileSync('web/final-evidence-audit.js','utf8');
const KEY='4d10637b-b367-474c-b588-770b5834764b';
const CT='CAND-090E5F562A951667';
function create(){
  const window={};
  const sandbox={window,URL,Date,Set,Map};
  runInNewContext(seedSource,sandbox);
  runInNewContext(engineSource,sandbox);
  return {w:window,e:window.SCIMED_FINAL};
}
function ctTopic(){
  return {
    candidate_id:CT,title:'Computed Tomography Fractional Flow Reserve in Left Main Disease',
    qualification_status:'PROVISIONAL_BACKUP',
    discovered_primary_study_candidates:58,
    research_dossier:{
      scientific_question:{
        question_type:'DIAGNOSTIC_TEST_ACCURACY',
        population:'Adults with intermediate left main stenosis on CTA',
        intervention_exposure_index_test:'CT-derived fractional flow reserve (FFR-CT)',
        comparator_reference:'Invasive fractional flow reserve measurements',
        eligible_designs:['Diagnostic accuracy study','Prospective cohort study'],
        outcomes:['Sensitivity','Specificity','Diagnostic odds ratio'],
      },
      verification_and_quality:{
        source_statuses:{OpenAlex:'ACCESS_FAILED','Europe PMC':'PARTIAL',
          'Semantic Scholar':'PARTIAL','ClinicalTrials.gov':'NOT_SEARCHED'},
        competing_review_screening:{
          published_review_records_discovered:21,
          registration_records_discovered:52,
        },
      },
    },
  };
}
const job={id:KEY,status:'COMPLETED'};
const emptyGap={read:()=>({decisions:{}}),rechecksOf:()=>[]};

test('Uploaded FFR-CT DTA PICO produces no DOAC or dialysis-only scientific gates',()=>{
  const {e}=create();
  const topic=ctTopic();
  const result=e.build(job,topic,emptyGap);
  assert.equal(result.question_type_verified_from_saved_pico,'DIAGNOSTIC_TEST_ACCURACY');
  assert.equal(result.audit_rules_version,'2026-11-24-question-specific-gates-v2');
  const all=result.scientific_gates_unresolved.map(x=>x.gate+' '+x.reason).join(' ');
  assert.doesNotMatch(all,/DOAC|dialysis.only|warfarin/i);
  assert.match(all,/INDEX_TEST_REFERENCE_STANDARD_AND_2X2_DATA/);
  assert.match(all,/TP\/FP\/FN\/TN/);
  assert.match(all,/QUADAS_3_AND_DTA_SYNTHESIS_FEASIBILITY/);
  assert.match(all,/patient\/vessel\/lesion/);
  assert.equal(result.eligible_independent_study_count,null);
  assert.equal(result.primary_study_count_from_bibliography_NOT_ELIGIBLE,58);
  assert.equal(result.published_review_source_hits,21);
  assert.equal(result.registration_source_hits,52);
  assert.equal(topic.qualification_status,'PROVISIONAL_BACKUP');
});
test('CT-FFR left main case is research-triaged and distinguishes invasive FFR from angiographic comparison',()=>{
  const {e}=create();
  const result=e.build(job,ctTopic(),emptyGap);
  assert.equal(result.recommendation,'REFINE');
  assert.equal(result.registration_recommendation,'DO_NOT_REGISTER_NOW');
  assert.ok(result.study_family_screening_ledger.length>=3);
  assert.ok(result.study_family_screening_ledger.every(x=>x.fulltext_eligibility_verified===false));
  const tavi=result.study_family_screening_ledger.find(s=>/PRE_TAVI/.test(s.family));
  assert.equal(tavi.targeted_fit,'INDEX_TEST_REFERENCE_STANDARD_MISMATCH');
  assert.equal(result.eligible_independent_study_count,null);
  assert.equal(result.direct_comparator_reports_identified_in_curated_audit,0);
  assert.equal(result.studied_full_text_eligible_independent_populations_verified_in_this_audit,0);
  assert.ok(result.evidence_methods.some(s=>s.name.includes('PRISMA-DTA')));
  assert.ok(result.evidence_methods.some(s=>s.name.includes('QUADAS-3')));
  assert.match(e.render(job,ctTopic(),emptyGap),/DTA|DIAGNOSTIC_TEST_ACCURACY/);
});
test('The 2026 expert consensus caution is source-linked, not a fabricated primary-study eligibility decision',()=>{
  const {e}=create();
  const result=e.build(job,ctTopic(),emptyGap);
  const guidance=result.evidence_methods.find(s=>s.name.includes('SCCT/SCAI 2026'));
  assert.ok(guidance.url.startsWith('https://www.journalofcardiovascularct.com/'));
  assert.equal(result.source_search_reexecuted,false);
  assert.equal(result.full_text_screening_performed_by_this_feature,false);
  assert.equal(result.count_is_not_exhaustive,true);
  assert.ok(result.study_family_screening_ledger.every(s=>s.endpoint_extraction_verified===false));
});
test('The same audit engine handles a non-curated generic diagnostic question',()=>{
  const {e}=create();
  const t={candidate_id:'UNRESEARCHED',title:'MRI index test for a condition',
    research_dossier:{scientific_question:{
      population:'Adults',intervention_exposure_index_test:'MRI',
      comparator_reference:'Reference histology',
      outcomes:['Sensitivity','Specificity'],
    }}};
  const a=e.build({id:'OTHER',status:'COMPLETED'},t,emptyGap);
  assert.equal(a.question_type_verified_from_saved_pico,'DIAGNOSTIC_TEST_ACCURACY');
  assert.equal(a.recommendation,'UNRESOLVED');
  assert.equal(a.external_research_curated_as_of,null);
  assert.equal(a.eligible_independent_study_count,null);
  assert.ok(a.scientific_gates_unresolved.some(g=>g.gate==='INDEX_TEST_REFERENCE_STANDARD_AND_2X2_DATA'));
});
test('Comparative intervention question retains intervention-specific gates and source-linked LAAO data',()=>{
  const {e}=create();
  const t={
    candidate_id:'CAND-BCD199B816F41CFC',title:'LAAO versus DOACs in ESRD',
    qualification_status:'PROVISIONAL_BACKUP',
    research_dossier:{scientific_question:{
      population:'ESRD with atrial fibrillation',
      intervention_exposure_index_test:'Left atrial appendage occlusion',
      comparator_reference:'Direct oral anticoagulants',
      outcomes:['Stroke','bleeding'],
    }},
  };
  const result=e.build(job,t,emptyGap);
  assert.equal(result.question_type_verified_from_saved_pico,'COMPARATIVE_INTERVENTION');
  assert.ok(result.scientific_gates_unresolved.some(g=>g.gate==='PICO_MATCHED_COMPARATIVE_OUTCOME_EXTRACTION'));
  assert.equal(result.direct_comparator_reports_identified_in_curated_audit,1);
  assert.equal(result.recommendation,'REFINE');
  assert.equal(result.eligible_independent_study_count,null);
});
test('No universal four-study methodological threshold is asserted',()=>{
  const {e}=create();
  const audit=e.build(job,ctTopic(),emptyGap);
  assert.equal(audit.minimum_independent_study_target_for_scout,4);
  assert.equal(audit.minimum_target_is_methodological_requirement,false);
  assert.ok(audit.scientific_gates_unresolved.some(g=>g.gate==='INDEPENDENT_ELIGIBLE_STUDY_FAMILIES'));
  assert.ok(audit.scientific_gates_unresolved.every(g=>g.status==='UNRESOLVED'));
});
