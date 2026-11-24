import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {randomUUID} from 'node:crypto';
import {runInNewContext} from 'node:vm';

const code=readFileSync('web/gap-verification.js','utf8');
const app=readFileSync('web/app.js','utf8');
const html=readFileSync('web/index.html','utf8');
const sw=readFileSync('web/sw.js','utf8');
function setup(){
 const window={};
 const localStorage={getItem:()=>null,setItem:()=>{}};
 runInNewContext(code,{window,localStorage,URL,Date,Set,Map,crypto:{randomUUID}});
 return window.SCIMED_GAP;
}
const job={id:'JOB-1',status:'COMPLETED'};
const topic={
 candidate_id:'PICO-A',title:'LAAO versus DOACs in ESRD',
 research_dossier:{
  scientific_question:{
   population:'Adults with atrial fibrillation and ESRD',
   intervention_exposure_index_test:'LAAO',
   comparator_reference:'DOACs',outcomes:['stroke'],
  },
  verification_and_quality:{
   source_statuses:{PubMed:'SEARCHED_POSITIVE',PROSPERO:'PARTIAL',
                    OpenAlex:'ACCESS_FAILED'},
   competing_review_screening:{published_review_records_discovered:0,
                                registration_records_discovered:0},
  },
 },
};
test('The targeted source recheck UI uses failed sources from the saved PICO',()=>{
 const gap=setup();
 const rendered=gap.render(job,topic);
 assert.match(rendered,/Targeted Source Recheck/);
 assert.match(rendered,/PROSPERO \(PARTIAL\)/);
 assert.match(rendered,/OpenAlex \(ACCESS_FAILED\)/);
 assert.doesNotMatch(rendered,/PubMed \(PARTIAL\)/);
 assert.match(rendered,/data-source-recheck="JOB-1"/);
 assert.match(rendered,/data-gap-topic="PICO-A"/);
});
test('One active recheck prevents duplicate requests in the user interface',()=>{
 const gap=setup();
 gap.setSourceRechecks([{
  id:'R1',job_id:job.id,candidate_id:topic.candidate_id,
  status:'RUNNING',message:'Checking PROSPERO',
  created_at:'2026-11-24T10:00:00Z',
 }]);
 const rendered=gap.sourceRecheckHtml(job,topic);
 assert.match(rendered,/Targeted Source Recheck · RUNNING/);
 assert.match(rendered,/data-source-recheck="JOB-1"[^>]* disabled/);
});
test('Completed source reports retain original statuses and never claim qualification',()=>{
 const gap=setup();
 gap.setSourceRechecks([{
  id:'R1',job_id:job.id,candidate_id:topic.candidate_id,status:'COMPLETED',
  message:'Source recheck completed',
  created_at:'2026-11-24T10:00:00Z',
  result_json:{
   original_source_statuses:{PROSPERO:'PARTIAL'},
   qualification_status_unchanged:true,
   source_reports:[{
    source:'PROSPERO',previous_status:'PARTIAL',
    targeted_search_status:'TARGETED_QUERIES_INCOMPLETE',
    attempted_queries:[{
     evidence_type:'REGISTRATION',query:'LAAO AF ESRD',
     status:'PARTIAL',total_count:120,
     message:'Results incomplete',
     citations:[{
      title:'Trial protocol',source:'PROSPERO',url:'https://osf.io/abc123',
     }],
    }],
   }],
  },
 }]);
 const rendered=gap.sourceRecheckHtml(job,topic);
 assert.match(rendered,/TARGETED_QUERIES_INCOMPLETE/);
 assert.match(rendered,/Previous source status: PARTIAL/);
 assert.match(rendered,/LAAO AF ESRD/);
 assert.match(rendered,/Original source flags remain unchanged/);
 assert.equal(topic.qualification_status,undefined);
});
test('The app uses a dedicated table rather than mutating discovery_jobs for recheck results',()=>{
 assert.match(app,/from\('scimed_source_rechecks'\)/);
 assert.match(app,/async function requestTargetedRecheck/);
 assert.match(app,/await loadSourceRechecks\(\)/);
 assert.match(app,/data-source-recheck/);
 assert.match(html,/gap-verification\.js\?v=/);
 assert.match(sw,/gap-verification\.js\?v=/);
});
