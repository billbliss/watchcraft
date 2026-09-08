import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "authoring-pipeline"
    / "project"
)
EXAMPLES = PROJECT_ROOT / "examples"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def structure_digest(snapshot: dict) -> str:
    projection = {
        "source": {
            key: snapshot["source"][key]
            for key in ("source_id", "source_type")
        },
        "nodes": [
            {
                key: node[key]
                for key in ("node_id", "node_type", "parent_node_id", "position")
            }
            for node in snapshot["nodes"]
        ],
        "items": [
            {
                "item_id": item["item_id"],
                "media": [
                    {key: media[key] for key in ("type", "media_id")}
                    for media in item["media"]
                ],
            }
            for item in snapshot["items"]
        ],
        "placements": [
            {
                key: placement[key]
                for key in ("placement_id", "item_id", "parent_node_id", "position")
            }
            for placement in snapshot["placements"]
        ],
    }
    payload = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CatalogProjectSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_schema = load_json(PROJECT_ROOT / "catalog-project.schema.json")
        cls.snapshot_schema = load_json(
            PROJECT_ROOT / "collection-iterator-snapshot.schema.json"
        )
        Draft202012Validator.check_schema(cls.project_schema)
        Draft202012Validator.check_schema(cls.snapshot_schema)
        cls.project_validator = Draft202012Validator(
            cls.project_schema,
            format_checker=FormatChecker(),
        )
        cls.snapshot_validator = Draft202012Validator(
            cls.snapshot_schema,
            format_checker=FormatChecker(),
        )

    def test_candidate_projects_and_iterator_snapshots_validate(self):
        for project_path in sorted(EXAMPLES.glob("*.project.json")):
            with self.subTest(project=project_path.name):
                self.project_validator.validate(load_json(project_path))
        for snapshot_path in sorted(EXAMPLES.glob("*.snapshot.json")):
            with self.subTest(snapshot=snapshot_path.name):
                self.snapshot_validator.validate(load_json(snapshot_path))

    def test_candidate_cross_document_graphs_are_coherent(self):
        for project_path in sorted(EXAMPLES.glob("*.project.json")):
            stem = project_path.name.removesuffix(".project.json")
            snapshot_path = EXAMPLES / f"{stem}.snapshot.json"
            project = load_json(project_path)
            snapshot = load_json(snapshot_path)
            with self.subTest(example=stem):
                self.assertEqual(
                    snapshot["project"],
                    {
                        "project_id": project["project_id"],
                        "revision": project["revision"],
                    },
                )
                self.assertEqual(snapshot["structure_hash"], structure_digest(snapshot))
                snapshot_bytes = snapshot_path.read_bytes()
                snapshot_digest = hashlib.sha256(snapshot_bytes).hexdigest()
                snapshot_length = len(snapshot_bytes)
                self.assertEqual(
                    snapshot["iterator"],
                    {
                        "id": project["iterator"]["id"],
                        "version": project["iterator"]["version"],
                    },
                )
                accepted_snapshot = project["iterator"]["accepted_snapshot"]
                self.assertEqual(accepted_snapshot["digest"], snapshot_digest)
                self.assertEqual(accepted_snapshot["byte_length"], snapshot_length)
                self.assertEqual(
                    accepted_snapshot["key"],
                    f"objects/sha256/{snapshot_digest[:2]}/{snapshot_digest[2:]}",
                )
                for basis in project["metadata_basis"].values():
                    if "iterator_snapshot_sha256" in basis:
                        self.assertEqual(
                            basis["iterator_snapshot_sha256"],
                            snapshot_digest,
                        )

                nodes = {node["node_id"]: node for node in snapshot["nodes"]}
                items = {item["item_id"]: item for item in snapshot["items"]}
                placement_ids = [
                    placement["placement_id"] for placement in snapshot["placements"]
                ]
                self.assertEqual(len(nodes), len(snapshot["nodes"]))
                self.assertEqual(len(items), len(snapshot["items"]))
                self.assertEqual(len(placement_ids), len(set(placement_ids)))
                roots = [
                    node for node in snapshot["nodes"]
                    if node["parent_node_id"] is None
                ]
                self.assertEqual(len(roots), 1)
                for node in snapshot["nodes"]:
                    parent = node["parent_node_id"]
                    if parent is not None:
                        self.assertIn(parent, nodes)
                    seen = {node["node_id"]}
                    while parent is not None:
                        self.assertNotIn(parent, seen)
                        seen.add(parent)
                        parent = nodes[parent]["parent_node_id"]
                for placement in snapshot["placements"]:
                    self.assertIn(placement["item_id"], items)
                    self.assertIn(placement["parent_node_id"], nodes)

                coverage = snapshot["coverage"]
                self.assertEqual(
                    coverage["expected"],
                    coverage["resolved"] + len(coverage["unresolved"]),
                )


if __name__ == "__main__":
    unittest.main()
