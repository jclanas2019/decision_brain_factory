"""Local-only immutable model registration and atomic activation/rollback."""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from decision_brain.contracts import require

FILES=('brain.json','model.json','encoder.json','weights.npz','report.json')
VERSION=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()

def write_atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.write-')
    try:
        with os.fdopen(fd,'w', encoding='utf-8') as stream:
            json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def check_gate(report,policy,evidence):
    errors=[]
    if not isinstance(report.get('metrics'),dict) or not report['metrics']:return ['missing decision metrics']
    if report.get('data_origin')!='user_supplied':errors.append('synthetic datasets cannot be promoted to production')
    if evidence.get('dataset_sha256')!=report.get('dataset_sha256'):errors.append('evidence dataset hash mismatch')
    for key in ('reviewer','reviewed_at','split_method','business_acceptance'):
        if not isinstance(evidence.get(key),str) or not evidence[key].strip():errors.append('missing evidence: '+key)
    if evidence.get('real_data_confirmed') is not True:errors.append('real-data attestation missing')
    if report['split_sizes']['test']<policy['min_test_rows']:errors.append('insufficient test rows')
    if not report.get('functional_test',{}).get('serialization_passed'):errors.append('functional test not passed')
    for name,m in report['metrics'].items():
        gate=policy.get('decisions',{}).get(name,policy['default'])
        for metric in ('accuracy','log_loss','baseline_accuracy','ece','coverage','selective_accuracy'):
            if not isinstance(m.get(metric),(int,float)) or not math.isfinite(m[metric]):
                errors.append(name+': missing or nonfinite '+metric)
        if any(name+': missing or nonfinite '+k in errors for k in ('accuracy','log_loss','baseline_accuracy','ece','coverage','selective_accuracy')):
            continue
        if m['accuracy']<gate['min_accuracy']:errors.append(name+': accuracy below threshold')
        if m['log_loss']>gate['max_log_loss']:errors.append(name+': log loss above threshold')
        if m['accuracy']<m['baseline_accuracy']+gate.get('min_baseline_gain',0):errors.append(name+': baseline gain below threshold')
        if m['ece']>gate['max_ece']:errors.append(name+': calibration error above threshold')
        if m['coverage']<gate['min_coverage']:errors.append(name+': insufficient automation coverage')
        if m['selective_accuracy']<gate['min_selective_accuracy']:errors.append(name+': selective accuracy below threshold')
        cm=m.get('confusion_matrix')
        if not isinstance(cm,list) or len(cm)<2 or any(not isinstance(row,list) or len(row)!=len(cm) or any(type(v) is not int or v<0 for v in row) for row in cm):
            errors.append(name+': invalid confusion matrix');continue
        if sum(sum(row) for row in cm)!=report['split_sizes']['test']:
            errors.append(name+': confusion support differs from test rows')
        support=[sum(row) for row in cm]
        if min(support)<policy['min_rows_per_class']:errors.append(name+': insufficient class coverage')
        if any(row[i]/max(support[i],1)<gate['min_class_recall'] for i,row in enumerate(m['confusion_matrix'])):
            errors.append(name+': class recall below threshold')
    return errors


def verify(registry,version,environment):
    require(bool(VERSION.fullmatch(version)),'invalid version')
    folder=registry/'versions'/version
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    require(manifest['version']==version,'manifest version mismatch')
    require(manifest['environment']==environment,'environment mismatch')
    require(set(manifest['hashes'])==set(FILES),'incomplete artifact manifest')
    for name,expected in manifest['hashes'].items():
        require(digest(folder/name)==expected,'artifact integrity failure: '+name)
    if environment=='production':
        require(manifest.get('gate_passed') is True,'model has not passed production gate')
    return folder,manifest


def register(registry,run,version,environment,policy=None,evidence=None):
    require(bool(VERSION.fullmatch(version)),'invalid version')
    require(environment in ('development','production'),'invalid environment')
    destination=registry/'versions'/version
    require(not destination.exists(),'version already exists; immutable releases cannot be overwritten')
    for name in FILES:require((run/name).is_file(),'missing artifact: '+name)
    report=json.loads((run/'report.json').read_text(encoding='utf-8'))
    if environment=='production':
        require(policy is not None and evidence is not None,'production requires policy and evidence')
        errors=check_gate(report,policy,evidence)
        require(not errors,'promotion rejected: '+'; '.join(errors))
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(dir=destination.parent,prefix='.register-'))
    try:
        for name in FILES:shutil.copyfile(run/name,temporary/name)
        manifest={'version':version,'environment':environment,'created_at':now(),
                  'gate_passed':environment=='production','policy':policy,'evidence':evidence,
                  'hashes':{name:digest(temporary/name) for name in FILES}}
        (temporary/'manifest.json').write_text(json.dumps(manifest,indent=2), encoding='utf-8')
        temporary.rename(destination)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return manifest


def activate(registry,version,environment):
    _,manifest=verify(registry,version,environment)
    # Serialize local administration on Linux/macOS; the service only reads pointers.
    import fcntl
    registry.mkdir(parents=True,exist_ok=True)
    with (registry/'.admin.lock').open('a', encoding='utf-8') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        current=registry/'active.json'
        old=json.loads(current.read_text(encoding='utf-8')).get('version') if current.exists() else None
        entry={'version':version,'previous':old,'environment':environment,'activated_at':now()}
        with (registry/'audit.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry)+'\n');f.flush();os.fsync(f.fileno())
        write_atomic(current,entry)
    return entry


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,default=Path('registry'))
    sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('register');r.add_argument('--run',type=Path,required=True);r.add_argument('--version',required=True)
    r.add_argument('--environment',choices=['development','production'],default='production')
    r.add_argument('--policy',type=Path);r.add_argument('--evidence',type=Path)
    a=sub.add_parser('activate');a.add_argument('--version',required=True);a.add_argument('--environment',choices=['development','production'],default='production')
    b=sub.add_parser('rollback');b.add_argument('--environment',choices=['development','production'],default='production')
    args=p.parse_args()
    try:
        if args.command=='register':
            result=register(args.registry,args.run,args.version,args.environment,
                            json.loads(args.policy.read_text(encoding='utf-8')) if args.policy else None,
                            json.loads(args.evidence.read_text(encoding='utf-8')) if args.evidence else None)
        elif args.command=='activate':result=activate(args.registry,args.version,args.environment)
        else:
            previous=json.loads((args.registry/'active.json').read_text(encoding='utf-8')).get('previous')
            require(bool(previous),'no previous version available')
            result=activate(args.registry,previous,args.environment)
        print(json.dumps(result,indent=2))
    except (ValueError,KeyError,FileNotFoundError) as e:p.error(str(e))


if __name__=='__main__':main()
