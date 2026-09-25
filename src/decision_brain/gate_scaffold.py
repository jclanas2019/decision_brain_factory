"""Generate per-brain contracts and global edge examples without credentials."""
import json
import re
from pathlib import Path
from decision_brain.edge_contracts import BRAIN,actions,contract_hash

def write_config(root,spec,brain_id,owner='equipo-local'):
    if not BRAIN.fullmatch(brain_id):raise ValueError('brain_id must be namespaced, e.g. logistica.incidencia')
    root=Path(root);folder=root/'config/gates';folder.mkdir(parents=True,exist_ok=True)
    limits={'max_body_bytes':65536,'max_text_chars':12000,'max_numeric_magnitude':1e12}
    gate={'brain_id':brain_id,'allowed_callers':['orchestrator','postventa-api'],
          'required_headers':['authorization','traceparent','accept-version','idempotency-key'],
          'input':'contract.fields','output':['answers','action','needs_review','model_version'],
          'pin_version_from':'registry.production','limits':limits,'event_facts':[]}
    observe={'labels':['brain_id','version','action','needs_review'],'redact':[f['id'] for f in spec['fields'] if f['type']=='text'],
             'audit':'registry/audit.jsonl','retention':{'mode':'append_only_manual_archive','metrics_window_seconds':3600},
             'slo':{'availability':.995,'p95_ms':80,'review_rate_max':.25,'fallback_rate_max':.25}}
    entry={'brain_id':brain_id,'contract_hash':contract_hash(spec),'endpoint':'http://127.0.0.1:8000','owner':owner,'latency_sla_ms':80,
           'actions':actions(spec),'interop_config':'interop_gate.json','observe_config':'observe.json','upstream_token_env':'BRAIN_'+re.sub('[^A-Z0-9]','_',brain_id.upper())+'_TOKEN',
           'mode':'active','environments':{'production':{'registry':'../../registry/production'},'development':{'registry':'../../registry/development','interop_config':'interop_gate.development.json'}}}
    gateway={'version':1,'environment':'production','require_tls':True,'catalog':'catalog.json','routes':'routes.json',
             'database':'../../registry/edge.sqlite3','limits':limits,'max_response_bytes':262144,'max_inflight':16,'upstream_timeout_seconds':10,
             'callers':{'orchestrator':{'token_env':'BRAIN_ORCHESTRATOR_TOKEN','brains':[brain_id]},'postventa-api':{'token_env':'BRAIN_POSTVENTA_TOKEN','brains':[brain_id]}}}
    observer={'version':1,'environment':'production','catalog':'catalog.json','database':'../../registry/edge.sqlite3',
              'audit':'../../registry/audit.jsonl','token_env':'BRAIN_OBSERVER_TOKEN'}
    request_schema,response_schema=envelope_schemas(spec,brain_id)
    for name,value in [('request.schema.json',request_schema),('response.schema.json',response_schema),('interop_gate.json',gate),('interop_gate.development.json',dict(gate,pin_version_from='registry.development')),('observe.json',observe),('catalog.json',{'version':1,'brains':[entry]}),('gateway.json',gateway),('observer.json',observer),('routes.json',{'version':1,'routes':[]})]:
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    deployment=root/'deploy/gates';deployment.mkdir(parents=True,exist_ok=True)
    container_entry=dict(entry,endpoint='http://brain:8000',interop_config='/app/config/gates/interop_gate.json',observe_config='/app/config/gates/observe.json',upstream_token_env='BRAIN_STACK_WORKER_TOKEN',environments={'production':{'registry':'/app/registry/production'}})
    container_gateway=dict(gateway,catalog='catalog.json',database='/app/registry/edge.sqlite3',routes='/app/config/gates/routes.json')
    container_observer=dict(observer,catalog='catalog.json',database='/app/registry/edge.sqlite3',audit='/app/registry/audit.jsonl')
    for name,value in [('catalog.json',{'version':1,'brains':[container_entry]}),('gateway.json',container_gateway),('observer.json',container_observer)]:
        (deployment/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    compose=root/'deploy/compose.yaml'
    if compose.exists():compose.write_text(re.sub(r'(?m)^      BRAIN_ID: .*$', '      BRAIN_ID: '+brain_id,compose.read_text(encoding='utf-8')),encoding='utf-8')


def envelope_schemas(spec,brain_id):
    fields={}
    for f in spec['fields']:
        fields[f['id']]={'type':'number','minimum':-1e12,'maximum':1e12} if f['type']=='number' else {'type':'string','minLength':1,'maxLength':12000}
        if f['type']=='category':fields[f['id']]['enum']=f['values']
    def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    request=obj({'brain_id':{'const':brain_id},'context':obj(fields)})
    heads={};confidence={}
    for d in spec['decisions']:
        options=[o['id'] for o in d['options']];prob={'type':'number','minimum':0,'maximum':1}
        properties={'kind':{'const':d['kind']},'choice':{'enum':options},'probabilities':obj({o:prob for o in options}),'max_probability':prob,'needs_review':{'type':'boolean'}}
        if d['kind']=='boolean':properties['probability_true']=prob
        if d['kind']=='score':properties['expected_score']={'type':'number'}
        heads[d['id']]=obj(properties);confidence[d['id']]=prob
    identifier={'type':'string','pattern':'^[0-9a-f]{32}$'}
    response=obj({'request_id':identifier,'correlation_id':identifier,'brain_id':{'const':brain_id},'model_version':{'type':'string'},'context':obj({}),
                  'answers':obj(heads),'action':{'enum':actions(spec)},'needs_review':{'type':'boolean'},'confidence':obj(confidence),'trace_id':identifier,'event_id':identifier})
    for value in (request,response):value['$schema']='https://json-schema.org/draft/2020-12/schema'
    response['description']='Runtime also verifies probability sums, argmax, thresholds, action rule, contract hash and model identity.'
    return request,response
