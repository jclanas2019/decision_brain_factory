"""Run the complete software suite and persist a machine-readable summary."""
import argparse
import json
from pathlib import Path
import time
import unittest

from decision_brain.layout import project_root

def main():
    p=argparse.ArgumentParser();p.add_argument('--result',required=True,type=Path);a=p.parse_args()
    start=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(project_root()/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'passed':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),'duration_seconds':time.perf_counter()-start,
            'details':[{'test':str(case),'traceback':detail} for case,detail in result.failures+result.errors]}
    a.result.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
