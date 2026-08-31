import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import video_catalog
from analyze_catalog import (
    ApproximateDate,
    FeaturedTechnique,
    GeneratedAnalysis,
    GeneratedTimeline,
    Location,
    Section,
    analysis_with_publisher_chapters,
    analysis_path,
    analyze_state,
    request_timeline_repair,
    transcript_has_timeline_evidence,
)
from build_collection import (
    build_collection_manifest,
    build_topic_chapter_map,
    render_csv,
    update_collection_directory,
    write_collection,
)
from chunked_download import chunk_plan
from normalize_topics import (
    DisplayLabelBatchError,
    DisplayLabelDecision,
    GeneratedDisplayLabels,
    alias_candidates,
    build_parser as build_normalization_parser,
    deterministic_display_label,
    display_label_error,
    finalize_canonical_assignments,
    label_batch,
    load_state,
    make_related_symmetric,
    mechanically_equivalent,
    topic_inventory,
)
from process_catalog import select_work
from repair_timelines import pending_repairs
from watchcraft_author import (
    CategoryProposal,
    YouTubeCaptionsUnavailable,
    YouTubeIpBlocked,
    build_parser as build_authoring_parser,
    collection_directory_categories,
    create_playlist_collection,
    ensure_collection_category,
    import_youtube,
    import_youtube_playlist,
    process_and_normalize_collection,
    request_collection_category,
    youtube_description_chapters,
    youtube_playlist,
    youtube_playlist_id,
    youtube_transcript,
    youtube_transcript_client,
    youtube_video_id,
)


