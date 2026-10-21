'use strict';
(() => {
  names.partners='我的伙伴';
  const workspace=document.createElement('section');
  workspace.id='page-partners';workspace.className='page';workspace.hidden=true;
  workspace.innerHTML=`<div class="heading"><div><p class="eyebrow">YOUR COMPANIONS</p><h1>我的分身</h1><p>选择一位分身，开始今天的协作。</p></div></div>
    <div class="partner-workspace"><div class="partner-sidebar"><div class="section-title"><h2>智能体列表</h2><button class="text-button" id="partners-refresh">刷新</button></div><p class="muted">切换分身不会停止其他运行中的分身。</p><div id="partners-list" aria-label="选择管理的分身"></div><p id="partners-message" role="status"></p><button class="secondary" id="partners-add">＋ 创建子智能体</button></div><div id="partner-detail"><p id="partners-empty" class="panel muted">先创建主智能体，再来这里启动和管理子智能体。<button class="primary" data-page="create">创建主智能体</button></p></div></div>`;
  document.querySelector('main').append(workspace);
  const createShortcut=document.createElement('button');createShortcut.className='primary';createShortcut.id='partners-create-shortcut';createShortcut.textContent='＋ 创建子智能体';
  createShortcut.onclick=()=>window.dispatchEvent(new Event('open-child-create'));
  workspace.querySelector('.heading').append(createShortcut);
  const supportNote=document.createElement('p');supportNote.id='partners-create-support';supportNote.className='muted';
  workspace.querySelector('#partners-add').after(supportNote);
  const nav=document.createElement('button');nav.dataset.page='partners';nav.innerHTML='<span class="nav-icon" aria-hidden="true">✳</span><span class="nav-text">我的伙伴</span>';
  document.querySelector('nav button').after(nav);
  const panel=document.createElement('div');
  panel.className='panel'; panel.hidden=true;
  panel.innerHTML=`<div class="section-title"><h2>让分身开始工作</h2><span id="runtime-badge">等待检查</span></div>
    <button id="runtime-parent" class="secondary" hidden>切换到主智能体</button>
    <p class="muted">主、子智能体可分别启动，切换管理对象不会停止正在运行的伙伴。首次使用会下载运行组件。</p>
    <p id="runtime-message" role="status" aria-live="polite"></p>
    <div class="runtime-actions"><button id="runtime-start" class="primary">部署并启动</button>
    <a id="runtime-open" class="primary" target="_blank" rel="noopener noreferrer" hidden>开始对话 ↗</a>
    <button id="runtime-stop" class="secondary" hidden>停止智能体</button><button id="runtime-refresh" class="secondary">刷新状态</button></div>
    <p id="runtime-config-notice" class="muted"></p>
    <details id="runtime-model"><summary>高级模型设置（可选）</summary><p class="muted">默认使用已有模型连接，可直接启动。仅在需要更换模型时修改下列设置。</p>
    <form id="runtime-model-form"><label>服务地址<input id="runtime-base" type="url" required placeholder="https://api.deepseek.com/v1"></label>
    <label>模型名称<input id="runtime-model-name" required placeholder="服务商提供的模型名称"></label>
    <label>API Key<input id="runtime-key" type="password" autocomplete="new-password" placeholder="留空保留已有密钥"></label>
    <p id="runtime-key-status" class="muted"></p><button class="secondary">保存模型配置</button></form></details>`;
  workspace.querySelector('#partner-detail').append(panel);
  const roster=new Map();let rosterVersion=0;
  let currentType='octopus';let current='', timer, inflight=false, first=true, childSelected=false, selection=0;
  const el=id=>panel.querySelector('#'+id);
  const stageNames={idle:'等待启动',checking:'环境检查',installing:'安装中',starting:'启动中',ready:'服务已就绪',error:'需要处理'};
  function drawRoster(){
    const list=workspace.querySelector('#partners-list');list.replaceChildren();
    for(const item of roster.values()){
      const button=document.createElement('button');button.className='partner-choice';button.dataset.agent=item.id;
      button.setAttribute('aria-pressed',String(item.id===current));button.disabled=item.stage==='unavailable';
      const icon=document.createElement('span');icon.className='partner-avatar';icon.textContent=item.child?'✦':'✳';
      const text=document.createElement('span');const title=document.createElement('strong');title.textContent=item.name;
      const status=document.createElement('small');status.textContent=(item.agent_type==='openclaw'?'OpenClaw 执行分支':item.child?'Octopus 问答智能体':'Octopus 主智能体')+' · '+(stageNames[item.stage]||({recovering:'自动恢复中',unavailable:'旧实例待迁移'}[item.stage])||'待查询');
      text.append(title,status);button.append(icon,text);button.dataset.stage=item.stage||'unknown';
      button.onclick=()=>{selectAgent(item);};list.append(button);
    }
  }
  async function loadRoster(){
    supportNote.textContent=!state.phc?.id||!state.pa?'请先申领 Octopus 主智能体。':state.type==='openclaw'?'OpenClaw 为独立身份认证实例，不支持创建子智能体。':'Octopus 问答智能体通过 ANP 互发消息；OpenClaw 执行分支在执行控制台完成工作。';
    createShortcut.hidden=state.type!=='octopus';
    const parent=state.phc?.id;if(!state.loggedIn||!state.pa||!parent)return;
    const version=++rosterVersion;const id=parent.replaceAll(':','_');
    roster.clear();roster.set(id,{id,name:'我的主智能体',child:false,agent_type:state.type});drawRoster();
    const message=workspace.querySelector('#partners-message');message.textContent='正在更新分身列表…';
    workspace.querySelector('#partners-add').hidden=state.type!=='octopus';
    try{
      const main=await request('status',undefined,id);if(version!==rosterVersion)return;
      roster.get(id).stage=main.stage;drawRoster();
      if(state.type==='octopus'){
        const response=await fetch('/user/children/'+encodeURIComponent(parent),{credentials:'same-origin'});
        if(response.status===401||response.redirected){loginRequired();return;}
        const data=await response.json();if(!response.ok||data.success===false)throw Error(typeof data.detail==='string'?data.detail:'分身列表读取失败，请重试');
        if(version!==rosterVersion)return;
        for(const child of data.children)roster.set(child.phc_id,{id:child.phc_id,name:child.name,child:true,stage:child.stage,agent_type:child.agent_type});
      }
      message.textContent=state.type==='openclaw'?'独立 OpenClaw 实例，可在此启动与使用。':roster.size===1?'还没有子智能体，可以创建一位不同分工的分身。':'点击分身即可切换，状态以最近查询为准。';drawRoster();
      if(current&&!roster.has(current))selectAgent(roster.get(id));
    }catch(e){if(version===rosterVersion)message.textContent=e.message;}
  }
  workspace.querySelector('#partners-refresh').onclick=()=>{loadRoster();refresh();};
  workspace.querySelector('#partners-add').onclick=()=>window.dispatchEvent(new Event('open-child-create'));
  window.addEventListener('children-updated',loadRoster);
  window.addEventListener('hashchange',()=>{if(location.hash==='#partners')loadRoster();});
  async function request(suffix,body,id=current){
    const response=await fetch(`/user/runtime/${encodeURIComponent(id)}/${suffix}`,{credentials:'same-origin',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    if(response.status===401||response.redirected){loginRequired();throw new Error('请重新登录。');}
    if(response.status===404)throw new Error('网页启动服务尚未启用，请管理员重新运行用户端启动程序。');
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'操作未完成，请重试。');return data;
  }
  function render(data){
    const item=roster.get(current);if(item){item.stage=data.stage;drawRoster();}
    panel.dataset.stage=data.stage;
    el('runtime-open').textContent=currentType==='openclaw'?'打开执行控制台 ↗':'开始问答 ↗';
    const working=['checking','installing','starting','recovering'].includes(data.stage);
    el('runtime-badge').textContent=(data.stage==='recovering'?'自动恢复中':stageNames[data.stage])||'待检查';
    el('runtime-message').textContent=data.message;
    el('runtime-message').classList.toggle('runtime-error',data.stage==='error');
    el('runtime-start').disabled=working||data.stage==='ready';
    el('runtime-start').hidden=data.stage==='ready';
    el('runtime-start').textContent=working?'正在准备…':data.stage==='error'?'重试部署与启动':'部署并启动';
    el('runtime-start').setAttribute('aria-busy',String(working));
    el('runtime-stop').hidden=!['ready','recovering','error'].includes(data.stage);
    el('runtime-open').hidden=true;el('runtime-open').removeAttribute('href');
    if(data.stage==='ready'&&data.url){const target=new URL(data.url);if(target.hostname==='127.0.0.1'&&target.protocol==='http:'){el('runtime-open').href=target.href;el('runtime-open').hidden=false;}}
    panel.querySelectorAll('#runtime-model-form input, #runtime-model-form button').forEach(input=>input.disabled=working||data.stage==='ready');
    el('runtime-key-status').textContent=data.key_configured?({parent:'已自动沿用主智能体的模型配置，无需填写密钥。',system:'已自动使用平台默认模型配置，无需填写密钥。'}[data.model_config_source]||'已配置模型密钥，无需重复填写。'):'平台尚未配置模型密钥，请联系管理员。';
    el('runtime-config-notice').textContent=data.key_configured?'已使用本机已有模型密钥，可直接部署并启动。':'正在使用本机模型配置；若无法启动，请管理员检查默认连接。';
    el('runtime-key').closest('label').hidden=!!data.key_configured;
    if(data.key_configured&&data.message==='请先在下方填写并保存模型 API Key。')el('runtime-message').textContent='已有模型配置已补齐，请点击重试部署与启动。';
    if(first){el('runtime-base').value=data.base_url||'';el('runtime-model-name').value=data.model||'';el('runtime-model').open=false;first=false;}
    if(data.stage==='ready'){document.querySelector('#agent-stat').textContent='服务已就绪';document.querySelector('#progress-stat').textContent='可以开始对话';}
    clearTimeout(timer);timer=setTimeout(refresh,working?1800:10000);
  }
  async function refresh(){if(!current||inflight)return;const version=selection;inflight=true;try{const data=await request('status');if(version===selection)render(data);}catch(e){if(version===selection){el('runtime-message').textContent=e.message;clearTimeout(timer);}}finally{if(version===selection)inflight=false;}}
  async function command(suffix){const version=selection;el('runtime-start').disabled=true;el('runtime-stop').disabled=true;try{const data=await request(suffix,{});if(version===selection)render(data);}catch(e){if(version===selection){el('runtime-message').textContent=e.message;el('runtime-start').disabled=false;}}finally{if(version===selection)el('runtime-stop').disabled=false;}}
  el('runtime-start').addEventListener('click',()=>command('start'));
  el('runtime-stop').addEventListener('click',()=>command('stop'));
  el('runtime-refresh').addEventListener('click',refresh);
  el('runtime-model-form').addEventListener('submit',async event=>{event.preventDefault();const version=selection;const button=event.submitter;button.disabled=true;try{await request('model',{api_key:el('runtime-key').value,base_url:el('runtime-base').value,model:el('runtime-model-name').value});if(version!==selection)return;el('runtime-key').value='';await refresh();notice('模型配置已保存，点击部署并启动。');}catch(e){if(version===selection)notice(e.message,true);}finally{if(version===selection)button.disabled=false;}});
  function selectAgent(detail){
    selection++;inflight=false;childSelected=!!detail.child;current=detail.id.replaceAll(':','_');currentType=detail.agent_type||roster.get(current)?.agent_type||state.type;first=true;
    window.dispatchEvent(new CustomEvent('runtime-selected',{detail:{id:current,child:childSelected,agent_type:currentType}}));
    clearTimeout(timer);panel.hidden=false;
    workspace.querySelector('#partners-empty').hidden=true;drawRoster();
    panel.classList.remove('partner-enter');void panel.offsetWidth;panel.classList.add('partner-enter');
    panel.querySelector('h2').textContent=detail.name+' · 运行管理';
    el('runtime-parent').hidden=!childSelected;
    el('runtime-badge').textContent='正在查询';el('runtime-message').textContent='正在读取当前智能体状态…';
    el('runtime-open').hidden=true;el('runtime-open').removeAttribute('href');
    el('runtime-stop').hidden=true;el('runtime-stop').disabled=false;el('runtime-start').disabled=true;
    el('runtime-start').hidden=false;
    el('runtime-start').textContent='正在查询…';
    panel.querySelectorAll('#runtime-model-form input').forEach(input=>{input.value='';input.disabled=true;});
    panel.querySelector('#runtime-model-form button').disabled=true;
    el('runtime-key-status').textContent='';refresh();
  }
  el('runtime-parent').addEventListener('click',()=>{if(state.phc?.id)selectAgent({id:state.phc.id,name:'主智能体',child:false});});
  function connect(){
    loadRoster();
    if(childSelected)return;
    const id=state.phc?.id?.replaceAll(':','_');
    if(!state.loggedIn||!state.pa||!id)return;
    panel.hidden=false;
    if(id!==current)selectAgent({id,name:'主智能体',child:false});
  }
  window.addEventListener('agent-record-ready',connect);
  window.addEventListener('select-agent-runtime',event=>{
    selectAgent(event.detail);
    page('partners');
  });
  connect();
  if(location.hash==='#partners')page('partners');
})();
