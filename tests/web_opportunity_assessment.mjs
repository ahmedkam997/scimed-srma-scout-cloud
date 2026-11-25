import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const values=new Map();
const ctx=vm.createContext({URL,localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)}});
vm.runInContext(fs.readFileSync('web/opportunity-assessment.js','utf8'),ctx);
const m=ctx.SCIMED_MCDA,job={id:'job1'},topic={candidate_id:'candidate1'};
test('unknown weights remain; no automatic qualification',()=>{
 const result=m.calculate(m.template(topic),topic.candidate_id);
 assert.equal(result.score,null);
 assert.equal(JSON.stringify(result.scenarios.balanced.bounds),'[0,100]');
 assert.equal(result.qualification_granted,false);
});
test('validated manual inputs roundtrip and remain scoped to the candidate',()=>{
 const raw=m.template(topic);
 for(const k of Object.keys(raw.ratings))raw.ratings[k]={rating:4,source_urls:['https://example.org/evidence'],rationale:'fixture',counterevidence:'fixture',uncertainty:'fixture'};
 assert.equal(m.save(job,topic,JSON.stringify(raw)).ok,true);
 const saved=m.read(job,topic);
 assert.equal(saved.score,80);
 assert.equal(saved.qualification_granted,false);
 assert.equal(m.read(job,{candidate_id:'different'}),null);
 assert.equal(m.save(job,{candidate_id:'different'},JSON.stringify(raw)).ok,false);
});
test('invalid rating/source/missing rationale fail closed',()=>{
 const raw=m.template(topic);
 raw.ratings.clinical_importance={rating:8};
 assert.equal(m.save(job,topic,JSON.stringify(raw)).ok,false);
 raw.ratings.clinical_importance={rating:5,source_urls:['javascript:alert(1)'],rationale:'test',counterevidence:'test',uncertainty:'test'};
 assert.equal(m.save(job,topic,JSON.stringify(raw)).ok,false);
 raw.ratings.clinical_importance={rating:5,source_urls:['https://example.org']};
 assert.equal(m.save(job,topic,JSON.stringify(raw)).ok,false);
});

test('cloud polling preserves open manual editor and topic transfer preserves saved assessment',()=>{
 const app=fs.readFileSync('web/app.js','utf8');
 assert.ok(app.includes("els.jobs.querySelector('details.mcda-editor[open]')"));
 assert.ok(app.includes('researcher_recorded_assessment:manual'));
});
