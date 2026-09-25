"""Bootstrap cases are synthetic smoke tests, not an independent benchmark."""
import json
from pathlib import Path


def build(spec):
    cases=[]
    for scene in spec.get('synthetic_scenarios',[]):
        state={}
        for field in spec['fields']:
            value=scene['context'][field['id']]
            if field['type']=='number':value=sum(value)/2
            elif field['type']=='text':value=value['test'].format_map({'company':'Empresa Ejemplo','name':'Persona Ejemplo','city':'Santiago','code':'TEST-001'})
            state[field['id']]=value
        cases.append({'id':scene['id'],'context':state,'expected':{'answers':scene['targets']}})
    cases.append({'id':'reject_unknown_field','context':{'__unexpected__':'invalid'},'expect_error':True})
    return {'version':1,'origin':'synthetic_preset_smoke_only','cases':cases}

if __name__=='__main__':
    path=Path('config/harness_suite.json')
    if path.exists():raise SystemExit('harness_suite.json already exists')
    path.write_text(json.dumps(build(json.loads(Path('config/brain.json').read_text(encoding='utf-8'))),ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
