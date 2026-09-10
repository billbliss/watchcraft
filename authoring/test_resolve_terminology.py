import json
import unittest
from unittest.mock import Mock

import resolve_terminology


class TerminologyResolutionTests(unittest.TestCase):
    def test_corpus_resolution_separates_safe_spelling_from_semantic_ambiguity(self):
        project = {
            "project_id": "linear-algebra",
            "revision": 2,
            "metadata": {"title": "Essence of linear algebra"},
        }
        records = [{
            "item_id": "youtube:lesson",
            "source_title": "Linear combinations and basis vectors",
            "transcript": {
                "text": "The basis vectors are i hat and j hat.",
                "segments": [{
                    "start": 1.0,
                    "end": 3.0,
                    "text": "The basis vectors are i hat and j hat.",
                    "avg_logprob": -0.3,
                    "words": [{
                        "start": 2.0,
                        "end": 2.2,
                        "word": "j",
                        "probability": 0.61,
                    }],
                }],
            },
            "analysis": {
                "title": "Basis vectors",
                "summary": "The basis vectors are i_hat and j_hat.",
                "topics": ["i_hat", "j_hat"],
                "sections": [{"concepts": ["basis vectors i_hat and j_hat"]}],
            },
        }]
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[
                {
                    "observed_forms": ["i_hat"],
                    "canonical_term": "i-hat",
                    "display_label": "i-hat",
                    "classification": "orthographic-normalization",
                    "confidence": 0.99,
                    "rationale": "The underscore is a transcription spelling.",
                    "affected_items": ["youtube:lesson"],
                    "evidence": ["topic:i_hat"],
                    "alternatives": [],
                },
                {
                    "observed_forms": ["j_hat"],
                    "canonical_term": "j-hat",
                    "display_label": "j-hat",
                    "classification": "possible-acoustic-confusion",
                    "confidence": 0.82,
                    "rationale": "The audio may instead say y-hat.",
                    "affected_items": ["youtube:lesson"],
                    "evidence": ["domain:linear-algebra"],
                    "alternatives": [{"term": "y-hat", "confidence": 0.18}],
                },
            ]
        )
        client = Mock()
        client.responses.parse.return_value.output_parsed = generated

        result = resolve_terminology.infer_terminology_resolution(
            project=project,
            records=records,
            client=client,
            model="test-model",
            retries=0,
        )

        self.assertEqual(result["observed_terms"], 3)
        prompt_payload = json.loads(
            client.responses.parse.call_args.kwargs["input"][1]["content"]
        )
        i_hat = next(
            item for item in prompt_payload["observed_terms"] if item["term"] == "i_hat"
        )
        self.assertEqual(
            i_hat["transcript_evidence"][0]["excerpts"][0]["start"], 1.0
        )
        self.assertEqual(
            i_hat["transcript_evidence"][0]["excerpts"][0]["words"][0][
                "probability"
            ],
            0.61,
        )
        by_term = {item["canonical_term"]: item for item in result["resolutions"]}
        self.assertEqual(by_term["i-hat"]["disposition"], "automatic-safe")
        self.assertEqual(by_term["j-hat"]["disposition"], "needs-review")
        self.assertEqual(by_term["j-hat"]["alternatives"][0]["term"], "y-hat")

    def test_resolution_rejects_invented_unobserved_forms(self):
        payload = {
            "observed_terms": [{"term": "i_hat", "item_ids": ["youtube:lesson"]}],
            "items": [{"item_id": "youtube:lesson"}],
        }
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[{
                "observed_forms": ["invented term"],
                "canonical_term": "term",
                "display_label": "Term",
                "classification": "domain-correction",
                "confidence": 0.9,
                "rationale": "No evidence.",
                "affected_items": ["youtube:lesson"],
                "evidence": [],
                "alternatives": [],
            }]
        )

        with self.assertRaisesRegex(ValueError, "no observed corpus form"):
            resolve_terminology.normalize_resolutions(generated, payload)


if __name__ == "__main__":
    unittest.main()
