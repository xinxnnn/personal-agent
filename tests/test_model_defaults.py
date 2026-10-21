import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import experience_runtime as rt

class DefaultsTests(unittest.TestCase):
    def test_defaults_parent_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agents=root/'agents'
            for name in ('parent','child'):
                p=agents/name;(p/'octopus_build').mkdir(parents=True)
                (p/'agent_manifest.json').write_text(json.dumps({'parent_phc_id':'parent'} if name=='child' else {}))
            default=root/'agent_provider/octopus';default.mkdir(parents=True)
            (default/'.env').write_text('OPENAI_API_KEY=default-test-key\nOPENAI_BASE_URL=https://example.test/v1\nOPENAI_MODEL=test\n')
            with patch.object(rt,'ROOT',root),patch.object(rt,'AGENTS',agents):
                self.assertEqual(rt.model_env(agents/'parent')[1],'system')
                values,source=rt.model_env(agents/'child')
                self.assertEqual(source,'parent');self.assertEqual(values['OPENAI_API_KEY'],'default-test-key')
                self.assertNotIn('default-test-key',json.dumps(rt.snapshot('child')))
                (agents/'child/octopus_build/.env').write_text('OPENAI_API_KEY=own-test-key\n')
                self.assertEqual(rt.model_env(agents/'child')[0]['OPENAI_API_KEY'],'own-test-key')
                self.assertEqual(rt.model_env(agents/'child')[1],'instance')

if __name__=='__main__':unittest.main()
