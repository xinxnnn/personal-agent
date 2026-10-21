"""Octopus runtime adapter: native MessageAgent over the existing ANP gateway."""
import asyncio
import hmac
import json
import os
import sys
import uuid
from typing import Literal
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'anp-proxy'))
sys.path.insert(0,str(ROOT))
from app.anp_mailbox import ActivityLog, Mailbox
from app.identity_memory import Memory

class MessageRequest(BaseModel):
    message_id:str=Field(default_factory=lambda:uuid.uuid4().hex,pattern=r'^[A-Za-z0-9_-]{1,80}$')
    target_id:str=Field(max_length=120)
    content:str=Field(min_length=1,max_length=4000)
    purpose:Literal['message','chat']='message'

class AuthenticatedMessage(MessageRequest):
    identity_proof:dict

async def group_chat(message, target_host, message_id=None):
    """Route native chat through the managed gateway, never a direct fallback."""
    registry=Path(os.environ['OCTOPUS_GROUP_FILE'])
    data=json.loads(registry.read_text(encoding='utf-8'))
    source=os.environ['OCTOPUS_INSTANCE_ID']
    targets=[key for key,value in data['members'].items()
             if target_host in (f"127.0.0.1:{value['port']}",f"localhost:{value['port']}") and key!=source]
    if len(targets)!=1:
        raise ValueError('请选择已启动的同组主/子智能体地址；目标端口请从伙伴运行页面获取。')
    target=targets[0]
    body=MessageRequest(message_id=message_id or uuid.uuid4().hex,target_id=target,content=message,purpose='chat').model_dump()
    activity=ActivityLog(registry.with_suffix('.activity.sqlite3'))
    event_prefix=f"{source}:{body['message_id']}"
    activity.record(f"{event_prefix}:request-sent",'request_sent',source,target,body['message_id'])
    memory=Memory(Path(os.environ['OCTOPUS_GROUP_FILE']).parents[1]/'agents'/source,source,
                  'octopus-group:'+Path(os.environ['OCTOPUS_GROUP_FILE']).stem,
                  lambda:json.loads(Path(os.environ['OCTOPUS_GROUP_FILE']).read_text(encoding='utf-8'))['members'])
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=120) as client:
            headers={'Host':f"127.0.0.1:{data['members'][target]['port']}",
                     'Authorization':'Bearer '+data['members'][source]['token'],'x-agent-sender':source}
            challenge=await client.post(data['gateway_http']+'/local-anp/challenge',json=body,headers=headers)
            if challenge.status_code!=200:raise ValueError('目标智能体认证服务不可用，请刷新列表并确认双方已重启')
            proof=memory.answer(challenge.json(),body)
            response=await client.post(data['gateway_http']+'/local-anp/chat',
                json={**body,'identity_proof':proof},headers=headers)
            response.raise_for_status()
            result=response.json()
            evidence=result.get('identity_evidence')
            from app.identity_memory import digest
            if (not evidence or evidence['event']['request']!=memory.event_request(source,body)
                    or evidence['event'].get('response_hash')!=digest(result['response'])):
                raise ValueError('目标回复缺少有效的签名证据')
            memory.record(evidence)
            activity.record(f"{event_prefix}:response-received",'response_received',source,target,body['message_id'])
            mailbox=Mailbox(Path(os.environ['OCTOPUS_GROUP_FILE']).parents[1]/'agents'/source/'anp_messages.sqlite3')
            mailbox.begin_conversation(body['message_id'],'sent',target,message)
            mailbox.finish_conversation(body['message_id'],'sent',result['response'])
            return {'response':result['response'],'identity_auth':result['identity_auth'],
                    'identity_events':memory.status()['events'],'peer_id':target}
    except Exception:
        activity.record(f"{event_prefix}:request-failed",'request_failed',source,target,body['message_id'],'failed')
        raise

