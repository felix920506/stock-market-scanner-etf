#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(SCRIPT_DIR, 'run_market_scanner_deterministic.py')


def main():
    parser = argparse.ArgumentParser(description='Resend a staged market scanner report via webhook only')
    parser.add_argument('temp_dir', help='Existing temp run directory containing stages/02-report.txt')
    args = parser.parse_args()

    temp_dir = os.path.abspath(args.temp_dir)
    stage_dir = os.path.join(temp_dir, 'stages')
    report_txt = os.path.join(stage_dir, '02-report.txt')
    meta_json = os.path.join(stage_dir, '00-meta.json')

    if not os.path.exists(report_txt):
        raise SystemExit(f'Missing staged report: {report_txt}')

    cmd = [sys.executable, RUNNER, '--reuse-temp-dir', temp_dir, '--delivery-only', '--keep-temp']
    proc = subprocess.run(cmd, capture_output=True, text=True)

    result = {
        'temp_dir': temp_dir,
        'stage_dir': stage_dir,
        'report_txt': report_txt,
        'meta_json_exists': os.path.exists(meta_json),
        'returncode': proc.returncode,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


if __name__ == '__main__':
    main()
