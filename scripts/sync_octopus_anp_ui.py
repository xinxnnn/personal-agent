"""Update generated Octopus ANP UI/API assets, keeping per-file backups."""
from datetime import datetime
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'agent_provider/octopus'
FILES=('web/index.html','web/script.js','octopus/api/chat_router.py','octopus/api/auth_middleware.py','octopus/master_agent.py')


def main():
    backup=ROOT/'local_store/migration_backups'/datetime.now().strftime('anp_ui_%Y%m%d_%H%M%S_%f')
    count=0
    agents=(ROOT/'local_store/agents').resolve()
    for package in agents.glob('*/octopus_build'):
        if not package.resolve().is_relative_to(agents):
            raise RuntimeError('Package path outside agent directory')
        for relative in FILES:
            source=SOURCE/relative
            target=package/relative
            if not target.is_file():continue
            if not target.resolve().is_relative_to(package.resolve()):
                raise RuntimeError('Asset path outside package')
            if target.read_bytes()==source.read_bytes():continue
            saved=backup/package.parent.name/relative
            saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,saved)
            shutil.copy2(source,target)
            count+=1
    print(f'Updated assets: {count}')
    if count:print(f'Backups: {backup}')


if __name__=='__main__':main()
