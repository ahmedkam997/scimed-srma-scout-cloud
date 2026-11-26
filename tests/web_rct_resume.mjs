import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const app=fs.readFileSync('web/app.js','utf8');
const fn=app.slice(app.indexOf('async function retryJob('),app.indexOf('async function cancelJob('));
function fixture(job,other=[],answer=true){
 const calls=[],feedback=[],cleared=[];
 const ctx={jobs:[job,...other],hasCurrentReport:j=>j.current===true,window:{confirm:()=>true},
 els:{jobs:{querySelectorAll:()=>[]}},supabase:{rpc:async(name,args)=>{calls.push([name,args]);return {data:answer};}},
 openedReports:{delete:id=>cleared.push(id)},loadJobs:async()=>{},wakeWorker:async()=>{},
 backendState:(...a)=>feedback.push(a)};
 vm.runInNewContext(fn,ctx);
 return {ctx,calls,feedback,cleared};
}
test('completed current report resumes same job via owner-scoped RPC',async()=>{
 const f=fixture({id:'x',status:'COMPLETED',current:true,result_json:{run_summary:{resume_eligible:true}}});
 await f.ctx.retryJob('x');assert.equal(f.calls[0][0],'scimed_resume_rct_job');assert.equal(f.calls[0][1].p_job_id,'x');assert.deepEqual(f.cleared,['x']);
});
test('manual-only, stale or active matching job does not requeue',async()=>{
 for(const job of [{id:'x',status:'COMPLETED',current:true,result_json:{run_summary:{resume_eligible:false}}},{id:'x',status:'COMPLETED',current:false,result_json:{run_summary:{resume_eligible:true}}}]){
 const f=fixture(job);await f.ctx.retryJob('x');assert.equal(f.calls.length,0);
 }
 const f=fixture({id:'x',status:'COMPLETED',current:true,specialty:'Cardiology',question_type:'ALL',result_json:{run_summary:{resume_eligible:true}}},[{id:'y',status:'RUNNING',specialty:'Cardiology',question_type:'ALL'}]);
 await f.ctx.retryJob('x');assert.equal(f.calls.length,0);
});
test('failed job retains existing retry RPC',async()=>{
 const f=fixture({id:'x',status:'FAILED'});await f.ctx.retryJob('x');assert.equal(f.calls[0][0],'scimed_retry_job');
});
