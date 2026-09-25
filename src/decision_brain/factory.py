"""Create independent brains using only the files shipped with this project."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from decision_brain.contracts import read_spec
from decision_brain.harness_suite_builder import build
from decision_brain.layout import project_root
ROOT=project_root()

def create(config,destination):
    spec=read_spec(config)
    destination=destination.resolve()
    if destination.exists():raise ValueError(f'La carpeta ya existe: {destination}. Usa otra para un cerebro nuevo.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.brain-create-',dir=destination.parent))
    try:
        files=json.loads((ROOT/'config/project_files.json').read_text(encoding='utf-8'))
        for name in files:
            source=ROOT/name
            if not source.is_file():raise ValueError(f'Entrega incompleta: falta {name}')
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        suite=build(spec)
        for name,value in [('config/brain.json',spec),('config/harness_suite.json',suite)]:
            (stage/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        example=next((c['context'] for c in suite['cases'] if 'expected' in c),{})
        (stage/'examples/example_state.json').write_text(json.dumps(example,ensure_ascii=False,indent=2),encoding='utf-8')
        for script in stage.glob('*.sh'):script.chmod(0o755)
        stage.rename(destination)
    finally:
        if stage.exists():shutil.rmtree(stage)
    print(f'Creado: {destination}\nArranque: cd "{destination}" && bash start.sh')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    v=sub.add_parser('validate');v.add_argument('config',type=Path)
    n=sub.add_parser('new');g=n.add_mutually_exclusive_group(required=True)
    g.add_argument('--preset',choices=['retail','logistica','manufactura']);g.add_argument('--config',type=Path)
    n.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    try:
        if a.command=='new':create(a.config or ROOT/'config/presets'/f'{a.preset}.json',a.out)
        elif a.command=='validate':read_spec(a.config);print('Contrato válido')
        else:
            for f in sorted((ROOT/'config/presets').glob('*.json')):print(f.stem+': '+read_spec(f)['industry'])
    except (ValueError,TypeError,KeyError,OSError) as e:p.error(str(e))

if __name__=='__main__':main()
