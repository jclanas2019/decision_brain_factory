"""Local authoritative catalog: endpoints are configuration, never event data."""
import json
import math
from pathlib import Path
from urllib.parse import urlparse
from decision_brain.contracts import read_spec
from decision_brain.edge_contracts import BRAIN,actions,contract_hash
from decision_brain.releases import verify

class Catalog:
    def __init__(self,path):self.path=Path(path).resolve()
    def entries(self):
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('version')!=1 or not isinstance(data.get('brains'),list):raise ValueError('invalid_catalog')
        result={}
        for entry in data['brains']:
            bid=entry.get('brain_id','');url=urlparse(entry.get('endpoint',''))
            if not BRAIN.fullmatch(bid) or bid in result:raise ValueError('invalid_brain_id')
            if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise ValueError('invalid_endpoint')
            if not entry.get('owner') or type(entry.get('latency_sla_ms')) not in (int,float) or not math.isfinite(entry['latency_sla_ms']) or entry['latency_sla_ms']<=0:raise ValueError('missing_catalog_metadata')
            result[bid]=entry
        return result
    def path_for(self,value):return (self.path.parent/Path(value)).resolve()
    def resolve(self,bid,environment):
        entry=self.entries()[bid]
        registration=entry['environments'][environment]
        registry=self.path_for(registration['registry'])
        pointer=json.loads((registry/'active.json').read_text(encoding='utf-8'))
        if pointer['environment']!=environment:raise ValueError('catalog_environment_mismatch')
        folder,manifest=verify(registry,pointer['version'],environment)
        spec=read_spec(folder/'brain.json')
        if contract_hash(spec)!=entry['contract_hash'] or actions(spec)!=sorted(entry['actions']):raise ValueError('catalog_contract_drift')
        gate=json.loads(self.path_for(registration.get('interop_config',entry['interop_config'])).read_text(encoding='utf-8'))
        observe=json.loads(self.path_for(entry['observe_config']).read_text(encoding='utf-8'))
        if gate['brain_id']!=bid or gate['input']!='contract.fields' or gate['pin_version_from']!='registry.'+environment:raise ValueError('invalid_interop_pin')
        if not isinstance(gate['allowed_callers'],list) or not gate['allowed_callers']:raise ValueError('no_authorized_callers')
        expected={'authorization','traceparent','accept-version','idempotency-key'}
        if set(gate['required_headers'])!=expected:raise ValueError('unsupported_required_headers')
        if set(gate['output'])!={'answers','action','needs_review','model_version'}:raise ValueError('invalid_output_contract')
        if set(observe['labels'])!={'brain_id','version','action','needs_review'}:raise ValueError('unsupported_metric_labels')
        if observe.get('retention')!={'mode':'append_only_manual_archive','metrics_window_seconds':3600}:raise ValueError('unsupported_retention_policy')
        slo=observe['slo']
        if any(type(slo.get(k)) not in (int,float) or not math.isfinite(slo[k]) or not 0<=slo[k]<=1 for k in ('availability','review_rate_max','fallback_rate_max')) or slo.get('p95_ms',0)<=0:raise ValueError('invalid_slo')
        for key in ('max_body_bytes','max_text_chars','max_numeric_magnitude'):
            value=gate['limits'][key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('invalid_brain_limit')
        handoff=gate.get('handoff_fields',[])
        if not isinstance(handoff,list) or any(f.get('type')!='number' or f.get('id') in observe.get('redact',[]) for f in handoff):raise ValueError('unsafe_handoff')
        if len({f['id'] for f in handoff})!=len(handoff):raise ValueError('duplicate_handoff_field')
        for field in gate.get('event_facts',[]):
            f=next((f for f in spec['fields'] if f['id']==field),None)
            if not f or f['type']=='text' or field in observe.get('redact',[]):raise ValueError('unsafe_event_fact')
        return {'entry':entry,'version':pointer['version'],'spec':spec,'manifest':manifest,'gate':gate,'observe':observe}


def main():
    import argparse
    import os
    from decision_brain.releases import write_atomic
    p=argparse.ArgumentParser(description='Add a generated brain to a shared catalog')
    p.add_argument('--catalog',type=Path,default=Path('config/gates/catalog.json'))
    p.add_argument('--project',required=True,type=Path);p.add_argument('--endpoint',required=True)
    p.add_argument('--owner');p.add_argument('--upstream-token-env')
    args=p.parse_args();source=args.project.resolve()/'config/gates/catalog.json';dest=args.catalog.resolve()
    entry=Catalog(source).entries();entry=dict(next(iter(entry.values())))
    url=urlparse(args.endpoint)
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        p.error('endpoint must be an HTTP(S) origin without credentials, path, query or fragment')
    entry['endpoint']=args.endpoint
    if args.owner:entry['owner']=args.owner
    if args.upstream_token_env:entry['upstream_token_env']=args.upstream_token_env
    for key in ('interop_config','observe_config'):entry[key]=os.path.relpath((source.parent/entry[key]).resolve(),dest.parent)
    for registration in entry['environments'].values():
        for key in ('registry','interop_config'):
            if key in registration:registration[key]=os.path.relpath((source.parent/registration[key]).resolve(),dest.parent)
    document=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {'version':1,'brains':[]}
    if any(e['brain_id']==entry['brain_id'] for e in document['brains']):p.error('brain_id already in catalog; edit intentionally to change it')
    document['brains'].append(entry)
    write_atomic(dest,document)
    print('Catalog entry added:',entry['brain_id'])

if __name__=='__main__':main()
