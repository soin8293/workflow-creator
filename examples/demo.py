"""Run a small fake-data workflow using native Foundry state and checks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills' / 'workflow-creator' / 'runtime'))
from workflow_foundry import SQLiteRuntime, compile_file


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def errors(case, runtime):
    inputs = next(event['payload']['inputs'] for event in runtime.events('demo')
                  if event['event_type'] == 'RUN_STARTED')
    if sha(case / 'input.json') != inputs['input_sha256']:
        return ['Input changed; preserve this run and start another case']
    try:
        source, output = read(case / 'input.json'), read(case / 'output.json')
        if not isinstance(output, dict) or set(output) != {'accepted', 'rejected', 'total'}:
            return ['Output needs accepted, rejected and total fields']
        if any(type(output[k]) is not int or output[k] < 0 for k in output):
            return ['Counts must be nonnegative integers']
        if any(output[k] != source[k] for k in ['accepted', 'rejected']):
            return ['Output counts do not match the input']
        if output['total'] != source['accepted'] + source['rejected']:
            return ['Total is wrong even though the JSON file is valid']
    except (OSError, ValueError, TypeError) as error:
        return [str(error)]
    return []


def make_report(case, bad=False):
    source = read(case / 'input.json')
    write(case / 'output.json', dict(source, total=sum(source.values()) + int(bad)))


def drive(case, runtime):
    state = runtime.get_run('demo')
    if state['current_node'] == 'check':
        failures = errors(case, runtime)
        runtime.complete_node('demo', 'fail' if failures else 'pass', state['revision'],
                              {'errors': failures, 'output_sha256': sha(case / 'output.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'status', 'repair'])
    parser.add_argument('case', type=Path)
    parser.add_argument('--bad-output', action='store_true')
    args = parser.parse_args()
    case = args.case.resolve()
    if case == ROOT or ROOT in case.parents:
        raise ValueError('Choose a case folder outside this source repo')
    if args.action == 'run':
        if case.exists():
            raise ValueError('Case already exists; use status or choose a new folder')
        case.mkdir(parents=True)
        write(case / 'input.json', {'accepted': 2, 'rejected': 1})
        write(case / 'progress.agent.json', {'about': 'Fake-data example progress only',
              'writes': 'Only native SQLiteRuntime through demo.py; no direct SQL'})
        runtime = SQLiteRuntime(case / 'progress.sqlite')
        state = runtime.start_run(compile_file(ROOT / 'examples' / 'workflow.json'), 'demo',
                                  {'input_sha256': sha(case / 'input.json')})
        make_report(case, args.bad_output)
        runtime.complete_node('demo', 'success', state['revision'])
        drive(case, runtime)
    else:
        if not (case / 'progress.sqlite').is_file():
            raise ValueError('No saved case at this path')
        runtime = SQLiteRuntime(case / 'progress.sqlite')
        if args.action == 'repair':
            state = runtime.get_run('demo')
            if state['current_node'] != 'repair':
                raise ValueError('Repair is not allowed at this step')
            make_report(case)
            runtime.resume_wait('demo', 'repair.reported', 'count-report', 'approved', state['revision'],
                                {'actor': 'demo-script', 'evidence': [{'kind': 'repair'}]})
            drive(case, runtime)
    print(json.dumps({'run': runtime.get_run('demo'), 'validation_errors': errors(case, runtime),
                      'replay_matches': runtime.replay('demo')['matches_projection']}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
