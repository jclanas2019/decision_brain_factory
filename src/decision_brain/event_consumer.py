"""Single-host durable outbox consumer. Retries preserve target version and idempotency key."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import httpx
from decision_brain.edge_store import Store

class Consumer:
    def __init__(self,database,routes,gateway,token):
        self.store=Store(database);self.routes=Path(routes);self.gateway=gateway.rstrip('/');self.token=token
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS consumer_cursor(id INTEGER PRIMARY KEY,seq INTEGER NOT NULL);
            INSERT OR IGNORE INTO consumer_cursor VALUES(1,0);
            CREATE TABLE IF NOT EXISTS consumer_health(id INTEGER PRIMARY KEY,last_seen REAL);
            INSERT OR IGNORE INTO consumer_health VALUES(1,0);
            CREATE TABLE IF NOT EXISTS deliveries(event_id TEXT,route_id TEXT,route_hash TEXT,brain_id TEXT,trace_id TEXT,version TEXT,state TEXT,attempts INTEGER,next_attempt REAL,result_id TEXT,error TEXT,PRIMARY KEY(event_id,route_id));''')
    def discover(self):
        routes=json.loads(self.routes.read_text())['routes']
        ids=[r['id'] for r in routes]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate_route_id')
        # Prevent routing cycles before accepting any events.
        graph={}
        for r in routes:graph.setdefault(r['source_brain'],set()).add(r['target_brain'])
        def visit(node,path):
            if node in path:raise ValueError('routing_cycle')
            for target in graph.get(node,()):visit(target,path|{node})
        for node in graph:visit(node,set())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor=db.execute('SELECT seq FROM consumer_cursor WHERE id=1').fetchone()[0]
            rows=db.execute('SELECT seq,event FROM decisions WHERE seq>? ORDER BY seq LIMIT 100',(cursor,)).fetchall()
            for row in rows:
                event=json.loads(row['event'])
                if event.get('caller')!='orchestrator':continue
                for r in routes:
                    if r['source_brain']==event['brain_id'] and r['action']==event['action']:
                        digest=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()
                        db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,NULL,?,0,0,NULL,NULL)',(event['event_id'],r['id'],digest,r['target_brain'],event['trace_id'],'pending'))
            if rows:db.execute('UPDATE consumer_cursor SET seq=? WHERE id=1',(rows[-1]['seq'],))
    def tick(self,client):
        self.discover()
        with self.store.connect() as db:db.execute('UPDATE consumer_health SET last_seen=? WHERE id=1',(time.time(),))
        with self.store.connect() as db:rows=db.execute("SELECT * FROM deliveries WHERE state='pending' AND next_attempt<=? ORDER BY rowid LIMIT 20",(time.time(),)).fetchall()
        for row in rows:
            version=row['version'];result_id=None;error=None;state='pending'
            try:
                current=next(r for r in json.loads(self.routes.read_text())['routes'] if r['id']==row['route_id'])
                if hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()!=row['route_hash']:raise ValueError('route_changed_requires_review')
                auth={'Authorization':'Bearer '+self.token}
                if not version:
                    response=client.get(self.gateway+'/v1/catalog',headers=auth);response.raise_for_status()
                    version=next(e['model_version'] for e in response.json()['brains'] if e['brain_id']==row['brain_id'])
                    with self.store.connect() as db:db.execute('UPDATE deliveries SET version=? WHERE event_id=? AND route_id=?',(version,row['event_id'],row['route_id']))
                key='route-'+hashlib.sha256((row['event_id']+':'+row['route_id']).encode()).hexdigest()[:56]
                headers={**auth,'X-Route-Hash':row['route_hash'],'Accept-Version':version,'Idempotency-Key':key,'traceparent':f"00-{row['trace_id']}-{uuid.uuid4().hex[:16]}-01"}
                response=client.post(self.gateway+'/v1/events/'+row['event_id']+'/predict',json={'brain_id':row['brain_id'],'route_id':row['route_id']},headers=headers)
                if response.status_code==200:state='delivered';result_id=response.json()['request_id']
                else:
                    error='http_'+str(response.status_code)
                    if response.status_code in (400,401,403,404,409,413,422,500):state='dead'
            except (ValueError,StopIteration,KeyError):state='dead';error='contract_or_route_requires_review'
            except httpx.HTTPError:error='network_or_gateway_unavailable'
            attempts=row['attempts']+1
            if state=='pending' and attempts>=5:state='dead'
            with self.store.connect() as db:
                db.execute('UPDATE deliveries SET state=?,attempts=?,next_attempt=?,result_id=?,error=? WHERE event_id=? AND route_id=?',
                           (state,attempts,time.time()+min(60,2**attempts),result_id,error,row['event_id'],row['route_id']))
    def run(self):
        import fcntl
        with self.store.path.with_suffix('.consumer.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('consumer_already_running')
            with httpx.Client(trust_env=False,timeout=15) as client:
                while True:self.tick(client);time.sleep(.5)

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',required=True,type=Path);p.add_argument('--routes',required=True,type=Path);p.add_argument('--gateway',required=True);a=p.parse_args()
    token=os.environ.get('BRAIN_ORCHESTRATOR_TOKEN','')
    if len(token)<32:p.error('missing orchestrator secret')
    try:Consumer(a.database,a.routes,a.gateway,token).run()
    except KeyboardInterrupt:pass
if __name__=='__main__':main()
