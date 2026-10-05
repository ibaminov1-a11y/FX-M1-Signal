"""Stdlib Windows preflight and read-only diagnosis; never initializes MT5.

The server inherits the console, because its pairing key must never be copied
into a log. Only this helper's structured, sanitized results are persisted.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys


def environment_report():
    python = dict(version=list(sys.version_info[:3]), bits=struct.calcsize('P') * 8,
                  platform=sys.platform)
    python['supported'] = (python['version'] >= [3, 10, 0]
                           and python['bits'] == 64 and python['platform'] == 'win32')
    dependencies = {}
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name, attributes in (
            ('flask', ('Flask',)), ('MetaTrader5', ('initialize',)),
            ('colorama', ('AnsiToWin32',)), ('event_core', ('VERSION', 'BUILD', 'REVISION')),
            ('bridge_v10_0', ('main',)),
        ):
            try:
                # Import errors may contain private paths/credentials. Record only type.
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    module = importlib.import_module(name)
                if not all(hasattr(module, field) for field in attributes):
                    raise AttributeError('Incomplete module')
                dependencies[name] = 'OK'
            except Exception as exc:
                dependencies[name] = type(exc).__name__
    finally:
        sys.dont_write_bytecode = old_bytecode
    return dict(ok=python['supported'] and all(v == 'OK' for v in dependencies.values()),
                python=python, dependencies=dependencies)


def _lock_status(path):
    if not path.exists():
        return 'absent'
    try:
        # Never create, truncate or write the runtime lock during diagnosis.
        with path.open('r+b') as handle:
            if os.name == 'nt':
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return 'held'
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 'held'
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return 'free'
    except OSError:
        return 'unavailable'


def network_report(state_dir, port):
    """Collect local facts without authenticating, querying trading APIs or editing state."""
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None,
                                                                     family=socket.AF_INET)})
    except OSError:
        addresses = []
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            reachable = True
    except OSError:
        reachable = False
    report = dict(port=port, local_ipv4=addresses, localhost_reachable=reachable,
                  runtime_lock=_lock_status(Path(state_dir) / 'runtime.lock'),
                  listener_pids=[], remote_reachability='not_tested', read_only=True)
    if os.name == 'nt':
        try:
            result = subprocess.run(['netstat.exe', '-ano', '-p', 'tcp'], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=10)
            # Only include numeric owners of listeners on this port, not all network activity.
            for line in result.stdout.splitlines():
                fields = line.split()
                if (len(fields) == 5 and fields[0] == 'TCP'
                        and fields[1].rsplit(':', 1)[-1] == str(port)
                        and fields[3] == 'LISTENING' and fields[4].isdigit()):
                    report['listener_pids'].append(int(fields[4]))
            report['listener_pids'] = sorted(set(report['listener_pids']))
        except (OSError, subprocess.TimeoutExpired):
            report['listener_query'] = 'unavailable'
    return report


def _record(state_dir, message):
    try:
        directory = Path(state_dir)
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / 'bridge-startup.log', maxBytes=262144,
                                      backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        try:
            handler.emit(logging.LogRecord('bridge.startup', logging.INFO, '', 0, message, (), None))
        finally:
            handler.close()
    except OSError:
        print('Could not write bridge-startup.log; check folder write permissions.', flush=True)


def launch(root, server_args, state_dir):
    _record(state_dir, 'Starting Bridge process; console output is not recorded here')
    try:
        result = subprocess.run([sys.executable, '-u', str(Path(root) / 'bridge_v10_0.py'), *server_args],
                                cwd=root)
        code = result.returncode
    except KeyboardInterrupt:
        code = 130
    except OSError as exc:
        _record(state_dir, 'Bridge process could not start: ' + type(exc).__name__)
        code = 1
    _record(state_dir, 'Bridge process exited with code ' + str(code))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bridge startup check and read-only network diagnosis')
    parser.add_argument('--check', action='store_true', help='Check imports without starting the server')
    parser.add_argument('--diagnose', action='store_true', help='Show network/process facts without starting the server')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--state-dir', default=None)
    args, server_args = parser.parse_known_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    root = Path(__file__).resolve().parent
    state_dir = Path(args.state_dir) if args.state_dir else root / 'event_state'
    report = environment_report()
    if args.diagnose:
        # Deliberately do not write a diagnostic file or touch tokens/databases.
        print(json.dumps(dict(environment=report, network=network_report(state_dir, args.port)),
                         ensure_ascii=True, indent=2))
        print('Local reachability does not prove phone Wi-Fi/VPN/firewall reachability.')
        return 0
    summary = json.dumps(report, ensure_ascii=True, sort_keys=True)
    print('Bridge environment:', summary, flush=True)
    _record(state_dir, summary)
    if not report['ok']:
        print('Bridge did not start. Use Windows 64-bit Python 3.10+ (3.12 recommended).', flush=True)
        print('Run INSTALL_R7_3.cmd from the full package for this working Bridge folder.', flush=True)
        print('Details: event_state/bridge-startup.log. Keep .venv and event_state intact.', flush=True)
        return 1
    if args.check:
        return 0
    return launch(root, ['--host', '0.0.0.0', '--port', str(args.port), '--state-dir', str(state_dir),
                         *server_args], state_dir)


if __name__ == '__main__':
    raise SystemExit(main())
