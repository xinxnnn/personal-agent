'use strict';
(() => {
 const queue=document.getElementById('deletionQueue');
 const stats=document.getElementById('deletionStats');
 const labels={pending:'待审核',approved:'已批准',rejected:'已拒绝',executing:'正在归档',failed:'归档未完成',deleted:'已删除'};
 const text=(value)=>value==null||value===''?'—':String(value);
 function summary(items){
   stats.replaceChildren();
   for(const [key,label] of [['pending','待审核'],['approved','已批准'],['failed','归档未完成'],['deleted','已删除'],['rejected','已拒绝']]){
     const card=document.createElement('div');card.className='deletion-stat';
     const value=document.createElement('b');value.textContent=String(items.filter(item=>item.status===key).length);
     const caption=document.createElement('span');caption.textContent=label;card.append(value,caption);stats.append(card);
   }
 }
 function canReopen(item,items){
   return item.status==='rejected'&&!items.some(other=>other.agent_id===item.agent_id&&other.id!==item.id&&['pending','approved','executing','failed','deleted'].includes(other.status));
 }
 function addAction(row,item,items){
   if(item.status==='pending'){
     const comment=document.createElement('input');comment.placeholder='填写审核意见（可选）';comment.maxLength=500;comment.setAttribute('aria-label','删除审核意见');row.append(comment);
     const actions=document.createElement('div');actions.className='actions';
     for(const [decision,label] of [['approved','批准删除'],['rejected','拒绝删除']]){
       const button=document.createElement('button');button.className=decision==='approved'?'primary-btn':'ghost-btn danger';button.textContent=label;
       button.onclick=async()=>{
         actions.querySelectorAll('button').forEach(b=>b.disabled=true);
         try{await request(`/v1/tp/deletions/${encodeURIComponent(item.id)}/review`,{method:'POST',body:JSON.stringify({decision,comment:comment.value})});await load();}
         catch(error){showAlert(error.message);actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
       };actions.append(button);
     }row.append(actions);
   }
   if(canReopen(item,items)){
     const button=document.createElement('button');button.className='ghost-btn';button.textContent='重新送审';
     button.onclick=async()=>{button.disabled=true;try{await request(`/v1/tp/deletions/${encodeURIComponent(item.id)}/reopen`,{method:'POST',body:'{}'});await load();}catch(error){showAlert(error.message);button.disabled=false;}};
     row.append(button);
   }
 }
 function render(item,items){
   const card=document.createElement('article');card.className='deletion-card';
   const head=document.createElement('div');head.className='deletion-card-head';
   const title=document.createElement('h3');title.textContent=text(item.name);
   const badge=document.createElement('span');badge.className='badge';badge.textContent=labels[item.status]||text(item.status);
   head.append(title,badge);card.append(head);
   const facts=document.createElement('dl');facts.className='deletion-facts';
   for(const [label,value] of [['申请人',item.owner],['申请时间',fmtTime(item.created_at)],['删除原因',item.reason]]){
     const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=text(value);facts.append(dt,dd);
   }card.append(facts);
   if(item.last_error&&item.status==='failed'){
     const error=document.createElement('p');error.className='deletion-error';error.textContent='归档未完成：'+item.last_error;card.append(error);
   }
   if(item.status!=='pending'){
     const note=document.createElement('p');note.className='deletion-note';note.textContent=`审核人：${text(item.reviewer)} · 意见：${text(item.comment)}`;card.append(note);
   }
   addAction(card,item,items);
   const detail=document.createElement('details');detail.className='technical-details';
   const detailTitle=document.createElement('summary');detailTitle.textContent='查看申请编号与实例标识';detail.append(detailTitle);
   for(const [label,value] of [['申请编号',item.id],['智能体实例',item.agent_id]]){
     const p=document.createElement('p');p.textContent=`${label}：${text(value)}`;detail.append(p);
   }card.append(detail);return card;
 }
 async function load(){
   try{const data=await request('/v1/tp/deletions');const items=Array.isArray(data.items)?data.items:[];
     summary(items);queue.replaceChildren();
     if(!items.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='暂无删除申请';queue.append(empty);}
     for(const item of items)queue.append(render(item,items));
   }catch(error){showAlert(error.message);}
 }
 document.getElementById('refreshDeletions').onclick=load;
 document.querySelector('[data-view="deletions"]').addEventListener('click',load);
})();
