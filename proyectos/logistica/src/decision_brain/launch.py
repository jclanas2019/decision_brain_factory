"""One-command local demonstration, with durable logs and a single HTML entry."""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import webbrowser
from decision_brain.runtime_paths import atomic_text,remember_model

from decision_brain.layout import project_root
ROOT=project_root()

def step(command,log,stream=False):
    with log.open('w',encoding='utf-8') as file:
        if not stream:return subprocess.run(command,cwd=ROOT,stdout=file,stderr=subprocess.STDOUT).returncode
        with subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace") as process:
            for line in process.stdout:
                print(line,end='',flush=True);file.write(line)
            return process.wait()

def dashboard(folder,status,checks,training,evaluation):
    esc=html.escape
    for name in ('checks','training','harness'):
        log=folder/(name+'.log')
        if log.exists():
            content=log.read_text(encoding='utf-8',errors='replace')
            (folder/(name+'_log.html')).write_text('<html lang="es"><meta charset="utf-8"><title>Registro</title><pre style="white-space:pre-wrap">'+esc(content)+'</pre></html>',encoding='utf-8')
    links='<p><a href="checks_log.html">Registro de pruebas</a></p>'
    if training:links+='<p><a href="model/report.html">Entrenamiento: loss, métricas y matrices de confusión</a></p>'
    elif (folder/'training.log').exists():links+='<p><a href="training_log.html">Registro del entrenamiento</a></p>'
    if evaluation:links+='<p><a href="evaluation/report.html">Harness: expectativas e interpretación por caso</a></p>'
    elif (folder/'harness.log').exists():links+='<p><a href="harness_log.html">Registro del harness</a></p>'
    origin='Demostración con datos sintéticos.'
    if (folder/'model/report.json').exists():
        model_report=json.loads((folder/'model/report.json').read_text(encoding='utf-8'))
        if model_report.get('data_origin')=='user_supplied':origin='Evaluación del CSV suministrado por el usuario.'
    text=f'<!doctype html><html lang="es"><meta charset="utf-8"><title>Resultado del sistema</title><style>body{{font:18px system-ui;max-width:900px;margin:50px auto;padding:24px}}a{{display:inline-block;padding:10px}}p{{line-height:1.6}}</style><h1>{esc(status)}</h1><p>Pruebas de software: {esc(checks)}.</p>{links}<p>{esc(origin)} Aprobar las pruebas técnicas no certifica las decisiones del modelo ni su preparación para producción.</p></html>'
    if checks=='FALLARON':
        detail=(folder/'checks.log').read_text(encoding='utf-8')[-6000:] if (folder/'checks.log').is_file() else 'No hay registro disponible.'
        text=text.replace('</html>','<h2>Detalle del fallo</h2><pre style="white-space:pre-wrap">'+esc(detail)+'</pre></html>')
    (folder/'index.html').write_text(text,encoding='utf-8')
    # Relative link remains valid when the project is moved.
    (ROOT/'runs/latest.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>Última ejecución</title><h1>Última ejecución</h1><p>'+esc(status)+'</p><a href="'+esc(folder.name)+'/index.html">Abrir informe completo</a></html>', encoding='utf-8')
    summary_page='<html lang="es"><meta charset="utf-8"><title>Último informe</title><h1>'+esc(status)+'</h1><a href="runs/'+esc(folder.name)+'/index.html">Abrir informe completo</a></html>'
    atomic_text(ROOT/'report.html',summary_page)
    (folder/'status.json').write_text(json.dumps({'status':status,'software_checks':checks,'training_report':training,'evaluation_report':evaluation},ensure_ascii=False,indent=2), encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description='Prueba, entrena y evalúa con un único comando.')
    p.add_argument('--no-open',action='store_true',help='No abrir navegador')
    p.add_argument('--check-only',action='store_true')
    p.add_argument('--rows',type=int,default=2000)
    p.add_argument('--trials',type=int,default=3)
    p.add_argument('--epochs',type=int,default=40)
    p.add_argument('--data',type=Path,help='CSV anotado; si se omite, usa el generador sintético')
    a=p.parse_args()
    os.environ['PYTHONUTF8']='1';os.environ['PYTHONIOENCODING']='utf-8'
    if a.rows<200 or a.trials<1 or a.epochs<1:p.error('rows >= 200; trials y epochs >= 1')
    folder=ROOT/'runs'/('session_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    checks='pendientes';training=False;evaluation=False;code=2;status='Ejecución incompleta'
    try:
        print('[1/3] Ejecutando pruebas del servicio, harness y configuración…',flush=True)
        result=step([sys.executable,'-m','decision_brain.check_runner','--result',str(folder/'checks.json')],folder/'checks.log')
        if (folder/'checks.json').is_file():
            summary=json.loads((folder/'checks.json').read_text(encoding='utf-8'))
            print(f"Pruebas: {summary['tests']}; fallos: {summary['failures']}; errores: {summary['errors']}.",flush=True)
        if result:
            print((folder/'checks.log').read_text(encoding='utf-8')[-6000:],flush=True)
            checks='FALLARON';status='Fallaron las pruebas del software. Consulta el registro.'
        else:
            checks='APROBADAS'
            if a.check_only:status='Pruebas del software aprobadas';code=0
            else:
                print('[2/3] Entrenando y generando el informe del modelo…',flush=True)
                model=folder/'model'
                command=[sys.executable,'-m','decision_brain.brain']+(['train','--data',str(a.data.resolve())] if a.data else ['demo','--rows',str(a.rows)])
                command+=['--trials',str(a.trials),'--epochs',str(a.epochs),'--output',str(model)]
                result=step(command,folder/'training.log',True)
                training=(model/'report.html').is_file()
                if result:status='Falló el entrenamiento. Consulta el registro.'
                else:
                    remember_model(ROOT,model)
                    print('[3/3] Evaluando decisiones con el harness…',flush=True)
                    # Explicit paths override stale output/model paths in project.toml.
                    result=step([sys.executable,'-m','decision_brain.harness','--run',str(model),'--output',str(folder/'evaluation')],folder/'harness.log',True)
                    evaluation=(folder/'evaluation/report.html').is_file()
                    code=result if result in (0,1) else 2
                    status={0:'Ejecución completada: el modelo cumple los criterios del harness',1:'Ejecución completada: hay decisiones que no cumplen los criterios',2:'Error al ejecutar el harness. Consulta el registro.'}[code]
    except Exception as exc:
        status=f'Error de ejecución: {exc}';code=2
    finally:
        dashboard(folder,status,checks,training,evaluation)
        report=folder/'index.html'
        print(f'\n{status}\nINFORME: {report}\nAcceso permanente: {ROOT / "runs/latest.html"}',flush=True)
        if not a.no_open:
            try:
                if sys.platform=='darwin':
                    opened=subprocess.run(['open',str(report)],timeout=10,check=False)
                    if opened.returncode:print('Abre manualmente el informe indicado.')
                else:webbrowser.open(report.as_uri())
            except Exception:print('No se pudo abrir el navegador. Abre el informe indicado.')
    return code

if __name__=='__main__':sys.exit(main())
