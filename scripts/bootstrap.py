"""Idempotent isolated environment setup with actionable diagnostics."""
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import html
import os
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def missing():
    result=[]
    for line in (ROOT/'config/requirements.lock').read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        name,wanted=line.split('==',1)
        try: installed=version(name)
        except PackageNotFoundError: installed=None
        if installed!=wanted:result.append(line)
    return result

def fail(message,log=None):
    detail=log.read_text(encoding='utf-8',errors='replace')[-6000:] if log and log.exists() else ''
    print(message,file=sys.stderr)
    if detail:print(detail,file=sys.stderr)
    if log:print(f'Registro completo: {log}',file=sys.stderr)
    (ROOT/'setup_error.html').write_text('<html lang="es"><meta charset="utf-8"><h1>No se completó la instalación</h1><p>'+html.escape(message)+'</p><pre>'+html.escape(detail)+'</pre></html>',encoding='utf-8')
    return 2

def install(command,log):
    with log.open('w',encoding='utf-8') as stream:
        return subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT).returncode

def inside():
    if Path(sys.prefix).resolve()!=(ROOT/'.venv').resolve():return fail('El intérprete no pertenece a .venv del proyecto.')
    logs=ROOT/'runs';logs.mkdir(exist_ok=True)
    pip=[sys.executable,'-m','pip','install','--disable-pip-version-check','--timeout','30','--retries','2']
    if missing():
        print('Instalando las dependencias fijadas. La primera ejecución requiere conexión…',flush=True)
        log=logs/'setup.log'
        result=install(pip+['-r',str(ROOT/'config/requirements.lock')],log)
        if result:
            detail=log.read_text(encoding='utf-8',errors='replace')
            if 'BadZipFile' in detail or 'Wheel' in detail and 'invalid' in detail:
                log.replace(log.with_name('setup-first-attempt.log'))
                print('Descarga de paquete inválida. Reintentando una vez sin caché…',flush=True)
                result=install(pip+['--no-cache-dir','--force-reinstall','-r',str(ROOT/'config/requirements.lock')],log)
            if result:return fail('Falló la instalación de dependencias.',log)
        if missing():return fail('Las versiones instaladas no coinciden con config/requirements.lock.',log)
    fingerprint=hashlib.sha256((ROOT/'pyproject.toml').read_bytes()+str(ROOT).encode()+sys.version.encode()).hexdigest()
    stamp=ROOT/'.venv/project-install.sha256'
    if not (ROOT/'.venv/bin/decision-harness').exists() or not stamp.exists() or stamp.read_text(encoding='utf-8')!=fingerprint:
        print('Preparando los comandos del proyecto…',flush=True)
        log=logs/'package-setup.log'
        if install(pip+['--no-deps','-e',str(ROOT)],log):return fail('Falló la instalación del paquete.',log)
        stamp.write_text(fingerprint,encoding='utf-8')
    smoke=subprocess.run([sys.executable,'-c','import numpy, sklearn, matplotlib, faker, fastapi, httpx, autoevals; from decision_brain import harness, brain'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if smoke.returncode:
        log=logs/'import-error.log';log.write_text(smoke.stdout+smoke.stderr,encoding='utf-8')
        return fail('Una dependencia no puede importarse.',log)
    print('Entorno listo.',flush=True)
    return 0

def main():
    if not (3,12)<=sys.version_info[:2]<(3,14):return fail('Se necesita Python 3.12 o 3.13.')
    os.environ['PYTHONUTF8']='1';os.environ['PYTHONIOENCODING']='utf-8'
    if '--inside' in sys.argv:return inside()
    # Serialize setup only; training sessions have unique output directories.
    import fcntl
    with (ROOT/'.setup.lock').open('a',encoding='utf-8') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        python=ROOT/'.venv/bin/python'
        usable=False
        if python.exists():
            try:
                probe=subprocess.run([str(python),'-c','import sys;sys.exit(not ((3,12)<=sys.version_info[:2]<(3,14)))'],capture_output=True,timeout=15)
                usable=probe.returncode==0
            except (OSError,subprocess.TimeoutExpired):pass
        if not usable:
            existing=ROOT/'.venv'
            if existing.exists():existing.rename(ROOT/('.venv_backup_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')))
            print('Creando entorno Python aislado…',flush=True)
            venv.EnvBuilder(with_pip=True).create(existing)
        return subprocess.call([str(python),str(Path(__file__).resolve()),'--inside'],cwd=ROOT)

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,subprocess.SubprocessError) as exc:raise SystemExit(fail(str(exc)))
