from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from poc_youtube_audio_transcript import (
    normalized_words,
    transcript_comparison,
)
from youtube_audio import (
    YOUTUBE_ORIGINAL_AUDIO_FORMAT,
    YouTubeAcquisitionError,
    canonical_youtube_url,
    classify_youtube_acquisition_failure,
    download_youtube_audio,
    merge_speech_ranges,
    youtube_video_id,
    yt_dlp_audio_command,
    yt_dlp_audio_download_command,
    yt_dlp_command,
)


class YouTubeAudioTranscriptPocTests(unittest.TestCase):
    def test_uses_yt_dlp_from_the_active_python_environment_by_default(self) -> None:
        command = yt_dlp_command()

        self.assertEqual(command[1:], ["-m", "yt_dlp"])

    def test_allows_an_explicit_yt_dlp_executable(self) -> None:
        self.assertEqual(yt_dlp_command("/tmp/yt-dlp"), ["/tmp/yt-dlp"])

    def test_enables_node_for_youtube_javascript_challenges(self) -> None:
        command = yt_dlp_audio_command(
            "https://www.youtube.com/watch?v=PjObX9XQvgI",
            ["yt-dlp"],
        )

        self.assertEqual(
            command[command.index("--js-runtimes") + 1],
            "node",
        )
        self.assertEqual(command[command.index("--format") + 1], YOUTUBE_ORIGINAL_AUDIO_FORMAT)

    def test_normalizes_one_short_to_a_canonical_video_identity(self) -> None:
        short = "https://www.youtube.com/shorts/WPtpUu3uIUI"

        self.assertEqual(youtube_video_id(short), "WPtpUu3uIUI")
        self.assertEqual(
            canonical_youtube_url(short),
            "https://www.youtube.com/watch?v=WPtpUu3uIUI",
        )

    def test_builds_a_bounded_single_item_download(self) -> None:
        destination = Path("/tmp/watchcraft-test-audio")
        command = yt_dlp_audio_download_command(
            "https://www.youtube.com/watch?v=WPtpUu3uIUI",
            ["python", "-m", "yt_dlp"],
            destination,
            10_000_000,
        )

        self.assertIn("--no-playlist", command)
        self.assertEqual(command[command.index("--format") + 1], YOUTUBE_ORIGINAL_AUDIO_FORMAT)
        self.assertEqual(command[command.index("--max-filesize") + 1], "10000000")
        self.assertEqual(command[command.index("--output") + 1], str(destination))

    def test_download_records_observed_media_identity_without_a_temporary_url(self) -> None:
        payload = b"youtube audio bytes"
        metadata = {
            "video_id": "WPtpUu3uIUI",
            "duration": 120.0,
            "format_id": "251-20",
            "language": "en-US",
            "extension": "webm",
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "audio"

            def run_download(*args, **kwargs):
                destination.write_bytes(payload)
                return Mock(returncode=0, stdout=json.dumps(metadata), stderr="")

            with patch("youtube_audio.command_version", return_value="2026.8.19"):
                with patch("youtube_audio.subprocess.run", side_effect=run_download):
                    result = download_youtube_audio(
                        "https://www.youtube.com/shorts/WPtpUu3uIUI",
                        destination,
                        maximum_bytes=10_000_000,
                        maximum_duration_seconds=300,
                        timeout_seconds=180,
                    )

        self.assertEqual(result["video_id"], "WPtpUu3uIUI")
        self.assertEqual(result["canonical_url"], "https://www.youtube.com/watch?v=WPtpUu3uIUI")
        self.assertEqual(result["byte_length"], len(payload))
        self.assertEqual(result["duration_seconds"], 120.0)
        self.assertNotIn("url", result)

    def test_download_timeout_is_classified_and_removes_partial_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "audio"
            destination.write_bytes(b"partial")
            with patch("youtube_audio.command_version", return_value="2026.8.19"):
                with patch(
                    "youtube_audio.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(["yt-dlp"], 180),
                ):
                    with self.assertRaises(YouTubeAcquisitionError) as raised:
                        download_youtube_audio(
                            "WPtpUu3uIUI",
                            destination,
                            maximum_bytes=10_000_000,
                            maximum_duration_seconds=300,
                            timeout_seconds=180,
                        )

            self.assertFalse(destination.exists())
        self.assertEqual(raised.exception.classification, "source_acquisition_timeout")
        self.assertTrue(raised.exception.retryable)

    def test_classifies_common_provider_failures(self) -> None:
        self.assertEqual(
            classify_youtube_acquisition_failure("HTTP Error 429: Too Many Requests"),
            ("source_rate_limited", True),
        )
        self.assertEqual(
            classify_youtube_acquisition_failure("This video is private. Please sign in"),
            ("source_access_denied", False),
        )

    def test_merges_nearby_speech_ranges_but_preserves_music_gaps(self) -> None:
        self.assertEqual(
            merge_speech_ranges([(1.0, 4.0), (5.5, 8.0), (15.0, 18.0)]),
            [(1.0, 8.0), (15.0, 18.0)],
        )

    def test_normalizes_case_punctuation_and_apostrophes(self) -> None:
        self.assertEqual(
            normalized_words("Hello, DON'T stop—now!"),
            ["hello", "don't", "stop", "now"],
        )

    def test_identical_word_sequences_have_full_similarity(self) -> None:
        comparison = transcript_comparison(
            "This is a short transcript.",
            "this is a short transcript",
        )

        self.assertEqual(comparison["caption_word_count"], 5)
        self.assertEqual(comparison["whisper_word_count"], 5)
        self.assertEqual(comparison["word_count_difference"], 0)
        self.assertEqual(comparison["sequence_similarity"], 1.0)

    def test_reports_inserted_and_replaced_words(self) -> None:
        comparison = transcript_comparison(
            "one two three four",
            "one two extra five four",
        )

        self.assertEqual(comparison["caption_word_count"], 4)
        self.assertEqual(comparison["whisper_word_count"], 5)
        self.assertEqual(comparison["word_count_difference"], 1)
        self.assertLess(comparison["sequence_similarity"], 1.0)


if __name__ == "__main__":
    unittest.main()
