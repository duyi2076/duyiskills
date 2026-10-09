from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
CONFIG = ROOT / "assets" / "composition" / "semantic-stage" / "config.example.json"
SELECTOR = ROOT / "scripts" / "select_visual_style.py"
STYLES = ROOT / "assets" / "composition" / "style-presets.json"
ROUTING = ROOT / "assets" / "composition" / "style-routing.json"


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AIJianjiLightSkinTests(unittest.TestCase):
    def test_manual_light_skin_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            output_path = root / "decision.json"
            input_path.write_text(
                json.dumps(
                    {
                        "user_style": "white-wall-fusion-fixed",
                        "user_reason": "拍摄背景是白墙。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SELECTOR),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("user_confirmed=true", completed.stderr)

    def test_light_skin_is_manual_only_and_dark_stays_default(self) -> None:
        styles = json.loads(STYLES.read_text(encoding="utf-8"))
        dark = styles["presets"]["dark-reference-fixed"]
        light = styles["presets"]["white-wall-fusion-fixed"]

        self.assertEqual(styles["default"], "dark-reference-fixed")
        self.assertTrue(dark["auto_eligible"])
        self.assertFalse(light["auto_eligible"])
        self.assertEqual(dark["panel"], "#0A141B")
        self.assertEqual(dark["panel_opacity"], 0.82)
        self.assertEqual(dark["text_primary"], "#F3F5F7")
        self.assertEqual(dark["text_secondary"], "#A7ADB4")
        self.assertEqual(set(dark["paint_tokens"]), set(light["paint_tokens"]))
        self.assertEqual(light["panel"], "#0A141B")
        self.assertEqual(light["panel_opacity"], 0.82)
        self.assertEqual(light["text_primary"], "#17212B")
        self.assertEqual(light["paint_tokens"]["panel_text_primary"], "#F3F5F7")
        self.assertEqual(light["paint_tokens"]["stage_feather_opacity"], 0.0)
        self.assertEqual(light["paint_tokens"]["fullscreen_opacity"], 0.0)

    def test_selector_accepts_explicit_light_skin_but_never_ai_routes_to_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="composition-light-select-") as folder:
            root = Path(folder)
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text(
                json.dumps(
                    {
                        "user_style": "white-wall-fusion-fixed",
                        "user_confirmed": True,
                        "user_reason": "拍摄背景是白墙，明确使用融合皮肤。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SELECTOR),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            decision = json.loads(output_path.read_text(encoding="utf-8"))
            styles = json.loads(STYLES.read_text(encoding="utf-8"))
            tokens = styles["presets"]["white-wall-fusion-fixed"]["paint_tokens"]
            self.assertEqual(decision["source"], "user_override")
            self.assertEqual(decision["style_id"], "white-wall-fusion-fixed")
            self.assertEqual(decision["skin_id"], "white-wall-fusion-fixed")
            self.assertEqual(decision["paint_tokens_sha256"], canonical_sha256(tokens))

            routed = json.loads(ROUTING.read_text(encoding="utf-8"))
            routed["auto_profiles"]["knowledge_explainer"]["style_id"] = (
                "white-wall-fusion-fixed"
            )
            routing_path = root / "routing.json"
            routing_path.write_text(
                json.dumps(routed, ensure_ascii=False),
                encoding="utf-8",
            )
            input_path.write_text(
                json.dumps(
                    {
                        "ai_assessment": {
                            "profile": "knowledge_explainer",
                            "confidence": 1.0,
                            "reasons": ["自动画像不能越过手动皮肤边界。"],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_path.unlink()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SELECTOR),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--routing",
                    str(routing_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manual-only", result.stderr)

    def test_two_skins_share_dom_timeline_assertions_and_fonts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="composition-skin-parity-") as folder:
            root = Path(folder)
            dark_output = root / "dark"
            light_output = root / "light"
            subprocess.run(
                [sys.executable, str(BUILDER), str(CONFIG), str(dark_output)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    str(CONFIG),
                    str(light_output),
                    "--style",
                    "white-wall-fusion-fixed",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            dark_spec = json.loads(
                (dark_output / "overlay-spec.json").read_text(encoding="utf-8")
            )
            light_spec = json.loads(
                (light_output / "overlay-spec.json").read_text(encoding="utf-8")
            )
            dark_html = (dark_output / "index.html").read_text(encoding="utf-8")
            light_html = (light_output / "index.html").read_text(encoding="utf-8")
            dark_body = re.search(r"<body>(.*)</body>", dark_html, re.DOTALL)
            light_body = re.search(r"<body>(.*)</body>", light_html, re.DOTALL)

            self.assertIsNotNone(dark_body)
            self.assertIsNotNone(light_body)
            self.assertEqual(dark_body.group(1), light_body.group(1))
            self.assertEqual(
                (dark_output / "index.motion.json").read_bytes(),
                (light_output / "index.motion.json").read_bytes(),
            )
            self.assertEqual(
                dark_spec["timeline_contract"],
                light_spec["timeline_contract"],
            )
            self.assertEqual(
                dark_spec["timeline_contract"]["id"],
                "semantic-stage-timeline-v1",
            )
            self.assertNotEqual(
                dark_spec["paint_tokens_sha256"],
                light_spec["paint_tokens_sha256"],
            )
            self.assertEqual(dark_spec["skin_id"], "dark-reference-fixed")
            self.assertEqual(light_spec["skin_id"], "white-wall-fusion-fixed")
            self.assertEqual(
                dark_spec["font_family_id"],
                light_spec["font_family_id"],
            )
            self.assertEqual(
                dark_spec["animation_font_file"],
                light_spec["animation_font_file"],
            )
            self.assertEqual(
                dark_spec["reference_contract"]["panel_rgba"],
                [10, 20, 27, 0.82],
            )
            self.assertEqual(
                light_spec["reference_contract"]["panel_rgba"],
                [10, 20, 27, 0.82],
            )
            self.assertEqual(
                light_spec["source_background_policy"],
                "transparent-stage",
            )
            self.assertEqual(
                light_spec["reference_contract"]["stage_feather_rgba"],
                [255, 255, 255, 0.0],
            )
            self.assertEqual(
                light_spec["reference_contract"]["full_field_overlay_opacity"],
                0.0,
            )
            self.assertEqual(
                light_spec["reference_contract"]["free_text_primary"],
                "#17212B",
            )
            self.assertEqual(
                light_spec["reference_contract"]["panel_text_primary"],
                "#F3F5F7",
            )
            self.assertIn("background: none;", light_html)
            self.assertIn(
                "1.5px 0 0 rgba(255,255,255,.92)",
                light_html,
            )
            self.assertNotIn("rgba(252, 250, 246, 0.94)", light_html)

    def test_selector_rejects_unknown_paint_or_timing_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="composition-token-gate-") as folder:
            root = Path(folder)
            styles = json.loads(STYLES.read_text(encoding="utf-8"))
            bad_styles = copy.deepcopy(styles)
            bad_styles["presets"]["dark-reference-fixed"]["paint_tokens"][
                "container_entry_seconds"
            ] = 0.01
            styles_path = root / "styles.json"
            styles_path.write_text(
                json.dumps(bad_styles, ensure_ascii=False),
                encoding="utf-8",
            )
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SELECTOR),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--styles",
                    str(styles_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("locked whitelist", result.stderr)
            self.assertIn("container_entry_seconds", result.stderr)

    def test_white_wall_generation_tokens_are_fixed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="composition-white-wash-") as folder:
            root = Path(folder)
            styles = json.loads(STYLES.read_text(encoding="utf-8"))
            styles["presets"]["white-wall-fusion-fixed"]["paint_tokens"][
                "stage_feather_opacity"
            ] = 0.01
            styles_path = root / "styles.json"
            styles_path.write_text(
                json.dumps(styles, ensure_ascii=False),
                encoding="utf-8",
            )
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text(
                json.dumps(
                    {
                        "user_style": "white-wall-fusion-fixed",
                        "user_confirmed": True,
                        "user_reason": "用户确认白墙融合。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SELECTOR),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--styles",
                    str(styles_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fixed to a transparent stage", result.stderr)

    def test_builder_rejects_config_level_skin_or_css_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="composition-config-paint-") as folder:
            root = Path(folder)
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            config["paint_tokens"] = {"text_primary": "#000000"}
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(config, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    str(config_path),
                    str(root / "out"),
                    "--style",
                    "white-wall-fusion-fixed",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("config cannot contain paint_tokens", result.stderr)



if __name__ == "__main__":
    unittest.main()
