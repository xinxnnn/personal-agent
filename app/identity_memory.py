"""Local managed identity + signed event graph for Octopus history challenges.

Trust anchor: the user service's group registry, NOT a new PHC/PA verifier.
Each instance owns a separate key and SQLite graph. No LLM participates.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def provision(path):
    """Called under the trusted orchestrator lock, never by a remote peer."""
    path = Path(path)/'identity_memory.key'
    if not path.exists():
        key = Ed25519PrivateKey.generate()
        with path.open('xb') as f:
            f.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption()))
        path.chmod(0o600)
    key = Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


class Memory:
    def __init__(self, path, identity, domain, members):
        self.path = Path(path)/'identity_memory.sqlite3'
        self.identity, self.domain, self.members = identity, domain, members
        self.key = Ed25519PrivateKey.from_private_bytes((Path(path)/'identity_memory.key').read_bytes())
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        if members()[identity].get('memory_public_key') != public:
            raise RuntimeError('行为认证密钥与受信实例注册不匹配，请检查实例配置')
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS edges(event_id TEXT, relation TEXT, node_id TEXT,
                    PRIMARY KEY(event_id,relation,node_id));
                CREATE INDEX IF NOT EXISTS edge_lookup ON edges(relation,node_id,event_id);
                CREATE TABLE IF NOT EXISTS challenges(nonce TEXT PRIMARY KEY, document TEXT NOT NULL,
                    expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, peer TEXT, mode TEXT,
                    event_id TEXT, time REAL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def sign(self, payload):
        return base64.b64encode(self.key.sign(canonical(payload))).decode()

    def verify(self, identity, payload, signature):
        try:
            public = self.members()[identity]['memory_public_key']
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
                base64.b64decode(signature, validate=True), canonical(payload))
        except Exception:
            raise HTTPException(403, '行为认证签名无效或身份已失效')

    def event_request(self, source, body):
        return dict(domain=self.domain, sender=source, target=body['target_id'],
                    message_id=body['message_id'], content_hash=digest(body['content']), action='message.received',
                    purpose=body.get('purpose','message'))

    def record(self, document):
        event = document['event']
        request = event['request']
        if request['domain'] != self.domain or self.identity not in (request['sender'], request['target']):
            raise HTTPException(403, '事件不属于当前身份范围')
        self.verify(request['sender'], request, event['sender_signature'])
        self.verify(request['target'], event, document['signature'])
        eid = digest([self.domain, request['sender'], request['target'], request['message_id']])
        # The graph links one event to typed semantic entities. Shared nodes never
        # merge separate events; every edge retains event_id.
        semantics = dict(sender=('identity', request['sender']), target=('identity', request['target']),
                         action=('action', request['action']), time=('time', event['timestamp']),
                         object=('digest', request['content_hash']), domain=('domain', self.domain))
        with self.db() as db:
            old = db.execute('SELECT document FROM events WHERE id=?', (eid,)).fetchone()
            if old and old[0] != canonical(document).decode():
                raise HTTPException(409, '历史事件编号冲突')
            db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (eid, canonical(document).decode()))
            for relation, (kind, value) in semantics.items():
                nid = digest([kind, value])
                db.execute('INSERT OR IGNORE INTO nodes VALUES (?,?,?)', (nid, kind, value))
                db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?)', (eid, relation, nid))
        return eid

    def query(self, source, target, event_id=None):
        """Actual graph intersection: sender AND recipient AND action, same event."""
        with self.db() as db:
            rows = db.execute('''SELECT e.id,e.document FROM events e
                JOIN edges s ON s.event_id=e.id AND s.relation='sender' AND s.node_id=?
                JOIN edges t ON t.event_id=e.id AND t.relation='target' AND t.node_id=?
                JOIN edges a ON a.event_id=e.id AND a.relation='action' AND a.node_id=?
                WHERE (? IS NULL OR e.id=?) ORDER BY e.rowid DESC LIMIT 1''',
                (digest(['identity', source]), digest(['identity', target]),
                 digest(['action', 'message.received']), event_id, event_id)).fetchall()
        if not rows:
            return None
        eid, raw = rows[0]
        doc = json.loads(raw)
        request = doc['event']['request']
        if request['sender'] != source or request['target'] != target or request['domain'] != self.domain:
            raise HTTPException(403, '行为图谱关系与证据不一致')
        self.verify(source, request, doc['event']['sender_signature'])
        self.verify(target, doc['event'], doc['signature'])
        if eid != digest([self.domain, source, target, request['message_id']]):
            raise HTTPException(403, '行为图谱事件标识不一致')
        return eid, doc

    def challenge(self, source, body):
        previous = self.query(source, self.identity)
        # Missing graph edges must not silently downgrade existing history.
        if previous is None:
            with self.db() as db:
                for (raw,) in db.execute('SELECT document FROM events'):
                    r = json.loads(raw)['event']['request']
                    if r['sender'] == source and r['target'] == self.identity:
                        raise HTTPException(409, '行为图谱索引缺失，请修复后认证')
        payload = dict(nonce=secrets.token_hex(32), domain=self.domain, source=source,
                       verifier=self.identity, request_hash=digest(body), expires=time.time()+60,
                       mode='history' if previous else 'bootstrap', event_id=previous[0] if previous else None)
        with self.db() as db:
            db.execute('DELETE FROM challenges WHERE expires<?', (time.time()-300,))
            db.execute('INSERT INTO challenges VALUES (?,?,?,0)',
                       (payload['nonce'], canonical(payload).decode(), payload['expires']))
        return dict(payload=payload, signature=self.sign(payload))

    def answer(self, challenge, body):
        c = challenge['payload']
        self.verify(body['target_id'], c, challenge['signature'])
        if (c['source'] != self.identity or c['verifier'] != body['target_id'] or
                c['domain'] != self.domain or c['request_hash'] != digest(body) or c['expires'] <= time.time()):
            raise HTTPException(403, '认证挑战上下文无效或已过期')
        previous = self.query(self.identity, body['target_id'], c['event_id']) if c['mode'] == 'history' else None
        if c['mode'] == 'history' and previous is None:
            raise HTTPException(409, '缺少对方要求的历史证据，不能通过行为认证')
        if c['mode'] == 'bootstrap' and self.query(self.identity, body['target_id']):
            raise HTTPException(409, '对方历史记忆缺失，拒绝降级为首次认证')
        payload = dict(challenge=c, evidence_hash=digest(previous[1]) if previous else None)
        request = self.event_request(self.identity, body)
        return dict(payload=payload, signature=self.sign(payload), request_signature=self.sign(request))

    def authenticate(self, source, body, proof):
        try:
            payload = proof['payload']; c = payload['challenge']
            self.verify(source, payload, proof['signature'])
            self.verify(source, self.event_request(source, body), proof['request_signature'])
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT document,expires,used FROM challenges WHERE nonce=?', (c['nonce'],)).fetchone()
                if (not row or row[2] or row[1] <= time.time() or row[0] != canonical(c).decode()
                        or c['source'] != source or c['verifier'] != self.identity
                        or c['domain'] != self.domain or c['request_hash'] != digest(body)):
                    raise HTTPException(403, '挑战已使用、过期或不属于本次请求')
                previous = self.query(source, self.identity, c['event_id']) if c['mode'] == 'history' else None
                if c['mode'] == 'history' and (not previous or payload['evidence_hash'] != digest(previous[1])):
                    raise HTTPException(403, '历史行为证据不一致')
                if c['mode'] == 'bootstrap' and self.query(source, self.identity):
                    raise HTTPException(409, '历史状态已变化，请重新获取挑战')
                db.execute('UPDATE challenges SET used=1 WHERE nonce=?', (c['nonce'],))
                db.execute('INSERT INTO audit(peer,mode,event_id,time) VALUES (?,?,?,?)',
                           (source, c['mode'], c['event_id'], time.time()))
            return c['mode']
        except (KeyError, TypeError, ValueError):
            raise HTTPException(403, '行为认证响应格式无效')

    def receipt(self, source, body, proof, timestamp, response=None):
        event = dict(request=self.event_request(source, body), sender_signature=proof['request_signature'], timestamp=timestamp)
        if response is not None:
            event['response_hash']=digest(response)
        doc = dict(event=event, signature=self.sign(event))
        self.record(doc)
        return doc

    def status(self):
        with self.db() as db:
            count = db.execute('SELECT count(*) FROM events').fetchone()[0]
            last = db.execute('SELECT peer,mode,event_id,time FROM audit ORDER BY id DESC LIMIT 1').fetchone()
        return dict(events=count, last_auth=dict(zip(('peer','mode','event_id','time'), last)) if last else None)
