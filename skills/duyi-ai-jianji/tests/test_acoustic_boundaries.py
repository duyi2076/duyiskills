from __future__ import annotations

from array import array
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from acoustic_vad import candidate_speech_onset, speech_regions  # noqa: E402
from refine_boundaries import choose_continuous_splice_boundary  # noqa: E402


class AIJianjiAcousticBoundaryTests(unittest.TestCase):
    def test_speech_regions_keep_media_timeline_offset(self) -> None:
        probabilities = [0.02, 0.04, 0.92, 0.98, 0.20, 0.10]
        regions = speech_regions(
            probabilities,
            timeline_offset=0.176667,
            decoded_duration=0.192,
        )
        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(regions[0]["start"], 0.240667, places=6)
        self.assertAlmostEqual(regions[0]["end"], 0.304667, places=6)

    def test_opening_can_use_speech_onset_after_early_asr_time(self) -> None:
        regions = [{"start": 0.593, "end": 4.9, "peak_probability": 0.999}]
        onset = candidate_speech_onset(
            regions,
            first_word_start=0.456,
            entry_context="opening",
            predecessor_end=None,
        )
        self.assertEqual(onset, (0.593, 0.999))

    def test_filler_region_is_not_mistaken_for_next_word(self) -> None:
        regions = [
            {"start": 5.265, "end": 6.0, "peak_probability": 1.0},
        ]
        onset = candidate_speech_onset(
            regions,
            first_word_start=5.417,
            entry_context="after-filler",
            predecessor_end=5.297,
        )
        self.assertIsNone(onset)

    def test_new_region_after_filler_is_selected(self) -> None:
        regions = [
            {"start": 24.177, "end": 24.657, "peak_probability": 0.99},
            {"start": 25.105, "end": 28.2, "peak_probability": 1.0},
        ]
        onset = candidate_speech_onset(
            regions,
            first_word_start=24.917,
            entry_context="after-filler",
            predecessor_end=24.317,
        )
        self.assertEqual(onset, (25.105, 1.0))

    def test_continuous_filler_uses_nearest_zero_crossing(self) -> None:
        samples = array("h", [100] * 160)
        samples[79] = 20
        samples[80] = -20
        samples[81] = -40
        boundary = choose_continuous_splice_boundary(
            samples,
            lower=0.004,
            upper=0.006,
            target=0.005,
        )
        self.assertAlmostEqual(boundary, 0.005, places=6)

    def test_continuous_filler_falls_back_to_exact_asr_boundary(self) -> None:
        samples = array("h", [100] * 160)
        boundary = choose_continuous_splice_boundary(
            samples,
            lower=0.004,
            upper=0.006,
            target=0.005,
        )
        self.assertAlmostEqual(boundary, 0.005, places=6)


if __name__ == "__main__":
    unittest.main()
