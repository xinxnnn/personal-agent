'use strict';
const $ = s => document.querySelector(s);
const escapeHTML = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { phc:null, pa:null, cmc:null, matrix:null, user:null, requestId:'', type:'octopus', created:null, loggedIn:false };
const names = {home:'工作台',create:'创建智能体',identity:'我的可信身份',settings:'连接与设置'};
$('#agent-type option[value="openclaw"]').remove();
$('#agent-type').closest('label').hidden=true;
const openclawInfo=document.createElement('aside');openclawInfo.className='panel';
openclawInfo.innerHTML='<h2>执行分支 · OpenClaw</h2><p class="muted">Octopus 负责问答与分析。在「我的智能体」中添加 OpenClaw 执行分支，关联主身份并独立运行。部署后打开执行控制台，在配置工具并授权后完成电脑操作。执行分支不能创建子智能体。</p><button type="button" class="secondary" data-page="partners">管理我的智能体</button>';
$('#page-settings').append(openclawInfo);
const openclawEntry=document.createElement('p');openclawEntry.className='muted';
openclawEntry.innerHTML='另支持 <button type="button" class="text-button" data-page="settings">了解 OpenClaw 执行分支 ↗</button>';
$('#page-create .heading').append(openclawEntry);
let noticeTimer;
let dependencyCheck = null;
let dependencyType = null;
const dependencyPanel = $('#dependencies').closest('.panel');
$('#agent-type').closest('label').after(dependencyPanel);
dependencyPanel.hidden = true;
async function checkOpenClawEnvironment(){
 if(dependencyCheck) return dependencyCheck;
 $('#dependencies').textContent='正在检查 OpenClaw 所需的 Node.js 和 Git…';
 dependencyCheck=(async()=>{
  try{
   const d=await api('/user/openclaw/dependencies');
   $('#dependencies').innerHTML=['node','git'].map(k=>`<p><b>${k==='node'?'Node.js':'Git'}</b>　${d[k]?.installed&&!d[k]?.error?`已检测到 ${escapeHTML(d[k].version||'')}`:'未就绪，请安装或检查 PATH'}</p>`).join('')+`<p>${d.ready_for_openclaw?'环境已就绪，可以继续创建 OpenClaw。':'环境尚未就绪，安装完成后请点击「重新检测」。'}</p>`;
   return d;
  }catch(e){$('#dependencies').textContent='环境检查失败：'+e.message;throw e;}
  finally{dependencyCheck=null;}
 })();
 return dependencyCheck;
}
function notice(message, error=false) { const el=$('#notice'); el.textContent=message; el.classList.toggle('error',error); el.hidden=false; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>el.hidden=true,12000); }
function page(name) { if(!names[name]) name='home'; if(!state.avatarReady && !state.created && !['settings','identity'].includes(name)) name='create'; document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==`page-${name}`); document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('active',el.dataset.page===name)); $('#page-name').textContent=names[name]; location.hash=name; }
function loginRequired(){state.loggedIn=false;document.body.classList.add('session-checking');location.replace('./login.html?page='+encodeURIComponent(location.hash.slice(1)||'home'));}
async function api(path, payload, allowFalse=false) {
 const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),120000);
 try {
  const response=await fetch(path,{credentials:'same-origin',signal:controller.signal,...(payload===undefined?{}:{method:'POST',...(payload instanceof FormData?{body:payload}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})})});
  if(response.status===401 || response.redirected){loginRequired();throw new Error('请登录后继续。');}
  if(!(response.headers.get('content-type')||'').includes('application/json')) throw new Error('服务没有返回有效数据，请检查服务是否启动。');
  const data=await response.json();
  if(!response.ok || (data.success===false&&!allowFalse)) throw new Error(typeof data.detail==='string'?data.detail:data.message||data.error||'操作未完成，请检查输入或服务状态。');
  return data;
 } catch(e){if(e.name==='AbortError') throw new Error('请求超时，请检查服务状态后重试。');throw e;} finally {clearTimeout(timer);}
}
function action(selector,fn){$(selector).addEventListener('click',event=>busy(event.currentTarget,fn));}
async function busy(button,fn){const label=button.textContent;button.disabled=true;button.textContent='处理中…';try{await fn();}catch(e){notice(e.message,true);}finally{button.textContent=label;button.disabled=false;sync();}}
function sync(){
 dependencyPanel.hidden=state.type!=='openclaw';
 if(state.loggedIn && dependencyType!==state.type){
  dependencyType=state.type;
  if(state.type==='openclaw') checkOpenClawEnvironment().catch(()=>{});
 }
 window.dispatchEvent(new Event('avatar-flow-sync'));
 $('#identity-stat').textContent=state.phc?'已持有身份凭证':state.requestId?'审核中':'尚未认证';
 $('#agent-stat').textContent=state.created?'已生成 · 待启动':state.pa?'已绑定 · 状态待确认':'尚未创建';
 $('#progress-stat').textContent=state.created?'生成完成':state.pa?'等待生成':state.phc?'选择能力':state.requestId?'等待身份审核':'尚未开始';
 $('#review-status').textContent=state.phc?'身份已确认':state.requestId?'审核中':'未提交';
 $('#submit-identity').disabled=!!(state.phc||state.requestId); $('#check-review').hidden=!state.requestId;
 $('#load-capabilities').disabled=!state.phc || !!state.pa; $('#agent-type').disabled=!!state.pa;
 $('#confirm-capabilities').disabled=!state.matrix || !!state.pa; $('#create-agent').disabled=!state.pa||!state.phc;
 for(let i=1;i<=3;i++) $(`#step${i}`).classList.toggle('done',!![state.phc,state.pa,state.created][i-1]);
 $('#credential-state').textContent=state.phc?'已持有可信身份凭证':'尚未完成身份确认';
 const did=state.phc?.DID || state.phc?.ASO?.TPM?.CDID || '尚未生成';
 $('#credential-details').innerHTML=[['身份凭证编号',state.phc?.id||'尚未签发'],['去中心化身份',did],['智能体类型',state.pa?state.type:'尚未绑定'],['智能体凭证',state.pa?'已持有':'尚未签发']].map(([k,v])=>`<dt>${k}</dt><dd>${escapeHTML(v)}</dd>`).join('');
 if(state.pa) $('#agent-card').innerHTML=`<div class="agent-live"><span class="empty-icon">✳</span><div><h3>我的${state.type==='openclaw'?'本地':'通用'}智能体</h3><p>${state.created?'智能体文件已生成，请完成启动后使用。':'已读取最近的绑定记录，运行状态尚未确认。'}</p><small>身份已绑定 · ${escapeHTML(state.type)}</small></div><button class="primary" data-page="create">${state.created?'查看启动指引':'继续创建'}</button></div>`;
}
const normalizeServiceUrl=value=>{
 const url=new URL(value.trim());
 if(['/ap','/tp','/user'].includes(url.pathname.replace(/\/+$/,'').toLowerCase()))url.pathname='';
 return url.toString().replace(/\/$/,'');
};
const connection = () => ({tp:normalizeServiceUrl($('#tp-url').value),ap:normalizeServiceUrl($('#ap-url').value)});
function pendingKey(){return `banxing.pending.${state.account||''}`;}
async function restore(){
 state.avatarReady=false;
 const data=await api('/user/last_agent',undefined,true);
 if(data.success&&data.agent){const a=data.agent;state.phc=a.phc||null;state.pa=a.pa||null;state.cmc=a.cmc||null;state.type=a.agent_type||'octopus';if(state.type==='openclaw'&&!$('#agent-type option[value="openclaw"]'))$('#agent-type').add(new Option('OpenClaw','openclaw'));$('#agent-type').value=state.type;state.created=null;
  if(a.identity){for(const key of ['name','id_number','id_card_number','email']) $('#identity-form').elements[key].value=a.identity[key]||'';$('#recovery-name').value=a.identity.name||'';$('#recovery-id').value=a.identity.id_number||'';$('#recovery-id-card').value=a.identity.id_card_number||'';$('#recovery-email').value=a.identity.email||'';state.user={pii:a.identity,bi:{last_login_ip:'127.0.0.1'},cdid:'cdid:user.placeholder',ecid:'g'};}
 }
 try{const pending=JSON.parse(sessionStorage.getItem(pendingKey())||'null');if(pending&&!state.phc){state.requestId=pending.id;$('#tp-url').value=pending.tp;}}catch{}
 if(state.pa&&state.phc){try{await api('/user/runtime/'+encodeURIComponent(state.phc.id.replaceAll(':','_'))+'/status');state.avatarReady=true;}catch{}}
 $('#use-saved-phc').hidden=!state.phc;
 sync();
 window.dispatchEvent(new Event('agent-record-ready'));
}
document.addEventListener('click',e=>{const nav=e.target.closest('[data-page]');if(nav)page(nav.dataset.page);const scene=e.target.closest('[data-scenario]');if(scene){$('#scenario-note').textContent=`为「${scene.dataset.scenario}」创建伙伴。审核通过后可按需选择服务提供的能力。`;if(!state.pa){state.type='octopus';$('#agent-type').value=state.type;state.matrix=null;$('#capabilities').replaceChildren();sync();}page('create');}});
window.addEventListener('hashchange',()=>page(location.hash.slice(1)));
action('#logout',async()=>{await api('/user/api/logout',{});loginRequired();});
action('#refresh',async()=>{await restore();notice('已刷新本地绑定记录。');});
$('#identity-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter,async()=>{
 const f=new FormData(e.target);const photo=f.get('photo');if(!photo||!photo.size)throw new Error('请选择核验照片。');if(!photo.type.startsWith('image/'))throw new Error('请选择图片文件。');if(photo.size>10*1024*1024)throw new Error('请选择小于 10 MB 的图片。');
 const upload=new FormData();upload.append('file',photo);const pic=await api('/v1/pic/upload',upload);if(!pic.string_part)throw new Error('照片上传未成功，请重试。');
 state.user={pii:{name:f.get('name').trim(),id_number:f.get('id_number').trim(),id_card_number:f.get('id_card_number'),email:f.get('email')},bi:{last_login_ip:'127.0.0.1',pic_string:pic.string_part},cdid:'cdid:user.placeholder',ecid:'g'};
 const d=await api('/user/request_phc',{base_url:connection().tp,user:state.user});state.phc=d.phc||d.PHC||null;state.requestId=d.request_id||'';
 if(!state.phc&&!state.requestId)throw new Error('未收到审核申请编号，请检查身份服务。');
 if(state.requestId)sessionStorage.setItem(pendingKey(),JSON.stringify({id:state.requestId,tp:connection().tp}));
 notice(state.phc?'身份确认完成，可以选择能力了。':'申请已提交。请等待身份服务审核，再查询进度。');
 });});
