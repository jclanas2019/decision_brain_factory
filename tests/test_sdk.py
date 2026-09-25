import json
import unittest
import httpx
from decision_brain_sdk import DecisionClient,ObserverClient,BrainError,TransportError,ProtocolError

class SDKTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.version='v1';self.status=200;self.bad=False;self.fail=False;self.replay=False
        def handler(r):
            self.calls.append(r)
            if self.fail:raise httpx.ReadTimeout('SECRET',request=r)
            if r.url.path.endswith('/v1/catalog'):return httpx.Response(200,json={'brains':[{'brain_id':'test.brain','model_version':self.version}]})
            if r.method=='POST':
                if self.status!=200:return httpx.Response(self.status,json={'error':'SECRET_CONTEXT'})
                body=json.loads(r.content);value={'request_id':'r1','brain_id':body['brain_id'],'model_version':r.headers['accept-version'],'action':'review','needs_review':True,
                  'trace_id':'1'*32 if self.replay else r.headers['traceparent'].split('-')[1],'event_id':'r1','answers':{'head':{'choice':'yes','probabilities':{'yes':.8,'no':.2}}},'confidence':{'head':.8}}
                if self.bad:value['answers']['head']['probabilities']['yes']=float('nan');return httpx.Response(200,content=json.dumps(value))
                return httpx.Response(200,json=value,headers={'Idempotency-Replayed':'true' if self.replay else 'false'})
            if r.url.path.endswith('/v1/dashboard'):return httpx.Response(200,json={'deliveries':[{'event_id':'e1','state':'delivered'}]})
            return httpx.Response(200,json={'ok':True})
        self.client=DecisionClient('http://localhost/base','test-token',transport=httpx.MockTransport(handler))
        self.handler=handler
    def tearDown(self):self.client.close()
    def test_typed_prediction_and_prefix(self):
        d=self.client.predict('test.brain',{'message':'a'},idempotency_key='case-1')
        self.assertEqual(d.action,'review');self.assertTrue(d.needs_review);self.assertFalse(d.replayed)
        self.assertEqual(self.calls[-1].url.path,'/base/v1/predict');self.assertEqual(self.calls[-1].headers['authorization'],'Bearer test-token')
    def test_preparation_freezes_context_version_key_trace(self):
        context={'message':'a'};request=self.client.prepare('test.brain',context,idempotency_key='case-1');context['message']='changed';self.version='v2'
        self.client.send(request);self.client.send(request)
        first,second=self.calls[-2:];self.assertEqual(first.content,second.content);self.assertEqual(json.loads(second.content)['context']['message'],'a')
        for h in ('accept-version','idempotency-key','traceparent'):self.assertEqual(first.headers[h],second.headers[h])
        self.assertEqual(second.headers['accept-version'],'v1')
    def test_timeout_not_retried_or_leaked(self):
        self.fail=True
        with self.assertRaises(TransportError) as exc:self.client.predict('test.brain',{},version='v1',idempotency_key='case-1')
        self.assertEqual(len(self.calls),1);self.assertNotIn('SECRET',str(exc.exception))
    def test_http_errors_typed_and_private(self):
        for status in (401,403,409,422,503):
            self.status=status
            with self.assertRaises(BrainError) as exc:self.client.predict('test.brain',{},version='v1',idempotency_key='case-1')
            self.assertEqual(exc.exception.status,status);self.assertNotIn('SECRET',str(exc.exception))
    def test_response_probabilities_validated(self):
        self.bad=True
        with self.assertRaises(ProtocolError):self.client.predict('test.brain',{},version='v1',idempotency_key='case-1')
    def test_replay_preserves_original_trace(self):
        self.replay=True;d=self.client.predict('test.brain',{},version='v1',idempotency_key='case-1');self.assertTrue(d.replayed);self.assertEqual(d.trace_id,'1'*32)
    def test_invalid_input_before_network(self):
        for context in ({'x':float('nan')},{'x':'a'*66000}):
            with self.assertRaises(ValueError):self.client.prepare('test.brain',context,version='v1',idempotency_key='case-1')
        with self.assertRaises(ValueError):self.client.prepare('test.brain',{},version='v1',idempotency_key='')
        self.assertEqual(self.calls,[])
    def test_event_preparation(self):
        request=self.client.prepare_event('event-1','route-1','test.brain',version='v1',idempotency_key='event-key',trace_id='1'*32)
        self.client.send(request);self.assertEqual(self.calls[-1].url.path,'/base/v1/events/event-1/predict')
        self.assertEqual(json.loads(self.calls[-1].content),{'brain_id':'test.brain','route_id':'route-1'})
    def test_observer_delivery_filter(self):
        with ObserverClient('http://localhost','observer-secret',transport=httpx.MockTransport(self.handler)) as o:
            self.assertEqual(len(o.deliveries('e1')),1);self.assertEqual(o.deliveries('missing'),[])
        self.assertEqual(self.calls[-1].headers['authorization'],'Bearer observer-secret')
    def test_remote_http_and_credentials_in_url_rejected(self):
        for url in ('http://example.com','https://secret@example.com','https://example.com/?token=a'):
            with self.assertRaises(ValueError):DecisionClient(url,'x')
