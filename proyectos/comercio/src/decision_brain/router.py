"""Deterministic event router. It never calls brain endpoints or interprets prose."""
import argparse
import json
import os
from pathlib import Path
import uuid
import httpx

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gateway',default='https://127.0.0.1:8443')
    p.add_argument('--event-id',required=True);p.add_argument('--route-id',required=True);p.add_argument('--brain-id',required=True)
    p.add_argument('--version');p.add_argument('--trace-id',required=True);p.add_argument('--key',required=True,help='Idempotency key, not a secret')
    a=p.parse_args();token=os.environ.get('BRAIN_ORCHESTRATOR_TOKEN','')
    if len(token)<32:p.error('set BRAIN_ORCHESTRATOR_TOKEN')
    if not a.version:
        catalog=httpx.get(a.gateway.rstrip('/')+'/v1/catalog',headers={'Authorization':'Bearer '+token},timeout=10,trust_env=False)
        catalog.raise_for_status()
        entry=next((e for e in catalog.json()['brains'] if e['brain_id']==a.brain_id),None)
        if entry is None:p.error('target is not active and authorized in catalog')
        a.version=entry['model_version']
    headers={'Authorization':'Bearer '+token,'Accept-Version':a.version,'Idempotency-Key':a.key,'traceparent':f'00-{a.trace_id}-{uuid.uuid4().hex[:16]}-01'}
    response=httpx.post(a.gateway.rstrip('/')+'/v1/events/'+a.event_id+'/predict',json={'brain_id':a.brain_id,'route_id':a.route_id},headers=headers,timeout=15,trust_env=False)
    print(json.dumps(response.json(),ensure_ascii=False,indent=2));return 0 if response.status_code==200 else 1

if __name__=='__main__':raise SystemExit(main())
