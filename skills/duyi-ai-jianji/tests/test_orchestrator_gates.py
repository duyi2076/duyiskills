from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_acceptance import build_brief  # noqa: E402
from common import file_fingerprint, write_json  # noqa: E402
from contracts import (  # noqa: E402
    PIPELINE_VERSION,
    RUN_STATE_SCHEMA_VERSION,
    STAGE_ORDER,
    composition_contract,
)
from duyi_edit import cmd_verify, stage_template  # noqa: E402


class AIJianjiOrchestratorGateTests(unittest.TestCase):
    def prepare_run(self, root: Path) -> tuple[Path, dict]:
        run_dir = root / "run"
        for relative in (
            "artifacts",
            "review",
            "deliverable",
            "qa",
            "logs",
            "work/rhythm",
        ):
            (run_dir / relative).mkdir(parents=True, exist_ok=True)
        source = root / "source.mp4"
        source.write_bytes(b"source")
        files = {
            "artifacts/corrected-transcript.json": {"words": [{"text": "你好"}]},
            "artifacts/asr-integrity.json": {"ok": True},
            "review/cut-plan.refined.json": {"segments": [{"id": "s1"}]},
            "review/acoustic-boundaries.json": {"ok": True},
            "qa/report.json": {"ok": True},
            "review/visual-direction.json": {"schema_version": 3},
            "review/animation-plan.json": {"schema_version": 3},
            "review/semantic-reveal-timeline.json": {"events": []},
            "review/semantic-reveal.audit.json": {"ok": True},
            "artifacts/style-decision.json": {
                "skin_id": "dark-reference-fixed"
            },
            "review/rhythm-plan.json": {"policy": "adaptive-rhythm-conservative-v1"},
            "review/layout-fit-report.json": {
                "policy": "automatic-ai-layout-reflow",
                "layout_model": "measured-content-height-reflow-v1",
                "ok": True,
            },
            "work/rhythm/rhythm-manifest.json": {
                "policy": "adaptive-rhythm-conservative-v1",
                "ok": True,
            },
        }
        for relative, payload in files.items():
            write_json(run_dir / relative, payload)
        (run_dir / "deliverable" / "final.mp4").write_bytes(b"final-current")
        (run_dir / "review" / "contact-sheet.jpg").write_bytes(b"contact")
        (run_dir / "review" / "semantic-reveal-sheet.jpg").write_bytes(b"semantic")
        stages = {name: stage_template() for name in STAGE_ORDER}
        for name in STAGE_ORDER[: STAGE_ORDER.index("agent_review")]:
            stages[name]["status"] = "succeeded"
        state = {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "status": "BLOCKED",
            "created_at": "2026-07-25T00:00:00+00:00",
            "updated_at": "2026-07-25T00:00:00+00:00",
            "run_dir": str(run_dir),
            "jobs": 1,
            "composition": composition_contract(),
            "inputs": {
                "source": file_fingerprint(source),
                "asr": file_fingerprint(source),
            },
            "stages": stages,
        }
        write_json(run_dir / "run-state.json", state)
        brief = build_brief(run_dir, skin_id="dark-reference-fixed")
        write_json(run_dir / "artifacts" / "agent-review-brief.json", brief)
        return run_dir, brief

    def acceptance(self, brief: dict) -> dict:
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
                    "evidence": "fresh lens checked current artifact",
                }
                for item in brief["checks"]
            ],
            "decision": "approved",
        }

    def test_verify_accepts_current_fresh_ai_review_and_rejects_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            run_dir, brief = self.prepare_run(Path(folder))
            write_json(
                run_dir / "review" / "ai-acceptance.json",
                self.acceptance(brief),
            )
            self.assertEqual(cmd_verify(argparse.Namespace(run_dir=str(run_dir))), 0)
            state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "READY")

            (run_dir / "deliverable" / "final.mp4").write_bytes(b"replaced-final")
            self.assertNotEqual(cmd_verify(argparse.Namespace(run_dir=str(run_dir))), 0)


if __name__ == "__main__":
    unittest.main()
