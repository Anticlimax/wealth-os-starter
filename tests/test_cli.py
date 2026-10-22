import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data'
        self.env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'wealthos', '--data', str(self.data), *args],
                              cwd=ROOT, env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=15)

    def test_init_export_report_and_no_overwrite(self):
        self.assertEqual(self.cli('init-demo').returncode, 0)
        self.assertNotEqual(self.cli('init-demo').returncode, 0)
        self.assertEqual(self.cli('validate').returncode, 0)
        snap = self.cli('snapshot'); self.assertEqual(snap.returncode, 0, snap.stderr)
        self.assertEqual(json.loads(snap.stdout)['net_worth'], 90000)
        self.assertIn('虚构演示', self.cli('report').stdout)
        output = Path(self.temp.name) / 'output'
        self.assertEqual(self.cli('export', '--output', str(output)).returncode, 0)
        self.assertTrue((output / 'report.md').exists())
        self.assertEqual(json.loads((output / 'snapshot.json').read_text(encoding='utf-8'))['net_worth'], 90000)
        self.assertNotEqual(self.cli('export', '--output', str(self.data)).returncode, 0)

    def test_personal_starts_unknown(self):
        self.assertEqual(self.cli('init').returncode, 0)
        snapshot = json.loads(self.cli('snapshot').stdout)
        self.assertEqual(snapshot['mode'], 'personal')
        self.assertIsNone(snapshot['net_worth'])
        self.assertIsNone(snapshot['cashflow']['monthly_surplus'])

    def test_readonly_server_and_file_isolation(self):
        self.cli('init-demo')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'wealthos', '--data', str(self.data), 'serve', '--port', str(port)],
                                   cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        base = f'http://127.0.0.1:{port}'
        # Never use user's outbound proxy for local test traffic.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                response = opener.open(base + '/api/snapshot', timeout=1)
                break
            except (urllib.error.URLError, TimeoutError): time.sleep(.05)
        else: self.fail('server failed to start')
        with response:
            self.assertEqual(json.load(response)['net_worth'], 90000)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with opener.open(base) as response: self.assertIn('Wealth OS', response.read().decode())
        for path in ('/events.jsonl', '/data/profile.json', '/../README.md'):
            with self.assertRaises(urllib.error.HTTPError) as error: opener.open(base + path)
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as error:
            opener.open(urllib.request.Request(base + '/api/snapshot', headers={'Host': 'untrusted.example'}))
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as error:
            opener.open(urllib.request.Request(base + '/api/snapshot', data=b'{}', method='POST'))
        self.assertEqual(error.exception.code, 501)
        process.terminate(); process.wait(timeout=5)


if __name__ == '__main__': unittest.main()
