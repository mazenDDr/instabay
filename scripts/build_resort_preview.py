"""FR-06, NFR-03: approved photo baseline or verified recorded native motion, never publishing."""

import argparse
import json
from pathlib import Path

from instabay.core.recipe import RenderRecipe
from instabay.generation_commands import ReelCopy
from instabay.video.backends.recorded import RecordedMotionBackend
from instabay.video.files import command, digest
from instabay.video.keyframes import stub_recipe
from instabay.video.shotlist import Keyframe, Shot, ShotList
from instabay.video.studio import VideoStudio

ROOT = Path.cwd()
BASE = Path("outputs/resort-preview")
CREDIT = "Photo: Ercan.G / CC BY 3.0 - cropped and animated"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion", type=Path)
    parser.add_argument("--repeat-single-clip", action="store_true")
    args = parser.parse_args()
    original = Path("assets/photos/grand_resort_day.jpg")
    manifest = json.loads(Path("assets/photos/manifest.json").read_text())["assets"][0]
    if digest(original) != manifest["sha256"]:
        raise ValueError("Original resort photo differs")
    crop = BASE / "keyframes/day-arch.jpg"
    crop.parent.mkdir(parents=True, exist_ok=True)
    if not crop.exists():
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(original),
                "-vf",
                "crop=1296:2304:1440:0,scale=576:1024",
                "-frames:v",
                "1",
                str(crop),
            ]
        )
    approval = {
        "scope": "User-approved crops for unpublished resort previews only",
        "approved_by": "mazenDDr",
        "approval_id": "crop-approval-2026-10-12",
        "user_instruction": "the photo crops are approved",
        "parent": {"uri": str(original), "sha256": digest(original)},
        "crop": {
            "uri": str(crop),
            "sha256": digest(crop),
            "xywh": [1440, 0, 1296, 2304],
            "resize": [576, 1024],
        },
        "source_page": manifest["source_page"],
        "license_url": manifest["license_url"],
        "attribution": CREDIT,
        "faces_checked": True,
        "reference_only": True,
        "property_claims_approved": False,
    }
    (BASE / "crop-approval.json").write_text(json.dumps(approval, indent=2) + "\n")
    raw_copy = ReelCopy.model_validate_json((BASE / "copy.json").read_bytes())
    # Preserve raw model output separately from explicit editorial corrections.
    corrected = raw_copy.model_dump()
    corrected["ar"]["caption"] = (
        "أقواس بلون الطين، وسقف خشبي، وأوراق نخيل. لمحة من ماء فيروزي عبر الممر، وضوء نهار هادئ."
    )
    corrected["ar"]["alt_text"] = "أقواس بلون الطين تحت سقف خشبي، وأوراق نخيل ولمحة ماء فيروزي."
    for overlay, text in zip(
        corrected["overlays"], ["أقواس وضوء نهار", "أوراق نخيل ولمحة ماء", "لحظة هدوء"], strict=True
    ):
        overlay["ar"] = text
    copy = ReelCopy.model_validate(corrected)
    (BASE / "copy.edited.json").write_text(copy.model_dump_json(indent=2) + "\n")
    (BASE / "editorial-edits.json").write_text(
        json.dumps(
            {
                "raw_copy_sha256": digest(BASE / "copy.json"),
                "edited_copy_sha256": digest(BASE / "copy.edited.json"),
                "reason": (
                    "Raw Arabic used awkward translations and unsupported metaphors; "
                    "concise factual wording supplied in editorial post-processing."
                ),
                "human_post_approval": False,
            },
            indent=2,
        )
        + "\n"
    )
    shots = []
    clips = []
    native = None
    motion_recipe = None
    if args.motion:
        native = json.loads((args.motion / "result.json").read_text())
        motion_recipe = json.loads((args.motion / "recipe.json").read_text())
        if digest(args.motion / "recipe.json") != native["recipe_file_sha256"]:
            raise ValueError("Native recipe bytes differ")
        references = native["clips"]
        if len(references) == 1 and args.repeat_single_clip:
            references = references * 3
        if motion_recipe["spec"]["image_sha256"] != digest(crop) or len(references) != 3:
            raise ValueError(
                "Supply three conditioned clips, or explicitly --repeat-single-clip for a sample"
            )
        for ref in references:
            file = args.motion / Path(ref["file"]).name
            if digest(file) != ref["sha256"]:
                raise ValueError("Native clip bytes differ")
            clips.append({"uri": file.as_posix(), "sha256": digest(file)})
    for index, overlay in enumerate(copy.overlays):
        source = crop
        key = Keyframe(
            uri=source.as_posix(),
            sha256=digest(source),
            source="photo",
            scene="mood",
            approved_by="mazenDDr",
            approval_id=approval["approval_id"],
            faces_checked=True,
            attribution=CREDIT,
        )
        shots.append(
            Shot(
                id=f"resort-{index}",
                role=["hook", "body", "cta"][index],
                keyframe=key,
                motion_prompt="Gentle motion through the approved historical resort crop.",
                negative_prompt="No people, buildings, facilities or signs added.",
                camera="static" if native else ["push_in", "pan_right", "pull_out"][index],
                seconds=5,
                overlay=overlay,
            )
        )
    recipe = stub_recipe(ShotList(reel_id="resort-preview", duration_s=15, shots=shots), ROOT)
    data = recipe.model_dump()
    data["post"].update(
        preview_label="AI motion - historical resort photo"
        if native
        else "Real photo - camera motion preview",
        credit=CREDIT,
    )
    data["model"]["workflow"] = {
        "uri": str(args.motion / "recipe.json" if native else BASE / "generation.json"),
        "sha256": digest(args.motion / "recipe.json" if native else BASE / "generation.json"),
    }
    data["model"]["scheduler_config"] = {
        "stage": "CPU post-processing of recorded motion" if native else "photo Ken Burns",
        "native_recipe_hash": native["recipe_hash"] if native else None,
        "input_clips": native["clips"] if native else [],
    }
    if native:
        data["post"]["recorded_motion"] = {
            "backend": "wan",
            "recipe": data["model"]["workflow"],
            "recipe_hash": native["recipe_hash"],
            "conditioning_sha256": digest(crop),
            "clips": clips,
        }
    recipe = RenderRecipe.model_validate(data)
    result = VideoStudio(
        BASE / "renders.sqlite3",
        ROOT,
        BASE / ("native-renders" if native else "baseline-renders"),
        RecordedMotionBackend() if native else None,
    ).render(recipe)
    file = Path(result.file)
    sheet = Path(result.contact_sheet)
    name = "resort-ai-motion" if native else "resort-photo-preview"
    (BASE / f"{name}.mp4").write_bytes(file.read_bytes())
    (BASE / f"{name}-contact.jpg").write_bytes(sheet.read_bytes())
    en = copy.en.caption
    ar = copy.ar.caption
    if native:
        en += "\nAI-generated motion based on a historical resort photograph."
        ar += "\nحركة مولدة بالذكاء الاصطناعي اعتماداً على صورة تاريخية للمنتجع."
    captions = {
        "en": en,
        "ar": ar,
        "credit": CREDIT,
        "source_page": manifest["source_page"],
        "license_url": manifest["license_url"],
        "reference_only": True,
        "ai_disclosure": bool(native),
        "post_approved": False,
        "recipe_hash": recipe.recipe_hash,
        "copy_editorially_corrected": True,
        "unique_motion_clips": len(native["clips"]) if native else 0,
        "source_clip_reused": bool(native and len(native["clips"]) == 1),
    }
    (BASE / f"{name}-captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=2) + "\n"
    )
    print("Saved", BASE / f"{name}.mp4", "recipe", recipe.recipe_hash)


if __name__ == "__main__":
    main()
