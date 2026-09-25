import contextlib
import io
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from decision_brain.operations import prepare,main

class OperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=self.root/'state';self.state.mkdir()
        self.commerce=self.root/'comercio';self.logistics=self.root/'logistica'
        self.saved={'models':{'comercio':{'project':str(self.commerce)},'logistica':{'project':str(self.logistics)}},'version':1}
        (self.state/'fleet.json').write_text(json.dumps(self.saved))
    def tearDown(self):self.tmp.cleanup()
    def test_restart_reuses_configuration(self):
        self.assertEqual(prepare(self.state),self.saved)
        self.assertEqual(prepare(self.state,self.commerce,self.logistics),self.saved)
    def test_different_projects_rejected(self):
        with self.assertRaises(ValueError):prepare(self.state,self.root/'other',self.logistics)
    def test_launchd_definition_contains_no_secrets(self):
        with patch('sys.argv',['operations','service-file','--state',str(self.state)]),contextlib.redirect_stdout(io.StringIO()):main()
        definition=plistlib.loads((self.state/'decision-brain.plist').read_bytes())
        self.assertTrue(definition['KeepAlive']);self.assertIn('--no-open',definition['ProgramArguments'])
        self.assertFalse(any('TOKEN' in k for k in definition['EnvironmentVariables']))
    def test_projects_root_typo_rejected(self):
        with patch('sys.argv',['operations','up','--projects-root',str(self.root/'missing')]),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:main()
        self.assertEqual(exc.exception.code,2)
