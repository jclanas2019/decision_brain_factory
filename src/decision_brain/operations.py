"""Persistent single-host development fleet: projects, catalog, workers, consumer and UI."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import uuid
import httpx
from decision_brain.factory import create
from decision_brain.gate_scaffold import write_config
from decision_brain.harness_suite_builder import build
from decision_brain.layout import project_root
from decision_brain.releases import register,activate,verify
from decision_brain.runtime_paths import latest_model,atomic_text

ROOT=project_root()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def put(p,v):atomic_text(p,json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def execute(command,log,env,quality=False):
    with log.open('w',encoding='utf-8') as stream:r=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if r.returncode not in ((0,1) if quality else (0,)):raise RuntimeError('Falló el proceso. Registro: '+str(log))

def prepare(state,commerce=None,logistics=None,base_port=8101):
    state=state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700);state.chmod(0o700)
    config=state/'fleet.json'
    if config.exists():
        saved=read(config)
        for name,requested in (('comercio',commerce),('logistica',logistics)):
            if requested and Path(requested).resolve()!=Path(saved['models'][name]['project']).resolve():raise ValueError('Entorno ya configurado con otros proyectos. Usa otra carpeta --state.')
        return saved
    secret_path=state/'secrets.json'
    if not secret_path.exists():
        fd=os.open(secret_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump({k:secrets.token_urlsafe(48) for k in ('BRAIN_ORCHESTRATOR_TOKEN','BRAIN_POSTVENTA_TOKEN','BRAIN_OBSERVER_TOKEN','BRAIN_COMMERCE_TOKEN','BRAIN_LOGISTICS_TOKEN')},f)
    secret_path.chmod(0o600)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),BRAIN_PROJECT_ROOT=str(ROOT),PYTHONUTF8='1',OPENBLAS_NUM_THREADS='1')
    projects=[('comercio',commerce or ROOT/'proyectos/comercio','retail','comercio.triaje','BRAIN_COMMERCE_TOKEN'),('logistica',logistics or ROOT/'proyectos/logistica','logistica','logistica.incidencia','BRAIN_LOGISTICS_TOKEN')]
    entries=[];workers=[];models={}
    for index,(name,path,preset,bid,token) in enumerate(projects):
        project=Path(path).resolve()
        if not project.exists():create(ROOT/'config/presets'/f'{preset}.json',project,bid)
        spec=read(project/'config/brain.json')
        expected={'dias_desde_compra':'number','mensaje':'text','contexto':'text'} if name=='comercio' else {'horas_desviacion':'number','estado_entrega':'text','contexto':'text'}
        if {f['id']:f['type'] for f in spec['fields']}!=expected:raise ValueError('Contrato incompatible con el flujo configurado: '+str(project))
        folder=state/name;folder.mkdir(exist_ok=True)
        try:run=latest_model(project)
        except ValueError:
            run=project/'runs/operation_initial'
            if not (run/'report.json').exists():
                print('Entrenando por primera vez:',bid,flush=True)
                execute([sys.executable,'-m','decision_brain.brain','--config',str(project/'config/brain.json'),'demo','--rows','2000','--trials','3','--epochs','30','--output',str(run)],folder/'training.log',dict(env,BRAIN_PROJECT_ROOT=str(project)))
        if read(run/'brain.json')!=spec:raise ValueError('El modelo guardado no corresponde al contrato del proyecto: '+str(project))
        suite=project/'config/harness_suite.json';evaluation=folder/'evaluation'
        if not (evaluation/'report.json').exists():
            execute([sys.executable,'-m','decision_brain.harness','--project',str(project/'project.toml'),'--run',str(run),'--suite',str(suite),'--output',str(evaluation)],folder/'harness.log',env,True)
        registry=folder/'registry'
        if not (registry/'versions/v1').exists():
            register(registry,run,'v1','development',harness=evaluation/'report.json')
        activate(registry,'v1','development')
        local=folder/'edge';write_config(local,spec,bid)
        cfg=local/'config/gates';gate=read(cfg/'interop_gate.development.json')
        if name=='logistica':
            gate['handoff_fields']=[{'id':'dias_desde_compra','type':'number','description':'Dato aportado por el sistema de compras; no inferido del retraso.'}]
            schema=read(cfg/'request.schema.json');schema['properties']['handoff']={'type':'object','properties':{'dias_desde_compra':{'type':'number','minimum':0,'maximum':1e12}},'required':['dias_desde_compra'],'additionalProperties':False};schema['required'].append('handoff');put(cfg/'request.schema.json',schema)
        put(cfg/'interop_gate.development.json',gate)
        entry=read(cfg/'catalog.json')['brains'][0];entry.update(endpoint=f'http://127.0.0.1:{base_port+index}',upstream_token_env=token,
          interop_config=str(cfg/'interop_gate.development.json'),observe_config=str(cfg/'observe.json'),environments={'development':{'registry':str(registry)}})
        entries.append(entry);workers.append({'name':name,'brain_id':bid,'registry':str(registry),'token':token,'port':base_port+index})
        models[name]={'project':str(project),'model':str(run),'harness':str(evaluation/'report.json'),'passed':read(evaluation/'report.json')['passed']}
    edge=state/'edge';write_config(edge,read(Path(models['comercio']['project'])/'config/brain.json'),'comercio.triaje');cfg=edge/'config/gates'
    put(cfg/'catalog.json',{'version':1,'brains':entries})
    routes=[]
    for action in entries[1]['actions']:
        # A structured hypothesis from logistics, not a fabricated customer quote.
        message='Solicitud interna de seguimiento de entrega. Resultado logístico: '+action+'. No representa intención de cancelación del cliente.'
        routes.append({'id':'logistica-a-comercio-'+action,'source_brain':'logistica.incidencia','target_brain':'comercio.triaje','action':action,
            'mapping':{'dias_desde_compra':{'fact':'dias_desde_compra'},'mensaje':{'literal':message},'contexto':{'literal':'Traspaso interno desde logística. Evaluación orientativa; revisar evidencia y calidad antes de actuar.'}}})
    put(cfg/'routes.json',{'version':1,'routes':routes})
    g=read(cfg/'gateway.json');g.update(environment='development',require_tls=False)
    for caller in g['callers'].values():caller['brains']=[e['brain_id'] for e in entries]
    put(cfg/'gateway.json',g)
    o=read(cfg/'observer.json');o['environment']='development';put(cfg/'observer.json',o)
    conf={'version':1,'mode':'development','workers':workers,'models':models,'gateway_port':base_port+2,'observer_port':base_port+3,'config':str(cfg),'database':str(edge/'registry/edge.sqlite3'),'telemetry':str(state/'telemetry.sqlite3')}
    put(config,conf)
    print('Configuración persistente:',config,flush=True)
    return conf

def up(state,commerce=None,logistics=None,base_port=8101,no_open=False):
    state=state.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700);state.chmod(0o700)
    with (state/'supervisor.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Este entorno ya está funcionando.')
        conf=prepare(state,commerce,logistics,base_port);secrets_map=read(state/'secrets.json')
        env=dict(os.environ,**secrets_map,PYTHONPATH=str(ROOT/'src'),BRAIN_PROJECT_ROOT=str(ROOT),BRAIN_MODE='development',BRAIN_TELEMETRY_DB=conf['telemetry'],PYTHONUTF8='1',OPENBLAS_NUM_THREADS='1')
        configs=Path(conf['config']);definitions=[]
        for w in conf['workers']:definitions.append((w['name'],'decision_brain.service',w['port'],{'BRAIN_ID':w['brain_id'],'BRAIN_REGISTRY':w['registry'],'BRAIN_API_KEY':secrets_map[w['token']]}))
        definitions.extend([('gateway','decision_brain.gateway',conf['gateway_port'],{'BRAIN_GATEWAY_CONFIG':str(configs/'gateway.json')}),('observer','decision_brain.observer',conf['observer_port'],{'BRAIN_OBSERVER_CONFIG':str(configs/'observer.json')})])
        for _,_,port,_ in definitions:
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                s.bind(('127.0.0.1',port))
        processes=[];streams=[];stopping=False
        def stop(*_):raise KeyboardInterrupt()
        previous=signal.signal(signal.SIGTERM,stop)
        def launch(name,command,extra):
            stream=(state/(name+'.log')).open('a',encoding='utf-8');streams.append(stream)
            process=subprocess.Popen(command,cwd=ROOT,env=dict(env,**extra),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            item={'name':name,'command':command,'extra':extra,'process':process,'restarts':[]};processes.append(item);return process
        try:
            for name,module,port,extra in definitions:
                command=[sys.executable,'-m','uvicorn',module+':create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log']
                process=launch(name,command,extra)
                for _ in range(200):
                    if process.poll() is not None:raise RuntimeError('No inició '+name+'. Consulta '+str(state/(name+'.log')))
                    try:
                        if httpx.get(f'http://127.0.0.1:{port}/ready',trust_env=False,timeout=1).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise RuntimeError('Timeout iniciando '+name)
            launch('consumer',[sys.executable,'-m','decision_brain.event_consumer','--database',conf['database'],'--routes',str(configs/'routes.json'),'--gateway',f"http://127.0.0.1:{conf['gateway_port']}"],{})
            def remember_processes():put(state/'processes.json',{'running':True,'processes':{i['name']:i['process'].pid for i in processes}})
            remember_processes()
            url=f"http://127.0.0.1:{conf['observer_port']}/#token="+secrets_map['BRAIN_OBSERVER_TOKEN']
            print('Panel local (URL privada): '+url,flush=True)
            print('Entorno DEVELOPMENT persistente. Ctrl+C detiene servicios y conserva datos. No ejecuta acciones externas.',flush=True)
            if not no_open:
                import webbrowser
                webbrowser.open(url)
            while True:
                for item in list(processes):
                    if item['process'].poll() is not None:
                        now=time.time();item['restarts']=[t for t in item['restarts'] if now-t<60]
                        if len(item['restarts'])>=3:raise RuntimeError('Reinicios agotados: '+item['name'])
                        item['restarts'].append(now);print('Reiniciando:',item['name'],flush=True)
                        stream=(state/(item['name']+'.log')).open('a',encoding='utf-8');streams.append(stream)
                        item['process']=subprocess.Popen(item['command'],cwd=ROOT,env=dict(env,**item['extra']),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                        remember_processes()
                time.sleep(.5)
        except KeyboardInterrupt:print('Deteniendo servicios; los datos quedan conservados.',flush=True)
        finally:
            for item in reversed(processes):
                process=item['process']
                if process.poll() is None:process.terminate()
            for item in reversed(processes):
                try:item['process'].wait(timeout=10)
                except subprocess.TimeoutExpired:item['process'].kill();item['process'].wait()
            for stream in streams:stream.close()
            put(state/'processes.json',{'running':False,'processes':{}})
            signal.signal(signal.SIGTERM,previous)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['up','status','submit','example','service-file'],nargs='?',default='up');p.add_argument('--state',type=Path,default=ROOT/'runtime/commerce-logistics')
    p.add_argument('--projects-root',type=Path);p.add_argument('--commerce',type=Path);p.add_argument('--logistics',type=Path);p.add_argument('--base-port',type=int,default=8101);p.add_argument('--no-open',action='store_true');p.add_argument('--file',type=Path);p.add_argument('--key')
    a=p.parse_args();state=a.state.resolve()
    if a.projects_root:
        if a.commerce or a.logistics:p.error('Usa --projects-root o rutas individuales, no ambos.')
        a.commerce=a.projects_root/'comercio';a.logistics=a.projects_root/'logistica'
        if not all((folder/'config/brain.json').is_file() for folder in (a.commerce,a.logistics)):p.error('--projects-root debe contener comercio/config/brain.json y logistica/config/brain.json')
    try:
        if a.command=='up':return up(state,a.commerce,a.logistics,a.base_port,a.no_open)
        conf=read(state/'fleet.json')
        if a.command=='service-file':
            import plistlib
            label='local.decisionbrain.'+__import__('hashlib').sha256(str(state).encode()).hexdigest()[:10]
            definition={'Label':label,'ProgramArguments':[str(Path(sys.executable).absolute()),'-m','decision_brain.operations','up','--state',str(state),'--no-open'],'WorkingDirectory':str(ROOT),
              'EnvironmentVariables':{'PYTHONPATH':str(ROOT/'src'),'BRAIN_PROJECT_ROOT':str(ROOT),'PYTHONUTF8':'1','OPENBLAS_NUM_THREADS':'1'},'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,
              'StandardOutPath':str(state/'supervisor.stdout.log'),'StandardErrorPath':str(state/'supervisor.stderr.log')}
            output=state/'decision-brain.plist';output.write_bytes(plistlib.dumps(definition));print(output);return
        secret=read(state/'secrets.json');auth={'Authorization':'Bearer '+secret['BRAIN_ORCHESTRATOR_TOKEN']}
        with httpx.Client(trust_env=False,timeout=20) as client:
            if a.command=='status':
                response=client.get(f"http://127.0.0.1:{conf['observer_port']}/v1/dashboard",headers={'Authorization':'Bearer '+secret['BRAIN_OBSERVER_TOKEN']});response.raise_for_status();d=response.json();print(json.dumps({'operations':d['operations'],'consumer':d.get('consumer'),'deliveries':d.get('deliveries')},ensure_ascii=False,indent=2));return
            if not a.key:p.error('Usa --key con un identificador estable de caso; repetirlo no duplica decisiones.')
            if a.command=='example':
                spec=read(Path(conf['models']['logistica']['project'])/'config/brain.json');context=build(spec)['cases'][0]['context'];body={'brain_id':'logistica.incidencia','context':context,'handoff':{'dias_desde_compra':7}}
            else:
                if not a.file:p.error('submit requiere --file con el envelope completo')
                body=read(a.file)
            gateway=f"http://127.0.0.1:{conf['gateway_port']}"
            response=client.get(gateway+'/v1/catalog',headers=auth);response.raise_for_status();version=next(e['model_version'] for e in response.json()['brains'] if e['brain_id']==body['brain_id'])
            headers={**auth,'Accept-Version':version,'Idempotency-Key':a.key,'traceparent':f'00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01'}
            response=client.post(gateway+'/v1/predict',headers=headers,json=body);print(json.dumps(response.json(),ensure_ascii=False,indent=2));response.raise_for_status()
    except (ValueError,KeyError,OSError,RuntimeError,httpx.HTTPError,StopIteration) as exc:p.error(str(exc))
if __name__=='__main__':main()
