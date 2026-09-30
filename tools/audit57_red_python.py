"""Run current causal Engine tests on the delivered old source, requiring real assertions."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'a983ee1293647e2d312c55af13bd14c0b1723a8e'
CASES = (
    'test_fresh_micro_sequence_opens_first_buy_and_sell_away_from_old_levels',
    'test_one_two_three_positions_have_new_events_and_fixed_initial_forecast',
    'test_resumption_tick_can_itself_cross_the_observed_micro_level',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline = subprocess.check_output(['git', 'rev-parse', args.baseline], cwd=ROOT, text=True).strip()
    with tempfile.TemporaryDirectory(prefix='r57-old-engine-') as directory:
        old = Path(directory)
        archive = old / 'source.zip'
        subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(archive), baseline, 'mt5_bridge'], cwd=ROOT, check=True)
        with zipfile.ZipFile(archive) as source:
            source.extractall(old)
        runner = '''import json,sys,unittest
from pathlib import Path
names=json.loads(sys.argv[1])
suite=unittest.TestLoader().loadTestsFromNames(['test_r57_scalp.FastScalpTests.'+name for name in names])
result=unittest.TextTestRunner(verbosity=2).run(suite)
failed=[test.id() for test,trace in result.failures]
assert result.testsRun==len(names),(result.testsRun,names)
assert not result.errors,[(test.id(),trace) for test,trace in result.errors]
assert not result.skipped,result.skipped
assert all(any(name in failure for failure in failed) for name in names),failed
assert all('AssertionError:' in trace for test,trace in result.failures),result.failures
Path(sys.argv[2]).write_text(json.dumps(dict(baseline=sys.argv[3],tests_run=result.testsRun,
    assertion_failures=len(result.failures),errors=len(result.errors),failed_cases=failed),indent=2)+'\\n')
print('R57_RED_PYTHON_CONFIRMED',sys.argv[3],result.testsRun,len(result.failures))
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join((str(old / 'mt5_bridge'), str(ROOT / 'tests/event_core'), env.get('PYTHONPATH', '')))
        import json
        result = subprocess.run([sys.executable, '-c', runner, json.dumps(CASES),
                                 str(args.output.resolve() / 'R57_RED_PYTHON.json'), baseline],
                                cwd=old, env=env, capture_output=True, text=True)
        log = result.stdout + result.stderr
        (args.output / 'R57_RED_PYTHON.log').write_text(log, encoding='utf-8')
        print(log, end='')
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
