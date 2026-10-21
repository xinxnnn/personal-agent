'use strict';
(() => {
 const panel=document.createElement('section');panel.className='panel anp-panel';panel.hidden=true;
 panel.innerHTML='<div class="section-title"><div><h2>智能体通信协同 · 工作日志</h2><p class="muted">按时间记录智能体启动、协同请求与结果返回；不记录消息或问答内容。</p></div><button type="button" class="secondary" id="anp-refresh">刷新日志</button></div><p id="anp-status" role="status" aria-live="polite"></p><div id="anp-log" class="anp-log" role="log" aria-label="智能体协同工作日志" aria-live="polite"></div>';
 document.querySelector('#partner-detail').append(panel);
 let currentType='octopus',current='',version=0,loading=false,timer=null;
 const el=id=>panel.querySelector('#'+id);
 const endpoint=()=>'/user/anp/'+encodeURIComponent(current);
 const statusLabels={processing:'处理中',completed:'已完成',failed:'未完成',sent:'已发起',received:'已接收',delivered:'已投递',pending:'等待确认',unknown:'状态未知'};
 function formatTime(value){const date=new Date(value);return Number.isNaN(date.getTime())?'时间未知':date.toLocaleString();}
 function eventDescription(item){
  const actor=item.agent_name||item.agent_id||'智能体',peer=item.peer_name||item.peer_id||'同组伙伴';
  if(item.kind==='agent_started')return `${actor} 已启动`;
  if(item.kind==='agent_stopped')return `${actor} 已停止`;
  if(item.kind==='request_sent')return `${actor} 向 ${peer} 发起协同请求`;
  if(item.kind==='request_received')return `${actor} 收到 ${peer} 的协同请求`;
  if(item.kind==='response_returned')return `${actor} 向 ${peer} 返回协同结果`;
  if(item.kind==='response_received')return `${actor} 收到 ${peer} 返回的协同结果`;
  if(item.kind==='request_failed')return `${actor} 与 ${peer} 的协同请求未完成`;
  if(item.kind==='chat_request')return item.direction==='received'?`${actor} 收到 ${peer} 的协同请求`:`${actor} 向 ${peer} 发起协同请求`;
  if(item.kind==='chat_response')return item.direction==='received'?`${actor} 向 ${peer} 返回协同结果`:`${actor} 收到 ${peer} 返回的协同结果`;
  if(item.kind==='message')return item.direction==='in'?`${actor} 收到 ${peer} 的通信消息`:`${actor} 向 ${peer} 发送通信消息`;
  return `${actor} 的通信状态已更新`;
 }
 function eventStatus(item){
  if(item.status==='failed'||item.kind==='request_failed')return '未完成';
  if(item.kind==='agent_started')return '已启动';
  if(item.kind==='agent_stopped')return '已停止';
  if(item.kind==='request_sent')return '已发起';
  if(item.kind==='request_received')return '已接收';
  if(item.kind==='response_returned')return '已返回';
  if(item.kind==='response_received')return '已收到';
  return statusLabels[item.status]||statusLabels.unknown;
 }
 async function refresh(){
  const v=version;if(!current||loading)return;loading=true;el('anp-status').textContent='正在读取工作日志…';
  try{
   const data=await api(endpoint());if(v!==version)return;
   const events=data.activity||[];
   el('anp-status').textContent=data.connected?'通信服务已连接，工作日志每 5 秒更新。':(data.message||'通信服务未连接；仍可查看已有工作日志。');
   const log=el('anp-log'),scrollTop=log.scrollTop;log.replaceChildren();
   for(const item of events){
    const row=document.createElement('article');row.className='anp-log-entry';
    const marker=document.createElement('span');marker.className='anp-log-marker';
    const detail=document.createElement('div');detail.className='anp-log-detail';
    const title=document.createElement('strong');title.textContent=eventDescription(item);
    const meta=document.createElement('p');meta.textContent=formatTime(item.timestamp);
    const stateLabel=document.createElement('span');stateLabel.className='anp-log-state';stateLabel.textContent=eventStatus(item);
    detail.append(title,meta);row.append(marker,detail,stateLabel);log.append(row);
   }
   if(!events.length){const empty=document.createElement('p');empty.className='muted';empty.textContent='暂无工作记录；智能体启动或开始协同时，事件会显示在这里。';log.append(empty);}
   log.scrollTop=scrollTop;
  }catch(e){if(v===version)el('anp-status').textContent=e.message;}
  finally{if(v===version)loading=false;}
 }
 async function select(id,type=currentType){
  currentType=type;current=id;version++;loading=false;
  if(timer){clearInterval(timer);timer=null;}
  panel.hidden=currentType!=='octopus';if(panel.hidden)return;
  el('anp-status').textContent='正在读取工作日志…';el('anp-log').replaceChildren();
  await refresh();timer=setInterval(refresh,5000);
 }
 el('anp-refresh').onclick=refresh;
 window.addEventListener('runtime-selected',event=>select(event.detail.id,event.detail.agent_type||state.type));
 window.addEventListener('children-updated',()=>{if(current)select(current);});
 window.addEventListener('agent-record-ready',()=>{if(!current&&state.phc?.id)select(state.phc.id.replaceAll(':','_'));});
 if(state.phc?.id)select(state.phc.id.replaceAll(':','_'));
})();
