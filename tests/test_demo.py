import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.case = Path(self.temp.name) / 'case'

    def tearDown(self):
        self.temp.cleanup()

    def run_demo(self, action, *args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'examples' / 'demo.py'),
                                 action, str(self.case), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout) if ok else result

    def test_valid_output_completes_and_saved_run_reopens(self):
        state = self.run_demo('run')
        self.assertEqual(state['run']['terminal_outcome'], 'report_checked')
        self.assertEqual(json.loads((self.case / 'output.json').read_text()),
                         {'accepted': 2, 'rejected': 1, 'total': 3})
        self.assertTrue(self.run_demo('status')['replay_matches'])

    def test_wrong_payload_waits_then_repairs_without_restart(self):
        failed = self.run_demo('run', '--bad-output')
        self.assertEqual(failed['run']['current_node'], 'repair')
        self.assertIsNone(failed['run']['terminal_outcome'])
        self.assertTrue(failed['validation_errors'])
        self.assertEqual(self.run_demo('status')['run']['revision'], failed['run']['revision'])
        repaired = self.run_demo('repair')
        self.assertEqual(repaired['run']['terminal_outcome'], 'report_checked')
        self.assertFalse(repaired['validation_errors'])
        self.run_demo('repair', ok=False)

    def test_changed_input_invalidates_completed_output(self):
        self.run_demo('run')
        (self.case / 'input.json').write_text('{"accepted": 5, "rejected": 1}')
        self.assertIn('Input changed', self.run_demo('status')['validation_errors'][0])
