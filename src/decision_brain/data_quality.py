"""Dataset structure diagnostics; counts do not certify semantic independence."""
from collections import Counter
import math


def audit_dataset(parts,spec):
    message=spec.get('synthetic_design',{}).get('message_field')
    text_fields=[f['id'] for f in spec['fields'] if f['type']=='text']
    keys=[message] if message else text_fields
    counts={};seen={};combinations=set();warnings=[]
    for split,rows in parts.items():
        texts={' | '.join(str(state[k]) for k in keys) for state,_ in rows}
        seen[split]=texts
        for _,labels in rows:combinations.add(tuple(labels))
        counts[split]={'rows':len(rows),'unique_task_texts':len(texts),'target_combinations':len({tuple(labels) for _,labels in rows})}
        if len(texts)<len(rows)*.5:warnings.append(f'{split}: more than half of rows repeat task wording')
    overlaps={}
    names=list(seen)
    for i,a in enumerate(names):
        for b in names[i+1:]:overlaps[a+':'+b]=len(seen[a]&seen[b])
    if any(overlaps.values()):warnings.append('Identical task wording occurs across partitions')
    all_targets=[labels for rows in parts.values() for _,labels in rows]
    dependence={}
    for i,d in enumerate(spec['decisions']):
        for j,e in enumerate(spec['decisions']):
            if i>=j:continue
            pairs=Counter((t[i],t[j]) for t in all_targets);left=Counter(t[i] for t in all_targets);right=Counter(t[j] for t in all_targets);n=len(all_targets)
            mi=sum(v/n*math.log(v*n/(left[a]*right[b])) for (a,b),v in pairs.items())
            hx=-sum(v/n*math.log(v/n) for v in left.values());hy=-sum(v/n*math.log(v/n) for v in right.values())
            nmi=mi/min(hx,hy) if min(hx,hy)>0 else 0
            dependence[d['id']+':'+e['id']]=max(0.0,nmi)
            if nmi>.9:warnings.append(f'Nearly deterministic targets: {d["id"]}, {e["id"]}')
    return {'splits':counts,'task_text_overlap':overlaps,'target_combinations':len(combinations),
            'normalized_label_mutual_information':dependence,'warnings':warnings,
            'limitations':'Counts measure textual diversity and label association, not realistic coverage or causal independence.'}
