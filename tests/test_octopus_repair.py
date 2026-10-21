import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import experience_runtime as rt

class RepairTests(unittest.TestCase):
    def test_restore_missing_assets_preserves_credentials_and_existing_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'agent_provider/octopus';(source/'octopus/api').mkdir(parents=True)
            (source/'octopus/octopus.py').write_text('# original')
            (source/'octopus/api/chat_router.py').write_text('# current chat api')
            (source/'octopus/api/auth_middleware.py').write_text('# current auth middleware')
            (source/'pyproject.toml').write_text('[project]')
            (source/'README.md').write_text('readme')
            (source/'web').mkdir();(source/'web/index.html').write_text('<html>chat</html>')
            (source/'web/script.js').write_text('// current chat UI')
            pkg=root/'instance';pkg.mkdir();(pkg/'.env').write_text('OPENAI_API_KEY=keep-this')
            (pkg/'.web-dependencies-ready').touch()
            with patch.object(rt,'ROOT',root):
                self.assertEqual(len(rt.repair_octopus_package(pkg)),4)
                self.assertEqual((pkg/'.env').read_text(),'OPENAI_API_KEY=keep-this')
                self.assertFalse((pkg/'.web-dependencies-ready').exists())
                (pkg/'web/script.js').write_text('// stale chat UI')
                (pkg/'octopus/api/chat_router.py').write_text('# stale chat api')
                (pkg/'octopus/api/auth_middleware.py').write_text('# stale auth middleware')
                self.assertEqual(rt.repair_octopus_package(pkg),[])
                self.assertEqual((pkg/'web/script.js').read_text(),'// current chat UI')
                self.assertEqual((pkg/'octopus/api/chat_router.py').read_text(),'# current chat api')
                self.assertEqual((pkg/'octopus/api/auth_middleware.py').read_text(),'# current auth middleware')
                (pkg/'octopus/octopus.py').write_text('# customized')
                self.assertEqual(rt.repair_octopus_package(pkg),[])
                self.assertEqual((pkg/'octopus/octopus.py').read_text(),'# customized')

if __name__=='__main__':unittest.main()
