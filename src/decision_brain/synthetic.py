"""Compositional synthetic data: independent labeled factors and held-out wording."""
import itertools
import random
from string import Formatter

SPLITS=('train','validation','calibration','test')

def validate_design(spec):
    design=spec.get('synthetic_design')
    if design is None:return
    fields={f['id']:f for f in spec['fields']};heads={d['id']:d for d in spec['decisions']}
    if design.get('version')!=1 or design.get('message_field') not in fields:raise ValueError('invalid synthetic design')
    fraction=design.get('uncertainty_training_fraction',0)
    if type(fraction) not in (int,float) or not 0<=fraction<=.5:raise ValueError('uncertainty fraction must be in [0,.5]')
    factors=design.get('factors',[])
    if len(factors)!=len(heads) or {f['decision'] for f in factors}!=set(heads):raise ValueError('one independent factor per decision required')
    for factor in factors:
        d=heads[factor['decision']]
        if set(factor['phrases'])!={o['id'] for o in d['options']}:raise ValueError('factor labels mismatch')
        for pools in factor['phrases'].values():
            if set(pools)!=set(SPLITS):raise ValueError('factor requires four wording pools')
            seen=set()
            for split in SPLITS:
                pool=pools[split]
                if not isinstance(pool,list) or len(pool)<3 or any(not isinstance(s,str) or not s.strip() for s in pool):raise ValueError('each wording pool needs >=3 phrases')
                if len(set(pool))!=len(pool) or seen.intersection(pool):raise ValueError('wording reused across splits')
                seen.update(pool)
                for text in pool:
                    if any(key is not None for _,key,_,_ in Formatter().parse(text)):raise ValueError('factor phrases must be literal text')
    for f in fields.values():
        if f['type']=='number':
            bounds=design.get('numeric_ranges',{}).get(f['id'])
            if not isinstance(bounds,list) or len(bounds)!=2 or not 0<=bounds[0]<=bounds[1]:raise ValueError('numeric range required')
        if f['type']=='category' and not f.get('values'):raise ValueError('category values required')


def rows_for_split(spec,n,split,seed,fake):
    design=spec['synthetic_design'];rng=random.Random(f'{seed}:{split}')
    factors=design['factors'];combinations=list(itertools.product(*[list(f['phrases']) for f in factors]))
    labels=[combinations[i%len(combinations)] for i in range(n)];rng.shuffle(labels)
    for values in labels:
        clauses=[rng.choice(f['phrases'][v][split]) for f,v in zip(factors,values)]
        rng.shuffle(clauses)
        # Faker supplies case identifiers and business context, never target labels.
        record=fake.bothify('PED-????-#####');product=rng.choice(design.get('products',['artículo']))
        state={}
        for field in spec['fields']:
            key=field['id']
            if field['type']=='number':state[key]=round(rng.uniform(*design['numeric_ranges'][key]),3)
            elif field['type']=='category':state[key]=rng.choice(field['values'])
            elif key==design['message_field']:state[key]=' '.join(clauses)
            else:state[key]=f'Pedido {record}; producto: {product}; empresa: {fake.company()}; ciudad: {fake.city()}.'
        yield state,{f['decision']:v for f,v in zip(factors,values)}


def uncertainty_rows(spec,n,seed,fake):
    """Training-only conflicts/missing factors with soft distributions, not false labels."""
    rng=random.Random(f'uncertainty:{seed}')
    factors=spec['synthetic_design']['factors']
    source=list(rows_for_split(spec,n,'train',seed+193,fake))
    for index,(state,labels) in enumerate(source):
        mode=index%3;uncertain=index%len(factors);clauses=[];targets=[]
        for j,f in enumerate(factors):
            ids=list(f['phrases']);selected=labels[f['decision']]
            distribution=[float(v==selected) for v in ids]
            if mode==0: # No task evidence: no label is supported.
                distribution=[1/len(ids)]*len(ids)
            elif j==uncertain:
                if mode==1: # Sources disagree and no resolution is available.
                    other=rng.choice([v for v in ids if v!=selected])
                    clauses.extend([rng.choice(f['phrases'][selected]['train']),rng.choice(f['phrases'][other]['train'])])
                    distribution=[.5 if v in (selected,other) else 0 for v in ids]
                else:distribution=[1/len(ids)]*len(ids) # Missing this factor.
            else:clauses.append(rng.choice(f['phrases'][selected]['train']))
            targets.append(distribution)
        rng.shuffle(clauses)
        if mode==0:
            text=rng.choice(['Buenos días. Necesito ayuda pero aún no tengo los detalles.','Gracias por su atención. Enviaré antecedentes después.','Solo saludo al equipo de soporte.','Quisiera conversar sobre un tema sin relación con la compra.','No tengo información del caso todavía.'])
        else:text=' '.join(clauses)+(' Hay versiones diferentes y falta confirmar los antecedentes.' if mode==1 else ' Los demás antecedentes todavía no están disponibles.')
        state[spec['synthetic_design']['message_field']]=text
        yield state,targets
