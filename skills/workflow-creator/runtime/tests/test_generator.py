import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from workflow_foundry import BriefError, compile_file, generate_coding_workflow, generate_file


ROOT = Path(__file__).resolve().parents[1]


class GeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = json.loads(
            (ROOT / "examples" / "coding-task-brief.json").read_text(encoding="utf-8")
        )

    def test_brief_generates_stable_compiled_workflow(self) -> None:
        first = generate_coding_workflow(self.brief)
        second = generate_coding_workflow(deepcopy(self.brief))
        self.assertEqual(first.digest, second.digest)
        self.assertEqual("research", first.spec["entry"])
        self.assertTrue(first.spec["policies"]["worker_protocol_required"])
        self.assertIn("diagnose", first.nodes["validate"]["routes"].values())

    def test_optional_research_review_and_effect_are_removed_cleanly(self) -> None:
        self.brief["research_required"] = False
        self.brief["human_review"] = False
        del self.brief["final_effect"]
        workflow = generate_coding_workflow(self.brief)
        self.assertEqual("plan", workflow.spec["entry"])
        self.assertNotIn("research", workflow.nodes)
        self.assertNotIn("review", workflow.nodes)
        self.assertNotIn("publish", workflow.nodes)
        self.assertEqual("complete", workflow.nodes["validate"]["routes"]["pass"])

    def test_missing_requirements_fail_before_generation(self) -> None:
        self.brief["requirements"] = []
        with self.assertRaises(BriefError):
            generate_coding_workflow(self.brief)

    def test_generated_file_round_trips_through_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workflow.json"
            generated = generate_file(ROOT / "examples" / "coding-task-brief.json", output)
            recompiled = compile_file(output)
        self.assertEqual(generated.digest, recompiled.digest)


if __name__ == "__main__":
    unittest.main()
