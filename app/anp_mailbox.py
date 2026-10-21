"""Durable group messages with immutable IDs and idempotent receipt storage."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException

class Mailbox:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row
        try:
            with c:
                c.execute('CREATE TABLE IF NOT EXISTS messages (direction TEXT, sender TEXT, id TEXT, target TEXT, content TEXT, timestamp TEXT, status TEXT, receipt TEXT, PRIMARY KEY(direction,sender,id))')
                c.execute('CREATE TABLE IF NOT EXISTS conversations (message_id TEXT, direction TEXT, peer_id TEXT, request TEXT, response TEXT, timestamp TEXT, status TEXT, updated_at TEXT, PRIMARY KEY(message_id,direction))')
                columns={row['name'] for row in c.execute('PRAGMA table_info(conversations)')}
                if 'updated_at' not in columns:
                    c.execute('ALTER TABLE conversations ADD COLUMN updated_at TEXT')
                    c.execute('UPDATE conversations SET updated_at=timestamp WHERE updated_at IS NULL')
                yield c
        finally:c.close()
    def reserve(self,direction,sender,mid,target,content):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM messages WHERE direction=? AND sender=? AND id=?',(direction,sender,mid)).fetchone()
            if row:
                if row['target']!=target or row['content']!=content:raise HTTPException(409,'消息编号已被其他内容使用')
                return dict(row)
            stamp=datetime.now(timezone.utc).isoformat()
            c.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)',(direction,sender,mid,target,content,stamp,'pending',None))
            return dict(direction=direction,sender=sender,id=mid,target=target,content=content,timestamp=stamp,status='pending',receipt=None)
    def finish(self,direction,sender,mid,status,receipt=None):
        with self.db() as c:
            # A late failure cannot overwrite an acknowledged delivery.
            c.execute("UPDATE messages SET status=?,receipt=COALESCE(?,receipt) WHERE direction=? AND sender=? AND id=? AND status NOT IN ('delivered','received')",
                (status,json.dumps(receipt,ensure_ascii=False) if receipt else None,direction,sender,mid))
    def listing(self,direction):
        with self.db() as c:
            rows=c.execute('SELECT * FROM messages WHERE direction=? ORDER BY timestamp DESC LIMIT 50',(direction,)).fetchall()
        return [dict(message_id=r['id'],sender_did='local:'+r['sender'],target_id=r['target'],content=r['content'],timestamp=r['timestamp'],status=r['status']) for r in rows]
    def begin_conversation(self,message_id,direction,peer_id,request):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM conversations WHERE message_id=? AND direction=?',(message_id,direction)).fetchone()
            if row:
                if row['peer_id']!=peer_id or row['request']!=request:
                    raise HTTPException(409,'ANP 会话编号已被其他内容使用')
                return dict(row)
            stamp=datetime.now(timezone.utc).isoformat()
            c.execute('INSERT INTO conversations (message_id,direction,peer_id,request,response,timestamp,status,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                      (message_id,direction,peer_id,request,None,stamp,'processing',stamp))
            return dict(message_id=message_id,direction=direction,peer_id=peer_id,request=request,
                        response=None,timestamp=stamp,status='processing',updated_at=stamp)
    def finish_conversation(self,message_id,direction,response,status='completed'):
        with self.db() as c:
            c.execute('UPDATE conversations SET response=?,status=?,updated_at=? WHERE message_id=? AND direction=?',
                      (response,status,datetime.now(timezone.utc).isoformat(),message_id,direction))
    def conversations(self):
        with self.db() as c:
            rows=c.execute('SELECT * FROM conversations ORDER BY timestamp DESC LIMIT 100').fetchall()
        return [dict(row) for row in reversed(rows)]
    def activity(self):
        with self.db() as c:
            conversations=c.execute(
                'SELECT message_id,direction,peer_id,timestamp,updated_at,status FROM conversations ORDER BY timestamp DESC LIMIT 100'
            ).fetchall()
            messages=c.execute(
                'SELECT direction,sender,id,target,timestamp,status FROM messages ORDER BY timestamp DESC LIMIT 100'
            ).fetchall()
        events=[]
        for row in conversations:
            request_status='processing' if row['status']=='processing' else (
                'sent' if row['direction']=='sent' else 'received'
            )
            events.append(dict(event_id=f"chat:{row['message_id']}:{row['direction']}:request",
                               kind='chat_request',direction=row['direction'],peer_id=row['peer_id'],
                               conversation_id=row['message_id'],timestamp=row['timestamp'],status=request_status))
            if row['status']!='processing':
                events.append(dict(event_id=f"chat:{row['message_id']}:{row['direction']}:response",
                                   kind='chat_response',direction=row['direction'],peer_id=row['peer_id'],
                                   conversation_id=row['message_id'],timestamp=row['updated_at'] or row['timestamp'],status=row['status']))
        for row in messages:
            events.append(dict(
                event_id=f"message:{row['id']}:{row['direction']}",
                kind='message',
                direction=row['direction'],
                peer_id=row['sender'] if row['direction']=='in' else row['target'],
                conversation_id=row['id'],
                timestamp=row['timestamp'],
                status=row['status'],
            ))
        return sorted(events,key=lambda item:item['timestamp'],reverse=True)[:100]


class ActivityLog:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(self.path,timeout=15);connection.row_factory=sqlite3.Row
        try:
            with connection:
                connection.execute('CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, kind TEXT, agent_id TEXT, peer_id TEXT, conversation_id TEXT, timestamp TEXT, status TEXT)')
                yield connection
        finally:connection.close()
    def record(self,event_id,kind,agent_id,peer_id=None,conversation_id=None,status='completed'):
        timestamp=datetime.now(timezone.utc).isoformat()
        with self.db() as connection:
            connection.execute(
                'INSERT INTO events VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET status=excluded.status',
                (event_id,kind,agent_id,peer_id,conversation_id,timestamp,status),
            )
        return timestamp
    def listing(self):
        with self.db() as connection:
            rows=connection.execute('SELECT * FROM events ORDER BY timestamp DESC LIMIT 200').fetchall()
        return [dict(row) for row in reversed(rows)]
