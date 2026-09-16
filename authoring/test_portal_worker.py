import argparse
import unittest
from unittest.mock import Mock, patch
from portal_worker import perform_phase, run_portal_worker, submit_pull_request

class PortalWorkerTests(unittest.TestCase):
    def config(self):
        return argparse.Namespace(operator_token_source='auto', r2_credentials_source='auto', r2_staging_credentials_source='auto', poll_seconds=2, once=True)
    def work(self, phase='processing'):
        return dict(execution_id='approved', phase=phase, execution=dict(plan=dict(job_id='plan'), estimate=dict(planned_items=1), selection=dict(item_ids=['a'])))
    def test_idle_never_processes(self):
        q, perform = Mock(), Mock()
        q.operator_client.return_value.post.return_value = dict(workflow=None)
        self.assertEqual(run_portal_worker(self.config(), q, perform=perform), 0)
        perform.assert_not_called()
    def test_success_advances_only_claimed_phase(self):
        q, perform = Mock(), Mock(return_value={})
        q.operator_client.return_value.post.side_effect = [dict(workflow=self.work()), dict(updated=True)]
        self.assertEqual(run_portal_worker(self.config(), q, perform=perform), 0)
        self.assertEqual(q.operator_client.return_value.post.call_args.args[1]['event'], 'complete')
        perform.assert_called_once()
    def test_failure_stops_for_explicit_retry(self):
        q = Mock()
        q.operator_client.return_value.post.side_effect = [dict(workflow=self.work()), dict(updated=True)]
        self.assertEqual(run_portal_worker(self.config(), q, perform=Mock(side_effect=RuntimeError('failed'))), 1)
        self.assertEqual(q.operator_client.return_value.post.call_args.args[1]['event'], 'failed')
    def test_partial_approval_cannot_assemble_unapproved_items(self):
        work = self.work('compilation')
        work['execution']['estimate']['planned_items'] = 2
        q = Mock()
        with self.assertRaisesRegex(RuntimeError, 'only the approved'):
            perform_phase(work, self.config(), q)
        q.run_compile_project.assert_not_called()
    def test_compilation_records_verified_job(self):
        q = Mock()
        q.run_compile_project.side_effect = lambda args, completed_callback: completed_callback('compiled')
        self.assertEqual(perform_phase(self.work('compilation'), self.config(), q), dict(compilation_job_id='compiled'))
    @patch('portal_worker.command')
    def test_pr_retry_reuses_existing_pr(self, command):
        command.return_value = '[{"url":"https://github.com/billbliss/watchcraft-collections/pull/42","headRefOid":"abc"}]'
        result = submit_pull_request(dict(preview_branch='codex/portal-'+'a'*24, preview_commit='abc'))
        self.assertTrue(result['pull_request_url'].endswith('/42'))
        self.assertEqual(command.call_count, 1)
    @patch('portal_worker.command')
    def test_changed_branch_cannot_create_pr(self, command):
        command.side_effect = ['[]', 'different']
        with self.assertRaisesRegex(RuntimeError, 'changed after validation'):
            submit_pull_request(dict(preview_branch='codex/portal-'+'a'*24, preview_commit='abc'))
        self.assertEqual(command.call_count, 2)

    @patch('youtube_discovery.request_text')
    @patch('portal_worker.command')
    def test_preview_uses_isolated_checkout_and_verifies_resources(self, command, request_text):
        import json
        from pathlib import Path
        from portal_worker import publish_preview
        manifest = dict(collection_id='example', title='Example', items={'a': {'analysis': {'path': 'analyses/a.json'}}})
        analysis = dict(topics=[])
        def commands(args, cwd=None):
            if args[:3] == ['gh', 'repo', 'view']:
                return json.dumps(dict(defaultBranchRef=dict(name='main'), isPrivate=False))
            if args[:2] == ['git', 'clone']:
                Path(args[-1]).mkdir()
            if args[:2] == ['git', 'rev-parse']:
                return 'a'*40
            return ''
        command.side_effect = commands
        request_text.side_effect = [json.dumps(manifest), json.dumps(analysis)]
        q = Mock()
        q.operator_client.return_value.post.return_value = {"job": {}}
        q.verified_json_result.return_value = dict(manifest=manifest)
        def materialize(args):
            args.output_directory.mkdir()
            (args.output_directory / 'analyses').mkdir()
            (args.output_directory / 'collection.json').write_text(json.dumps(manifest))
            (args.output_directory / 'analyses/a.json').write_text(json.dumps(analysis))
        q.run_materialize_project.side_effect = materialize
        work = {**self.work('preview'), 'compilation_job_id': 'compiled'}
        result = publish_preview(work, self.config(), q)
        self.assertIn('/'+'a'*40+'/collections/example/', result['preview_url'])
        self.assertFalse(q.run_publish_project.call_args.args[0].collections_root.exists())
        self.assertFalse(any(call.args[0][:3] == ['gh', 'pr', 'create'] for call in command.call_args_list))
        self.assertEqual(request_text.call_count, 2)
        request_text.side_effect = [json.dumps(manifest), '{"wrong":true}']
        with self.assertRaisesRegex(RuntimeError, 'resource does not match'):
            publish_preview(work, self.config(), q)

    @patch('youtube_discovery.request_text')
    @patch('portal_worker.command')
    def test_new_pr_describes_collection_and_links_to_playable_preview(self, command, request_text):
        import json
        from pathlib import Path
        manifest = {'title': 'GDC — Popular videos', 'items': {str(i): {'title': f'Talk {i}'} for i in range(20)},
                    'source': {'canonical_url': 'https://www.youtube.com/@Gdconf', 'metadata': {'publisher': 'GDC'}},
                    'topics': {'a': {}}, 'topic_families': {'b': {}}}
        request_text.return_value = json.dumps(manifest)
        head = 'a' * 40
        preview = f'https://raw.githubusercontent.com/billbliss/watchcraft-collections/{head}/collections/gdc/collection.json'
        def run(args, cwd=None):
            if args[:3] == ['gh', 'pr', 'list']: return '[]'
            if args[:2] == ['gh', 'api']: return head
            if args[:3] == ['gh', 'repo', 'view']: return 'main'
            self.assertEqual(args[:3], ['gh', 'pr', 'create'])
            self.assertEqual(args[args.index('--title')+1], 'Add collection: GDC — Popular videos')
            body = Path(args[args.index('--body-file')+1]).read_text()
            self.assertIn('**Videos:** 20', body)
            self.assertIn('**Publisher:** GDC', body)
            self.assertIn('https://www.youtube.com/@Gdconf', body)
            self.assertIn('https://watchcraft.stream/app/?catalog=https%3A', body)
            self.assertIn('…and 15 more', body)
            self.assertGreater(body.index('execution-secret-id'), body.index('<details>'))
            return 'https://github.com/billbliss/watchcraft-collections/pull/3'
        command.side_effect = run
        submit_pull_request({'preview_branch': 'codex/portal-'+'b'*24, 'preview_commit': head,
                             'preview_url': preview, 'execution_id': 'execution-secret-id'})
