/* Local source-linked researcher input. Does not authenticate sources,
   modify cloud status, or decide scientific eligibility. */
(function(root){
  'use strict';
  const weights={clinical_importance:15,research_gap_novelty:20,information_gain:20,evidence_readiness:15,methodological_feasibility:15,timeliness:5,operational_feasibility:5,editorial_relevance:5};
  const keys=Object.keys(weights);
  const vectors={balanced:Object.values(weights),novelty_information:[10,25,25,10,15,5,5,5],readiness_feasibility:[10,15,15,25,20,5,5,5],equal:keys.map(()=>12.5)};
  const VERSION='SCIMED_MANUAL_MCDA_V2';
  const key=(job,topic)=>'scimed.mcda.v2:'+encodeURIComponent(job.id)+':'+encodeURIComponent(topic.candidate_id);
  function validURL(v){try {const u=new URL(v);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password;}catch{return false;}}
  function template(topic){
    return {candidate_id:topic.candidate_id,ratings:Object.fromEntries(keys.map(k=>[k,{rating:null,source_urls:[],rationale:'',counterevidence:'',uncertainty:''}]))};
  }
  function calculate(input,candidateId){
    if(!input || input.candidate_id!==candidateId || !input.ratings || typeof input.ratings!=='object' || Array.isArray(input.ratings))throw Error('Candidate ID must match this topic; include a ratings object.');
    if(Object.keys(input.ratings).some(k=>!keys.includes(k)))throw Error('Unknown assessment domain.');
    const domains={},ratings={};
    for(const k of keys){
      const r=input.ratings[k]??{};
      if(!r||typeof r!=='object'||Array.isArray(r))throw Error(k+': expected an object.');
      const n=r.rating??null;
      const urls=Array.isArray(r.source_urls)?r.source_urls:[];
      if(n!==null&&(!Number.isFinite(n)||typeof n!=='number'||n<0||n>5))throw Error(k+': use a number 0–5 or null.');
      if(urls.length>20||urls.some(u=>typeof u!=='string'||!validURL(u)))throw Error(k+': provide valid HTTP(S) evidence URLs.');
      const fields={};for(const f of ['rationale','counterevidence','uncertainty']){
        if(r[f]!==undefined&&typeof r[f]!=='string')throw Error(k+': '+f+' must be text.');
        fields[f]=(r[f]||'').trim();if(fields[f].length>4000)throw Error(k+': text too long.');
      }
      if(n!==null&&(!urls.length||!fields.rationale||!fields.counterevidence||!fields.uncertainty))throw Error(k+': scored inputs need sources, rationale, counterevidence and uncertainty. Use null if not resolved.');
      ratings[k]={rating:n,source_urls:urls,...fields};
      domains[k]={...ratings[k],weight:weights[k],status:n===null?'UNKNOWN':'RESEARCHER_RECORDED_NOT_AUTHENTICATED',weighted_contribution:n===null?null:Math.round(weights[k]*n/5*100)/100};
    }
    const scenarios={};
    for(const [name,vec] of Object.entries(vectors)){
      let lo=0,missing=0;keys.forEach((k,i)=>{const n=ratings[k].rating;if(n===null)missing+=vec[i];else lo+=vec[i]*n/5;});
      scenarios[name]={bounds:[Math.round(lo*100)/100,Math.round((lo+missing)*100)/100],weights:Object.fromEntries(keys.map((k,i)=>[k,vec[i]]))};
    }
    const complete=keys.every(k=>ratings[k].rating!==null);
    return {version:VERSION,candidate_id:candidateId,ratings,domains,scenarios,score:complete?scenarios.balanced.bounds[0]:null,
      score_status:complete?'COMPLETE_RESEARCHER_INPUTS_NOT_AUTHENTICATED':'INCOMPLETE',qualification_granted:false,
      independently_eligible_rct_count:null,warning:'Researcher-supplied ratings only. Independent full-text eligibility, material overlap, scientific gates and actual source validity must still be verified.'};
  }
  function read(job,topic){
    try{const raw=root.localStorage.getItem(key(job,topic));if(!raw)return null;const data=JSON.parse(raw);const verified=calculate(data,topic.candidate_id);return {...verified,saved_at:data.saved_at||null};}catch{return null;}
  }
  function save(job,topic,text){
    try{
      if(typeof text!=='string'||text.length>100000)throw Error('Assessment JSON exceeds the size limit.');
      const result=calculate(JSON.parse(text),topic.candidate_id);
      const data={...result,saved_at:new Date().toISOString()};
      root.localStorage.setItem(key(job,topic),JSON.stringify(data));
      return {ok:true,data};
    }catch(e){return {ok:false,error:String(e.message||e)};}
  }
  function esc(s){return String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));}
  function preview(data){if(!data)return '<p>No manual assessment saved.</p>';
    return '<p><b>'+esc(data.score_status)+'</b> · score '+esc(data.score??'UNKNOWN')+' / 100; balanced range '+esc(data.scenarios.balanced.bounds.join('–'))+'. This is not qualification.</p>'+
      Object.entries(data.scenarios).map(([n,s])=>'<p>'+esc(n)+': '+esc(s.bounds.join('–'))+'</p>').join('');
  }
  function render(job,topic){
    const saved=read(job,topic);const model=saved?{candidate_id:topic.candidate_id,ratings:saved.ratings}:template(topic);
    return '<details class="mcda-editor" data-mcda-key="'+esc(key(job,topic))+'"><summary>Researcher assessment · record eight domains</summary>'+
      '<p class="help">Review primary sources yourself. Paste or edit the JSON below. For a resolved rating include evidence URLs, a rationale, counterevidence and uncertainty. Leave unknown ratings null. Stored only in this browser; export a backup. Never changes cloud qualification.</p>'+
      '<textarea class="mcda-json" aria-label="Researcher assessment JSON" rows="12" style="width:100%">'+esc(JSON.stringify(model,null,2))+'</textarea>'+
      '<div class="job-actions"><button type="button" class="secondary small" data-mcda-save="'+esc(job.id)+'" data-mcda-topic="'+esc(topic.candidate_id)+'">Save assessment locally</button>'+
      '<button type="button" class="secondary small" data-mcda-export="'+esc(job.id)+'" data-mcda-topic="'+esc(topic.candidate_id)+'">Export saved assessment</button></div>'+
      '<p class="mcda-message" role="status"></p><div class="mcda-preview">'+preview(saved)+'</div></details>';
  }
  root.SCIMED_MCDA=Object.freeze({weights,template,calculate,read,save,preview,render});
})(typeof window!=='undefined'?window:globalThis);
