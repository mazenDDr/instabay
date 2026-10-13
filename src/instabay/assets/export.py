"""FR-04, FR-06: turn reviewed library photos into the evidence/catalog the generator consumes."""

from pathlib import Path

import yaml

from instabay.assets.library import Asset, AssetLibrary
from instabay.content.evidence import ContentEvidence, VisualFact
from instabay.core.schemas import BrandConstitution
from instabay.video.direction import CropBox, ObjectCatalog, ResortObject
from instabay.video.shotlist import FileRef

PROPERTY_KEY = "property"


SCENIC_MIN = (1080, 1920)


def scenic_ready(asset: Asset) -> bool:
    """FR-06: Wan motion needs a full-resolution 9:16 scene; smaller photos get camera moves."""
    return asset.width >= SCENIC_MIN[0] and asset.height >= SCENIC_MIN[1]


def resort_object(asset: Asset, property_name: str, scenic: bool = True) -> ResortObject:
    """FR-08: owner rights confirmation is the approval; generated views stay reference-only."""
    generated = asset.origin == "generated"
    return ResortObject(
        id=asset.id,
        label=(asset.note_en if asset.described else f"Photo {asset.id}")[:60],
        observed=asset.note_en if asset.described else "",
        photo=FileRef(uri=asset.file, sha256=asset.sha256),
        crop=CropBox(x=0, y=0, width=asset.width, height=asset.height),
        approved_by=asset.added_by,
        approval_id=f"asset-library-{asset.id}",
        faces_checked=True,
        attribution=(
            f"AI-generated camera view of {asset.parent_id}"
            if generated
            else f"Photo supplied by {asset.added_by}"
        ),
        author=asset.added_by,
        license_id="ai-generated-from-owner-photo" if generated else "owner-supplied",
        source_page="instabay-asset-library",
        license_url="instabay-asset-library",
        reference_only=False,
        source="synthetic" if generated else "photo",
        approval_scope="owner_approved_view" if generated else "crop",
        allowed_actions=("photo_camera", "scenic_motion") if scenic else ("photo_camera",),
        property_name=property_name,
    )


def export_library(
    library: AssetLibrary, brand: BrandConstitution, output: Path
) -> tuple[ContentEvidence, ObjectCatalog]:
    """FR-04: every usable photo; owner descriptions become facts, the writer sees the rest."""
    property_name = str(library.setting(PROPERTY_KEY) or "Insta Bay")
    chosen = [a for a in library.all() if a.usable]
    if not chosen:
        raise ValueError("No usable photos: sort them into pillars first")
    scenic = all(scenic_ready(a) for a in chosen)
    catalog = ObjectCatalog(
        resort=property_name,
        objects=[resort_object(a, property_name, scenic) for a in chosen],
        edit_style="scenic" if scenic else "detail_reveal",
    )
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    objects_file = output / "objects.yaml"
    objects_file.write_text(
        yaml.safe_dump(catalog.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
    )
    evidence = ContentEvidence(
        property_name=property_name,
        geography=str(library.setting("geography") or "Hurghada, Red Sea, Egypt"),
        source_date_note="Photos supplied by the brand owner through the asset library.",
        objects_file=objects_file.relative_to(library.root).as_posix(),
        facts=[
            VisualFact(
                id=f"{a.id}-fact",
                scene_id=a.id,
                text=a.note_en,
                caption_en=a.note_en,
                caption_ar=a.note_ar,
            )
            for a in chosen
            if a.described
        ],
        pillar_guidance={
            p.id: (
                f"{p.description}. Use only what is visible in the selected photos; "
                "never claim facilities that are not in the brand's verified list."
            )
            for p in brand.pillars
        },
        reference_only=False,
    )
    (output / "evidence.yaml").write_text(
        yaml.safe_dump(evidence.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
    )
    evidence.objects(library.root)
    return evidence, catalog
