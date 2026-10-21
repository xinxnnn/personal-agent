'use strict';
(() => {
 const card=document.createElement('section');card.className='panel';
 card.innerHTML='<h2>删除申请</h2><p class="muted">删除须经身份审核端批准。批准后移出工作目录并归档，不撤销已签发凭证；主智能体须先处理所有子智能体。</p><button class="secondary" id="delete-main">申请删除主智能体</button> <button class="text-button" id="delete-refresh">刷新审批结果</button><div id="deletion-list"></div>';
 document.querySelector('#page-home').append(card);
 function addReapply(row,item,items){
   if(item.status!=='rejected'||items.some(x=>x.agent_id===item.agent_id&&['pending','approved','executing','failed','deleted'].includes(x.status)))return;
   const button=document.createElement('button');button.className='secondary';button.textContent='重新申请删除';
   button.onclick=async()=>{button.disabled=true;try{await apply(item.agent_id);}finally{button.disabled=false;}};row.append(button);
 }
 async function call(url,body){const r=await fetch(url,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});if(r.status===401||r.redirected){loginRequired();throw Error('请重新登录');}const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'操作失败，请检查服务是否已更新');return d;}
 const labels={pending:'待审核',approved:'已批准，待执行',rejected:'已拒绝',executing:'执行中',deleted:'已删除并归档',failed:'执行未完成，可重试'};
 async function refresh(){try{const d=await call('/user/deletions');const list=card.querySelector('#deletion-list');list.replaceChildren();for(const item of d.items){const row=document.createElement('div');row.className='child-card';const p=document.createElement('p');p.textContent=`${item.name} · ${labels[item.status]||item.status}${item.comment?' · 审核意见：'+item.comment:''}`;if(item.last_error){const detail=document.createElement('p');detail.className='runtime-error';detail.textContent=item.last_error;row.append(detail);}row.append(p);if(['approved','failed'].includes(item.status)){const button=document.createElement('button');button.className='secondary';button.textContent='执行已批准的删除';button.onclick=async()=>{button.disabled=true;try{await call('/user/deletions/'+item.id+'/execute',{});location.reload();}catch(e){notice(e.message,true);button.disabled=false;}};row.append(button);}addReapply(row,item,d.items);list.append(row);}}catch(e){notice(e.message,true);}}
 async function apply(id){const reason=prompt('请填写删除原因。申请通过前不会删除，审批后需在本页执行。');if(!reason?.trim())return;try{await call('/user/deletions',{agent_id:id,reason:reason.trim()});notice('已提交删除申请，请等待 TP 审核。');page('home');await refresh();}catch(e){notice(e.message,true);}}
 card.querySelector('#delete-main').onclick=()=>{if(!state.phc?.id)return notice('尚无主智能体',true);apply(state.phc.id.replaceAll(':','_'));};
 card.querySelector('#delete-refresh').onclick=refresh;
 window.addEventListener('request-agent-deletion',event=>apply(event.detail.id));
 let loaded=false;window.addEventListener('agent-record-ready',()=>{if(!loaded){loaded=true;refresh();}});
})();
