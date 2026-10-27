"""Portable launcher for the bundled, unchanged Workflow Foundry 0.2.0 runtime."""
import json
from pathlib import Path
import sys
import tempfile

RUNTIME_HOME = Path(__file__).resolve().parents[1] / 'runtime'
sys.path.insert(0, str(RUNTIME_HOME))


def self_test():
    from workflow_foundry import SQLiteRuntime, RevisionConflict, compile_workflow

    graph = compile_workflow({
        'schema_version': 'workflow_foundry_v0',
        'workflow_id': 'installation_smoke', 'definition_version': '1.0.0',
        'objective': 'Verify native persisted state, revision fencing and replay offline.',
        'entry': 'check', 'terminal_nodes': ['done', 'failed'],
        'policies': {'max_steps': 3, 'worker_protocol_required': False},
        'nodes': [
            {'id': 'check', 'kind': 'activity', 'routes': {'success': 'done', 'error': 'failed'}},
            {'id': 'done', 'kind': 'terminal', 'outcome': 'passed'},
            {'id': 'failed', 'kind': 'terminal', 'outcome': 'failed'}]})
    with tempfile.TemporaryDirectory(prefix='workflow-creator-check-') as tmp:
        db = Path(tmp) / 'smoke.sqlite'
        runtime = SQLiteRuntime(db)
        initial = runtime.start_run(graph, 'check')
        completed = runtime.complete_node('check', 'success', initial['revision'])
        if completed['terminal_outcome'] != 'passed':
            raise RuntimeError('Native transition did not complete')
        reopened = SQLiteRuntime(db)
        if reopened.get_run('check')['revision'] != completed['revision']:
            raise RuntimeError('Saved state did not reopen')
        try:
            reopened.complete_node('check', 'success', initial['revision'])
        except RevisionConflict:
            pass
        else:
            raise RuntimeError('Stale revision was accepted')
        if not reopened.replay('check')['matches_projection']:
            raise RuntimeError('Native replay does not match saved state')
    print(json.dumps({'ok': True, 'runtime_version': '0.2.0',
                      'checks': ['native compile', 'transition', 'reopen', 'stale revision', 'replay']}))


if __name__ == '__main__':
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or newer is required')
    if sys.argv[1:] == ['--self-test']:
        self_test()
    else:
        from workflow_foundry.cli import main
        main()
