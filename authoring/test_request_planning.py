import argparse
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import queued_authoring as q
import request_planning as p

VIDEO = "PjObX9XQvgI"
URL = f"https://www.youtube.com/watch?v={VIDEO}"
REQUEST = {"_id": "request123", "revision": 2, "state": "planning", "updated_at": 1000,
           "source": {"url": URL, "videoId": VIDEO}, "title": "Video", "channel": "Publisher",
           "selected_scope": "video", "options": [{"scope": "video", "targetUrl": URL}]}
VIDEO_DATA = {"video_id": VIDEO, "url": URL, "title": "Video", "publisher": "Publisher", "duration_seconds": 60}


class RequestPlanningTests(unittest.TestCase):
    def test_exact_single_video_project_is_valid(self):
        ids = p.request_members(REQUEST, 500)
        self.assertEqual(ids, [VIDEO])
        project = p.request_project(REQUEST, [VIDEO_DATA])
        q.validate_explicit_membership_project(project)
        self.assertEqual(project["iterator"]["configuration"]["entries"][0]["duration_seconds"], 60)
        self.assertEqual(project["project_id"], "request-request123-r2")

    def test_publication_name_is_readable_and_revision_independent(self):
        request = {**REQUEST, "title": "Jeanne Bliss — Customer Experience!"}
        name = p.request_project(request, [VIDEO_DATA])["publication"]["collection_id"]
        self.assertRegex(name, r"^jeanne-bliss-customer-experience-[a-f0-9]{10}$")
        revised = {**request, "revision": 9, "_id": "another-request"}
        self.assertEqual(name, p.request_project(revised, [VIDEO_DATA])["publication"]["collection_id"])
        other = {**request, "options": [{"scope": "video", "targetUrl": "https://www.youtube.com/watch?v=abcdefghijk"}]}
        self.assertNotEqual(name, p.request_project(other, [VIDEO_DATA])["publication"]["collection_id"])
        self.assertRegex(p.publication_name(REQUEST, "你好"), r"^collection-[a-f0-9]{10}$")
        self.assertLessEqual(len(p.publication_name(REQUEST, "a" * 300)), 91)

    def test_over_limit_or_missing_anchor_never_yields_partial_plan(self):
        request = {**REQUEST, "selected_scope": "playlist", "options": [{"scope": "playlist", "targetUrl": "https://www.youtube.com/playlist?list=PL1234567890"}]}
        with patch.object(p, "discover_youtube_playlist", return_value={"video_ids": [VIDEO, "abcdefghijk"]}):
            with self.assertRaisesRegex(ValueError, "no partial plan"):
                p.request_members(request, 1)
        with patch.object(p, "discover_youtube_playlist", return_value={"video_ids": ["abcdefghijk"]}):
            with self.assertRaisesRegex(ValueError, "no longer in this scope"):
                p.request_members(request, 500)

    def test_popular_follows_explicit_control(self):
        data = {"chipViewModel": {"text": {"simpleText": "Popular"}, "tapCommand": {"innertubeCommand": {"continuationCommand": {"token": "popular"}}}}, "videoRenderer": {"videoId": "abcdefghijk"}}
        page = 'var ytInitialData = ' + json.dumps(data) + '; "INNERTUBE_CLIENT_VERSION":"test"'
        with patch.object(p, "request_text", return_value=page), patch.object(p, "request_json", return_value={"lockupViewModel": {"contentType": "LOCKUP_CONTENT_TYPE_VIDEO", "contentId": VIDEO}}) as fetch:
            self.assertEqual(p.channel_members("https://www.youtube.com/@CustomerBliss", True), [VIDEO])
            self.assertEqual(fetch.call_args.args[1]["continuation"], "popular")
        with patch.object(p, "request_text", return_value='var ytInitialData = {"videoRenderer":{"videoId":"abcdefghijk"}};'):
            with self.assertRaisesRegex(ValueError, "could not be verified"):
                p.channel_members("https://www.youtube.com/@CustomerBliss", True)

    def test_channel_resolves_uploads_playlist(self):
        channel_id = "UC" + "a" * 22
        page = 'var ytInitialData = ' + json.dumps({"channelMetadataRenderer": {"externalId": channel_id}}) + ';'
        with patch.object(p, "request_text", return_value=page), patch.object(p, "discover_youtube_playlist", return_value={"video_ids": [VIDEO]}) as discover:
            self.assertEqual(p.channel_members("https://www.youtube.com/@CustomerBliss", False), [VIDEO])
            discover.assert_called_once_with("UU" + "a" * 22)

    def test_preparation_only_dispatches_discovery_and_plan_and_leaves_execution_unapproved(self):
        project = p.request_project(REQUEST, [VIDEO_DATA])
        accepted = copy.deepcopy(project)
        accepted["revision"] = 2
        accepted["iterator"]["accepted_snapshot"] = {"digest": "x"}
        control = Mock()
        def post(path, payload):
            if path == "/requests/get": return REQUEST
            if path == "/projects/accept-snapshot": return {"project": accepted}
            if path == "/submissions/approve": return {"job": {"job_id": payload["job_id"], "state": "ready"}}
            return {}
        control.post.side_effect = post
        adapter = Mock()
        adapter.operator_client.return_value = control
        adapter.explicit_membership_iterator_spec.return_value = {"handler": {"id": "watchcraft.explicit-membership"}}
        adapter.project_processing_plan_spec.return_value = {"handler": {"id": "watchcraft.plan"}}
        adapter.submit_spec.side_effect = [{"job": {"job_id": name, "revision": 1, "spec_sha256": "a"}} for name in ["iterate", "plan"]]
        adapter.wait_for_terminal_job.side_effect = [{"job": {"job_id": name}} for name in ["iterate", "plan"]]
        adapter.verified_json_result_bytes.return_value = ({}, b"{}")
        adapter.create_pending_project_execution.return_value = {"execution": {"execution_id": "execution"}}
        args = argparse.Namespace(request_id="request123", expected_revision=2, operator_token_source="auto", r2_credentials_source="auto", timeout_seconds=900, max_videos=500)
        with patch.object(p, "discover_youtube_video", return_value=VIDEO_DATA), redirect_stdout(io.StringIO()):
            self.assertEqual(p.prepare_request(args, adapter), 0)
        paths = [call.args[0] for call in control.post.call_args_list]
        self.assertNotIn("/project-executions/approve", paths)
        self.assertEqual(paths[-1], "/requests/progress")
        self.assertEqual(adapter.create_pending_project_execution.call_args.args[1].request_args["expected_revision"], 2)
        self.assertEqual(adapter.dispatch_submission.call_count, 2)
        self.assertEqual(adapter.create_pending_project_execution.call_args.args[1].process_all, True)

    def test_failed_metadata_never_imports_or_approves_work(self):
        control = Mock()
        control.post.side_effect = lambda path, payload: REQUEST if path == "/requests/get" else {}
        adapter = Mock()
        adapter.operator_client.return_value = control
        args = argparse.Namespace(request_id="request123", expected_revision=2, operator_token_source="auto", r2_credentials_source="auto", timeout_seconds=900, max_videos=500)
        with patch.object(p, "discover_youtube_video", side_effect=RuntimeError("unavailable")), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                p.prepare_request(args, adapter)
        self.assertEqual(control.post.call_args.args[1]["stage"], "failed")
        adapter.submit_spec.assert_not_called()
        self.assertNotIn("/projects/import", [call.args[0] for call in control.post.call_args_list])


if __name__ == "__main__":
    unittest.main()
