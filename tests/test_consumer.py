import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from decision_brain.event_consumer import Consumer

class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.route={'id':'a-b','source_brain':'a.source','target_brain':'b.target','action':'follow','mapping':{}}
        self.routes=self.root/'routes.json';self.routes.write_text(json.dumps({'routes':[self.route]}))
        self.consumer=Consumer(self.root/'edge.sqlite3',self.routes,'http://gate','test-secret')
        self.event={'caller':'orchestrator','event_id':'e1','brain_id':'a.source','action':'follow','trace_id':'1'*32}
        with self.consumer.store.connect() as db:db.execute('INSERT INTO decisions(request_id,created,payload,event) VALUES(?,0,?,?)',('e1','{}',json.dumps(self.event)))
        self.calls=[];self.fail=False;self.version='v1';self.status=200
        def handler(request):
            if request.url.path=='/v1/catalog':return httpx.Response(200,json={'brains':[{'brain_id':'b.target','model_version':self.version}]})
            self.calls.append(request)
            if self.fail:raise httpx.ConnectError('offline',request=request)
            return httpx.Response(self.status,json={'request_id':'destination-1'})
        self.client=httpx.Client(transport=httpx.MockTransport(handler))
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def row(self):
        with self.consumer.store.connect() as db:return dict(db.execute('SELECT * FROM deliveries').fetchone())
    def due(self):
        with self.consumer.store.connect() as db:db.execute('UPDATE deliveries SET next_attempt=0')
    def test_restart_does_not_duplicate_delivery(self):
        self.consumer.tick(self.client);self.assertEqual(self.row()['state'],'delivered')
        restarted=Consumer(self.root/'edge.sqlite3',self.routes,'http://gate','test-secret');restarted.tick(self.client)
        self.assertEqual(len(self.calls),1)
    def test_network_retry_keeps_version_key_trace(self):
        self.fail=True;self.consumer.tick(self.client);self.assertEqual(self.row()['state'],'pending')
        self.fail=False;self.version='v2';self.due();self.consumer.tick(self.client)
        self.assertEqual(self.row()['state'],'delivered')
        for h in ('accept-version','idempotency-key','x-route-hash'):self.assertEqual(self.calls[0].headers[h],self.calls[1].headers[h])
        self.assertEqual(self.calls[1].headers['traceparent'].split('-')[1],'1'*32)
        self.assertEqual(self.calls[1].headers['accept-version'],'v1')
    def test_pending_resumes_after_restart(self):
        self.consumer.discover();self.consumer.discover()
        restarted=Consumer(self.root/'edge.sqlite3',self.routes,'http://gate','test-secret');restarted.tick(self.client)
        self.assertEqual(self.row()['state'],'delivered');self.assertEqual(len(self.calls),1)
    def test_poison_request_is_not_retried(self):
        self.status=422;self.consumer.tick(self.client);self.assertEqual(self.row()['state'],'dead');self.consumer.tick(self.client);self.assertEqual(len(self.calls),1)
    def test_retries_bounded(self):
        self.fail=True
        for _ in range(5):self.due();self.consumer.tick(self.client)
        self.assertEqual(self.row()['state'],'dead');self.assertEqual(self.row()['attempts'],5)
    def test_route_change_requires_review(self):
        self.consumer.discover();changed=dict(self.route,mapping={'x':{'literal':1}});self.routes.write_text(json.dumps({'routes':[changed]}));self.consumer.tick(self.client)
        self.assertEqual(self.row()['state'],'dead');self.assertEqual(self.calls,[])
    def test_cycles_rejected(self):
        back={'id':'b-a','source_brain':'b.target','target_brain':'a.source','action':'follow','mapping':{}}
        self.routes.write_text(json.dumps({'routes':[self.route,back]}))
        with self.assertRaisesRegex(ValueError,'routing_cycle'):self.consumer.discover()
    def test_foreign_caller_not_consumed(self):
        self.event['caller']='other'
        # Insert a separate event because decisions are immutable.
        with self.consumer.store.connect() as db:
            db.execute('INSERT INTO decisions(request_id,created,payload,event) VALUES(?,0,?,?)',('e2','{}',json.dumps(dict(self.event,event_id='e2'))))
        self.consumer.tick(self.client);self.assertEqual(len(self.calls),1)
