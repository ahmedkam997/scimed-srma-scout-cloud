import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync('web/app.js','utf8');
const start = source.indexOf('function completedGapTopics(job) {');
const end = source.indexOf('function safeEvidenceLink(record) {',start);
assert.ok(start > 0 && end > start,'Cloud gap synchronization functions must exist');
const functions = source.slice(start,end);

function setup({insertError=null, cloudRows=[]}={}) {
  const sent=[];
  const pending = [{
    id:'11111111-1111-4111-8111-111111111111',
    record_key:'review|123', record_type:'review',
    title_at_adjudication:'Published review',source:'PubMed',
    decision:'NEEDS_FULL_TEXT',
    evidence_url:'https://pubmed.ncbi.nlm.nih.gov/123/',
    documented_last_search_date:null,
    rationale:'Source only contains a preliminary abstract',
  }];
  const downloads=[];
  const client={
    from(table) {
      assert.equal(table,'scimed_gap_verification_events');
      return {
        insert:async row=>{sent.push(row);return {error:insertError};},
        select:() => ({
          in:() => ({
            order:() => ({
              limit:async()=>({data:cloudRows,error:null}),
            }),
          }),
        }),
      };
    },
  };
  const gap={
    assignPendingIds:()=>pending.slice(),
    markCloudSynced:(_job,_topic,id)=>{
      const k=pending.findIndex(v=>v.id===id);
      if(k>=0)pending.splice(k,1);
    },
    setCloudEvents:rows=>downloads.push(rows),
  };
  const context={
    supabase:client,
    window:{SCIMED_GAP:gap},
    jobs:[{
      id:'JOB-1', status:'COMPLETED',
      result_json:{package:{provisional_options:[{candidate_id:'TOP-1'}]}},
    }],
    lastGapLoadedAt:0,
    gapSyncError:'',
    renderJobs:()=>{},
    Date,
  };
  const exports=runInNewContext(
    'let supabase=globalClient;let jobs=globalJobs;'+
    'let lastGapLoadedAt=0;let gapSyncError="";'+
    functions+
    '\n({syncGapNotes,loadGapEvents,completedGapTopics,getError:()=>gapSyncError});',
    {
      globalClient:client,globalJobs:context.jobs,
      window:context.window,renderJobs:()=>{},Date,
    },
  );
  return {...exports, sent, pending, downloads, jobs:context.jobs};
}

test('Pending local note is uploaded once to the cloud and acknowledged',async()=>{
  const r=setup();
  const job=r.jobs[0],topic=job.result_json.package.provisional_options[0];
  const first=await r.syncGapNotes(job,topic);
  const second=await r.syncGapNotes(job,topic);
  assert.equal(first.synced,1);
  assert.equal(second.synced,0);
  assert.equal(r.sent.length,1);
  assert.equal(r.sent[0].job_id,'JOB-1');
  assert.equal(r.sent[0].candidate_id,'TOP-1');
  assert.equal(r.pending.length,0);
});

test('RLS failure never marks local evidence synchronized',async()=>{
  const r=setup({insertError:{code:'42501',message:'permission denied by row-level security'}});
  const p=await r.syncGapNotes(r.jobs[0],r.jobs[0].result_json.package.provisional_options[0]);
  assert.equal(p.synced,0);
  assert.match(p.error,/permission denied/);
  assert.equal(r.pending.length,1);
});

test('Duplicate UUID acknowledgment is treated as previous successful append, not an upsert',async()=>{
  const r=setup({insertError:{code:'23505',message:'duplicate id'}});
  const p=await r.syncGapNotes(r.jobs[0],r.jobs[0].result_json.package.provisional_options[0]);
  assert.equal(p.synced,1);
  assert.equal(r.pending.length,0);
});

test('Cloud refresh merges downloaded notes and does not skip work after one failed upload',async()=>{
  const item={id:'b',job_id:'JOB-1',candidate_id:'TOP-1',record_key:'review|123'};
  const r=setup({insertError:{code:'42501',message:'RLS denied'},cloudRows:[item]});
  await r.loadGapEvents(true);
  assert.equal(r.downloads.length,1);
  assert.equal(r.downloads[0][0].id,'b');
  assert.match(r.getError(),/RLS denied/);
  assert.equal(r.pending.length,1);
});
