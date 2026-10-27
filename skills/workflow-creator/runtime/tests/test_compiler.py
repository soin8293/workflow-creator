import json
import unittest
from copy import deepcopy
from pathlib import Path

from workflow_foundry import CompileError, compile_file, compile_workflow


ROOT = Path(__file__).resolve().parents[1]


class CompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = json.loads((ROOT / "examples" / "artifact-correction.json").read_text(encoding="utf-8"))

    def test_examples_compile_to_stable_digests(self) -> None:
        first = compile_file(ROOT / "examples" / "artifact-correction.json")
        second = compile_workflow(deepcopy(self.spec))
        research = compile_file(ROOT / "examples" / "research-report.json")
        self.assertEqual(first.digest, second.digest)
        self.assertNotEqual(first.digest, research.digest)

    def test_dangling_route_fails(self) -> None:
        self.spec["nodes"][0]["routes"]["success"] = "missing"
        with self.assertRaisesRegex(CompileError, "DANGLING_ROUTE"):
            compile_workflow(self.spec)

    def test_unreachable_node_fails(self) -> None:
        self.spec["nodes"].append({"id": "orphan", "kind": "terminal", "outcome": "orphan"})
        self.spec["terminal_nodes"].append("orphan")
        with self.assertRaisesRegex(CompileError, "UNREACHABLE_NODES"):
            compile_workflow(self.spec)

    def test_unbounded_cycle_fails(self) -> None:
        del self.spec["nodes"][0]["max_visits"]
        with self.assertRaisesRegex(CompileError, "UNBOUNDED_CYCLE"):
            compile_workflow(self.spec)

    def test_missing_outcome_route_fails(self) -> None:
        del self.spec["nodes"][1]["routes"]["error"]
        with self.assertRaisesRegex(CompileError, "OUTCOME_COVERAGE"):
            compile_workflow(self.spec)

    def test_effect_without_receipt_contract_fails(self) -> None:
        del self.spec["nodes"][3]["effect"]["receipt_type"]
        with self.assertRaisesRegex(CompileError, "EFFECT_CONTRACT"):
            compile_workflow(self.spec)

    def test_empty_objective_fails(self) -> None:
        self.spec["objective"] = "  "
        with self.assertRaisesRegex(CompileError, "OBJECTIVE_REQUIRED"):
            compile_workflow(self.spec)

    def test_unknown_output_contract_fails(self) -> None:
        self.spec["nodes"][0]["output_contract"] = "missing_contract"
        with self.assertRaisesRegex(CompileError, "UNKNOWN_OUTPUT_CONTRACT"):
            compile_workflow(self.spec)

    def test_conflicting_worker_authority_fails(self) -> None:
        self.spec["nodes"][0]["executor"]["forbidden_actions"].append("test")
        with self.assertRaisesRegex(CompileError, "EXECUTOR_AUTHORITY_CONFLICT"):
            compile_workflow(self.spec)

    def test_missing_independence_target_fails(self) -> None:
        self.spec["nodes"][1]["executor"]["independent_from"] = ["missing"]
        with self.assertRaisesRegex(CompileError, "INDEPENDENCE_TARGET"):
            compile_workflow(self.spec)


if __name__ == "__main__":
    unittest.main()
