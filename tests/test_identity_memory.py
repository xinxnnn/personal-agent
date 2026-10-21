import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from app.identity_memory import Memory, provision
from app.octopus_group_runtime import attach
from app import group_anp


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.members={}
        for name in ('a','b','c'):
            path=self.root/name;path.mkdir()
            self.members[name]={'memory_public_key':provision(path)}
        self.a,self.b,self.c=[Memory(self.root/n,n,'group:test',lambda:self.members) for n in ('a','b','c')]
        self.body={'message_id':'one','target_id':'b','content':'hello'}

    def exchange(self):
        challenge=self.b.challenge('a',self.body)
        proof=self.a.answer(challenge,self.body)
        self.assertEqual(self.b.authenticate('a',self.body,proof),'bootstrap')
        document=self.b.receipt('a',self.body,proof,'2026-10-14T00:00:00Z')
        self.a.record(document)
        return document

    def test_reopen_graph_history_and_duplicate(self):
        document=self.exchange()
        self.a.record(document)
        self.assertEqual(self.a.status()['events'],1)
        a=Memory(self.root/'a','a','group:test',lambda:self.members)
        b=Memory(self.root/'b','b','group:test',lambda:self.members)
        body={**self.body,'message_id':'two'}
        challenge=b.challenge('a',body)
        self.assertEqual(challenge['payload']['mode'],'history')
        proof=a.answer(challenge,body)
        self.assertEqual(b.authenticate('a',body,proof),'history')
        with self.assertRaises(HTTPException):b.authenticate('a',body,proof)

    def test_expired_wrong_identity_and_modified_request(self):
        challenge=self.b.challenge('a',self.body)
        proof=self.a.answer(challenge,self.body)
        with self.assertRaises(HTTPException):self.b.authenticate('c',self.body,proof)
        with self.assertRaises(HTTPException):self.b.authenticate('a',{**self.body,'content':'tampered'},proof)
        with patch('app.identity_memory.time.time',return_value=challenge['payload']['expires']+1):
            with self.assertRaises(HTTPException):self.b.authenticate('a',self.body,proof)

    def test_missing_history_fails_without_downgrade(self):
        self.exchange()
        challenge=self.b.challenge('a',self.body)
        with self.a.db() as db:
            db.execute('DELETE FROM events');db.execute('DELETE FROM edges')
        with self.assertRaises(HTTPException):self.a.answer(challenge,self.body)

    def test_tamper_evidence_and_graph(self):
        self.exchange()
        with self.a.db() as db:
            row=db.execute('SELECT id,document FROM events').fetchone()
            doc=json.loads(row[1]);doc['event']['timestamp']='forged'
            db.execute('UPDATE events SET document=? WHERE id=?',(json.dumps(doc),row[0]))
        with self.assertRaises(HTTPException):self.a.answer(self.b.challenge('a',self.body),self.body)
        with self.b.db() as db:db.execute("DELETE FROM edges WHERE relation='sender'")
        with self.assertRaises(HTTPException):self.b.challenge('a',self.body)

    def test_wrong_evidence_signed_by_real_sender_rejected(self):
        self.exchange()
        proof=self.a.answer(self.b.challenge('a',self.body),self.body)
        proof['payload']['evidence_hash']='forged'
        proof['signature']=self.a.sign(proof['payload'])
        with self.assertRaises(HTTPException):self.b.authenticate('a',self.body,proof)

    def test_atomic_challenge_consumption(self):
        from concurrent.futures import ThreadPoolExecutor
        proof=self.a.answer(self.b.challenge('a',self.body),self.body)
        def consume():
            try:return self.b.authenticate('a',self.body,proof)
            except HTTPException:return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:consume(),range(2)))
        self.assertCountEqual(results,['bootstrap','rejected'])

    def test_no_silent_downgrade_when_verifier_loses_history(self):
        self.exchange()
        with self.b.db() as db:
            db.execute('DELETE FROM events');db.execute('DELETE FROM edges')
        with self.assertRaises(HTTPException):self.a.answer(self.b.challenge('a',self.body),self.body)

    def test_graph_query_does_not_mix_participants(self):
        self.exchange()
        self.assertIsNone(self.a.query('a','c'))
        self.assertIsNone(self.a.query('c','b'))
        doc=self.a.query('a','b')[1]
        doc['signature']='invalid'
        with self.assertRaises(HTTPException):self.a.record(doc)


class GatewayHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_disconnect_reconnect_then_history_auth(self):
        http,ws=await asyncio.to_thread(group_anp.ensure_gateway)
        self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            members={}
            for name,port in [('parent',19031),('child',19032)]:
                path=root/'agents'/name;path.mkdir(parents=True)
                (path/'agent_manifest.json').write_text('{}')
                members[name]={'port':port,'token':name+'-test','memory_public_key':provision(path)}
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}',
                'gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            # Fresh app objects after both WebSocket receivers have shut down.
            for cycle,mode in [(0,'bootstrap'),(1,'history')]:
                a,b=FastAPI(),FastAPI()
                attach(a,None,registry,'parent');attach(b,None,registry,'child')
                async with a.router.lifespan_context(a),b.router.lifespan_context(b):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a),base_url='http://test') as ca,httpx.AsyncClient(transport=httpx.ASGITransport(app=b),base_url='http://test') as cb:
                        for source,target,client in [('parent','child',ca),('child','parent',cb)]:
                            response=await client.post('/local-anp/send',headers={'Authorization':'Bearer '+members[source]['token']},
                                json={'message_id':f'{source}-{cycle}','target_id':target,'content':'trusted history test'})
                            self.assertEqual(response.status_code,200,response.text)
                            self.assertEqual(response.json()['receipt']['identity_auth'],mode)
                        status=await cb.get('/local-anp/messages',headers={'Authorization':'Bearer child-test'})
                        self.assertEqual(status.json()['identity_memory']['last_auth']['mode'],mode)
                        self.assertEqual(status.json()['identity_memory']['events'],2*(cycle+1))


if __name__=='__main__':unittest.main()
