import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import group_anp
from app.anp_mailbox import ActivityLog, Mailbox


class ActivityTests(unittest.TestCase):
    def test_activity_contains_only_metadata_and_migrates_existing_conversations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'anp_messages.sqlite3'
            connection=sqlite3.connect(path)
            try:
                connection.execute(
                    'CREATE TABLE conversations (message_id TEXT, direction TEXT, peer_id TEXT, request TEXT, response TEXT, timestamp TEXT, status TEXT, PRIMARY KEY(message_id,direction))'
                )
                connection.execute(
                    'INSERT INTO conversations VALUES (?,?,?,?,?,?,?)',
                    ('chat-1','received','agent-1','private request','private reply','2026-10-18T08:00:00+00:00','completed'),
                )
                connection.commit()
            finally:
                connection.close()
            mailbox=Mailbox(path)
            events=mailbox.activity()
            self.assertEqual(len(events),2)
            response=next(item for item in events if item['kind']=='chat_response')
            self.assertEqual(response['status'],'completed')
            self.assertEqual(response['timestamp'],'2026-10-18T08:00:00+00:00')
            self.assertNotIn('private request',str(events))
            self.assertNotIn('private reply',str(events))
            self.assertNotIn('request',response)
            self.assertNotIn('response',response)

    def test_group_activity_includes_existing_mailbox_events_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            agents=root/'agents'
            for agent_id in ('parent_1','child_1'):
                agent=agents/agent_id
                agent.mkdir(parents=True)
                (agent/'agent_manifest.json').write_text(
                    '{"name":"'+agent_id+'"}',encoding='utf-8')
            group_dir=root/'local_store/anp_groups'
            group_dir.mkdir(parents=True)
            registry=group_dir/'parent_1.json'
            registry.write_text(
                '{"members":{"parent_1":{},"child_1":{}}}',encoding='utf-8')

            sender=Mailbox(agents/'parent_1/anp_messages.sqlite3')
            sender.begin_conversation('chat-1','sent','child_1','private request')
            sender.finish_conversation('chat-1','sent','private reply')
            receiver=Mailbox(agents/'child_1/anp_messages.sqlite3')
            receiver.begin_conversation('chat-1','received','parent_1','private request')
            receiver.finish_conversation('chat-1','received','private reply')

            with patch.object(group_anp.rt,'ROOT',root),patch.object(group_anp.rt,'AGENTS',agents):
                ActivityLog(registry.with_suffix('.activity.sqlite3')).record(
                    'parent_1:chat-1:request-sent','request_sent','parent_1','child_1','chat-1')
                events=group_anp.activity_events('parent_1')

            self.assertEqual([item['kind'] for item in events].count('request_sent'),1)
            self.assertEqual(
                {(item['kind'],item['agent_id'],item['peer_id']) for item in events},
                {('request_sent','parent_1','child_1'),('response_received','parent_1','child_1'),
                 ('request_received','child_1','parent_1'),('response_returned','child_1','parent_1')},
            )
            self.assertNotIn('private request',str(events))
            self.assertNotIn('private reply',str(events))


if __name__=='__main__':
    unittest.main()
