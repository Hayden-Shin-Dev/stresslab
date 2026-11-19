/* Shared browser/server contract. No credentials or remote execution. */
(function(root){
 'use strict';
 const roles={kim:'macro',yoon:'intraday',shin:'risk',kang:'portfolio'};
 const names={macro:'영호',intraday:'영숙',risk:'영철',portfolio:'옥순'};
 const personaKeys={macro:['scenario_conditions','gold_state_summary','transmission_channels','support_range_flags','next_checks'],intraday:['snapshot_status','market_flow','breadth_and_sectors','risk_signals','data_quality_flags'],risk:['asset_distribution','tail_reference','similar_regimes','model_limits','support_flags'],portfolio:['portfolio_metrics','tail_contributions','holding_valuation','risk_method','availability_flags']};
 const keys=['schema_version','context_version','role','intent','response_status','emission','silence_reason','summary_text','display_text','tts_text','view_status','claims','structured_source_ids','rag_source_ids','news_source_ids','uncertainty','questions_to_roles','ui_requests','follow_up','persona_data'];
 const copy=x=>JSON.parse(JSON.stringify(x));
 const naturalLimit='지금은 판단에 필요한 최신 데이터가 충분하지 않습니다. 기준 시각과 분석할 대상 또는 시나리오를 알려주시면 이어서 설명드리겠습니다.';
 const internal=/\b(schema_version|context_version|evidence_bundle_id|D_sources|N_sources|S_sources|persona_data|query_plan|response_status|view_status|model_version|approved|is_mock|cutoff|market_state_snapshot|quality_status|joint_portfolio_samples)\b/i;
 function validateInput(x){
  const required=['schema_version','role','phase','meeting_id','participation_scope_id','round_id','context_version','cutoff','evidence_bundle_id','result_version','user_message','role_payload'];
  const errors=required.filter(k=>!(k in (x||{}))).map(k=>'missing:'+k);
  if(x?.schema_version!==3)errors.push('schema');if(!personaKeys[x?.role])errors.push('role');
  if(!['automatic','user_request'].includes(x?.trigger_type)||!Array.isArray(x?.addressed_roles)||x.addressed_roles.some(r=>!personaKeys[r]))errors.push('trigger');
  if(!['INITIAL','CHALLENGE','REBUTTAL','LIVE_REVIEW','USER_ANSWER'].includes(x?.phase))errors.push('phase');
  if(x?.phase==='USER_ANSWER'&&!x.question_id)errors.push('question_id');
  if(['CHALLENGE','REBUTTAL'].includes(x?.phase)&&!x.reference_message_id)errors.push('reference_message_id');
  if(!Number.isFinite(Date.parse(x?.cutoff)))errors.push('cutoff');
  if(typeof x?.user_message!=='string'||x.user_message.length>12000)errors.push('question');
  if((x?.recent_history||[]).some(m=>m.participation_scope_id!==x.participation_scope_id)||(x?.recent_history||[]).length>6)errors.push('history_scope');
  const requiredPayload={macro:['scenario','gold_state','shock_support'],intraday:['market_state_snapshot','delivery'],risk:['asset_risk','similar_regimes','model_validation'],portfolio:['holdings','valuation','portfolio_risk']}[x?.role]||[];
  if(!x?.role_payload||requiredPayload.some(k=>!(k in x.role_payload)))errors.push('role_payload');
  return errors;
 }
 function sourcePool(x){
  const out={D:[],N:[],S:[]},cut=Date.parse(x.cutoff),seenNews=new Set();
  for(const k of ['D','N','S'])for(const s of x[k+'_sources']||[]){
   const available=s.available_at||s.received_at||s.published_at;
   if(!s.id||!available||!Number.isFinite(Date.parse(available))||Date.parse(available)>cut||s.is_mock===true||s.mock===true||s.approved===false)continue;
   if(k==='N'&&(s.verification_status!=='verified'||!s.published_at||Date.parse(s.published_at)>cut))continue;
   if(k==='N'){if([s.published_at,s.received_at,s.available_at].filter(Boolean).some(t=>!Number.isFinite(Date.parse(t))||Date.parse(t)>cut))continue;const key=s.event_id||s.news_id||s.canonical_url||s.url||s.id;if(seenNews.has(key))continue;seenNews.add(key);}
   if(!out[k].includes(s.id))out[k].push(s.id);
  }return out;
 }
 function validateOutput(y,x){
  const errors=[];if(!y||typeof y!=='object'||Array.isArray(y))return ['object'];
  if(keys.some(k=>!(k in y))||Object.keys(y).some(k=>!keys.includes(k)))errors.push('keys');
  if(y.schema_version!==3||y.role!==x.role||y.context_version!==x.context_version)errors.push('identity');
  if(!['initial_analysis','challenge','rebuttal','live_review','user_answer','insufficient_data','clarify','unsupported','no_op'].includes(y.intent))errors.push('intent');
  if(!['speak','silent'].includes(y.emission))errors.push('emission');
  if(y.emission==='silent'){
   if(y.intent!=='no_op'||!['not_relevant','insufficient_evidence','deferred','duplicate','no_material_change','not_addressed','invalid_input'].includes(y.silence_reason))errors.push('silence');
   if(['summary_text','display_text','tts_text'].some(k=>y[k]!==''))errors.push('silent_text');
   if(['claims','structured_source_ids','rag_source_ids','news_source_ids','questions_to_roles','ui_requests'].some(k=>!Array.isArray(y[k])||y[k].length)||y.follow_up!==null)errors.push('silent_payload');
   if(!['ok','insufficient_data','needs_clarification','data_conflict','unsupported'].includes(y.response_status)||!['maintained','deferred'].includes(y.view_status))errors.push('silent_status');
   if(!y.uncertainty||['missing','limitations','next_checks'].some(k=>!Array.isArray(y.uncertainty[k])||y.uncertainty[k].some(v=>typeof v!=='string')))errors.push('uncertainty');
   if(!y.persona_data||Object.keys(y.persona_data).length!==5||personaKeys[x.role].some(k=>!Array.isArray(y.persona_data[k])||y.persona_data[k].some(v=>typeof v!=='string')))errors.push('persona_data');
   return [...new Set(errors)];
  }
  if(y.silence_reason!==null)errors.push('silence_reason');
  if(x.trigger_type==='user_request'&&!x.addressed_roles.includes(x.role))errors.push('not_addressed');
  if(x.trigger_type==='automatic'&&(y.view_status==='deferred'||['insufficient_data','data_conflict','unsupported'].includes(y.response_status)))errors.push('automatic_deferred');
  const phaseIntent={INITIAL:'initial_analysis',CHALLENGE:'challenge',REBUTTAL:'rebuttal',LIVE_REVIEW:'live_review',USER_ANSWER:'user_answer'}[x.phase];
  if(y.response_status==='ok'&&y.intent!==phaseIntent)errors.push('phase_intent');
  if(['insufficient_data','data_conflict'].includes(y.response_status)&&y.view_status!=='deferred')errors.push('deferred');
  if(!['ok','insufficient_data','needs_clarification','data_conflict','unsupported'].includes(y.response_status))errors.push('status');
  if(!['initial','maintained','revised','deferred'].includes(y.view_status))errors.push('view');
  if(typeof y.display_text!=='string'||!y.display_text.startsWith('결론:')||/근거:\s*$/.test(y.display_text))errors.push('display');
  if([y.summary_text,y.display_text,y.tts_text].some(t=>typeof t!=='string'||internal.test(t)))errors.push('private_metadata');
  if(!x.voice_enabled&&y.tts_text!=='')errors.push('voice');
  const pool=sourcePool(x),lists={D:y.structured_source_ids,N:y.news_source_ids,S:y.rag_source_ids};
  for(const k of ['D','N','S'])if(!Array.isArray(lists[k])||lists[k].some(id=>!pool[k].includes(id)))errors.push('sources:'+k);
  const used=new Set();if(!Array.isArray(y.claims))errors.push('claims');else for(const c of y.claims){
   if(!c.claim_id||!['observation','interpretation','hypothesis'].includes(c.kind)||typeof c.statement!=='string'||!Array.isArray(c.evidence_refs))errors.push('claim');
   for(const id of c.evidence_refs||[]){used.add(id);if(![...pool.D,...pool.N,...pool.S].includes(id))errors.push('claim_source');}
   if(y.view_status==='revised'&&(!c.supersedes_claim_id||!c.change_reason))errors.push('revision');
  }
  for(const q of y.questions_to_roles||[])for(const id of q.evidence_refs||[])used.add(id);for(const r of y.ui_requests||[])for(const id of r.refs||[])used.add(id);
  const declared=new Set([...lists.D||[],...lists.N||[],...lists.S||[]]);if([...used].some(id=>!declared.has(id))||[...declared].some(id=>!used.has(id)))errors.push('source_parity');
  if(!y.uncertainty||['missing','limitations','next_checks'].some(k=>!Array.isArray(y.uncertainty[k])||y.uncertainty[k].some(v=>typeof v!=='string')))errors.push('uncertainty');
  if(!Array.isArray(y.questions_to_roles)||y.questions_to_roles.some(q=>!personaKeys[q.role]||q.role===x.role||typeof q.question!=='string'||!Array.isArray(q.evidence_refs)||q.evidence_refs.some(id=>!declared.has(id))))errors.push('role_questions');
  if(!Array.isArray(y.ui_requests)||y.ui_requests.some(r=>!['OPEN_SOURCE_PANEL','SUGGEST_ROLE_TARGET','REQUIRE_CURRENT_DATA','OPEN_ANALYSIS_TAB'].includes(r.type)))errors.push('ui_requests');
  if(y.follow_up!==null)errors.push('follow_up');
  if(!y.persona_data||Object.keys(y.persona_data).length!==5||personaKeys[x.role].some(k=>!Array.isArray(y.persona_data[k])||y.persona_data[k].some(t=>typeof t!=='string')))errors.push('persona_data');
  if(y.response_status==='ok'&&!pool.D.length&&!pool.S.length&&!pool.N.length)errors.push('unsupported_success');
  if(x.role==='portfolio'&&y.response_status==='ok'&&!portfolioReady(x.role_payload)&&!portfolioPnlReady(x))errors.push('portfolio_unapproved');
  return [...new Set(errors)];
 }
 function makeInput({id='kim',scope='personal/scenario',question='',context={},history=[],questionId='q',phase='USER_ANSWER',reference=null,now=new Date().toISOString(),triggerType='user_request',addressedRoles=null}){
  const role=roles[id]||id,run=context.run||null,c=run?.conditions||context.conditions||{};
  const scenario={shocks:{shock_fx:Number(c.fx)||0,shock_rate:(Number(c.rate)||0)*100,shock_oil:Number(c.oil)||0,shock_vix:Number(c.vix)||0},horizon_trading_days:run?.horizon||5};
  let payload=role==='macro'?{scenario,gold_state:null,shock_support:null}:role==='intraday'?{market_state_snapshot:null,delivery:{stale:true}}:role==='risk'?{scenario,asset_risk:null,similar_regimes:[],model_validation:null}:{holdings:context.holdings||[],valuation:null,portfolio_risk:{approved:false}};
  const x={schema_version:3,role,phase,meeting_id:scope.startsWith('collab/')?scope:'personal',participation_scope_id:scope,round_id:'round-1',context_version:context.version||'analysis-1',cutoff:now,evidence_bundle_id:'none',result_version:run?.version||null,user_message:question,role_payload:payload,question_id:questionId,voice_enabled:false,D_sources:[],N_sources:[],S_sources:[],recent_history:history.filter(m=>m.participation_scope_id===scope).slice(-6),local_context:copy(context),trigger_type:triggerType,addressed_roles:addressedRoles||[role],meeting_context:context.meeting_context||null,agenda_context:context.agenda_context||{agenda_id:questionId,topic:question,target:run?.targetLabel||null,question_status:'active'},daily_observations:null,prior_claims:[]};
  if(reference)x.reference_message_id=reference;return x;
 }
 function portfolioReady(payload){const p=payload?.portfolio_risk||{},m=p.risk_metrics||p;return p.approved===true&&p.is_mock!==true&&Number.isFinite(m.var95_krw)&&Number.isFinite(m.es95_krw)&&Number.isFinite(p.sample_count)&&p.sample_count>0&&!!p.weight_basis&&!!(payload?.valuation?.price_as_of||p.price_as_of)&&!!p.model_version&&!!p.scenario_id&&!!p.joint_sample_method;}
 function portfolioPnlReady(x){const pool=sourcePool(x).D,rows=(x.D_sources||[]).filter(s=>pool.includes(s.id));return ['holding_value_krw','center_pnl_krw'].every(id=>rows.some(s=>s.metric_id===id&&typeof s.value==='number'&&Number.isFinite(s.value)&&s.is_mock!==true&&s.approved!==false));}
 function validateModerator(y,x){
  const errors=[],required=['schema_version','role','meeting_id','context_version','status','emission','display_text','tts_text','next_actions','agenda_update','minutes_delta','awaiting_user','route','reason'];
  if(!y||typeof y!=='object')return ['object'];if(required.some(k=>!(k in y))||Object.keys(y).some(k=>!required.includes(k)))errors.push('keys');
  if(y.schema_version!==3||y.role!=='moderator'||y.meeting_id!==x.meeting_id||y.context_version!==x.context_version)errors.push('identity');
  if(!['active','waiting','closing','closed','invalid'].includes(y.status)||!['speak','silent'].includes(y.emission)||!['meeting','outside_meeting'].includes(y.route))errors.push('state');
  if(typeof y.display_text!=='string'||typeof y.tts_text!=='string'||y.tts_text!==''||internal.test(y.display_text))errors.push('text');if(y.emission==='silent'&&(y.display_text!==''||y.tts_text!==''))errors.push('silent');
  const ids=new Set(Object.values(sourcePool(x)).flat());
  if(!Array.isArray(y.next_actions)||y.next_actions.length>6)errors.push('actions');else for(const a of y.next_actions){if(!['pause_automatic','dispatch_persona','resume_agenda','wait_event','close_meeting','notify_operator'].includes(a.type)||!Array.isArray(a.target_roles)||a.target_roles.some(r=>!personaKeys[r])||!Array.isArray(a.evidence_refs)||a.evidence_refs.some(id=>!ids.has(id))||a.question!=null&&(typeof a.question!=='string'||a.question.length>12000))errors.push('action');}
  if(!Array.isArray(y.minutes_delta)||y.minutes_delta.length>30)errors.push('minutes');else for(const m of y.minutes_delta)if(!['news_fact','claim','challenge','revision','user_question','user_answer','summary'].includes(m.type)||typeof m.text!=='string'||!Array.isArray(m.evidence_refs)||m.evidence_refs.some(id=>!ids.has(id)))errors.push('minute');
  if(y.awaiting_user!==null&&(!y.awaiting_user?.question_id||typeof y.awaiting_user.question!=='string'))errors.push('awaiting_user');return [...new Set(errors)];
 }
 const api={roles,names,personaKeys,keys,copy,naturalLimit,validateInput,validateOutput,sourcePool,portfolioReady,portfolioPnlReady,makeInput,validateModerator};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;root.WhatIfAgentContract=api;
})(globalThis);
