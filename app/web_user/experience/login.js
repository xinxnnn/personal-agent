'use strict';
const form=document.querySelector('#login-form');
const password=document.querySelector('#password');
const toggle=document.querySelector('#toggle-password');
const error=document.querySelector('#login-error');
document.querySelector('#fill-demo').addEventListener('click',()=>{
 form.elements.username.value='user';
 password.value='pa@2026';
 error.textContent='';
 form.querySelector('[type=submit]').focus();
});
toggle.addEventListener('click',()=>{const show=password.type==='password';password.type=show?'text':'password';toggle.setAttribute('aria-label',show?'隐藏密码':'显示密码');toggle.setAttribute('aria-pressed',String(show));});
form.addEventListener('submit',async event=>{
 event.preventDefault(); const button=form.querySelector('[type=submit]'); if(button.disabled)return;
 button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='正在登录…';error.textContent='';
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
 try{
  const response=await fetch('/user/api/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value.trim(),password:password.value}),signal:controller.signal});
  if(response.status===401){throw new Error('账号或密码不正确，请重新输入。');}
  if(!response.ok)throw new Error('暂时无法登录，请稍后重试。');
  const data=await response.json();if(!data.success||!data.user)throw new Error('登录未成功，请重试。');
  password.value='';
  const next=new URLSearchParams(location.search).get('page');
  location.replace('./index.html'+(['home','create','identity','settings','partners'].includes(next)?'#'+next:''));
 }catch(e){error.textContent=e.name==='AbortError'?'连接超时，请检查用户服务是否启动。':e instanceof TypeError?'无法连接服务，请检查用户服务是否启动。':e.message;}
 finally{clearTimeout(timeout);button.disabled=false;button.removeAttribute('aria-busy');button.innerHTML='进入我的空间 <span aria-hidden="true">→</span>';}
});
