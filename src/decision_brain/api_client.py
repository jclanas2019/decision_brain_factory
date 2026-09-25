"""Call the local service without exposing credentials on the command line."""
import argparse
import json
import os
from pathlib import Path
import urllib.request
import urllib.error


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8000');p.add_argument('--state',type=Path,default=Path('examples/example_state.json'))
    a=p.parse_args();key=os.environ.get('BRAIN_API_KEY','')
    if os.environ.get('BRAIN_API_KEY_FILE'):key=Path(os.environ['BRAIN_API_KEY_FILE']).read_text(encoding='utf-8').strip()
    if not key:p.error('set BRAIN_API_KEY or BRAIN_API_KEY_FILE')
    request=urllib.request.Request(a.url.rstrip('/')+'/v1/predict',data=json.dumps({'context':json.loads(a.state.read_text(encoding='utf-8'))}).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=15) as r:print(json.dumps(json.load(r),indent=2,ensure_ascii=False))
    except urllib.error.HTTPError as e:raise SystemExit(f'HTTP {e.code}: '+e.read().decode())


if __name__=='__main__':main()
