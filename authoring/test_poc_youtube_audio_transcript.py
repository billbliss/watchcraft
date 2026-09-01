from __future__ import annotations

import unittest

from poc_youtube_audio_transcript import (
    normalized_words,
    transcript_comparison,
)
from youtube_audio import merge_speech_ranges, yt_dlp_audio_command, yt_dlp_command


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
