"""Stable, relocatable pointers to completed model runs."""
import json
from pathlib import Path
import uuid


def atomic_text(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(text,encoding='utf-8');tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()


def remember_model(root,model):
    root=Path(root).resolve();model=Path(model).resolve()
    atomic_text(root/'runs/latest_model.json',json.dumps({'run':str(model.relative_to(root))}))


def latest_model(root):
    root=Path(root).resolve();pointer=root/'runs/latest_model.json'
    if not pointer.is_file():raise ValueError('No hay un modelo entrenado. Ejecuta bash start.sh o indica --run.')
    model=(root/json.loads(pointer.read_text(encoding='utf-8'))['run']).resolve()
    if not all((model/name).is_file() for name in ('brain.json','model.json','encoder.json','weights.npz')):
        raise ValueError('El último modelo está incompleto; entrena otra vez o indica --run.')
    return model
