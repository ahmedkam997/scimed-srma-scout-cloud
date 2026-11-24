import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const app=readFileSync('web/app.js','utf8');
const edge=readFileSync('supabase/functions/wake-discovery-worker/index.ts','utf8');
const gap=readFileSync('web/gap-verification.js','utf8');
const sql=readFileSync('sql/2026-11-24_recheck_dispatch_rpc.sql','utf8');

function isolated(invoke){
  const start=app.indexOf('async function wakeSourceRecheck(recheckId) {');
  const end=app.indexOf('async function requestTargetedRecheck(job, topic) {',start);
  assert.ok(start>=0 && end>start);
  const code=app.slice(start,end);
  return runInNewContext('const supabase={functions:{invoke:globalInvoke}};'+
    'function deviceToken(){return "a".repeat(64);}\n'+code+
    '\n({wakeSourceRecheck});',{globalInvoke:invoke});
}
const id='8f5f4cd7-a382-43da-95cb-71eaec5d5e44';
test('New source recheck dispatch is passed by ID and owner token, never Github PAT',async()=>{
  const observed=[];
  const {wakeSourceRecheck}=isolated(async(name,args)=>{
    observed.push({name,args});
    return {data:{status:'dispatched'},error:null};
  });
  const result=await wakeSourceRecheck(id);
  assert.equal(result.dispatched,true);
  assert.equal(observed[0].name,'wake-discovery-worker');
  assert.equal(observed[0].args.body.recheck_id,id);
  assert.equal(observed[0].args.headers['x-scimed-client-token'].length,64);
  assert.doesNotMatch(app,/SCIMED_GITHUB_DISPATCH_TOKEN\s*=/);
});
test('No false success if Edge dispatch is unconfigured',async()=>{
  const {wakeSourceRecheck}=isolated(async()=>({
    data:null,error:{context:{json:async()=>({status:'configuration_required'})}},
  }));
  const result=await wakeSourceRecheck(id);
  assert.equal(result.dispatched,false);
  assert.match(result.message,/SCIMED_GITHUB_DISPATCH_TOKEN/);
});
test('Client explicitly wakes an existing queued recheck',()=>{
  assert.match(gap,/data-source-wake/);
  assert.match(app,/event.target.closest\('\[data-source-wake\]'\)/);
  assert.match(app,/await wakeSourceRecheck\(wakeButton.dataset.sourceWake\)/);
});
test('Source-only SQL cooldown and browser-owned RLS do not grant scientific updates',()=>{
  assert.match(sql,/dispatch_requested_at/);
  assert.match(sql,/private.scimed_client_hash\(\)/);
  assert.match(sql,/interval '120 seconds'/);
  assert.match(sql,/to_jsonb\(new\)-'dispatch_requested_at'/);
  assert.match(sql,/security invoker/);
  assert.doesNotMatch(sql,/security definer/i);
});
test('Existing discovery dispatch remains supported by the Edge Function',()=>{
  assert.match(edge,/scimed_request_dispatch/);
  assert.match(edge,/scimed_request_recheck_dispatch/);
  assert.match(edge,/p_recheck_id: requestedId/);
  assert.match(edge,/p_job_id: requestedId/);
  assert.match(edge,/hasJob === hasRecheck/);
  assert.doesNotMatch(edge,/service_role/);
});
