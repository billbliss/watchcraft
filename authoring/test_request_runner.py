import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from request_runner import run_request_planner


class RequestRunnerTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(operator_token_source="auto", poll_seconds=2, once=True, max_videos=500, timeout_seconds=900, r2_credentials_source="auto")

    def test_one_queued_request_is_prepared_and_runner_disconnects(self):
        q = Mock()
        q.operator_client.return_value.post.return_value = {"requests": [{"request_id": "video-request", "expected_revision": 2}]}
        prepare = Mock(return_value=0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run_request_planner(self.args(), q, prepare=prepare), 0)
        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.args[0].request_id, "video-request")
        self.assertEqual(prepare.call_args.args[0].expected_revision, 2)
        self.assertEqual(q.operator_client.return_value.post.call_args.args[0], "/requests/disconnect")
        self.assertEqual([c.args[0] for c in q.operator_client.return_value.post.call_args_list], ["/requests/poll", "/requests/disconnect"])

    def test_no_work_does_not_launch_a_job(self):
        q = Mock()
        q.operator_client.return_value.post.return_value = {"requests": []}
        prepare = Mock()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run_request_planner(self.args(), q, prepare=prepare), 0)
        prepare.assert_not_called()

    def test_failure_is_not_retried_in_a_loop(self):
        q = Mock()
        q.operator_client.return_value.post.return_value = {"requests": [{"request_id": "video-request", "expected_revision": 2}]}
        prepare = Mock(side_effect=RuntimeError("failed"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run_request_planner(self.args(), q, prepare=prepare), 1)
        prepare.assert_called_once()

    def test_competing_runner_cannot_start_preparation(self):
        q = Mock()
        q.operator_client.return_value.post.side_effect = RuntimeError("Another planner")
        prepare = Mock()
        with self.assertRaisesRegex(RuntimeError, "Another planner"):
            run_request_planner(self.args(), q, prepare=prepare)
        prepare.assert_not_called()
