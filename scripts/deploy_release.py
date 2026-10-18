"""Deploy image-only releases to existing Azure workloads; never run migrations.

The operator must pause and drain Airflow before dispatching the workflow.
Failure leaves Airflow paused and preserves a recovery record; no automatic rollback.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time


def az(*args):
    result = subprocess.run(
        ['az', *args, '--only-show-errors', '--output', 'json'],
        text=True, capture_output=True, timeout=600,
    )
    if result.returncode:
        # CLI responses can include configuration; avoid copying them into public logs.
        raise RuntimeError(f'Azure CLI failed for {args[0]} {args[1]}; inspect Azure activity logs.')
    return json.loads(result.stdout) if result.stdout.strip() else None


def image_of(resource):
    containers = resource['properties']['template']['containers']
    if len(containers) != 1:
        raise RuntimeError('Only single-container workloads are supported.')
    return containers[0]['image']


def require_digest(image):
    if not re.fullmatch(r'[a-z0-9.-]+\.azurecr\.io/(airflow|api)@sha256:[a-f0-9]{64}', image):
        raise ValueError('An ACR image pinned to a SHA-256 digest is required.')
    return image


def wait_ready(group, name, image, timeout=1200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app = az('containerapp', 'show', '--resource-group', group, '--name', name)
        props = app['properties']
        if props.get('provisioningState') == 'Failed':
            raise RuntimeError(f'{name}: provisioning failed; keep Airflow paused.')
        revision = props.get('latestRevisionName')
        if revision and props.get('latestReadyRevisionName') == revision and image_of(app) == image:
            data = az('containerapp', 'revision', 'show', '--resource-group', group,
                      '--name', name, '--revision', revision)
            state = data['properties']
            if state.get('healthState') == 'Healthy' and state.get('runningState') == 'Running':
                print(f'{name}: requested revision is healthy', flush=True)
                return
        time.sleep(15)
    raise TimeoutError(f'{name}: readiness timed out; keep Airflow paused and use release-record.json.')


def main():
    group = os.environ['AZURE_RESOURCE_GROUP']
    prefix = os.environ['APP_PREFIX']
    airflow = require_digest(os.environ['AIRFLOW_IMAGE'])
    api = require_digest(os.environ['API_IMAGE'])
    workloads = [('app', 'api', api), ('app', 'webserver', airflow),
                 ('app', 'scheduler', airflow), ('job', 'monitor', airflow),
                 ('job', 'bootstrap', airflow)]
    record = {'commit': os.getenv('GITHUB_SHA'), 'resource_group': group,
              'status': 'preflight', 'workloads': []}
    path = Path('release-record.json')
    # Validate every target and collect rollback references before modifying any workload.
    for kind, role, image in workloads:
        name = f'{prefix}-{role}'
        command = ['containerapp'] + (['job'] if kind == 'job' else [])
        resource = az(*command, 'show', '--resource-group', group, '--name', name)
        if kind == 'job':
            executions = az('containerapp', 'job', 'execution', 'list',
                            '--resource-group', group, '--name', name)
            if any(x['properties'].get('status') not in ('Succeeded', 'Failed', 'Stopped') for x in executions):
                raise RuntimeError(f'{name}: active or unknown job execution; wait before releasing.')
        record['workloads'].append({'kind': kind, 'name': name,
                                    'previous_image': image_of(resource), 'requested_image': image,
                                    'updated': False})
    path.write_text(json.dumps(record, indent=2))
    try:
        for item in record['workloads']:
            command = ['containerapp'] + (['job'] if item['kind'] == 'job' else [])
            az(*command, 'update', '--resource-group', group, '--name', item['name'],
               '--image', item['requested_image'])
            if item['kind'] == 'app':
                wait_ready(group, item['name'], item['requested_image'])
            else:
                actual = az(*command, 'show', '--resource-group', group, '--name', item['name'])
                if image_of(actual) != item['requested_image']:
                    raise RuntimeError(f"{item['name']}: job image verification failed")
            item['updated'] = True
            path.write_text(json.dumps(record, indent=2))
        record['status'] = 'deployed-awaiting-operator-verification'
    except Exception:
        record['status'] = 'failed-keep-airflow-paused'
        raise
    finally:
        path.write_text(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
