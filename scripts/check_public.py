#!/usr/bin/env python3
"""Privacy tripwire for versioned content. Never prints matched secret text."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {'data', 'output', 'private', 'backups', 'scratch', '.venv', 'node_modules', '__pycache__'}
PATTERNS = {
    'machine-home-path': re.compile(r'/(?:Users|home)/[a-zA-Z0-9_.-]+/'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})'),
    'api-key': re.compile(r'sk-[A-Za-z0-9_-]{24,}'),
    'aws-key': re.compile(r'AKIA[A-Z0-9]{16}'),
    'email-address': re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
}


def main():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
    files = [Path(p) for p in result.stdout.decode().split('\0') if p] if result.returncode == 0 else []
    # Fresh, not-yet-staged trees also get an initial check. Ignore only known runtime paths.
    if not files:
        files = [p.relative_to(ROOT) for p in ROOT.rglob('*') if p.is_file() and not any(part in BLOCKED | {'.git'} for part in p.relative_to(ROOT).parts)]
    findings = []
    for relative in files:
        path = ROOT / relative
        if any(part in BLOCKED for part in relative.parts) or relative.name.startswith('.env') or path.suffix in ('.db', '.sqlite', '.pem', '.key', '.pdf', '.xlsx', '.csv', '.zip'):
            findings.append((str(relative), 'private/runtime file tracked'))
            continue
        staged = subprocess.run(['git', 'show', ':' + relative.as_posix()], cwd=ROOT, capture_output=True) if result.returncode == 0 else None
        raw = staged.stdout if staged is not None and staged.returncode == 0 else path.read_bytes()
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            findings.append((str(relative), 'binary needs manual review'))
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append((str(relative), name))
    for path, rule in findings:
        print(f'FAIL {path}: {rule}')
    if findings:
        return 1
    print(f'Public-content checks passed for {len(files)} files. Review text manually for personal facts.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
