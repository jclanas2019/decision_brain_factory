import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from decision_brain import launch
class LaunchChecks(unittest.TestCase):
    def exercise(self,returns,check_only=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        args=['launch','--no-open']+(['--check-only'] if check_only else [])
        def fake_step(command,log,stream=False):
            log.write_text('test log', encoding='utf-8')
            result=returns.pop(0)
            if 'decision_brain.brain' in command or 'decision_brain.harness' in command:
                out=Path(command[command.index('--output')+1]);out.mkdir();(out/'report.html').write_text('report', encoding='utf-8')
            return result
        with patch.object(launch,'ROOT',root),patch('sys.argv',args),patch.object(launch,'step',side_effect=fake_step):code=launch.main()
        sessions=list((root/'runs').glob('session_*'))
        self.assertEqual(len(sessions),1)
        self.assertTrue((root/'runs/latest.html').exists())
        return code,json.loads((sessions[0]/'status.json').read_text(encoding='utf-8')),root
    def test_success(self):
        code,status,_=self.exercise([0,0,0]);self.assertEqual(code,0);self.assertTrue(status['evaluation_report'])
    def test_model_failure_keeps_reports(self):
        code,status,_=self.exercise([0,0,1]);self.assertEqual(code,1);self.assertTrue(status['evaluation_report'])
    def test_software_failure_stops_training(self):
        code,status,_=self.exercise([1]);self.assertEqual(code,2);self.assertFalse(status['training_report'])
    def test_check_only(self):
        code,status,_=self.exercise([0],True);self.assertEqual(code,0);self.assertFalse(status['training_report'])
    def test_repeated_runs_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(launch,'ROOT',root),patch('sys.argv',['launch','--no-open','--check-only']),patch.object(launch,'step',return_value=0):
                self.assertEqual(launch.main(),0);self.assertEqual(launch.main(),0)
            self.assertEqual(len(list((root/'runs').glob('session_*'))),2)

if __name__=='__main__':unittest.main()
