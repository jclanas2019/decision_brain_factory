import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from decision_brain import harness
from decision_brain.project_config import load_project

class TomlChecks(unittest.TestCase):
    def test_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'project.toml';p.write_text('version=1\n[harness]\nrun="runs/a"\nmin_pass_rate=0.8\n', encoding='utf-8')
            c=load_project(p);self.assertEqual(c['run'],(Path(tmp)/'runs/a').resolve());self.assertEqual(c['min_pass_rate'],.8)
    def test_symlinked_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            real=Path(tmp)/'real';real.mkdir()
            alias=Path(tmp)/'alias';alias.symlink_to(real,target_is_directory=True)
            (real/'project.toml').write_text('version=1\n[harness]\nrun="runs/a"\noutput="report"\n', encoding='utf-8')
            config=load_project(alias/'project.toml')
            self.assertEqual(config['run'],(real/'runs/a').resolve())
            with patch('sys.argv',['harness','--project',str(alias/'project.toml')]),patch('decision_brain.harness.run',return_value={'passed':True,'interpretation':'ok'}) as run:
                self.assertEqual(harness.main(),0)
                self.assertEqual(run.call_args.args[2],(real/'report').resolve())

    def test_reject_invalid(self):
        for text in ('version=2','version=1\n[harness]\nunknown=1','version=1\n[harness]\nmin_pass_rate=nan','version=1\n[harness]\nmin_pass_rate=true'):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'p.toml';p.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):load_project(p)
    def test_cli_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'p.toml';p.write_text('version=1\n[harness]\nrun="old"\noutput="report"\n', encoding='utf-8')
            with patch('sys.argv',['harness','--project',str(p),'--run','new']),patch('decision_brain.harness.run',return_value={'passed':True,'interpretation':'ok'}) as run:
                self.assertEqual(harness.main(),0)
                self.assertEqual(run.call_args.args[0],Path('new'))
                self.assertEqual(run.call_args.args[2],(Path(tmp)/'report').resolve())
    def test_explicit_missing_error(self):
        with patch('sys.argv',['harness','--project','missing-configuration.toml']):self.assertEqual(harness.main(),2)

if __name__=='__main__':unittest.main()
