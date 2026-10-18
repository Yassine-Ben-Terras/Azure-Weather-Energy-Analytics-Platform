import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import deploy_release as release

IMAGE = 'example.azurecr.io/airflow@sha256:' + 'a' * 64
API_IMAGE = 'example.azurecr.io/api@sha256:' + 'b' * 64


class DeploymentTests(unittest.TestCase):
    def test_rejects_mutable_image_tags(self):
        with self.assertRaises(ValueError):
            release.require_digest('example.azurecr.io/airflow:latest')
        self.assertEqual(release.require_digest(IMAGE), IMAGE)

    def test_unhealthy_revision_is_not_success(self):
        with patch.object(release, 'az', return_value={'properties': {'provisioningState': 'Failed'}}):
            with self.assertRaises(RuntimeError):
                release.wait_ready('rg', 'scheduler', IMAGE)

    def test_preflight_blocks_active_job_before_any_update(self):
        calls = []
        def fake(*args):
            calls.append(args)
            if 'execution' in args:
                return [{'properties': {'status': 'Running'}}]
            return {'properties': {'template': {'containers': [{'image': 'old'}]}}}
        with patch.dict(os.environ, AZURE_RESOURCE_GROUP='rg', APP_PREFIX='test', AIRFLOW_IMAGE=IMAGE, API_IMAGE=API_IMAGE):
            with patch.object(release, 'az', side_effect=fake):
                with self.assertRaises(RuntimeError):
                    release.main()
        self.assertFalse(any('update' in call for call in calls))

    def test_failed_rollout_preserves_previous_images(self):
        def fake(*args):
            if 'execution' in args:
                return []
            if 'update' in args:
                raise RuntimeError('simulated deployment failure')
            return {'properties': {'template': {'containers': [{'image': 'old-image'}]}}}
        with tempfile.TemporaryDirectory() as directory:
            original = Path.cwd()
            try:
                os.chdir(directory)
                with patch.dict(os.environ, AZURE_RESOURCE_GROUP='rg', APP_PREFIX='test', AIRFLOW_IMAGE=IMAGE, API_IMAGE=API_IMAGE):
                    with patch.object(release, 'az', side_effect=fake):
                        with self.assertRaises(RuntimeError):
                            release.main()
                data = json.loads(Path('release-record.json').read_text())
                self.assertEqual(data['status'], 'failed-keep-airflow-paused')
                self.assertEqual(len(data['workloads']), 5)
                self.assertTrue(all(x['previous_image'] == 'old-image' for x in data['workloads']))
            finally:
                os.chdir(original)


if __name__ == '__main__':
    unittest.main()
