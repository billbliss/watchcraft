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
                    "evidence": ["topic:i_hat"],
                    "alternatives": [{"term": "i hat", "confidence": 0.2}],
                },
                {
                    "observed_forms": ["j_hat"],
                    "canonical_term": "j-hat",
                    "display_label": "j-hat",
                    "classification": "possible-acoustic-confusion",
                    "confidence": 0.82,
                    "rationale": "The audio may instead say y-hat.",
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
            batch_max_terms=10,
            batch_max_chars=60_000,
        )

        self.assertEqual(result["observed_terms"], 3)
        prompt_payload = json.loads(
            client.responses.parse.call_args.kwargs["input"][1]["content"]
        )
        i_hat = next(
            item for item in prompt_payload["candidate_terms"] if item["term"] == "i_hat"
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
        self.assertEqual(by_term["i-hat"]["alternatives"], [])
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
                "evidence": [],
                "alternatives": [],
            }]
        )

        with self.assertRaisesRegex(ValueError, "no observed corpus form"):
            resolve_terminology.normalize_resolutions(generated, payload)

    def test_mapper_output_is_restricted_to_forms_owned_by_its_batch(self):
        payload = {
            "observed_terms": [
                {"term": "i_hat", "item_ids": ["youtube:lesson"]},
                {"term": "j_hat", "item_ids": ["youtube:lesson"]},
            ],
            "items": [{"item_id": "youtube:lesson"}],
        }
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[
                {
                    "observed_forms": ["i_hat", "j_hat"],
                    "canonical_term": "i-hat",
                    "display_label": "i-hat",
                    "classification": "orthographic-normalization",
                    "confidence": 0.99,
                    "rationale": "Normalize mathematical notation.",
                    "evidence": ["linear algebra context"],
                    "alternatives": [],
                },
                {
                    "observed_forms": ["j_hat"],
                    "canonical_term": "j-hat",
                    "display_label": "j-hat",
                    "classification": "orthographic-normalization",
                    "confidence": 0.99,
                    "rationale": "Normalize mathematical notation.",
                    "evidence": ["linear algebra context"],
                    "alternatives": [],
                },
                {
                    "observed_forms": ["invented notation"],
                    "canonical_term": "invented-notation",
                    "display_label": "invented notation",
                    "classification": "domain-correction",
                    "confidence": 0.8,
                    "rationale": "Not grounded in a candidate.",
                    "evidence": [],
                    "alternatives": [],
                },
            ]
        )

        resolutions = resolve_terminology.normalize_resolutions(
            generated,
            payload,
            allowed_forms={"i_hat"},
        )

        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]["observed_forms"], ["i_hat"])

    def test_batched_mapper_discards_an_empty_proposal(self):
        payload = {
            "observed_terms": [
                {"term": "i_hat", "item_ids": ["youtube:lesson"]},
            ],
            "items": [{"item_id": "youtube:lesson"}],
        }
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[{
                "observed_forms": ["i_hat"],
                "canonical_term": " ",
                "display_label": " ",
                "classification": "orthographic-normalization",
                "confidence": 0.99,
                "rationale": " ",
                "evidence": [],
                "alternatives": [],
            }]
        )

        resolutions = resolve_terminology.normalize_resolutions(
            generated,
            payload,
            allowed_forms={"i_hat"},
        )

        self.assertEqual(resolutions, [])

    def test_mapper_discards_a_proposal_that_makes_no_effective_change(self):
        payload = {
            "observed_terms": [
                {"term": "coordinate system", "item_ids": ["youtube:lesson"]},
                {"term": "inverse matrix", "item_ids": ["youtube:lesson"]},
            ],
            "items": [{"item_id": "youtube:lesson"}],
        }
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[
                {
                    "observed_forms": ["coordinate system"],
                    "canonical_term": "coordinate system",
                    "display_label": "coordinate system",
                    "classification": "orthographic-normalization",
                    "confidence": 0.99,
                    "rationale": "No change is needed.",
                    "evidence": [],
                    "alternatives": [],
                },
                {
                    "observed_forms": ["inverse matrix"],
                    "canonical_term": "inverse matrix",
                    "display_label": "Inverse Matrix",
                    "classification": "orthographic-normalization",
                    "confidence": 0.99,
                    "rationale": "Use the configured display casing.",
                    "evidence": [],
                    "alternatives": [],
                },
            ]
        )

        resolutions = resolve_terminology.normalize_resolutions(generated, payload)

        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]["canonical_term"], "inverse matrix")
        self.assertEqual(resolutions[0]["display_label"], "Inverse Matrix")

    def test_semantic_expansion_cannot_be_automatic_safe(self):
        payload = {
            "observed_terms": [{"term": "vectors", "item_ids": ["youtube:lesson"]}],
            "items": [{"item_id": "youtube:lesson"}],
        }
        generated = resolve_terminology.GeneratedTerminologyResolution(
            resolutions=[{
                "observed_forms": ["vectors"],
                "canonical_term": "vectors as ordered lists of numbers",
                "display_label": "vectors as ordered lists of numbers",
                "classification": "orthographic-normalization",
                "confidence": 0.99,
                "rationale": "Expand the term using collection context.",
                "evidence": [],
                "alternatives": [],
            }]
        )

        resolutions = resolve_terminology.normalize_resolutions(generated, payload)

        self.assertEqual(resolutions[0]["disposition"], "needs-review")

    def test_resolution_batches_are_deterministic_and_bounded(self):
        payload = {
            "project": {"project_id": "example", "revision": 1, "metadata": {}},
            "items": [{
                "item_id": "youtube:lesson",
                "source_title": "Lesson",
                "analysis_title": "Lesson",
                "summary": "Summary",
            }],
            "observed_terms": [
                {"term": term, "item_ids": ["youtube:lesson"], "transcript_evidence": []}
                for term in ["alpha", "beta", "gamma"]
            ],
        }

        batches = resolve_terminology.resolution_batches(
            payload, maximum_terms=2, maximum_chars=10_000
        )

        self.assertEqual(
            [[item["term"] for item in batch["candidate_terms"]] for batch in batches],
            [["alpha", "beta"], ["gamma"]],
        )
        self.assertTrue(all(
            len(json.dumps(batch, ensure_ascii=False, sort_keys=True)) <= 10_000
            for batch in batches
        ))

    def test_resolution_batches_split_on_the_character_bound(self):
        payload = {
            "project": {"project_id": "example", "revision": 1, "metadata": {}},
            "items": [{
                "item_id": "youtube:lesson",
                "source_title": "Lesson",
                "analysis_title": "Lesson",
                "summary": "Summary",
            }],
            "observed_terms": [
                {
                    "term": term,
                    "item_ids": ["youtube:lesson"],
                    "transcript_evidence": [{
                        "item_id": "youtube:lesson",
                        "excerpts": [{"text": character * 500}],
                    }],
                }
                for term, character in [("alpha", "a"), ("beta", "b")]
            ],
        }
        one_term_chars = len(json.dumps(
            resolve_terminology.resolution_batch_payload(
                payload, [payload["observed_terms"][0]]
            ),
            ensure_ascii=False,
            sort_keys=True,
        ))

        batches = resolve_terminology.resolution_batches(
            payload, maximum_terms=10, maximum_chars=one_term_chars + 10
        )

        self.assertEqual(len(batches), 2)
        self.assertEqual(
            [[item["term"] for item in batch["candidate_terms"]] for batch in batches],
            [["alpha"], ["beta"]],
        )

    def test_reducer_merges_compatible_mapper_proposals(self):
        base = {
            "canonical_term": "i-hat",
            "display_label": "i-hat",
            "classification": "orthographic-normalization",
            "confidence": 0.98,
            "rationale": "Normalize notation.",
            "evidence": ["linear algebra context"],
            "alternatives": [],
            "disposition": "automatic-safe",
        }
        merged = resolve_terminology.merge_resolutions([
            {
                **base,
                "resolution_id": "first",
                "observed_forms": ["i_hat"],
                "affected_items": ["youtube:first"],
            },
            {
                **base,
                "resolution_id": "second",
                "observed_forms": ["i hat"],
                "affected_items": ["youtube:second"],
                "alternatives": [{"term": "i_hat", "confidence": 0.2}],
            },
        ])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["observed_forms"], ["i_hat", "i hat"])
        self.assertEqual(
            merged[0]["affected_items"], ["youtube:first", "youtube:second"]
        )
        self.assertEqual(merged[0]["disposition"], "automatic-safe")

    def test_reducer_discards_identity_proposals_from_an_imported_checkpoint(self):
        resolution = {
            "resolution_id": "old-checkpoint-resolution",
            "observed_forms": ["coordinate system"],
            "canonical_term": "coordinate system",
            "display_label": "coordinate system",
            "classification": "orthographic-normalization",
            "confidence": 0.99,
            "rationale": "No change is needed.",
            "affected_items": ["youtube:lesson"],
            "evidence": [],
            "alternatives": [],
            "disposition": "automatic-safe",
        }

        self.assertEqual(resolve_terminology.merge_resolutions([resolution]), [])

    def test_resolution_resumes_after_the_last_completed_batch(self):
        project = {
            "project_id": "linear-algebra",
            "revision": 2,
            "metadata": {"title": "Linear algebra"},
        }
        records = [{
            "item_id": "youtube:lesson",
            "source_title": "Basis vectors",
            "transcript": {"segments": []},
            "analysis": {
                "title": "Basis vectors",
                "summary": "Basis vectors use i-hat.",
                "topics": ["i_hat", "basis vectors"],
                "sections": [],
            },
        }]
        empty = resolve_terminology.GeneratedTerminologyResolution(resolutions=[])
        first_client = Mock()
        first_client.responses.parse.return_value.output_parsed = empty
        checkpoints = []

        first = resolve_terminology.infer_terminology_resolution(
            project=project,
            records=records,
            client=first_client,
            model="test-model",
            retries=0,
            batch_max_terms=1,
            batch_max_chars=60_000,
            save_checkpoint=lambda value, *_: checkpoints.append(value),
        )

        self.assertEqual(first["batches"], 2)
        self.assertEqual(first_client.responses.parse.call_count, 2)
        self.assertEqual(checkpoints[0]["next_batch"], 1)

        resumed_client = Mock()
        resumed_client.responses.parse.return_value.output_parsed = empty
        resumed = resolve_terminology.infer_terminology_resolution(
            project=project,
            records=records,
            client=resumed_client,
            model="test-model",
            retries=0,
            batch_max_terms=1,
            batch_max_chars=60_000,
            resume_checkpoint=checkpoints[0],
        )

        self.assertEqual(resumed, first)
        self.assertEqual(resumed_client.responses.parse.call_count, 1)

    def test_completed_imported_checkpoint_is_rebound_without_model_calls(self):
        project = {
            "project_id": "linear-algebra",
            "revision": 2,
            "metadata": {"title": "Linear algebra"},
        }
        records = [{
            "item_id": "youtube:lesson",
            "source_title": "Basis vectors",
            "transcript": {"segments": []},
            "analysis": {
                "title": "Basis vectors",
                "summary": "Basis vectors use i-hat.",
                "topics": ["i_hat"],
                "sections": [],
            },
        }]
        payload = resolve_terminology.corpus_observations(project, records)
        batches = resolve_terminology.resolution_batches(
            payload, maximum_terms=1, maximum_chars=60_000
        )
        checkpoint = {
            "kind": "watchcraft.terminology-resolution-checkpoint",
            "schema_version": 1,
            "source_hash": resolve_terminology.source_hash(payload),
            "batch_plan_hash": resolve_terminology.batch_plan_hash(batches),
            "batches": 1,
            "next_batch": 1,
            "mapped_resolutions": [],
        }
        rebound = []
        client = Mock()

        result = resolve_terminology.infer_terminology_resolution(
            project=project,
            records=records,
            client=client,
            model="test-model",
            retries=0,
            batch_max_terms=1,
            batch_max_chars=60_000,
            resume_checkpoint=checkpoint,
            save_checkpoint=lambda value, *progress: rebound.append((value, progress)),
        )

        client.responses.parse.assert_not_called()
        self.assertEqual(result["resolutions"], [])
        self.assertEqual(len(rebound), 1)
        self.assertEqual(rebound[0][0], checkpoint)
        self.assertEqual(rebound[0][1], (1, 1, 1, "batch 1"))

    def test_permanent_provider_request_is_not_retried(self):
        class BadRequest(Exception):
            status_code = 400

        client = Mock()
        client.responses.parse.side_effect = BadRequest("context_length_exceeded")

        with self.assertRaisesRegex(RuntimeError, "after 1 attempts") as raised:
            resolve_terminology.request_resolution(
                client,
                model="test-model",
                payload={"candidate_terms": []},
                retries=5,
            )

        self.assertFalse(raised.exception.retryable)
        self.assertEqual(client.responses.parse.call_count, 1)


if __name__ == "__main__":
    unittest.main()
