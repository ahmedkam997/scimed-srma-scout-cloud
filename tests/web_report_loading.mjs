import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
const app=readFileSync('web/app.js','utf8');
const start=app.indexOf('function hasCurrentReport(');
const end=app.indexOf('async function loadJobReport(',start);
const pstart=app.indexOf('function reportPayload(');
const pend=app.indexOf('const LEGACY_CHATGPT_TOPIC_PROMPT',pstart);
function isolated(job,reply){
 const jobs=[job], openedReports=new Map();
 const supabase={from:()=>({select:()=>({eq:()=>({single:async()=>reply})})})};
 return runInNewContext(app.slice(start,end)+app.slice(pstart,pend)+'\n({hasCurrentReport,fetchLatestJobReport,reportPayload})',{jobs,openedReports,supabase});
}
test('Completed status-only job cannot export an empty report',()=>{
 const job={id:'J',status:'COMPLETED',updated_at:'final'};
 const f=isolated(job,{});
 assert.equal(f.hasCurrentReport(job),false);
 assert.throws(()=>f.reportPayload(job),/Load the completed cloud report/);
});
test('Fresh cloud result replaces stale checkpoint and preserves all provisional topics',async()=>{
 const job={id:'J',status:'COMPLETED',updated_at:'final',reportLoadedAt:'old',result_json:{checkpoint:{candidates:[]}}};
 const final={package:{options:[],provisional_options:[{candidate_id:'1'},{candidate_id:'2'}]},run_summary:{candidate_audits:[{candidate_id:'1'},{candidate_id:'2'}]}};
 const f=isolated(job,{data:{id:'J',updated_at:'final',result_json:final,error_text:''}});
 assert.equal(f.hasCurrentReport(job),false);
 const loaded=await f.fetchLatestJobReport('J');
 assert.equal(f.hasCurrentReport(loaded),true);
 assert.equal(f.reportPayload(loaded).provisional_options.length,2);
 assert.equal(f.reportPayload(loaded).summary.candidate_audits.length,2);
});
test('Incomplete final result never silently exports',async()=>{
 const f=isolated({id:'J',status:'COMPLETED'}, {data:{result_json:{checkpoint:{}}}});
 await assert.rejects(f.fetchLatestJobReport('J'),/missing final results/);
});
test('Both export actions retrieve current cloud report before serialization',()=>{
 for(const name of ['copyJob','downloadJob']){
  const start=app.indexOf('async function '+name+'(');
  assert.ok(start>=0);
  assert.ok(app.slice(start,start+400).includes('await fetchLatestJobReport(jobId)'));
 }
});
