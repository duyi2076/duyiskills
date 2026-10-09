from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_acceptance import CHECKS, validate_acceptance  # noqa: E402
from contracts import PIPELINE_VERSION  # noqa: E402


class AIJianjiAgentAcceptanceTests(unittest.TestCase):
    def brief(self, skin_id: str = "dark-reference-fixed") -> dict:
        return {
            "schema_version": 1,
            "pipeline_version": PIPELINE_VERSION,
            "policy": "fresh-ai-lens-acceptance",
            "skin_id": skin_id,
            "inputs": {"final": {"sha256": "current"}},
            "checks": [
                {
                    "id": check_id,
                    "required_status": (
                        "not_applicable"
                        if applicability == "white-wall"
                        and skin_id != "white-wall-fusion-fixed"
                        else "passed"
                    ),
                }
                for check_id, _question, applicability in CHECKS
            ],
        }

    def review(self, brief: dict) -> dict:
        return {
            "schema_version": 1,
            "pipeline_version": PIPELINE_VERSION,
            "policy": "fresh-ai-lens-acceptance",
            "reviewer": {
                "type": "ai-agent",
                "context_mode": "fresh",
                "reviewed_at": "2026-07-25T00:00:00Z",
            },
            "inputs": copy.deepcopy(brief["inputs"]),
            "checks": [
                {
                    "id": item["id"],
                    "status": item["required_status"],
                    "evidence": "已连续观看并核对对应证据帧",
                }
                for item in brief["checks"]
            ],
            "decision": "approved",
        }

    def test_requires_all_29_checks_and_current_hashes(self) -> None:
        brief = self.brief()
        review = self.review(brief)
        self.assertEqual(len(review["checks"]), 29)
        self.assertEqual(validate_acceptance(review, brief=brief), [])
        review["inputs"]["final"]["sha256"] = "old"
        self.assertIn(
            "review inputs do not match the current video and evidence hashes",
            validate_acceptance(review, brief=brief),
        )

    def test_white_wall_checks_cannot_be_skipped_for_white_wall_skin(self) -> None:
        brief = self.brief("white-wall-fusion-fixed")
        review = self.review(brief)
        next(
            item
            for item in review["checks"]
            if item["id"] == "white-wall-transparent-stage"
        )["status"] = "not_applicable"
        errors = validate_acceptance(review, brief=brief)
        self.assertTrue(any("white-wall-transparent-stage must be passed" in item for item in errors))

    def test_fresh_ai_lens_is_required(self) -> None:
        brief = self.brief()
        review = self.review(brief)
        review["reviewer"]["context_mode"] = "inherited"
        self.assertIn(
            "reviewer.context_mode must be fresh",
            validate_acceptance(review, brief=brief),
        )


if __name__ == "__main__":
    unittest.main()
