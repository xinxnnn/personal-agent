import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_subagents as sub
from app import experience_runtime as rt

class ChildrenTests(unittest.TestCase):
    # OpenClaw 不再作为子智能体创建；相关约束见 test_execution_branch.py。

    def test_legacy_colon_group_is_recovered_without_removing_original(self):
        with tempfile.TemporaryDirectory() as temp:
            groups=Path(temp)
            old=groups/'group_phc:legacy.json'
            data={'group_id':'group_phc:legacy','group_name':'Legacy',
                  'parent_agent_id':'phc:legacy','sub_agents':[],
                  'communication_config':{},'created_at':'2026-01-01T00:00:00Z'}
            old.write_text(json.dumps(data),encoding='utf-8')
            with patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups):
                result=sub.legacy.list_agent_groups('phc:legacy')
                self.assertEqual(len(result),1)
                self.assertTrue(old.exists())
                self.assertTrue((groups/'group_phc_legacy.json').is_file())
                self.assertEqual(len(sub.legacy.list_agent_groups('phc:legacy')),1)

if __name__=='__main__': unittest.main()
