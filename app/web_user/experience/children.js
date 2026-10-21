'use strict';
(() => {
 const section=document.createElement('section');section.className='panel';section.hidden=true;
 section.innerHTML=`<div class="section-title"><h2>我的智能体</h2><button class="secondary" id="children-refresh">刷新列表</button></div>
 <p class="muted">在 Octopus 主智能体下创建不同分工的 Octopus 子智能体，共用主身份关联，各自独立部署与运行。</p>
 <p id="children-status" role="status"></p><div id="children-list"></div>
 <details><summary>＋ 添加智能体</summary><form id="child-form"><div class="form-grid">
 <label>分身名称<input name="name" required maxlength="32" placeholder="例如：学习助手"></label>
 <label>分工说明<input name="description" maxlength="500" placeholder="例如：协助整理学习资料"></label></div>
 <p class="muted">子智能体只能是 Octopus 问答智能体。初始模型连接沿用主智能体，可在子智能体的运行管理中单独修改。</p>
 <div class="capability-row"></div>
 <button class="primary" style="margin-top:16px">添加智能体</button></form></details>`;
 document.querySelector('#agent-card').after(section);
 const dialog=document.createElement('dialog');dialog.className='child-create-dialog';dialog.setAttribute('aria-labelledby','child-create-title');
 dialog.innerHTML='<div class="section-title"><div><p class="eyebrow">NEW COMPANION</p><h2 id="child-create-title">添加智能体</h2></div><button type="button" class="text-button" id="child-create-close" aria-label="关闭创建窗口">关闭 ×</button></div><p class="muted">为主智能体添加一位有独立分工的子智能体。创建完成后，可以继续部署和配置。</p><p id="child-create-parent" class="muted"></p><p id="child-create-feedback" role="status" aria-live="polite"></p>';
 const form=section.querySelector('#child-form');dialog.append(form);document.body.append(dialog);
 const entry=document.createElement('button');entry.className='secondary';entry.textContent='＋ 添加智能体';
 section.querySelector('details').replaceWith(entry);
 let submitting=false;
 const choices=[['text-processing','文本处理'],['news-search','新闻搜索'],['web-browsing','网页浏览'],['webchat','网页对话']];
 const capabilityRow=form.querySelector('.capability-row');
 for(const [value,label] of choices){const option=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.name='capability';input.value=value;input.defaultChecked=input.checked=value==='webchat';option.append(input,document.createTextNode(label));capabilityRow.append(option);}
 function openCreate(){
   if(state.type!=='octopus'){notice('仅 Octopus 主智能体支持添加子智能体。',true);return;}
   if(!state.loggedIn||!state.phc?.id||!state.pa){notice('请先完成主智能体的创建，再添加子智能体。',true);return;}
   parent=state.phc.id;
   dialog.querySelector('#child-create-parent').textContent='所属主智能体：'+parent;
   dialog.querySelector('#child-create-feedback').textContent='';
   if(!dialog.open)dialog.showModal();form.elements.name.focus();
 }
 entry.onclick=openCreate;
 window.addEventListener('open-child-create',openCreate);
 dialog.querySelector('#child-create-close').onclick=()=>{if(!submitting)dialog.close();};
 dialog.addEventListener('cancel',event=>{if(submitting)event.preventDefault();});
 dialog.addEventListener('close',()=>document.querySelector('#partners-add')?.focus());
 const $c=s=>section.querySelector(s);let parent='', loading=false;
 async function call(path,body){const r=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});if(r.status===401||r.redirected){loginRequired();throw new Error('请重新登录');}if(r.status===404)throw new Error('请管理员重启用户服务以启用子智能体功能');let d;try{d=await r.json();}catch{throw new Error(`子智能体服务返回异常（HTTP ${r.status}），请管理员查看用户服务日志；更新代码后请重启用户服务。`);}if(!r.ok||d.success===false)throw new Error(typeof d.detail==='string'?d.detail:d.error||'操作失败');return d;}
 const labels={idle:'待启动',checking:'检查中',installing:'安装中',starting:'启动中',ready:'服务已就绪',error:'需要处理',unavailable:'旧实例待迁移'};
 async function refresh(){if(!parent||loading)return;loading=true;$c('#children-refresh').disabled=true;try{const data=await call('/user/children/'+encodeURIComponent(parent));$c('#children-list').replaceChildren();$c('#children-status').textContent=data.children.length?`共有 ${data.children.length} 位子智能体`:'还没有子智能体，在下方创建第一位伙伴。';for(const child of data.children){const card=document.createElement('article');card.className='child-card';const info=document.createElement('div');const title=document.createElement('h3');title.textContent=child.name;const status=document.createElement('p');status.className='muted';status.textContent='Octopus 问答智能体 · '+(labels[child.stage]||'状态待确认');info.append(title,status);const button=document.createElement('button');button.className='secondary';button.textContent='部署 / 对话 / 设置';button.disabled=child.stage==='unavailable';button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('select-agent-runtime',{detail:{id:child.phc_id,name:child.name,child:true,agent_type:'octopus'}})));const del=document.createElement('button');del.className='text-button';del.textContent='申请删除';del.onclick=()=>window.dispatchEvent(new CustomEvent('request-agent-deletion',{detail:{id:child.phc_id}}));card.append(info,button,del);$c('#children-list').append(card);}}catch(e){$c('#children-status').textContent=e.message;}finally{loading=false;$c('#children-refresh').disabled=false;}}
 $c('#children-refresh').addEventListener('click',refresh);
 form.addEventListener('submit',async event=>{
   event.preventDefault();if(submitting)return;
   if(state.type!=='octopus'){notice('仅 Octopus 支持添加智能体。',true);return;}
   const values=new FormData(form);const name=values.get('name').trim();
   const feedback=dialog.querySelector('#child-create-feedback');
   if(!name){feedback.textContent='请填写子智能体名称。';form.elements.name.focus();return;}
   submitting=true;const button=form.querySelector('button');button.textContent='正在创建…';
   dialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=true);feedback.textContent='正在生成伙伴，请稍候…';
   try{
     const result=await call('/user/children/create',{parent_phc_id:parent,agent_type:'octopus',name,description:values.get('description'),capabilities:values.getAll('capability')});
     form.reset();dialog.close();window.dispatchEvent(new Event('children-updated'));
     window.dispatchEvent(new CustomEvent('select-agent-runtime',{detail:{id:result.child.phc_id,name:result.child.name,child:true,agent_type:'octopus'}}));
     notice('子智能体已创建。点击部署并启动，让新分身开始工作。');await refresh();
   }catch(e){feedback.textContent=e.message;}
   finally{submitting=false;dialog.querySelectorAll('input,select,button').forEach(el=>el.disabled=false);button.textContent='添加智能体';}
 });
 function connect(){section.hidden=true;if(!state.loggedIn||!state.phc?.id||!state.pa||state.type!=='octopus')return;section.hidden=false;if(parent!==state.phc.id){parent=state.phc.id;refresh();}}
 window.addEventListener('agent-record-ready',connect);
 const parentButton=document.createElement('button');parentButton.className='text-button';parentButton.textContent='管理主智能体';parentButton.addEventListener('click',()=>{if(state.phc?.id)window.dispatchEvent(new CustomEvent('select-agent-runtime',{detail:{id:state.phc.id.replaceAll(':','_'),name:'主智能体',child:false,agent_type:'octopus'}}));});section.querySelector('.section-title').append(parentButton);
 connect();
})();
