"""Run `python3 -m wealthos --help`. No third-party dependencies."""
import argparse
import json
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import VERSION, append_event, atomic_json, load, project, read_inputs, report, scenario

REPO = Path(__file__).resolve().parents[1]


def initialize(root, demo):
    root = Path(root)
    if root.exists():
        raise ValueError('destination already exists; choose a new --data path to preserve your records')
    root.parent.mkdir(parents=True, exist_ok=True)
    if demo:
        shutil.copytree(REPO / 'examples/demo', root)
    else:
        root.mkdir()
        atomic_json(root / 'profile.json', dict(schema=VERSION, mode='personal', base_currency='CNY',
                    monthly_income=None, monthly_expenses=None, emergency_months=None, accounts={}, assets={}))
        atomic_json(root / 'opening.json', {'as_of': '2026-01-01T00:00:00+00:00', 'confirmed': False, 'positions': []})
        atomic_json(root / 'prices.json', {'quotes': {}, 'fx': {}})
        atomic_json(root / 'plan.json', {'status': 'draft', 'targets': {}, 'goals': []})
        (root / 'events.jsonl').touch()
    print(f'Initialized {"fictional demo" if demo else "empty personal workspace"}: {root}')


def serve(root, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Only explicitly allowlisted resources. Never expose ledger files or repository root.
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                self.send_error(403, 'Unexpected Host')
                return
            route = urlsplit(self.path).path
            try:
                if route == '/api/snapshot':
                    body = json.dumps(project(read_inputs(root)), ensure_ascii=False, allow_nan=False).encode()
                    mime = 'application/json; charset=utf-8'
                elif route in ('/', '/app.js', '/style.css'):
                    file = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[route]
                    body = (REPO / 'web' / file).read_bytes()
                    mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[route] + '; charset=utf-8'
                else:
                    self.send_error(404)
                    return
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.send_error(422, 'Invalid workspace; run validate in terminal')
                print(f'Workspace error: {exc}', file=sys.stderr)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
    project(read_inputs(root))
    print(f'Local dashboard: http://127.0.0.1:{port} (Ctrl+C to stop)', flush=True)
    with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/local', help='private local input directory (before subcommand)')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init-demo', help='copy fictional examples, never overwrite')
    sub.add_parser('init', help='create empty personal workspace')
    sub.add_parser('validate', help='validate schema and event-boundary balances')
    snap = sub.add_parser('snapshot', help='print canonical read model'); snap.add_argument('--at')
    out = sub.add_parser('export', help='write derived JSON and Markdown'); out.add_argument('--output', default='output/local')
    sub.add_parser('report', help='print a concise Markdown review')
    add = sub.add_parser('add-event', help='append an evidence-backed event'); add.add_argument('--file', required=True); add.add_argument('--confirm', action='store_true')
    server = sub.add_parser('serve', help='read-only loopback dashboard'); server.add_argument('--port', type=int, default=8787)
    sim = sub.add_parser('scenario', help='hypothetical compounding, not a forecast')
    sim.add_argument('--initial', required=True); sim.add_argument('--monthly', required=True)
    sim.add_argument('--annual-return', required=True); sim.add_argument('--years', type=int, required=True)
    args = parser.parse_args(argv)
    root = Path(args.data).resolve()
    try:
        if args.command in ('init-demo', 'init'):
            initialize(root, args.command == 'init-demo')
        elif args.command == 'serve':
            if not 1024 <= args.port <= 65535:
                raise ValueError('port must be between 1024 and 65535')
            serve(root, args.port)
        elif args.command == 'add-event':
            print(json.dumps(append_event(root, load(args.file), args.confirm), ensure_ascii=False))
        elif args.command == 'scenario':
            print(json.dumps(scenario(args.initial, args.monthly, args.annual_return, args.years), ensure_ascii=False, indent=2))
        else:
            data = read_inputs(root)
            snapshot = project(data, getattr(args, 'at', None))
            if args.command == 'validate':
                from .core import timestamp
                for when in sorted({e['occurred_at'] for e in data['events']}, key=timestamp):
                    project(data, when)
                print(f'Valid workspace; {len(data["events"])} journal records; {len(snapshot["gaps"])} valuation gaps; mode={snapshot["mode"]}')
            elif args.command == 'snapshot':
                print(json.dumps(snapshot, ensure_ascii=False, indent=2))
            elif args.command == 'report':
                print(report(snapshot))
            elif args.command == 'export':
                output = Path(args.output).resolve()
                # Prevent accidentally overwriting authoritative input files.
                if output == root or root in output.parents:
                    raise ValueError('export output must be outside the input directory')
                atomic_json(output / 'snapshot.json', snapshot)
                (output / 'report.md').write_text(report(snapshot), encoding='utf-8')
                print(f'Exported derived snapshot and report: {output}')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