class FormattingTests(unittest.TestCase):
    def test_collection_create_command_parses_generation_options(self):
        args = build_authoring_parser().parse_args(
            [
                "collection",
                "create",
                "--from-youtube-playlist",
                "https://www.youtube.com/playlist?list=PL1234567890_example",
                "--collections-repo",
                "/tmp/watchcraft-collections",
                "--slug",
                "useful-lessons",
                "--exclude",
                "PjObX9XQvgI",
                "--skip-missing-captions",
                "--import-only",
                "--unlisted",
            ]
        )
        self.assertEqual(args.command, "collection")
        self.assertEqual(args.collection_command, "create")
        self.assertEqual(args.slug, "useful-lessons")
        self.assertEqual(args.exclude, ["PjObX9XQvgI"])
        self.assertTrue(args.skip_missing_captions)
        self.assertTrue(args.import_only)
        self.assertTrue(args.unlisted)
        self.assertIsNone(args.category)
        self.assertEqual(args.normalization_batch_size, 40)

    def test_collection_directory_lists_new_collection_and_preserves_description(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            workspace = repo / "collections" / "useful-lessons"
            workspace.mkdir(parents=True)
            (repo / "site").mkdir()
            directory_path = repo / "site" / "collections.json"
            directory_path.write_text(
                json.dumps({
                    "kind": "watchcraft.collection-directory",
                    "schema_version": 1,
                    "base_url": "https://example.com/library",
                    "collections": [],
                }),
                encoding="utf-8",
            )
            manifest = {
                "collection_id": "useful-lessons",
                "title": "Useful Lessons",
                "description": "Generated description.",
                "items": {
                    "lesson": {"media": [{"delivery": "remote"}]},
                },
            }
            (workspace / "watchcraft-authoring.json").write_text(
                json.dumps({
                    "kind": "watchcraft.authoring",
                    "schema_version": 1,
                    "collection": {"category": "Video Editing"},
                    "sources": {},
                }),
                encoding="utf-8",
            )

            update_collection_directory(workspace, manifest)
            entry = json.loads(directory_path.read_text())["collections"][0]
            self.assertEqual(entry["media_modes"], ["remote"])
            self.assertEqual(entry["category"], "Video Editing")
            self.assertEqual(
                entry["manifest_url"],
                "https://example.com/library/collections/useful-lessons/collection.json",
            )
            entry["description"] = "Hand-edited description."
            directory_path.write_text(
                json.dumps({
                    "kind": "watchcraft.collection-directory",
                    "schema_version": 1,
                    "base_url": "https://example.com/library",
                    "collections": [entry],
                }),
                encoding="utf-8",
            )
            manifest["title"] = "Better Lessons"
            update_collection_directory(workspace, manifest)
            updated = json.loads(directory_path.read_text())["collections"][0]
            self.assertEqual(updated["title"], "Better Lessons")
            self.assertEqual(updated["description"], "Hand-edited description.")

    def test_collection_category_reuses_existing_case_insensitively(self):
        client = Mock()
        client.responses.parse.return_value.output_parsed = CategoryProposal(
            category="video editing",
            rationale="The lessons teach a video editor.",
        )

        category, reused = request_collection_category(
            client,
            model="test-model",
            collection={"title": "Learn an Editor"},
            sources={"one.youtube": {"title": "Editing lesson"}},
            existing_categories=["Image Editing", "Video Editing"],
            retries=0,
        )

        self.assertEqual(category, "Video Editing")
        self.assertTrue(reused)

    def test_collection_category_reports_when_an_explicit_category_is_new(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            workspace = repo / "collections" / "garden-lessons"
            workspace.mkdir(parents=True)
            (repo / "site").mkdir()
            (repo / "site" / "collections.json").write_text(
                json.dumps({
                    "collections": [
                        {"collection_id": "cooking", "category": "Cooking"},
                        {"collection_id": "music", "category": "Music"},
                    ]
                }),
                encoding="utf-8",
            )
            (workspace / "watchcraft-authoring.json").write_text(
                json.dumps({
                    "kind": "watchcraft.authoring",
                    "schema_version": 1,
                    "collection": {"title": "Garden Lessons"},
                    "sources": {},
                }),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                unlisted=False,
                category="Gardening",
                timeout=30,
                analysis_model="test-model",
                retries=0,
            )
            output = io.StringIO()

            with redirect_stdout(output):
                chosen = ensure_collection_category(repo, workspace, args)

            self.assertEqual(chosen, "Gardening")
            self.assertIn("category: Gardening (new category)", output.getvalue())
            config = json.loads(
                (workspace / "watchcraft-authoring.json").read_text()
            )
            self.assertEqual(config["collection"]["category"], "Gardening")
            self.assertEqual(
                collection_directory_categories(repo),
                ["Cooking", "Music"],
            )

    def test_collection_directory_removes_explicitly_unlisted_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            workspace = repo / "collections" / "private-lessons"
            workspace.mkdir(parents=True)
            (repo / "site").mkdir()
            (workspace / "watchcraft-authoring.json").write_text(
                json.dumps({"collection": {"listed": False}}), encoding="utf-8"
            )
            directory_path = repo / "site" / "collections.json"
            directory_path.write_text(
                json.dumps({
                    "base_url": "https://example.com",
                    "collections": [{"collection_id": "private-lessons"}],
                }),
                encoding="utf-8",
            )

            update_collection_directory(
                workspace,
                {"collection_id": "private-lessons", "title": "Private Lessons"},
            )

            self.assertEqual(
                json.loads(directory_path.read_text())["collections"], []
            )

    @patch("watchcraft_author.run_topic_normalization", return_value=0)
    @patch("watchcraft_author.process_workspace", return_value=0)
    def test_collection_pipeline_normalizes_after_resumable_analysis(
        self, process_workspace_mock, normalize_mock
    ):
        args = build_authoring_parser().parse_args(
            [
                "collection",
                "create",
                "--from-youtube-playlist",
                "https://www.youtube.com/playlist?list=PL1234567890_example",
                "--collections-repo",
                "/tmp/watchcraft-collections",
            ]
        )
        workspace = Path("/tmp/watchcraft-collections/collections/useful-lessons")

        self.assertEqual(process_and_normalize_collection(workspace, args), 0)

        process_args = process_workspace_mock.call_args.args[0]
        normalization_args = normalize_mock.call_args.args[0]
        self.assertEqual(process_args.workspace, workspace)
        self.assertTrue(process_args.defer_build)
        self.assertEqual(normalization_args.root, workspace)
        self.assertFalse(normalization_args.force)
        self.assertFalse(normalization_args.no_rebuild)

    @patch("watchcraft_author.process_and_normalize_collection")
    @patch("watchcraft_author.import_youtube_playlist")
    @patch("watchcraft_author.youtube_playlist")
    def test_collection_create_fails_closed_after_partial_import(
        self, playlist_mock, import_mock, process_mock
    ):
        playlist = {
            "playlist_id": "PL1234567890_example",
            "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
            "title": "Useful Lessons",
            "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
            "duplicate_count": 0,
        }
        playlist_mock.return_value = playlist
        import_mock.return_value = {
            **playlist,
            "imported_count": 1,
            "completed_count": 1,
            "added_count": 1,
            "cached_count": 0,
            "failures": [
                {"video_id": "abcdefghijk", "error": "no English captions"}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            collections_repo = Path(directory)
            (collections_repo / "collections").mkdir()
            args = build_authoring_parser().parse_args(
                [
                    "collection",
                    "create",
                    "--from-youtube-playlist",
                    playlist["url"],
                    "--collections-repo",
                    str(collections_repo),
                ]
            )

            with self.assertRaisesRegex(
                RuntimeError, "Collection import is incomplete.*abcdefghijk"
            ):
                create_playlist_collection(args)

            workspace = (
                collections_repo / "collections" / "useful-lessons"
            ).resolve()
            self.assertTrue((workspace / "watchcraft-authoring.json").is_file())
            process_mock.assert_not_called()

    @patch("watchcraft_author.require_playlist_complete")
    @patch("watchcraft_author.process_and_normalize_collection", return_value=0)
    @patch("watchcraft_author.import_youtube_playlist")
    @patch("watchcraft_author.youtube_playlist")
    def test_collection_create_can_exclude_terminal_caption_failures(
        self, playlist_mock, import_mock, process_mock, require_complete_mock
    ):
        playlist = {
            "playlist_id": "PL1234567890_example",
            "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
            "title": "Useful Lessons",
            "video_ids": ["PjObX9XQvgI", "abcdefghijk", "zyxwvutsrqp"],
            "duplicate_count": 0,
        }
        playlist_mock.return_value = playlist

        def import_playlist(workspace, *args, **kwargs):
            (workspace / "watchcraft-authoring.json").write_text(
                json.dumps(
                    {
                        "kind": "watchcraft.authoring",
                        "schema_version": 1,
                        "collection": {
                            "source": {
                                "type": "youtube-playlist",
                                "playlist_id": playlist["playlist_id"],
                                "url": playlist["url"],
                            }
                        },
                        "sources": {
                            "PjObX9XQvgI.youtube": {
                                "video_id": "PjObX9XQvgI",
                                "position": 1,
                            },
                            "zyxwvutsrqp.youtube": {
                                "video_id": "zyxwvutsrqp",
                                "position": 3,
                            },
                        },
                    }
                )
            )
            return {
                **playlist,
                "imported_count": 2,
                "completed_count": 2,
                "added_count": 2,
                "cached_count": 0,
                "failures": [
                    {
                        "video_id": "abcdefghijk",
                        "error": "YouTube has no captions for 'en'",
                        "type": "captions-unavailable",
                        "reason": "requested-language-unavailable",
                        "language": "en",
                    }
                ],
            }

        import_mock.side_effect = import_playlist
        with tempfile.TemporaryDirectory() as directory:
            collections_repo = Path(directory)
            (collections_repo / "collections").mkdir()
            args = build_authoring_parser().parse_args(
                [
                    "collection",
                    "create",
                    "--from-youtube-playlist",
                    playlist["url"],
                    "--collections-repo",
                    str(collections_repo),
                    "--skip-missing-captions",
                ]
            )

            self.assertEqual(create_playlist_collection(args), 0)

            workspace = collections_repo / "collections" / "useful-lessons"
            config = json.loads(
                (workspace / "watchcraft-authoring.json").read_text()
            )
            source = config["collection"]["source"]
            self.assertEqual(source["excluded_video_ids"], ["abcdefghijk"])
            self.assertEqual(
                source["caption_exclusions"],
                [
                    {
                        "video_id": "abcdefghijk",
                        "language": "en",
                        "reason": "requested-language-unavailable",
                    }
                ],
            )
            self.assertEqual(
                config["sources"]["zyxwvutsrqp.youtube"]["position"], 2
            )
            require_complete_mock.assert_called_once_with(
                workspace.resolve(),
                ["PjObX9XQvgI", "zyxwvutsrqp"],
                require_analysis=False,
            )
            self.assertEqual(
                process_mock.call_args.kwargs["expected_video_ids"],
                ["PjObX9XQvgI", "zyxwvutsrqp"],
            )

    @patch("watchcraft_author.process_and_normalize_collection")
    @patch("watchcraft_author.import_youtube_playlist")
    @patch("watchcraft_author.youtube_playlist")
    def test_collection_create_still_fails_on_other_errors_when_skipping_captions(
        self, playlist_mock, import_mock, process_mock
    ):
        playlist = {
            "playlist_id": "PL1234567890_example",
            "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
            "title": "Useful Lessons",
            "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
            "duplicate_count": 0,
        }
        playlist_mock.return_value = playlist
        import_mock.return_value = {
            **playlist,
            "imported_count": 1,
            "completed_count": 1,
            "added_count": 1,
            "cached_count": 0,
            "failures": [
                {
                    "video_id": "abcdefghijk",
                    "error": "proxy timed out",
                    "type": "import-error",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            collections_repo = Path(directory)
            (collections_repo / "collections").mkdir()
            args = build_authoring_parser().parse_args(
                [
                    "collection",
                    "create",
                    "--from-youtube-playlist",
                    playlist["url"],
                    "--collections-repo",
                    str(collections_repo),
                    "--skip-missing-captions",
                ]
            )

            with self.assertRaisesRegex(
                RuntimeError, "Collection import is incomplete.*proxy timed out"
            ):
                create_playlist_collection(args)

            process_mock.assert_not_called()

    @patch("watchcraft_author.require_playlist_complete")
    @patch("watchcraft_author.process_and_normalize_collection", return_value=0)
    @patch("watchcraft_author.import_youtube_playlist")
    @patch("watchcraft_author.youtube_playlist")
    def test_collection_create_reuses_saved_caption_exclusions(
        self, playlist_mock, import_mock, process_mock, require_complete_mock
    ):
        playlist = {
            "playlist_id": "PL1234567890_example",
            "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
            "title": "Useful Lessons",
            "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
            "duplicate_count": 0,
        }
        playlist_mock.return_value = playlist
        import_mock.return_value = {
            **playlist,
            "video_ids": ["PjObX9XQvgI"],
            "imported_count": 1,
            "completed_count": 1,
            "added_count": 0,
            "cached_count": 1,
            "failures": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            collections_repo = Path(directory)
            workspace = collections_repo / "collections" / "useful-lessons"
            workspace.mkdir(parents=True)
            (workspace / "watchcraft-authoring.json").write_text(
                json.dumps(
                    {
                        "kind": "watchcraft.authoring",
                        "schema_version": 1,
                        "collection": {
                            "source": {
                                "type": "youtube-playlist",
                                "playlist_id": playlist["playlist_id"],
                                "url": playlist["url"],
                                "excluded_video_ids": ["abcdefghijk"],
                                "caption_exclusions": [
                                    {
                                        "video_id": "abcdefghijk",
                                        "language": "en",
                                        "reason": "captions-disabled",
                                    }
                                ],
                            }
                        },
                        "sources": {},
                    }
                )
            )
            args = build_authoring_parser().parse_args(
                [
                    "collection",
                    "create",
                    "--from-youtube-playlist",
                    playlist["url"],
                    "--collections-repo",
                    str(collections_repo),
                    "--skip-missing-captions",
                ]
            )

            self.assertEqual(create_playlist_collection(args), 0)

            self.assertEqual(
                import_mock.call_args.kwargs["playlist_data"]["video_ids"],
                ["PjObX9XQvgI"],
            )
            source = json.loads(
                (workspace / "watchcraft-authoring.json").read_text()
            )["collection"]["source"]
            self.assertEqual(source["excluded_video_ids"], ["abcdefghijk"])
            self.assertEqual(
                source["caption_exclusions"][0]["reason"], "captions-disabled"
            )

    def test_youtube_video_id_accepts_watch_and_short_urls(self):
        self.assertEqual(
            youtube_video_id(
                "https://www.youtube.com/watch?v=PjObX9XQvgI&list=private"
            ),
            "PjObX9XQvgI",
        )
        self.assertEqual(
            youtube_video_id("https://youtu.be/PjObX9XQvgI"), "PjObX9XQvgI"
        )

    def test_youtube_playlist_id_accepts_playlist_and_watch_urls(self):
        playlist_id = "PL1234567890_example"
        self.assertEqual(
            youtube_playlist_id(
                f"https://www.youtube.com/playlist?list={playlist_id}"
            ),
            playlist_id,
        )
        self.assertEqual(
            youtube_playlist_id(
                f"https://www.youtube.com/watch?v=PjObX9XQvgI&list={playlist_id}"
            ),
            playlist_id,
        )

    def test_youtube_playlist_follows_continuations_without_yt_dlp(self):
        playlist_id = "PL1234567890_example"

        def item(video_id, index):
            return {
                "lockupViewModel": {
                    "rendererContext": {
                        "commandContext": {
                            "onTap": {
                                "innertubeCommand": {
                                    "watchEndpoint": {
                                        "playlistId": playlist_id,
                                        "videoId": video_id,
                                        "index": index,
                                    }
                                }
                            }
                        }
                    }
                }
            }

        continuation = {
            "continuationItemViewModel": {
                "continuationCommand": {
                    "innertubeCommand": {
                        "continuationCommand": {
                            "token": "next-page",
                            "request": "CONTINUATION_REQUEST_TYPE_BROWSE",
                        }
                    }
                }
            }
        }
        initial = {
            "metadata": {
                "playlistMetadataRenderer": {"title": "Editing Lessons"}
            },
            "contents": {
                "itemSectionRenderer": {
                    "contents": [item("PjObX9XQvgI", 0), continuation]
                }
            },
        }
        page = (
            '<script>ytcfg.set({"INNERTUBE_API_KEY":"test-key",'
            '"INNERTUBE_CLIENT_VERSION":"test-version"});</script>'
            f"<script>var ytInitialData = {json.dumps(initial)};</script>"
        )
        next_page = {
            "onResponseReceivedActions": [
                {
                    "appendContinuationItemsAction": {
                        "continuationItems": [item("abcdefghijk", 1)]
                    }
                }
            ]
        }
        with patch("watchcraft_author.request_text", return_value=page), patch(
            "watchcraft_author.request_json", return_value=next_page
        ) as request_json:
            playlist = youtube_playlist(playlist_id)

        self.assertEqual(playlist["title"], "Editing Lessons")
        self.assertEqual(playlist["video_ids"], ["PjObX9XQvgI", "abcdefghijk"])
        request_url, request_payload = request_json.call_args.args
        self.assertEqual(
            request_url,
            "https://www.youtube.com/youtubei/v1/browse?key=test-key",
        )
        self.assertEqual(request_payload["continuation"], "next-page")

    def test_youtube_playlist_import_is_ordered_resumable_and_skips_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist = {
                "playlist_id": "PL1234567890_example",
                "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
                "title": "Editing Lessons",
                "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
                "duplicate_count": 0,
            }
            with patch(
                "watchcraft_author.youtube_playlist", return_value=playlist
            ), patch(
                "watchcraft_author.import_youtube",
                side_effect=[
                    {"title": "First Lesson"},
                    RuntimeError("no English captions"),
                ],
            ) as import_one:
                result = import_youtube_playlist(
                    root,
                    playlist["url"],
                    collection_title=None,
                    language="en",
                    force=False,
                    start_position=5,
                )

            self.assertEqual(result["imported_count"], 1)
            self.assertEqual(result["added_count"], 1)
            self.assertEqual(result["cached_count"], 0)
            self.assertEqual(result["failures"][0]["video_id"], "abcdefghijk")
            self.assertEqual(
                [call.kwargs["position"] for call in import_one.call_args_list],
                [5, 6],
            )
            config = json.loads((root / "watchcraft-authoring.json").read_text())
            self.assertEqual(config["collection"]["title"], "Editing Lessons")
            self.assertEqual(
                config["collection"]["source"],
                {
                    "type": "youtube-playlist",
                    "playlist_id": "PL1234567890_example",
                    "url": playlist["url"],
                },
            )

    def test_youtube_playlist_import_marks_terminal_caption_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist = {
                "playlist_id": "PL1234567890_example",
                "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
                "title": "Editing Lessons",
                "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
                "duplicate_count": 0,
            }
            unavailable = YouTubeCaptionsUnavailable(
                "YouTube has no captions for the requested language 'en'",
                reason="requested-language-unavailable",
            )
            with patch(
                "watchcraft_author.youtube_transcript_client",
                return_value=object(),
            ), patch(
                "watchcraft_author.import_youtube",
                side_effect=[{"title": "First Lesson"}, unavailable],
            ):
                result = import_youtube_playlist(
                    root,
                    playlist["url"],
                    collection_title=None,
                    language="en",
                    force=False,
                    playlist_data=playlist,
                )

            self.assertEqual(
                result["failures"],
                [
                    {
                        "video_id": "abcdefghijk",
                        "error": "YouTube has no captions for the requested language 'en'",
                        "type": "captions-unavailable",
                        "reason": "requested-language-unavailable",
                        "language": "en",
                    }
                ],
            )

    def test_youtube_playlist_import_stops_after_a_global_ip_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist = {
                "playlist_id": "PL1234567890_example",
                "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
                "title": "Editing Lessons",
                "video_ids": ["PjObX9XQvgI", "abcdefghijk"],
                "duplicate_count": 0,
            }
            with patch(
                "watchcraft_author.youtube_transcript_client",
                return_value=object(),
            ), patch(
                "watchcraft_author.import_youtube",
                side_effect=YouTubeIpBlocked("blocked"),
            ) as import_one:
                with self.assertRaisesRegex(YouTubeIpBlocked, "blocked"):
                    import_youtube_playlist(
                        root,
                        playlist["url"],
                        collection_title=None,
                        language="en",
                        force=False,
                        playlist_data=playlist,
                    )

            self.assertEqual(import_one.call_count, 1)

    def test_youtube_transcript_client_uses_environment_proxy_without_persisting_it(self):
        proxy_url = "http://user:secret@proxy.example:8080"
        with patch.dict(
            "watchcraft_author.os.environ",
            {"WATCHCRAFT_YOUTUBE_PROXY_URL": proxy_url},
            clear=True,
        ), patch("youtube_transcript_api.YouTubeTranscriptApi") as api:
            youtube_transcript_client()

        proxy_config = api.call_args.kwargs["proxy_config"]
        self.assertEqual(
            proxy_config.to_requests_dict(),
            {"http": proxy_url, "https": proxy_url},
        )

    def test_youtube_transcript_client_requires_both_webshare_credentials(self):
        with patch.dict(
            "watchcraft_author.os.environ",
            {"WATCHCRAFT_YOUTUBE_WEBSHARE_USERNAME": "only-a-username"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "Set both"):
                youtube_transcript_client()

    def test_youtube_transcript_maps_library_ip_block_to_global_failure(self):
        from youtube_transcript_api import IpBlocked

        class BlockedClient:
            def list(self, video_id):
                raise IpBlocked(video_id)

        with self.assertRaisesRegex(YouTubeIpBlocked, "blocked caption requests"):
            youtube_transcript(
                "PjObX9XQvgI", "en", transcript_api=BlockedClient()
            )

    def test_youtube_transcript_classifies_missing_language_as_unavailable(self):
        from youtube_transcript_api import NoTranscriptFound

        class TranscriptList:
            def find_transcript(self, languages):
                raise NoTranscriptFound("PjObX9XQvgI", languages, self)

            def __str__(self):
                return "Korean captions only"

        class MissingLanguageClient:
            def list(self, video_id):
                return TranscriptList()

        with self.assertRaises(YouTubeCaptionsUnavailable) as caught:
            youtube_transcript(
                "PjObX9XQvgI", "en", transcript_api=MissingLanguageClient()
            )

        self.assertEqual(caught.exception.reason, "requested-language-unavailable")
        self.assertRegex(str(caught.exception), "requested language 'en'")

    def test_youtube_transcript_classifies_disabled_captions_as_unavailable(self):
        from youtube_transcript_api import TranscriptsDisabled

        class DisabledClient:
            def list(self, video_id):
                raise TranscriptsDisabled(video_id)

        with self.assertRaises(YouTubeCaptionsUnavailable) as caught:
            youtube_transcript(
                "PjObX9XQvgI", "en", transcript_api=DisabledClient()
            )

        self.assertEqual(caught.exception.reason, "captions-disabled")

    def test_resumed_playlist_import_refreshes_positions_without_renaming_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_id = "PjObX9XQvgI"
            (root / "watchcraft-authoring.json").write_text(
                json.dumps(
                    {
                        "kind": "watchcraft.authoring",
                        "schema_version": 1,
                        "collection": {"title": "My Existing Course"},
                        "sources": {
                            f"{video_id}.youtube": {
                                "type": "youtube",
                                "video_id": video_id,
                                "title": "Existing Lesson",
                                "position": 99,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            state = root / "transcripts" / f"{video_id}.transcript.json"
            state.parent.mkdir()
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "video": f"{video_id}.youtube",
                        "segments": [
                            {"start": 0, "end": 1, "text": "Instruction"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            playlist = {
                "playlist_id": "PL1234567890_example",
                "url": "https://www.youtube.com/playlist?list=PL1234567890_example",
                "title": "YouTube Playlist Title",
                "video_ids": [video_id],
                "duplicate_count": 0,
            }

            with patch(
                "watchcraft_author.youtube_playlist", return_value=playlist
            ):
                result = import_youtube_playlist(
                    root,
                    playlist["url"],
                    collection_title=None,
                    language="en",
                    force=False,
                    start_position=2,
                )

            config = json.loads((root / "watchcraft-authoring.json").read_text())
            self.assertEqual(result["added_count"], 0)
            self.assertEqual(result["cached_count"], 1)
            self.assertEqual(config["collection"]["title"], "My Existing Course")
            self.assertEqual(
                config["sources"][f"{video_id}.youtube"]["position"], 2
            )

    def test_youtube_add_accepts_a_playlist_parameter(self):
        args = build_authoring_parser().parse_args(
            [
                "youtube",
                "add",
                "--workspace",
                "/tmp/watchcraft-playlist-test",
                "--playlist",
                "PL1234567890_example",
            ]
        )
        self.assertEqual(args.playlist, "PL1234567890_example")
        self.assertIsNone(args.url)

    def test_youtube_description_chapters_extracts_publisher_timestamps(self):
        description = """Links and notes
00:00 Introduction
00:19 Audio Remix
01:28 Generative Extend
04:00 Text-Based Editing
"""
        self.assertEqual(
            youtube_description_chapters(description, 300),
            [
                {"start_seconds": 0, "title": "Introduction"},
                {"start_seconds": 19, "title": "Audio Remix"},
                {"start_seconds": 88, "title": "Generative Extend"},
                {"start_seconds": 240, "title": "Text-Based Editing"},
            ],
        )

    def test_compact_topic_display_label_rules(self):
        self.assertIsNone(display_label_error("Multi-Camera Editing", set()))
        self.assertIsNone(display_label_error("Essential Sound", set()))
        self.assertIn(
            "characters",
            display_label_error(
                "Extremely Verbose Topic Label That Cannot Fit", set()
            ),
        )
        self.assertIn(
            "punctuation",
            display_label_error("Export Workflow (H.264)", set()),
        )
        self.assertIn(
            "duplicates",
            display_label_error("Essential Sound", {"essential sound"}),
        )
        self.assertEqual(
            deterministic_display_label(
                "Fermentation timing and dough rest", set()
            ),
            "Fermentation timing & dough rest",
        )
        self.assertEqual(
            deterministic_display_label(
                "Mediterranean braised green beans (Andrew Janjigian)",
                {"braised green beans"},
            ),
            "Mediterranean braised beans",
        )
        self.assertEqual(
            deterministic_display_label(
                "pan materials: cast iron, carbon steel, non-stick",
                {"pan material comparison"},
            ),
            "pan materials",
        )
        self.assertEqual(
            deterministic_display_label(
                "drain pitch",
                {"drain pitch"},
                preferred_label="Drain Pitch",
            ),
            "Drain Pitch Overview",
        )
        self.assertEqual(
            deterministic_display_label(
                "drains running through a finished basement and foundation",
                {"basement drain routing"},
                preferred_label="Basement Drain Routing",
            ),
            "Finished Basement Drain Routing",
        )

    def test_duplicate_display_label_gets_deterministic_qualifier(self):
        class FakeResponses:
            def parse(self, **_kwargs):
                generated = GeneratedDisplayLabels(
                    labels=[
                        DisplayLabelDecision(
                            source_id="D001", label="Drain Pitch"
                        )
                    ]
                )
                return type("Response", (), {"output_parsed": generated})()

        client = type("Client", (), {"responses": FakeResponses()})()
        canonical = {
            "drain pitch": {
                "label": "drain pitch",
                "family_ids": [],
                "contexts": set(),
            }
        }

        self.assertEqual(
            label_batch(
                client,
                model="test-model",
                keys=["drain pitch"],
                canonical=canonical,
                families={},
                reserved_labels=["Drain Pitch"],
                retries=0,
            ),
            {"drain pitch": "Drain Pitch Overview"},
        )

    def test_display_label_failure_preserves_valid_partial_results(self):
        valid = "valid topic"
        invalid = "verbose topic"
        long_label = "An excessively verbose label without useful shortening"

        class FakeResponses:
            def __init__(self):
                self.calls = 0

            def parse(self, **_kwargs):
                if self.calls == 0:
                    generated = GeneratedDisplayLabels(
                        labels=[
                            DisplayLabelDecision(
                                source_id="D001", label="Useful Topic"
                            ),
                            DisplayLabelDecision(
                                source_id="D002", label=long_label
                            ),
                        ]
                    )
                else:
                    generated = GeneratedDisplayLabels(
                        labels=[
                            DisplayLabelDecision(
                                source_id="D001", label=long_label
                            )
                        ]
                    )
                self.calls += 1
                return type("Response", (), {"output_parsed": generated})()

        client = type("Client", (), {"responses": FakeResponses()})()
        canonical = {
            valid: {
                "label": "Valid topic",
                "family_ids": [],
                "contexts": set(),
            },
            invalid: {
                "label": long_label,
                "family_ids": [],
                "contexts": set(),
            },
        }
        with patch(
            "normalize_topics.deterministic_display_label", return_value=None
        ), self.assertRaises(DisplayLabelBatchError) as raised:
            label_batch(
                client,
                model="test-model",
                keys=[valid, invalid],
                canonical=canonical,
                families={},
                reserved_labels=[],
                retries=0,
            )

        self.assertEqual(raised.exception.completed, {valid: "Useful Topic"})
        self.assertEqual(raised.exception.remaining, [invalid])
        self.assertIn("characters", raised.exception.rejected[invalid])

    def test_publisher_chapters_replace_ai_boundaries_but_keep_enrichment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "watchcraft-authoring.json").write_text(
                json.dumps({
                    "sources": {
                        "video.youtube": {
                            "duration_seconds": 30,
                            "chapters": [
                                {"start_seconds": 0, "title": "Publisher Intro"},
                                {"start_seconds": 10, "title": "Publisher Tool One"},
                                {"start_seconds": 20, "title": "Publisher Tool Two"},
                            ],
                        }
                    }
                }),
                encoding="utf-8",
            )
            analysis = {
                "video": "video.youtube",
                "sections": [
                    {
                        "start": "00:00:00",
                        "end": "00:00:12",
                        "title": "AI Intro",
                        "concepts": ["Orientation"],
                        "description": "Introduces the lesson.",
                    },
                    {
                        "start": "00:00:12",
                        "end": "00:00:21",
                        "title": "AI Tool One",
                        "concepts": ["First tool"],
                        "description": "Demonstrates the first tool.",
                    },
                    {
                        "start": "00:00:21",
                        "end": "00:00:30",
                        "title": "AI Tool Two",
                        "concepts": ["Second tool"],
                        "description": "Demonstrates the second tool.",
                    },
                ],
            }
            updated = analysis_with_publisher_chapters(root, "video.youtube", analysis)
            self.assertEqual(
                [section["start"] for section in updated["sections"]],
                ["00:00:00", "00:00:10", "00:00:20"],
            )
            self.assertEqual(
                [section["title"] for section in updated["sections"]],
                ["Publisher Intro", "Publisher Tool One", "Publisher Tool Two"],
            )
            self.assertEqual(updated["timeline_source"], "youtube-publisher-chapters")

    def test_youtube_workspace_keeps_transcript_private_and_emits_remote_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = {
                "source_id": "youtube:PjObX9XQvgI",
                "type": "youtube",
                "video_id": "PjObX9XQvgI",
                "url": "https://www.youtube.com/watch?v=PjObX9XQvgI",
                "title": "Premiere Pro AI Tools",
                "publisher": "Primal Video",
                "publisher_url": "https://www.youtube.com/@PrimalVideo",
                "thumbnail_url": "https://i.ytimg.com/test.jpg",
                "duration_seconds": 936,
                "published_at": "2025-03-24T21:00:33-07:00",
            }
            segments = [{"start": 0.0, "end": 4.0, "text": "First technique."}]
            captions = {
                "language": "en",
                "language_name": "English",
                "generated": True,
                "source": "youtube-captions",
            }
            with patch("watchcraft_author.youtube_metadata", return_value=metadata), patch(
                "watchcraft_author.youtube_transcript", return_value=(segments, captions)
            ):
                import_youtube(
                    root,
                    "PjObX9XQvgI",
                    collection_title="Editing Course",
                    language="en",
                    force=False,
                    position=2,
                )
            self.assertEqual(video_catalog.catalog_root(root), root)
            self.assertTrue((root / "transcripts/PjObX9XQvgI.transcript.json").is_file())
            analysis = {
                "video": "PjObX9XQvgI.youtube",
                "title": "Eight Premiere Pro AI Tools",
                "summary": "A useful lesson.",
                "schema_version": 2,
                "analysis_model": "test-model",
                "topics": ["Premiere Pro"],
                "sections": [],
                "locations": [],
            }
            analysis_file = root / "analysis/PjObX9XQvgI.analysis.json"
            analysis_file.parent.mkdir()
            analysis_file.write_text(json.dumps(analysis), encoding="utf-8")
            manifest = write_collection(root)
            item = next(iter(manifest["items"].values()))
            self.assertEqual(
                item["media"],
                [{
                    "type": "youtube",
                    "delivery": "remote",
                    "video_id": "PjObX9XQvgI",
                    "url": "https://www.youtube.com/watch?v=PjObX9XQvgI",
                }],
            )
            self.assertNotIn("transcript", item)
            self.assertNotIn("media_root_hint", manifest)
            self.assertEqual(manifest["title"], "Editing Course")
            self.assertEqual(
                json.loads((root / "watchcraft-authoring.json").read_text())["sources"]
                ["PjObX9XQvgI.youtube"]["position"],
                2,
            )

    def test_youtube_source_positions_control_root_lesson_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "watchcraft-authoring.json").write_text(
                json.dumps({
                    "collection": {"title": "Editing Course"},
                    "sources": {
                        "later.youtube": {"type": "youtube", "video_id": "later", "position": 2},
                        "first.youtube": {"type": "youtube", "video_id": "first", "position": 1},
                    },
                }),
                encoding="utf-8",
            )
            analyses = [
                {"video": "later.youtube", "title": "Alphabetically First", "topics": [], "sections": []},
                {"video": "first.youtube", "title": "Alphabetically Last", "topics": [], "sections": []},
            ]
            manifest = build_collection_manifest(root, analyses, {})
            ordered_titles = [
                manifest["items"][child["item_id"]]["title"]
                for child in manifest["root"]["children"]
            ]
            self.assertEqual(ordered_titles, ["Alphabetically Last", "Alphabetically First"])

    def test_srt_timestamp(self):
        self.assertEqual(video_catalog.format_clock(3661.234, srt=True), "01:01:01,234")

    def test_srt_rendering(self):
        rendered = video_catalog.render_srt(
            [{"start": 1.2, "end": 3.4, "text": "  Puppet   Warp  "}]
        )
        self.assertEqual(
            rendered, "1\n00:00:01,200 --> 00:00:03,400\nPuppet Warp\n"
        )

    def test_repetition_filter_rejects_stuck_decoder(self):
        text = "monitor " * 80
        accepted, rejected = video_catalog.clean_segments(
            [{"start": 1.0, "end": 2.0, "text": text}]
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)

    def test_repetition_filter_keeps_normal_instruction(self):
        text = (
            "Use the perspective warp to straighten the horizon without cropping "
            "the edges, then blend the sky with a soft clone stamp brush."
        )
        accepted, rejected = video_catalog.clean_segments(
            [{"start": 1.0, "end": 2.0, "text": text}]
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])

    def test_output_paths_preserve_collection_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Part 3" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            srt, text, state = video_catalog.output_paths(root, video)
            self.assertEqual(
                srt,
                root / "Video Catalog" / "transcripts" / "Part 3" / "Lesson.srt",
            )
            self.assertEqual(
                text,
                root
                / "Video Catalog"
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.txt",
            )
            self.assertEqual(
                state,
                root
                / "Video Catalog"
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.json",
            )

    def test_migrate_transcript_sidecars_preserves_relative_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Course" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            legacy_srt = video.with_suffix(".srt")
            legacy_text = video.with_suffix(".transcript.txt")
            legacy_srt.write_text("subtitle", encoding="utf-8")
            legacy_text.write_text("transcript", encoding="utf-8")

            planned, central = video_catalog.migrate_transcript_sidecars(
                root, dry_run=True
            )
            self.assertEqual((planned, central), (2, 0))
            self.assertTrue(legacy_srt.exists())

            moved, central = video_catalog.migrate_transcript_sidecars(root)
            self.assertEqual((moved, central), (2, 0))
            srt, text, _ = video_catalog.output_paths(root, video)
            self.assertEqual(srt.read_text(encoding="utf-8"), "subtitle")
            self.assertEqual(text.read_text(encoding="utf-8"), "transcript")
            self.assertFalse(legacy_srt.exists())
            self.assertFalse(legacy_text.exists())

    def test_chunk_plan_covers_file_exactly(self):
        chunks = chunk_plan(21, 8)
        self.assertEqual([(c.start, c.end, c.size) for c in chunks], [
            (0, 7, 8),
            (8, 15, 8),
            (16, 20, 5),
        ])

    def test_analysis_and_normalization_models_have_independent_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                "os.environ",
                {
                    "VIDEO_CATALOG_ANALYSIS_MODEL": "analysis-test-model",
                    "VIDEO_CATALOG_NORMALIZATION_MODEL": "normalization-test-model",
                },
            ):
                analysis_args = video_catalog.build_parser().parse_args(
                    ["analyze", "--root", directory, "--all", "--dry-run"]
                )
                normalization_args = build_normalization_parser().parse_args(
                    ["--root", directory, "--dry-run"]
                )
            self.assertEqual(analysis_args.analysis_model, "analysis-test-model")
            self.assertEqual(
                normalization_args.normalization_model,
                "normalization-test-model",
            )


    def test_collection_manifest_models_groups_stable_ids_and_scoped_topics(self):
        analyses = [
            {
                "video": "Course A/Module 1/Lesson One.mp4",
                "title": "Lesson One",
                "summary": "First lesson.",
                "schema_version": 2,
                "analysis_model": "test-model",
                "topics": ["Camera Raw", "Dodge and Burn"],
                "sections": [{"title": "Raw adjustments"}, {"title": "Dodging"}],
                "date": {"display": "2022 (approx.)"},
                "locations": [],
            },
            {
                "video": "Course A/Lesson Two.mp4",
                "title": "Lesson Two",
                "summary": "Second lesson.",
                "topics": ["camera raw"],
                "sections": [{"title": "Raw adjustments"}],
                "locations": [{"name": "Oregon Coast (probable)"}],
            },
        ]
        mappings = {
            "Course A/Module 1/Lesson One.mp4": {
                "camera raw": [0],
                "dodge and burn": [1],
            },
            "Course A/Lesson Two.mp4": {"camera raw": [0]},
        }

        manifest = build_collection_manifest(
            Path("/library/Landscape Classes"), analyses, mappings
        )

        self.assertEqual(manifest["kind"], "watchcraft.collection")
        self.assertEqual(manifest["schema_version"], 4)
        self.assertEqual(manifest["media_root_hint"], "..")
        self.assertEqual(manifest["collection_id"], "landscape-classes")
        self.assertEqual(manifest["topic_scope"], "collection")
        self.assertEqual(
            manifest["stats"],
            {"video_count": 2, "topic_count": 2, "topic_family_count": 0},
        )
        self.assertEqual(manifest["revision"], 1)

        course = manifest["root"]["children"][0]
        self.assertEqual((course["type"], course["title"]), ("group", "Course A"))
        self.assertEqual(course["children"][0]["title"], "Module 1")
        self.assertEqual(course["children"][0]["children"][0]["type"], "video")
        self.assertEqual(course["children"][1]["type"], "video")

        camera_raw = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "camera raw"
        )
        self.assertEqual(camera_raw["label"], "Camera Raw")
        self.assertEqual(camera_raw["aliases"], ["camera raw"])
        self.assertEqual(camera_raw["video_count"], 2)

        lesson_one_id = next(
            item_id
            for item_id, item in manifest["items"].items()
            if item["media"][0]["relative_path"]
            == "Course A/Module 1/Lesson One.mp4"
        )
        lesson_one = manifest["items"][lesson_one_id]
        self.assertEqual(lesson_one["media"][0]["delivery"], "referenced-local")
        self.assertNotIn("transcript", lesson_one)
        self.assertEqual(
            lesson_one["analysis"]["path"],
            "analysis/Course A/Module 1/Lesson One.analysis.json",
        )
        self.assertEqual(lesson_one["topic_sections"][camera_raw["topic_id"]], [0])

        unchanged = build_collection_manifest(
            Path("/moved/Landscape Classes"), analyses, mappings, manifest
        )
        self.assertEqual(unchanged["revision"], 1)
        self.assertEqual(unchanged["content_hash"], manifest["content_hash"])
        self.assertEqual(set(unchanged["items"]), set(manifest["items"]))

        changed_analyses = json.loads(json.dumps(analyses))
        changed_analyses[0]["summary"] = "Updated first lesson."
        changed = build_collection_manifest(
            Path("/moved/Landscape Classes"), changed_analyses, mappings, unchanged
        )
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(set(changed["items"]), set(manifest["items"]))

    def test_collection_manifest_applies_canonical_families_and_related_topics(self):
        family_id = "family-retouching-test"
        normalization = {
            "schema_version": 1,
            "prompt_version": 1,
            "model": "test-model",
            "source_hash": "test-source",
            "families": {
                family_id: {
                    "family_id": family_id,
                    "canonical_key": "retouching",
                    "label": "Retouching",
                    "description": "Localized cleanup and repair.",
                }
            },
            "assignments": {
                "clone stamp": {
                    "canonical_key": "clone stamp",
                    "canonical_label": "Clone Stamp",
                    "family_ids": [family_id],
                },
                "clone stamp tool": {
                    "canonical_key": "clone stamp",
                    "canonical_label": "Clone Stamp",
                    "family_ids": [family_id],
                },
                "content-aware fill": {
                    "canonical_key": "content-aware fill",
                    "canonical_label": "Content-Aware Fill",
                    "family_ids": [family_id],
                },
            },
            "display_labels": {
                "clone stamp": "Clone Stamp Cleanup",
                "content-aware fill": "Content-Aware Fill",
            },
            "related": {
                "clone stamp": ["content-aware fill"],
                "content-aware fill": ["clone stamp"],
            },
        }
        analyses = [
            {
                "video": "Course/A.mp4",
                "topics": ["Clone Stamp Tool", "Content-Aware Fill"],
                "sections": [{"title": "Cleanup"}, {"title": "Fill"}],
            },
            {
                "video": "Course/B.mp4",
                "topics": ["Clone Stamp"],
                "sections": [{"title": "Cleanup"}],
            },
        ]
        mappings = {
            "Course/A.mp4": {
                "clone stamp tool": [0],
                "content-aware fill": [1],
            },
            "Course/B.mp4": {"clone stamp": [0]},
        }
        manifest = build_collection_manifest(
            Path("/library/Classes"), analyses, mappings, normalization=normalization
        )
        self.assertEqual(manifest["stats"]["topic_count"], 2)
        self.assertEqual(manifest["stats"]["topic_family_count"], 1)
        clone = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "clone stamp"
        )
        fill = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "content-aware fill"
        )
        self.assertEqual(clone["video_count"], 2)
        self.assertEqual(clone["label"], "Clone Stamp Cleanup")
        self.assertEqual(clone["aliases"], ["Clone Stamp", "Clone Stamp Tool"])
        self.assertEqual(clone["family_ids"], [family_id])
        self.assertEqual(clone["related_topic_ids"], [fill["topic_id"]])
        self.assertEqual(
            manifest["topic_families"][family_id]["video_count"], 2
        )
        self.assertTrue(
            all(family_id in item["family_ids"] for item in manifest["items"].values())
        )

    def test_topic_chapter_mapping_combines_structured_and_transcript_evidence(self):
        analysis = {
            "video": "Course/Lesson.mp4",
            "topics": ["Dodge and Burn", "Camera Raw", "Unmapped"],
            "sections": [
                {
                    "start": "00:00:00",
                    "end": "00:01:00",
                    "title": "Introduction",
                    "concepts": ["dodge and burn"],
                    "description": "Overview.",
                },
                {
                    "start": "00:01:00",
                    "end": "00:03:00",
                    "title": "Sculpting light with dodging and burning",
                    "concepts": [],
                    "description": "Practical work.",
                },
            ],
            "featured_techniques": [
                {
                    "technique": "Dodge and burn to sculpt light",
                    "timestamp": "00:01:00",
                }
            ],
        }
        transcript = [
            {
                "start": 120,
                "end": 125,
                "text": "Now open Camera Raw and adjust the exposure.",
            }
        ]
        mapping = build_topic_chapter_map(analysis, transcript)
        self.assertEqual(mapping["dodge and burn"], [0, 1])
        self.assertEqual(mapping["camera raw"], [1])
        self.assertNotIn("unmapped", mapping)

    def test_collection_csv_export_remains_available(self):
        analysis = {
            "video": "Course/Lesson.mp4",
            "title": "Lesson",
            "date": {"display": "2024"},
            "locations": [{"name": "Oregon Coast"}],
            "summary": "A useful lesson.",
            "topics": ["Dodge and Burn"],
            "sections": [],
        }
        rows = render_csv([analysis]).splitlines()
        self.assertNotIn("\r", render_csv([analysis]))
        self.assertEqual(
            rows[0],
            "video,title,date,location,summary,topics,featured_techniques,section_count",
        )
        self.assertIn("Course/Lesson.mp4,Lesson,2024,Oregon Coast", rows[1])

    def test_collection_build_removes_the_legacy_html_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / video_catalog.CATALOG_DIR_NAME
            analysis_path = catalog / "analysis" / "Course" / "Lesson.analysis.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(
                json.dumps(
                    {
                        "video": "Course/Lesson.mp4",
                        "title": "Lesson",
                        "summary": "A useful lesson.",
                        "topics": [],
                        "sections": [],
                        "locations": [],
                    }
                ),
                encoding="utf-8",
            )
            legacy_html = catalog / "catalog.html"
            legacy_html.write_text("legacy UI", encoding="utf-8")

            manifest = write_collection(root)

            self.assertEqual(manifest["kind"], "watchcraft.collection")
            self.assertTrue((catalog / "collection.json").is_file())
            self.assertTrue((catalog / "catalog.csv").is_file())
            self.assertFalse(legacy_html.exists())

    def test_structured_analysis_is_atomic_normalized_and_resumable(self):
        class FakeResponses:
            def __init__(self, generated):
                self.generated = generated
                self.calls = 0

            def parse(self, **kwargs):
                self.calls += 1
                self.kwargs = kwargs
                return type("Response", (), {"output_parsed": self.generated})()

        class FakeClient:
            def __init__(self, generated):
                self.responses = FakeResponses(generated)

        generated = GeneratedAnalysis(
            title="A useful lesson",
            date=ApproximateDate(
                display="2022 (approx.)",
                iso="2022",
                precision="year",
                confidence=1.4,
                basis="Folder name",
            ),
            locations=[
                Location(name="Oregon Coast (probable)", confidence=-0.2, basis="Context")
            ],
            summary="A practical Photoshop workflow.",
            topics=["Puppet Warp", "puppet warp", "History Brush"],
            sections=[
                Section(
                    start="00:10:00",
                    end="00:12:00",
                    title="Warp",
                    concepts=["Puppet Warp"],
                    description="Reshapes the frame.",
                ),
                Section(
                    start="00:02:00",
                    end="00:05:00",
                    title="Blend",
                    concepts=["History Brush"],
                    description="Blends local changes.",
                ),
            ],
            featured_techniques=[
                FeaturedTechnique(
                    technique="Puppet Warp", timestamp="00:10:00", confidence=0.9
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Part 3" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            state_path = (
                root
                / video_catalog.CATALOG_DIR_NAME
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.json"
            )
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "video": "Part 3/Lesson.mp4",
                        "segments": [
                            {"start": 2, "end": 5, "text": "Use the History Brush."}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            client = FakeClient(generated)
            with patch("analyze_catalog.probe_creation_time", return_value="2022-01-01"):
                result = analyze_state(
                    root,
                    state_path,
                    client=client,
                    model="test-model",
                    force=False,
                    retries=0,
                    max_transcript_chars=10_000,
                )
            self.assertEqual(result, "completed")
            output = analysis_path(root, "Part 3/Lesson.mp4")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["date"]["confidence"], 1.0)
            self.assertEqual(payload["locations"][0]["confidence"], 0.0)
            self.assertEqual(payload["topics"], ["Puppet Warp", "History Brush"])
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["sections"][0]["title"], "Blend")
            self.assertEqual(payload["analysis_model"], "test-model")
            self.assertEqual(client.responses.kwargs["text_format"], GeneratedAnalysis)
            self.assertEqual(
                analyze_state(
                    root,
                    state_path,
                    client=client,
                    model="test-model",
                    force=False,
                    retries=0,
                    max_transcript_chars=10_000,
                ),
                "skipped",
            )
            self.assertEqual(client.responses.calls, 1)

    def test_topic_normalization_inventory_candidates_and_symmetric_relations(self):
        analyses = [
            {
                "video": "Course/A.mp4",
                "title": "Retouching",
                "topics": ["Clone Stamp Tool", "Masking"],
                "sections": [{"title": "Clone cleanup"}],
            },
            {
                "video": "Course/B.mp4",
                "title": "Cleanup",
                "topics": ["Clone Stamp", "Layer Masks"],
                "sections": [{"title": "Clone stamp"}],
            },
        ]
        maps = {
            "Course/A.mp4": {"clone stamp tool": [0]},
            "Course/B.mp4": {"clone stamp": [0]},
        }
        records = topic_inventory(analyses, maps)
        candidates = alias_candidates(records)
        self.assertIn("clone stamp", candidates["clone stamp tool"])
        self.assertIn("Retouching — Clone cleanup", records["clone stamp tool"]["contexts"])
        self.assertEqual(
            make_related_symmetric({"clone stamp": ["masking"], "masking": []}),
            {"clone stamp": ["masking"], "masking": ["clone stamp"]},
        )
        self.assertEqual(
            make_related_symmetric({"isolated topic": []}),
            {"isolated topic": []},
        )
        assignments = {
            "clone stamp": {"alias_source_keys": ["clone stamp tool"]},
            "clone stamp tool": {"alias_source_keys": ["clone stamp"]},
            "masking": {"alias_source_keys": ["layer masks"]},
            "layer masks": {"alias_source_keys": []},
        }
        finalize_canonical_assignments(records, assignments)
        self.assertEqual(
            assignments["clone stamp tool"]["canonical_key"], "clone stamp"
        )
        self.assertEqual(assignments["masking"]["canonical_key"], "masking")
        self.assertEqual(assignments["layer masks"]["canonical_key"], "layer masks")

    def test_timeline_repair_requires_and_returns_valid_sections(self):
        class FakeResponses:
            def __init__(self, generated):
                self.generated = generated

            def parse(self, **kwargs):
                self.kwargs = kwargs
                return type("Response", (), {"output_parsed": self.generated})()

        class FakeClient:
            def __init__(self, generated):
                self.responses = FakeResponses(generated)

        sections = [
            Section(
                start=f"00:0{index}:00",
                end=f"00:0{index + 1}:00",
                title=f"Chapter {index}",
                concepts=["Technique"],
                description="Demonstrates a technique.",
            )
            for index in range(3)
        ]
        client = FakeClient(GeneratedTimeline(sections=sections))
        repaired = request_timeline_repair(
            client,
            model="timeline-model",
            context={"filename": "Lesson.mp4"},
            existing_analysis={"title": "Lesson"},
            transcript="[00:00:00] Instruction",
            transcript_duration="00:10:00",
            retries=0,
        )
        self.assertEqual(len(repaired.sections), 3)
        self.assertEqual(client.responses.kwargs["text_format"], GeneratedTimeline)

        empty_client = FakeClient(GeneratedTimeline(sections=[]))
        with self.assertRaisesRegex(RuntimeError, "only 0 sections"):
            request_timeline_repair(
                empty_client,
                model="timeline-model",
                context={},
                existing_analysis={},
                transcript="[00:00:00] Instruction",
                transcript_duration="00:10:00",
                retries=0,
            )

    def test_music_only_captions_do_not_trigger_timeline_repair(self):
        music_only = {
            "video": "music.youtube",
            "text": "[Music]",
            "segments": [
                {"start": 1.26, "end": 196.3, "text": "[Music]"},
            ],
        }
        instructional = {
            "video": "lesson.youtube",
            "segments": [
                {"start": 0, "end": 10, "text": "Prepare the ingredients."},
                {"start": 10, "end": 20, "text": "Blend until smooth."},
                {"start": 20, "end": 30, "text": "Chill before serving."},
            ],
        }
        self.assertFalse(transcript_has_timeline_evidence(music_only))
        self.assertTrue(transcript_has_timeline_evidence(instructional))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "transcripts/music.transcript.json"
            transcript.parent.mkdir()
            transcript.write_text(json.dumps(music_only), encoding="utf-8")
            analysis = root / "analysis/music.analysis.json"
            analysis.parent.mkdir()
            analysis.write_text(json.dumps({"sections": []}), encoding="utf-8")

            self.assertEqual(pending_repairs(root, None, False), [])

    def test_canonical_aliases_are_conservative_and_mechanical(self):
        self.assertTrue(mechanically_equivalent("4x5 crop", "4x5 Cropping"))
        self.assertTrue(mechanically_equivalent("ACR", "Adobe Camera Raw"))
        self.assertTrue(mechanically_equivalent("Clone Stamp", "Clone Stamp Tool"))
        self.assertFalse(
            mechanically_equivalent("Local adjustments", "Tonal adjustments")
        )
        self.assertFalse(mechanically_equivalent("Luminosity", "Luminosity masks"))
        self.assertFalse(mechanically_equivalent("Camera Raw", "Camera Raw Filter"))
        self.assertFalse(mechanically_equivalent("Field technique", "Field workflow"))

    def test_normalization_resume_rejects_a_different_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topic-normalization.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_version": 2,
                        "collection_id": "collection",
                        "model": "first-model",
                        "families": {"one": {}},
                        "assignments": {},
                        "related": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "first-model"):
                load_state(path, "collection", "hash", "second-model", False)

    def test_process_limit_selects_next_unfinished_video_for_both_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = [root / f"Course/{name}.mp4" for name in ("A", "B", "C")]
            videos[0].parent.mkdir()
            for video in videos:
                video.touch()

            # A is fully complete. B has only its transcript. C has neither.
            for video in videos[:2]:
                srt_path, text_path, state_path = video_catalog.output_paths(root, video)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                srt_path.write_text("subtitle", encoding="utf-8")
                text_path.write_text("transcript", encoding="utf-8")
                state_path.write_text(
                    json.dumps(
                        {
                            "video": video.relative_to(root).as_posix(),
                            "segments": [
                                {"start": 0, "end": 1, "text": "Instruction"}
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            completed_analysis = analysis_path(
                root, videos[0].relative_to(root).as_posix()
            )
            completed_analysis.parent.mkdir(parents=True)
            completed_analysis.write_text("{}", encoding="utf-8")

            selected, total_pending = select_work(
                root, requested_video=None, limit=1
            )
            self.assertEqual(total_pending, 2)
            self.assertEqual(selected[0].video, videos[1])
            self.assertFalse(selected[0].transcribe)
            self.assertTrue(selected[0].analyze)

            selected, total_pending = select_work(
                root, requested_video=None, limit=2
            )
            self.assertEqual([item.video for item in selected], videos[1:])
            self.assertTrue(selected[1].transcribe)
            self.assertTrue(selected[1].analyze)


if __name__ == "__main__":
    unittest.main()