def attach(app,agent_getter,registry,instance_id,chat_getter=None):
    from anp_proxy.receiver.client import ReceiverClient
    from anp_proxy.common.config import ReceiverConfig, AuthConfig
    receiver_app=FastAPI()
    receiver=None
    mailbox=Mailbox(Path(registry).parents[1]/'agents'/instance_id/'anp_messages.sqlite3')
    delivery_lock=asyncio.Lock()
    def config():return json.loads(Path(registry).read_text(encoding='utf-8'))
    own_token=config()['members'][instance_id]['token']
    memory=Memory(Path(registry).parents[1]/'agents'/instance_id,instance_id,
                  'octopus-group:'+Path(registry).stem,lambda:config()['members'])
    def authorize(request,token):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):
            raise HTTPException(403,'Invalid group authentication')
    def peers(source,target):
        data=config();members=data['members']
        if source==target or source not in members or target not in members:
            raise HTTPException(403,'Only group peers may communicate')
        # Archived/deleted members must not retain access through stale registry entries.
        for member_id in (source,target):
            if not (Path(registry).parents[1]/'agents'/member_id/'agent_manifest.json').is_file():
                raise HTTPException(403,'Group member no longer exists')
        return data

    @receiver_app.post('/local-anp/challenge')
    async def challenge(body:MessageRequest,request:Request):
        sender=request.headers.get('x-agent-sender','')
        data=peers(sender,instance_id)
        authorize(request,data['members'][sender]['token'])
        if body.target_id!=instance_id:raise HTTPException(403,'Wrong recipient')
        return memory.challenge(sender,body.model_dump())

    @receiver_app.post('/local-anp/receive')
    async def receive(body:AuthenticatedMessage,request:Request):
        sender=request.headers.get('x-agent-sender','')
        data=peers(sender,instance_id)
        authorize(request,data['members'][sender]['token'])
        if body.target_id!=instance_id:raise HTTPException(403,'Wrong recipient')
        if body.purpose!='message':raise HTTPException(400,'Wrong operation')
        async with delivery_lock:
            message=body.model_dump(exclude={'identity_proof'})
            mode=memory.authenticate(sender,message,body.identity_proof)
            row=mailbox.reserve('in',sender,body.message_id,instance_id,body.content)
            if row['receipt']:return json.loads(row['receipt'])
            if agent_getter is not None:
                agent=agent_getter()
                if agent is None:raise HTTPException(503,'Message agent not ready')
                result=agent.receive_message(body.content,'local:'+sender,{'transport':'ANP','recipient':instance_id,'message_id':body.message_id})
                if not result.get('success'):raise HTTPException(502,'Message delivery failed')
            receipt={'success':True,'message_id':body.message_id,'sender_did':'local:'+sender,'content':body.content,'timestamp':row['timestamp'],'status':'received'}
            receipt['identity_evidence']=memory.receipt(sender,message,body.identity_proof,row['timestamp'])
            receipt['identity_auth']=mode
            mailbox.finish('in',sender,body.message_id,'received',receipt)
            return receipt

    @receiver_app.post('/local-anp/chat')
    async def chat(body:AuthenticatedMessage,request:Request):
        sender=request.headers.get('x-agent-sender','')
        data=peers(sender,instance_id)
        authorize(request,data['members'][sender]['token'])
        if body.target_id!=instance_id:raise HTTPException(403,'Wrong recipient')
        if body.purpose!='chat':raise HTTPException(400,'Wrong operation')
        agent=chat_getter() if chat_getter else None
        if agent is None:raise HTTPException(503,'目标智能体不支持对话或尚未就绪')
        mode=memory.authenticate(sender,body.model_dump(exclude={'identity_proof'}),body.identity_proof)
        mailbox.begin_conversation(body.message_id,'received',sender,body.content)
        activity_log=ActivityLog(Path(registry).with_suffix('.activity.sqlite3'))
        event_prefix=f"{instance_id}:{body.message_id}"
        activity_log.record(f"{event_prefix}:request-received",'request_received',instance_id,sender,body.message_id)
        try:
            result=await agent.process_natural_language(request=body.content,request_id=body.message_id)
        except Exception:
            mailbox.finish_conversation(body.message_id,'received','智能体暂时无法完成回复，请稍后重试。','failed')
            activity_log.record(f"{event_prefix}:response-returned",'response_returned',instance_id,sender,body.message_id,'failed')
            raise
        mailbox.finish_conversation(body.message_id,'received',result)
        activity_log.record(f"{event_prefix}:response-returned",'response_returned',instance_id,sender,body.message_id)
        from datetime import datetime,timezone
        evidence=memory.receipt(sender,body.model_dump(exclude={'identity_proof'}),body.identity_proof,
                                datetime.now(timezone.utc).isoformat(),response=result)
        return {'response':result,'identity_auth':mode,'identity_evidence':evidence}

    @app.get('/local-anp/messages')
    async def messages(request:Request):
        authorize(request,own_token)
        return {'success':True,'connected':bool(receiver and receiver.connected),'transport':'ANP / ANPX',
                'messages':mailbox.listing('in'),'sent':mailbox.listing('out'),
                'activity':mailbox.activity(),'identity_memory':memory.status()}

    @app.post('/local-anp/send')
    async def send(body:MessageRequest,request:Request):
        authorize(request,own_token)
        data=peers(instance_id,body.target_id)
        row=mailbox.reserve('out',instance_id,body.message_id,body.target_id,body.content)
        if row['receipt']:return {'success':True,'transport':'ANP / ANPX','receipt':json.loads(row['receipt'])}
        if not receiver or not receiver.connected:raise HTTPException(409,'ANP receiver disconnected')
        target=data['members'][body.target_id]
        async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
            try:
                headers={'Host':f"127.0.0.1:{target['port']}",'Authorization':'Bearer '+own_token,'x-agent-sender':instance_id}
                challenge_response=await client.post(data['gateway_http']+'/local-anp/challenge',json=body.model_dump(),headers=headers)
                challenge_response.raise_for_status()
                proof=memory.answer(challenge_response.json(),body.model_dump())
                response=await client.post(data['gateway_http']+'/local-anp/receive',
                    json={**body.model_dump(),'identity_proof':proof},headers=headers)
                response.raise_for_status();result=response.json()
            except (httpx.HTTPError,ValueError):
                mailbox.finish('out',instance_id,body.message_id,'failed')
                raise HTTPException(502,'ANP 投递未确认，可使用同一消息编号重试')
            except HTTPException:
                mailbox.finish('out',instance_id,body.message_id,'failed')
                raise
        if not result.get('success'):raise HTTPException(502,'Receiver did not acknowledge delivery')
        evidence=result.get('identity_evidence')
        if not evidence or evidence['event']['request']!=memory.event_request(instance_id,body.model_dump()):
            raise HTTPException(502,'接收回执缺少匹配的可信事件')
        memory.record(evidence)
        mailbox.finish('out',instance_id,body.message_id,'delivered',result)
        return {'success':True,'transport':'ANP / ANPX','receipt':result}

    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        nonlocal receiver
        async with original(application):
            data=config();info=data['members'][instance_id]
            receiver=ReceiverClient(ReceiverConfig(gateway_url=data['gateway_ws'],local_host='127.0.0.1',
                local_port=info['port'],auth=AuthConfig(enabled=False,did_wba_enabled=False)),receiver_app)
            try:
                await receiver.start()
                yield
            finally:await receiver.stop()
    app.router.lifespan_context=lifespan

def main():
    import uvicorn
    # The group receiver replaces the external DID receiver for this local launch only.
    os.environ['ANP_SDK_ENABLED']='false'
    from octopus.config.settings import set_cli_overrides
    set_cli_overrides(host='127.0.0.1',port=int(sys.argv[1]),anp_sdk_enabled=False)
    from octopus import octopus as native
    @asynccontextmanager
    async def native_lifespan(application):
        async with native.app.router.lifespan_context(native.app):yield
    application=FastAPI(lifespan=native_lifespan)
    # Keep native JWT middleware on native routes; group endpoints use their own tokens.
    from octopus.api import chat_router
    attach(application,lambda:native.message_agent,os.environ['OCTOPUS_GROUP_FILE'],os.environ['OCTOPUS_INSTANCE_ID'],lambda:chat_router.master_agent)
    application.mount('/',native.app)
    uvicorn.run(application,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')

if __name__=='__main__':main()