action('#check-review',async()=>{const d=await api('/user/check_phc_application',{base_url:connection().tp,request_id:state.requestId});const a=d.application||d.app||{};const status=d.status||a.status;const phc=d.phc||d.PHC||a.phc||a.PHC;
 if(phc&&['issued','approved','signed'].includes(status)){state.phc=phc;state.requestId='';sessionStorage.removeItem(pendingKey());notice('身份审核通过，接下来选择伙伴能力。');}
 else if(['rejected','denied'].includes(status)){state.requestId='';sessionStorage.removeItem(pendingKey());notice('审核未通过，请核对登记信息后重新提交。',true);}
 else notice('仍在等待审核，请稍后再查询。');
});
$('#agent-type').addEventListener('change',e=>{state.type=e.target.value;state.matrix=null;$('#capabilities').replaceChildren();sync();});
let recoveryMode='pa';
$('#use-saved-phc').addEventListener('click',()=>{
 if(!state.phc)return;
 $('#recovery-phc').value=JSON.stringify(state.phc,null,2);
 recoveryProgress('已填入本机最近一次保存的 PHC；提交后仍会由服务端重新校验。','success');
});
function setRecoveryMode(mode){
 recoveryMode=mode==='both'?'both':'pa';
 document.querySelectorAll('[data-recovery-mode]').forEach(button=>{
  const active=button.dataset.recoveryMode===recoveryMode;
  button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
 });
 $('#recovery-phc-field').hidden=recoveryMode==='both';
 $('#recovery-photo-field').hidden=recoveryMode!=='both';
 $('#recover-submit').textContent=recoveryMode==='both'?'核验身份并恢复 PHC + PA':'验证 PHC 并恢复 PA';
 $('#recovery-progress').hidden=true;
}
document.querySelectorAll('[data-recovery-mode]').forEach(button=>button.addEventListener('click',()=>setRecoveryMode(button.dataset.recoveryMode)));
function recoveryProgress(message,status='working'){
 const el=$('#recovery-progress');el.textContent=message;el.dataset.state=status;el.hidden=false;
}
function recoveryUser(){
 const pii={
  name:$('#recovery-name').value.trim(),
  id_number:$('#recovery-id').value.trim(),
  id_card_number:$('#recovery-id-card').value.trim(),
  email:$('#recovery-email').value.trim()
 };
 if(!pii.name||!pii.id_number)throw new Error('请填写与原身份登记一致的姓名和身份标识。');
 return {pii,bi:{last_login_ip:'127.0.0.1'},cdid:'cdid:user.placeholder',ecid:'g'};
}
function parseRecoveryPHC(){
 const raw=$('#recovery-phc').value.trim();
 if(!raw)throw new Error('请粘贴仍持有的 PHC 凭证 JSON。');
 if(raw.length>2*1024*1024)throw new Error('PHC 内容过大，请检查粘贴的凭证文件。');
 let parsed;
 try{parsed=JSON.parse(raw);}catch{throw new Error('PHC 不是有效的 JSON 格式。');}
 const phc=parsed?.PHC||parsed?.phc||parsed;
 if(!phc||typeof phc!=='object'||Array.isArray(phc)||!phc.TPA||!phc.ASO)throw new Error('JSON 中未找到完整的 PHC 凭证。');
 return phc;
}
function requireVerifiedPA(pa){
 if(!pa||!pa.PA||!Array.isArray(pa.CMC)||!pa.CMC.length)throw new Error('服务未返回历史 PA 或能力配置；为避免将新配置误报为恢复，已停止操作。');
 if(['recover_fallback','recover_local'].includes(pa.mode))throw new Error('服务端没有找到可恢复的历史配置，当前返回的是新申请结果；为保护原配置，已停止操作。');
 const checks=['verified_tp','verified_ch','verified_af','verified_af_user','verified_ch_user','verified_cch_user'];
 const failed=checks.filter(key=>pa[key]!==true);
 if(failed.length||pa.verified_cmi===false){
  const labels={verified_tp:'TP 签名',verified_ch:'TP 链式证明',verified_af:'AF',verified_af_user:'本地 AF',verified_ch_user:'CH',verified_cch_user:'CCH',verified_cmi:'CMI'};
  const failedChecks=failed.concat(pa.verified_cmi===false?['verified_cmi']:[]).map(key=>labels[key]||key);
  throw new Error(`恢复凭证校验未通过（${failedChecks.join('、')}），未保存或生成智能体。请确认 PHC 和服务端历史记录后重试。`);
 }
}
async function saveRecoveredSnapshot(phc,pa,cmc,type,user){
 const saved=await api('/user/last_agent',{phc,pa,cmc,agent_type:type,identity:user.pii});
 if(!saved.success)throw new Error('凭证已核验，但本地快照保存失败；请查看服务状态后重试。');
}
$('#recovery-form').addEventListener('submit',event=>{
 event.preventDefault();
 busy(event.submitter||$('#recover-submit'),async()=>{
  let uploadedPhoto=null;
  const selectedType=$('#recovery-agent-type').value;
  let user=null;
  try{
   user=recoveryUser();
   let phc;
   if(recoveryMode==='both'){
    const photo=$('#recovery-photo').files[0];
    if(!photo)throw new Error('请重新上传身份核验照片。');
    if(!photo.type.startsWith('image/'))throw new Error('请选择图片文件。');
    if(photo.size>10*1024*1024)throw new Error('请选择小于 10 MB 的图片。');
    recoveryProgress('正在将身份信息加密提交给 TP，核验是否与历史登记资料一致…');
    const upload=new FormData();upload.append('file',photo);
    uploadedPhoto=await api('/v1/pic/upload',upload);
    if(!uploadedPhoto.string_part)throw new Error('照片上传未成功，请重试。');
    user.bi.pic_string=uploadedPhoto.string_part;
    const recovered=await api('/user/recover_phc',{base_url:connection().tp,user});
    if(recovered.verified_identity!==true)throw new Error('TP 未确认身份资料与历史记录一致，已停止恢复。请核对身份信息和登记时使用的照片。');
    if(!recovered.phc||recovered.verified_tp!==true)throw new Error('TP 已完成身份资料比对，但 PHC 签名校验未通过，已停止恢复。请联系管理员。');
    phc=recovered.phc;
    user.bi={last_login_ip:'127.0.0.1'};
    uploadedPhoto.string_part='';
    recoveryProgress('TP 已确认身份资料与历史登记一致，PHC 签名验证通过。正在向 AP 恢复历史 PA…','success');
   }else{
    phc=parseRecoveryPHC();
   }
   if(recoveryMode!=='both')recoveryProgress('正在向 AP 找回历史 PA，并由 TP 复核恢复后的 PHC…');
   const recoveredPA=await api('/user/recover_pa',{base_url:connection().ap,tp_base_url:connection().tp,phc,user,agent_type:selectedType});
   const pa=recoveredPA.pa;
   requireVerifiedPA(pa);
   const restoredPHC=pa.PHC||recoveredPA.phc||phc;
   const restoredType=pa.agent_type||selectedType;
   await saveRecoveredSnapshot(restoredPHC,pa.PA,pa.CMC,restoredType,user);
   state.phc=restoredPHC;state.pa=pa.PA;state.cmc=pa.CMC;state.type=restoredType;state.user={pii:user.pii,bi:{last_login_ip:'127.0.0.1'},cdid:user.cdid,ecid:user.ecid};state.created=null;
   $('#use-saved-phc').hidden=false;
   if(restoredType==='openclaw'&&!$('#agent-type option[value="openclaw"]'))$('#agent-type').add(new Option('OpenClaw','openclaw'));
   $('#agent-type').value=restoredType;
   for(const key of ['name','id_number','id_card_number','email'])$('#identity-form').elements[key].value=user.pii[key]||'';
   sync();
   recoveryProgress('凭证已核验并保存，正在重建本地智能体文件…');
   try{
    await createAgent();
    $('#recovery-open-create').hidden=false;
    recoveryProgress('恢复完成。原 PA 与能力配置已找回，本地智能体文件已重新生成。','success');
    $('#recovery-phc').value='';
    $('#recovery-photo').value='';
   }catch(error){
    $('#recovery-open-create').hidden=false;
    recoveryProgress('凭证已恢复并保存，但本地文件生成未完成。可前往创建流程重试。','error');
    throw new Error(`凭证已恢复并保存，但智能体文件生成失败：${error.message}`);
   }
  }catch(error){
   const messages={
    tp_identity_mismatch:'TP 身份核验未通过：提交的信息与历史加密记录不一致。请核对身份资料，并上传登记时使用的同一张照片。',
    tp_identity_record_not_found:'TP 未找到该身份的历史记录，暂时无法恢复 PHC。请确认身份标识，或联系身份服务管理员。',
    tp_unavailable:'无法连接 TP 身份服务。请确认 TP 已启动，并检查身份服务地址。',
    tp_recovery_rejected:'TP 拒绝了恢复请求，请检查 TP 服务状态后重试。'
   };
   const message=messages[error.message]||error.message;
   recoveryProgress(message,'error');
   throw new Error(message);
  }finally{
   if(uploadedPhoto?.string_part)uploadedPhoto.string_part='';
   if(user?.bi?.pic_string)user.bi.pic_string='';
   if(recoveryMode==='both')$('#recovery-photo').value='';
  }
 });
});
// These are display names from the original user console. Every selectable item
// still comes from the AP-issued CMM; this table never creates capabilities.
const capabilityGroups=['功能','输入','推理','知识','输出','外观'];
const labels={'text-processing':'文本处理','news-search':'新闻查询',payment:'支付','web-browsing':'联网搜索',text:'文本',voice:'语音',image:'图像',video:'视频',speech:'语音',ppt:'ppt','rag-openai':'RAG+OPENAI','rag-deepseek':'RAG+deepseek',llm:'大模型',retrieval:'检索',planner:'规划','safety-filter':'安全过滤','local-memory':'本地记忆','long-term-memory':'长期记忆','knowledge-pro':'专业知识库','knowledge-base':'知识库','vector-index':'向量索引','appearance-purple':'紫色','appearance-blue':'蓝色','appearance-pink':'粉色','appearance-green':'绿色'};
function renderCapabilities(matrix){
 const container=$('#capabilities');container.replaceChildren();
 matrix.forEach((row,i)=>{
  if(!row.length)return;
  const group=document.createElement('div');group.className='capability-row';
  const heading=document.createElement('strong');heading.textContent=capabilityGroups[i]||`配置 ${i+1}`;
  const options=document.createElement('div');
  row.forEach((item,j)=>{
   const label=document.createElement('label');
   const input=document.createElement('input');input.type=i===5?'radio':'checkbox';input.name=`capability-row-${i}`;input.dataset.row=String(i);input.dataset.index=String(j);
   const raw=String(item.label||item.id||'');
   label.append(input,document.createTextNode(labels[raw]||raw));options.append(label);
  });
  group.append(heading,options);container.append(group);
 });
}
action('#load-capabilities',async()=>{
 if(state.type==='openclaw' && !(await checkOpenClawEnvironment()).ready_for_openclaw)throw new Error('请先完成伙伴类型下方的 OpenClaw 环境检查，再加载能力。');
 const f=new FormData($('#identity-form'));if(!f.get('name')?.trim()||!f.get('id_number')?.trim())throw new Error('请补全姓名和身份标识后加载能力。');
 state.user={pii:{name:f.get('name').trim(),id_number:f.get('id_number').trim(),id_card_number:f.get('id_card_number'),email:f.get('email')},bi:{last_login_ip:'127.0.0.1'},cdid:'cdid:user.placeholder',ecid:'g'};
 const d=await api('/user/cmm_init',{base_url:connection().ap,phc:state.phc,user:state.user,agent_type:state.type});if(!Array.isArray(d.cmm)||!d.sk||!d.pk)throw new Error('能力列表或绑定信息不完整。');state.matrix=d.cmm;state.sk=String(d.sk);state.pk=String(d.pk);
 renderCapabilities(state.matrix);notice('能力列表已加载，请选择你需要的能力。');
});
function extras(){const selected=(state.cmc||[]).flat();const hooks={};const mapping={'session-memory':'session_memory','command-logger':'command_logger','bootstrap-extra-files':'bootstrap_extra_files','boot-md':'boot_md'};selected.forEach(x=>{if(mapping[x.params?.hook_type])hooks[mapping[x.params.hook_type]]=true;});const llm=selected.find(x=>x.label==='llm-model')?.params;return state.type==='openclaw'?{hooks_config:hooks,skills_config:selected.map(x=>x.params?.skill_slug).filter(Boolean),llm_config:llm?{provider:llm.provider,model:llm.model,base_url:llm.base_url}:null}:{};}
action('#confirm-capabilities',async()=>{state.cmc=state.matrix.map((row,i)=>row.filter((_,j)=>$(`#capabilities input[data-row="${i}"][data-index="${j}"]`).checked));if(!state.cmc.flat().length)throw new Error('请至少选择一项能力。');
 if(state.type==='openclaw'&&!state.cmc[0]?.length)throw new Error('本地助手需要选择核心能力。');
 const d=await api('/user/cmm_submit',{base_url:connection().ap,cmc:state.cmc,hid:state.user.pii.id_number,phc:state.phc,user_sk:state.sk,user_pk:state.pk,agent_type:state.type,...extras()});if(!d.PHC||!d.PA)throw new Error('未收到完整凭证，绑定尚未完成。');state.phc=d.PHC;state.pa=d.PA;state.sk='';state.pk='';document.querySelectorAll('#capabilities input').forEach(el=>el.disabled=true);notice('能力与身份绑定完成，可以生成智能体。');});
