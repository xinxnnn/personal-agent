'use strict';
(() => {
  names.create='我的化身'; names.partners='我的智能体';
  const nav=document.querySelector('nav');
  nav.prepend(nav.querySelector('[data-page="create"]'));
  nav.querySelector('[data-page="create"] .nav-text').textContent='我的化身';
  nav.querySelector('[data-page="partners"] .nav-text').textContent='我的智能体';
  $('#page-create h1').textContent='先申领你的化身';
  $('#scenario-note').textContent='申领 Octopus 作为你的主智能体，创建不同分工的子智能体，通过系统内 ANP 交换信息。收到消息不代表自动执行任务。';
  $('#step1').textContent='01 申领资料'; $('#step2').textContent='02 化身能力'; $('#step3').textContent='03 完成申领';
  $('#identity-form').closest('.panel').querySelector('h2').textContent='1. 填写化身申领资料';
  $('#create-agent').textContent='完成申领 · 生成我的化身';
  $('#create-agent').closest('.panel').querySelector('h2').textContent='3. 生成我的化身';
  const welcome=document.createElement('p');welcome.className='panel';welcome.setAttribute('role','status');
  welcome.textContent='请先完成化身申领。身份审核与能力绑定仍由原有服务处理，完成后解锁个人工作台。';
  const recoveryShortcut=document.createElement('button');recoveryShortcut.type='button';recoveryShortcut.className='secondary setup-recovery-link';recoveryShortcut.textContent='已有身份凭证？找回身份与伙伴';recoveryShortcut.onclick=()=>page('identity');
  $('#page-create .steps').before(welcome,recoveryShortcut);
  const next=document.createElement('button');next.className='primary';next.textContent='查看我的可信身份 →';next.type='button';next.onclick=()=>page('identity');
  $('#creation-result').after(next);
  const enter=$('#page-identity .identity-banner button');
  $('#page-partners h1').textContent='我的智能体';
  $('#page-partners .heading p:last-child').textContent='为化身申领不同分工的分身，通过对话一步步完成创建。';
  $('#partners-create-shortcut').textContent='＋ 对话申领分身';$('#partners-add').textContent='＋ 对话申领分身';
  const setupBar=document.createElement('div');setupBar.className='setup-bar';
  setupBar.innerHTML='<b>智契化身 · 首次设置</b><div><button type="button" class="text-button" data-page="settings">连接设置</button><button type="button" class="text-button" id="setup-logout">退出账号</button></div>';
  document.querySelector('main').prepend(setupBar);
  $('#setup-logout').onclick=()=>$('#logout').click();
  const panels=[...$('#page-create').children].filter(el=>el.classList.contains('panel')&&el!==welcome);
  const back=document.createElement('button');back.type='button';back.className='text-button';back.textContent='← 返回化身申领';back.onclick=()=>page('create');$('#page-settings').prepend(back);
  function update(){
    const ready=!!(state.avatarReady||state.created);
    nav.querySelector('[data-page="partners"] .nav-text').textContent=state.type==='openclaw'?'独立实例':'我的智能体';
    $('#page-partners h1').textContent=state.type==='openclaw'?'OpenClaw 独立实例':'我的智能体';
    $('#page-partners .heading p:last-child').textContent=state.type==='openclaw'?'已绑定可信身份的独立工作助手，不支持创建子智能体。':'Octopus 负责问答与 ANP 通信；OpenClaw 执行分支负责在独立控制台完成工作。';
    document.body.classList.toggle('first-setup',!ready);setupBar.hidden=ready;back.hidden=ready;
    const current=state.pa?2:state.phc?1:0;
    panels.forEach((panel,index)=>panel.hidden=!ready&&index!==current);
    $('#page-create h1').textContent=ready?'我的化身':['欢迎，先申领你的化身','选择化身的能力','完成你的化身设置'][current];
    for(const key of ['home','partners']){const button=nav.querySelector(`[data-page="${key}"]`);button.disabled=!ready;button.title=ready?'':'完成化身申领后解锁';}
    const identityNav=nav.querySelector('[data-page="identity"]');identityNav.disabled=false;identityNav.hidden=false;identityNav.title='';
    enter.dataset.page=ready?'home':'create';enter.textContent=ready?'进入工作台 →':'返回化身申领 →';
    welcome.hidden=ready;recoveryShortcut.hidden=ready;next.hidden=!ready;
    if(!ready&&!['#settings','#identity'].includes(location.hash))page('create');
  }
  window.addEventListener('avatar-flow-sync',update);
  window.addEventListener('agent-record-ready',()=>{update();page(state.avatarReady?'home':'create');});
  update();

  const dialog=document.querySelector('.child-create-dialog'),form=$('#child-form');
  $('#child-create-title').textContent='添加问答智能体或执行分支';
  const intro=dialog.querySelector('.section-title + p');if(intro)intro.textContent='告诉化身你需要怎样的伙伴。确认后沿用现有创建流程。';
  const conversation=document.createElement('div');conversation.className='panel';conversation.setAttribute('aria-live','polite');
  const prompt=document.createElement('p'),answer=document.createElement('input'),advance=document.createElement('button');
  answer.className='conversation-answer';answer.setAttribute('aria-label','回复创建引导');advance.type='button';advance.className='primary';advance.textContent='下一步 →';
  conversation.append(prompt,answer,advance);form.before(conversation);
  const grid=form.querySelector('.form-grid');let step=0;
  function render(){
    form.hidden=step<2;conversation.hidden=step===2;
    prompt.textContent=step===0?'你好，我们来创建一位分身。你想给它取什么名字？':'你希望这位分身帮你做什么？例如：整理学习资料、总结论文。';
    answer.maxLength=step===0?32:500;answer.value=step===0?form.elements.name.value:form.elements.description.value;
    advance.textContent=step===0?'下一步 →':'确认分工，选择能力 →';
    if(step===2){grid.hidden=false;form.querySelector('button').textContent='确认添加智能体';}
  }
  advance.onclick=()=>{
    if(!answer.value.trim()){answer.setCustomValidity('请先填写你的回答');answer.reportValidity();return;}
    if(step===0)form.elements.name.value=answer.value.trim();else form.elements.description.value=answer.value.trim();
    step++;render();if(step<2)answer.focus();else form.elements.name.focus();
  };
  answer.oninput=()=>answer.setCustomValidity('');answer.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();advance.click();}};
  new MutationObserver(()=>{if(dialog.open){step=0;render();answer.focus();}}).observe(dialog,{attributes:true,attributeFilter:['open']});
})();
