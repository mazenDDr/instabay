"""FR-07, FR-08: missing/failing QA never masquerades as a passing render."""

import struct
from pathlib import Path

import pytest

from instabay.video.keyframes import stub_recipe
from instabay.video.qa import VisualEvidence, evaluate, faststart
from tests.unit.test_video_recipe import ROOT, shotlist


def test_faststart_parses_atoms_not_payload_substrings(tmp_path: Path) -> None:
    file = tmp_path / "test.mp4"
    file.write_bytes(struct.pack(">I4s", 12, b"mdat") + b"moov" + struct.pack(">I4s", 8, b"moov"))
    assert not faststart(file)
    file.write_bytes(struct.pack(">I4s", 8, b"moov") + struct.pack(">I4s", 8, b"mdat"))
    assert faststart(file)
    file.write_bytes(struct.pack(">I4s", 9999, b"moov"))
    assert not faststart(file)


@pytest.mark.parametrize("problem", ["missing", "seam", "semantic", "palette", "subject"])
def test_optional_visual_gate_must_pass_every_dimension(
    tmp_path: Path, monkeypatch, problem: str
) -> None:
    from instabay.video.qa import VideoQA

    spec = VideoQA(
        spec_ok=True,
        width=1080,
        height=1920,
        fps=30,
        duration_s=15,
        size_bytes=1000,
        moov_at_front=True,
        violations=[],
        status="needs_review",
    )
    monkeypatch.setattr("instabay.video.qa.check_spec", lambda *args: spec)
    monkeypatch.setattr("instabay.video.qa.command", lambda *args: bytes([20]) * 1792 * 450)
    recipe = stub_recipe(shotlist(), ROOT)

    class FakeVisual:
        def evaluate(self, *args):
            return VisualEvidence(
                provider="synthetic-fixture",
                synthetic=True,
                seam_similarity=[0.5 if problem == "seam" else 0.98] * 2,
                subject_consistency=0.5 if problem == "subject" else 0.98,
                background_consistency=0.99,
                palette_distance=0.5 if problem == "palette" else 0.01,
                planned_scene=problem != "semantic",
                distorted_faces_or_hands=False,
                stray_text=False,
            )

    qa = evaluate(tmp_path / "test.mp4", recipe, None if problem == "missing" else FakeVisual())
    assert qa.spec_ok and qa.status == "needs_review" and qa.violations


@pytest.mark.parametrize("scope", ["whole_reel", "within_shots"])
def test_directed_cuts_require_within_shot_fidelity_not_identical_subjects(
    tmp_path: Path, monkeypatch, scope: str
) -> None:
    from instabay.core.recipe import RenderRecipe
    from instabay.video.qa import VideoQA

    spec = VideoQA(
        spec_ok=True,
        width=1080,
        height=1920,
        fps=30,
        duration_s=15,
        size_bytes=1000,
        moov_at_front=True,
        violations=[],
        status="needs_review",
    )
    monkeypatch.setattr("instabay.video.qa.check_spec", lambda *args: spec)
    monkeypatch.setattr("instabay.video.qa.command", lambda *args: bytes([20]) * 1792 * 450)
    data = stub_recipe(shotlist(), ROOT).model_dump()
    data["post"].update(style="editorial", language="en", latin_font=data["post"]["font"])
    recipe = RenderRecipe.model_validate(data)

    class FixtureVisual:
        def evaluate(self, *args):
            return VisualEvidence(
                provider="offline-fixture",
                synthetic=True,
                seam_similarity=[0.1, 0.2],
                subject_consistency=0.99,
                background_consistency=0.99,
                palette_distance=0.01,
                planned_scene=True,
                distorted_faces_or_hands=False,
                stray_text=False,
                consistency_scope=scope,
                editorial_brief_match=True,
                object_actions_readable=True,
            )

    result = evaluate(tmp_path / "film.mp4", recipe, FixtureVisual())
    assert result.status == ("passed" if scope == "within_shots" else "needs_review")
    assert "DINO seam continuity failed" not in result.violations