async function createAgent(){
 if(state.type==='openclaw'){const deps=await checkOpenClawEnvironment();if(!deps.ready_for_openclaw)throw new Error('OpenClaw 环境尚未就绪，请在伙伴类型下方检查 Node.js 和 Git。');}
 const d=await api('/user/create_agent',{phc:state.phc,pa:state.pa,cmc:state.cmc,agent_type:state.type,...extras()});if(!d.success)throw new Error('生成未完成。');state.created=d;
 const launcher=d.personal_launcher||d.launcher||'';const path=d.agent_path||d.openclaw_package||'';
 $('#creation-result').innerHTML='<h3>你的伙伴已生成</h3><p>继续在下方点击「部署并启动」。服务就绪后，点击「开始对话」即可使用。</p>';
 window.dispatchEvent(new Event('agent-record-ready'));
 try{await api('/user/last_agent',{phc:state.phc,pa:state.pa,cmc:state.cmc,agent_type:state.type,identity:state.user?.pii||{},skills:{user_name:d.manifest?.id||state.phc.id,openclaw_path:d.openclaw_package||''}});notice('智能体已生成，创建记录已保存。');}catch(e){notice('智能体已生成，但记录保存失败：'+e.message,true);}
}
action('#create-agent',createAgent);
$('#settings-form').addEventListener('submit',e=>{e.preventDefault();try{const urls=connection();for(const val of Object.values(urls)){if(!['http:','https:'].includes(new URL(val).protocol))throw new Error('请填写 HTTP 或 HTTPS 地址。');}$('#tp-url').value=urls.tp;$('#ap-url').value=urls.ap;localStorage.setItem('banxing.connections',JSON.stringify(urls));notice('连接设置已保存。');}catch(e){notice(e.message,true);}});
action('#check-dependencies',checkOpenClawEnvironment);
(async()=>{page(location.hash.slice(1));try{const settings=JSON.parse(localStorage.getItem('banxing.connections')||'null');if(settings){$('#tp-url').value=normalizeServiceUrl(settings.tp);$('#ap-url').value=normalizeServiceUrl(settings.ap);localStorage.setItem('banxing.connections',JSON.stringify(connection()));}}catch{}try{const d=await api('/user/api/me');state.loggedIn=true;document.body.classList.remove('session-checking');state.account=d.user.username;$('#account').textContent=d.user.display||d.user.username;await restore();}catch(e){if(!state.loggedIn){loginRequired();}else{notice(e.message,true);}}})();
window.addEventListener('pageshow',event=>{if(event.persisted) location.reload();});
