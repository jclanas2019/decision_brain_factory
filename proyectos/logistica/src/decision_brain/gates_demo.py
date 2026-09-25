"""One-command, real-HTTP demonstration of two isolated brains and both gate families."""
import argparse
import copy
from datetime import datetime,timezone
import html
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid
import httpx
from decision_brain.layout import project_root
from decision_brain.gate_scaffold import write_config
from decision_brain.harness_suite_builder import build
from decision_brain.releases import register,activate
from decision_brain.edge_store import Store


def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    root=project_root();out=root/'runs'/('gates_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    processes=[];logs=[];report={'passed':False,'mode':'development','checks':{},'quality':{}}
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',OPENBLAS_NUM_THREADS='1',BRAIN_MODE='development')
    env.update({key:secrets.token_urlsafe(40) for key in ('BRAIN_ORCHESTRATOR_TOKEN','BRAIN_POSTVENTA_TOKEN','BRAIN_WORKER_TOKEN','BRAIN_OBSERVER_TOKEN')})
    def execute(command,name,allow_quality_fail=False):
        with (out/name).open('w',encoding='utf-8') as log:result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode not in ((0,1) if allow_quality_fail else (0,)):raise RuntimeError('Falló '+name)
    def server(module,port_value,extra,name):
        log=(out/name).open('w',encoding='utf-8');logs.append(log)
        process=subprocess.Popen([sys.executable,'-m','uvicorn',module+':create_app','--factory','--host','127.0.0.1','--port',str(port_value),'--no-access-log'],cwd=root,env=dict(env,**extra),stdout=log,stderr=subprocess.STDOUT);processes.append(process)
        address=f'http://127.0.0.1:{port_value}'
        for _ in range(150):
            if process.poll() is not None:raise RuntimeError('Proceso terminó: '+name)
            try:
                if httpx.get(address+'/ready',timeout=1,trust_env=False).status_code==200:return address
            except httpx.HTTPError:pass
            time.sleep(.05)
        raise RuntimeError('Timeout: '+name)
    try:
        spec_a=read(root/'config/presets/logistica.json');spec_b=copy.deepcopy(spec_a)
        spec_b['industry']='Logística: seguimiento de incidencias'
        rename={'horas_desviacion':'retraso_reportado_horas','estado_entrega':'detalle_evento','contexto':'centro_operativo'}
        for f in spec_b['fields']:f['id']=rename[f['id']]
        for scene in spec_b['synthetic_scenarios']:scene['context']={rename[k]:v for k,v in scene['context'].items()}
        catalog=[];workers=[]
        for name,spec,bid in [('source',spec_a,'logistica.incidencia'),('target',spec_b,'logistica.seguimiento')]:
            print('Preparando microcerebro:',bid,flush=True)
            worker=out/name;write_config(worker,spec,bid);put(worker/'brain.json',spec);put(worker/'suite.json',build(spec))
            (worker/'project.toml').write_text('version = 1\n[harness]\nmin_pass_rate = 1.0\n',encoding='utf-8')
            run=worker/'model'
            execute([sys.executable,'-m','decision_brain.brain','--config',str(worker/'brain.json'),'demo','--rows','1000','--trials','2','--epochs','20','--output',str(run)],name+'_train.log')
            execute([sys.executable,'-m','decision_brain.harness','--project',str(worker/'project.toml'),'--run',str(run),'--suite',str(worker/'suite.json'),'--output',str(worker/'evaluation')],name+'_harness.log',True)
            quality=read(worker/'evaluation/report.json');report['quality'][bid]={'passed':quality['passed'],'pass_rate':quality['pass_rate']}
            registry=worker/'registry';register(registry,run,'v1','development',harness=worker/'evaluation/report.json');activate(registry,'v1','development')
            cfg=worker/'config/gates';gate=read(cfg/'interop_gate.json');gate['pin_version_from']='registry.development';gate['event_facts']=['horas_desviacion'] if name=='source' else [];put(cfg/'interop_gate.json',gate)
            address=server('decision_brain.service',port(),{'BRAIN_ID':bid,'BRAIN_REGISTRY':str(registry),'BRAIN_API_KEY':env['BRAIN_WORKER_TOKEN']},name+'_server.log')
            entry=read(cfg/'catalog.json')['brains'][0];entry['endpoint']=address;entry['upstream_token_env']='BRAIN_WORKER_TOKEN';entry['interop_config']=str(cfg/'interop_gate.json');entry['observe_config']=str(cfg/'observe.json');entry['environments']={'development':{'registry':str(registry)}};catalog.append(entry);workers.append(worker)
        edge=out/'edge';write_config(edge,spec_a,'logistica.incidencia');cfg=edge/'config/gates'
        put(cfg/'catalog.json',{'version':1,'brains':catalog})
        gate=read(cfg/'gateway.json');gate.update(environment='development',require_tls=False)
        for caller in gate['callers'].values():caller['brains']=[e['brain_id'] for e in catalog]
        put(cfg/'gateway.json',gate)
        obs=read(cfg/'observer.json');obs['environment']='development';put(cfg/'observer.json',obs)
        routes=[]
        for i,action in enumerate(catalog[0]['actions']):
            rule=next((r for r in spec_a['routing']['rules'] if r['action']==action),None)
            detail='Caso incierto: requiere seguimiento humano.'
            if rule:
                decision=next(d for d in spec_a['decisions'] if d['id']==rule['decision'])
                detail=next(o['meaning'] for o in decision['options'] if o['id']==rule['option'])
            routes.append({'id':'followup-'+str(i),'source_brain':'logistica.incidencia','target_brain':'logistica.seguimiento','action':action,
                           'mapping':{'retraso_reportado_horas':{'fact':'horas_desviacion'},'detalle_evento':{'literal':detail},'centro_operativo':{'literal':'Seguimiento interno por evento'}}})
        put(cfg/'routes.json',{'version':1,'routes':routes})
        gateway=server('decision_brain.gateway',port(),{'BRAIN_GATEWAY_CONFIG':str(cfg/'gateway.json')},'gateway.log')
        observer=server('decision_brain.observer',port(),{'BRAIN_OBSERVER_CONFIG':str(cfg/'observer.json')},'observer.log')
        trace=uuid.uuid4().hex;headers={'Authorization':'Bearer '+env['BRAIN_ORCHESTRATOR_TOKEN'],'traceparent':f'00-{trace}-{uuid.uuid4().hex[:16]}-01','Accept-Version':'v1','Idempotency-Key':'source-1'}
        body={'brain_id':'logistica.incidencia','context':build(spec_a)['cases'][0]['context']}
        with httpx.Client(trust_env=False,timeout=15) as client:
            first=client.post(gateway+'/v1/predict',json=body,headers=headers);first.raise_for_status();a=first.json()
            replay=client.post(gateway+'/v1/predict',json=body,headers=headers)
            assert replay.json()==a and replay.headers['Idempotency-Replayed']=='true'
            route=next(r for r in routes if r['action']==a['action'])
            second=client.post(gateway+'/v1/events/'+a['event_id']+'/predict',json={'brain_id':'logistica.seguimiento','route_id':route['id']},headers={**headers,'Idempotency-Key':'target-1'});second.raise_for_status();b=second.json()
            assert a['trace_id']==b['trace_id']==trace and a['request_id']!=b['request_id']
            rejected=client.post(gateway+'/v1/predict',json=body,headers={**headers,'Accept-Version':'wrong','Idempotency-Key':'wrong-version'})
            assert rejected.status_code==409
            auth={'Authorization':'Bearer '+env['BRAIN_OBSERVER_TOKEN']}
            for _ in range(60):
                audit=edge/'registry/audit.jsonl'
                if audit.exists() and len(audit.read_text(encoding='utf-8').splitlines())==2:break
                time.sleep(.05)
            else:raise RuntimeError('Observer did not export two decisions')
            metrics=client.get(observer+'/metrics',headers=auth);metrics.raise_for_status();(out/'metrics.prom').write_text(metrics.text,encoding='utf-8')
            operations=client.get(observer+'/v1/operations',headers=auth);operations.raise_for_status();put(out/'operations.json',operations.json())
        store=Store(edge/'registry/edge.sqlite3')
        with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==2
        report.update(passed=True,trace_id=trace,checks={'real_http_two_brains':True,'distinct_target_contract':True,'event_state_mapping':True,'idempotent_replay':True,'shared_trace':True,'version_rejected':True,'central_audit_two_records':True,'separate_observer_process':True},decisions=[a,b])
    except Exception as exc:
        report['error']=str(exc)
    finally:
        for process in reversed(processes):
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for log in logs:log.close()
        put(out/'report.json',report)
        rows=''.join('<tr><td>'+html.escape(k)+'</td><td>'+('PASS' if v else 'FAIL')+'</td></tr>' for k,v in report['checks'].items())
        quality=''.join('<tr><td>'+html.escape(k)+'</td><td>'+('PASS' if v['passed'] else 'FAIL')+'</td><td>'+f"{v['pass_rate']:.0%}"+'</td></tr>' for k,v in report['quality'].items())
        page='<html lang="es"><meta charset="utf-8"><title>Gates: prueba funcional</title><style>body{font:17px system-ui;max-width:1000px;margin:40px auto}td,th{padding:12px;border:1px solid #ddd}table{border-collapse:collapse}</style><h1>Integración de gates: '+('PASS' if report['passed'] else 'FAIL')+'</h1><p>Dos procesos de inferencia, un gateway y un observador separados. Se cerraron al terminar la prueba.</p><h2>Interoperabilidad</h2><table>'+rows+'</table><h2>Calidad de los modelos sintéticos</h2><p>La demo usa ambiente development. Una calidad FAIL no es aceptable para promoción a producción.</p><table><tr><th>Cerebro</th><th>Harness</th><th>Casos aprobados</th></tr>'+quality+'</table><p>'+html.escape(report.get('error',''))+'</p><p><a href="report.json">Resultado JSON</a> · <a href="metrics.prom">Métricas</a> · <a href="operations.json">Semáforo</a></p></html>'
        (out/'report.html').write_text(page,encoding='utf-8');print('Informe gates:',out/'report.html',flush=True)
        if not args.no_open:
            import webbrowser
            webbrowser.open((out/'report.html').as_uri())
    return 0 if report['passed'] else 2

if __name__=='__main__':raise SystemExit(main())
