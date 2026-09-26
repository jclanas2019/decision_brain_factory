"""Split annotated real data by entity, without allowing groups across partitions."""
import argparse
import csv
import os
from pathlib import Path
import random
import tempfile
from decision_brain.contracts import read_spec,require,SPLITS
from decision_brain.brain import read_dataset


def prepare(source,output,spec,seed=42):
    require(not output.exists(),'Output exists; choose a new path')
    columns=[f['id'] for f in spec['fields']]+['target__'+d['id'] for d in spec['decisions']]+['__group']
    with source.open(newline='',encoding='utf-8-sig') as file:
        reader=csv.DictReader(file)
        require(len(reader.fieldnames or [])==len(columns) and set(reader.fieldnames or [])==set(columns),'Input requires context, target__ labels and __group; no __split')
        rows=list(reader)
    require(len(rows)>=200,'At least 200 annotated rows required')
    groups=sorted({row['__group'].strip() for row in rows})
    require('' not in groups and len(groups)>=20,'At least 20 nonempty entity groups required')
    random.Random(seed).shuffle(groups)
    sizes=[int(len(groups)*.55),int(len(groups)*.15),int(len(groups)*.15)]
    sizes.append(len(groups)-sum(sizes));assignment={};offset=0
    for split,n in zip(SPLITS,sizes):
        assignment.update({g:split for g in groups[offset:offset+n]});offset+=n
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.prepared-',suffix='.csv',dir=output.parent)
    try:
        with os.fdopen(fd,'w',newline='',encoding='utf-8') as file:
            writer=csv.DictWriter(file,fieldnames=columns+['__split']);writer.writeheader()
            for row in rows:
                group=row['__group'].strip();writer.writerow({**row,'__group':group,'__split':assignment[group]})
        # Fail before publication if a partition lacks labels, rows, or contains leakage.
        parts=read_dataset(Path(tmp),spec)
        os.link(tmp,output) # Exclusive publication: never overwrite another dataset.
        return {s:len(v) for s,v in parts.items()}
    finally:Path(tmp).unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--config',default=Path('config/brain.json'),type=Path);p.add_argument('--seed',type=int,default=42)
    a=p.parse_args()
    try:print(prepare(a.input,a.output,read_spec(a.config),a.seed))
    except (ValueError,OSError,KeyError,TypeError) as exc:p.error(str(exc))

if __name__=='__main__':main()
