"""FR-04, FR-09: a review gallery uses actual outputs, source links and caption snapshots."""

import json
import shutil
from pathlib import Path
from typing import Any

from instabay.content.photos import PhotoRecipe
from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Post
from instabay.video.direction import VideoBoard
from instabay.video.files import digest

PILLAR_NAMES = {
    "underwater": "Water & nature",
    "spa": "Relaxation",
    "guests": "Stay inspiration",
    "local": "The setting",
    "offers": "Travel planning",
}


def export_gallery(
    posts: list[Post], pillars: dict[str, str], root: Path, output: Path, *, synthetic: bool
) -> Path:
    """FR-09: copy reviewable artifacts without changing approval snapshots or publishing."""
    output.mkdir(parents=True, exist_ok=True)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    items: list[dict[str, Any]] = []
    for post in posts:
        images = []
        video = None
        sources = []
        if post.photo_artifact:
            for i, file in enumerate(post.photo_artifact.files, 1):
                target = assets / f"{post.id}-{i}.jpg"
                shutil.copyfile(file.file, target)
                images.append(
                    {"uri": target.relative_to(output).as_posix(), "sha256": digest(target)}
                )
            recipe = PhotoRecipe.model_validate(post.photo_artifact.render_recipe)
            for source in recipe.sources:
                sources.append(
                    {
                        "page": source.source_page,
                        "author": source.author,
                        "scene": source.id,
                    }
                )
        if post.render_artifact:
            target = assets / f"{post.id}.mp4"
            shutil.copyfile(post.render_artifact.file, target)
            poster = assets / f"{post.id}-contact.jpg"
            shutil.copyfile(post.render_artifact.contact_sheet, poster)
            video = {
                "uri": target.relative_to(output).as_posix(),
                "sha256": digest(target),
                "contact": poster.relative_to(output).as_posix(),
            }
            render_recipe = RenderRecipe.model_validate(post.render_artifact.render_recipe)
            board_ref = render_recipe.model.workflow
            if board_ref:
                board = VideoBoard.model_validate_json((root / board_ref.uri).read_bytes())
                sources = [
                    {"page": o.source_page, "author": o.author, "scene": o.id}
                    for o in board.catalog.objects
                ]
        items.append(
            {
                "id": post.id,
                "pillar": pillars[post.id],
                "pillar_name": PILLAR_NAMES.get(pillars[post.id], pillars[post.id]),
                "format": post.format,
                "captions": {"en": post.full_caption("en"), "ar": post.full_caption("ar")},
                "images": images,
                "video": video,
                "sources": sources,
                "approved": False,
                "generated": post.ai_disclosure,
                "content_hash": post.content_hash,
            }
        )
    property_name = (
        posts[0].evidence.context["property_name"]
        if posts and posts[0].evidence
        else "Reference campaign"
    )
    data = {"property": property_name, "synthetic": synthetic, "published": False, "items": items}
    (output / "gallery.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    # The companion JSON preserves hashes; the page needs only display data.
    display = {
        **data,
        "items": [
            {
                **{k: v for k, v in item.items() if k != "content_hash"},
                "images": [{"uri": im["uri"]} for im in item["images"]],
                "video": {k: v for k, v in item["video"].items() if k != "sha256"}
                if item["video"]
                else None,
            }
            for item in items
        ],
    }
    payload = json.dumps(display, ensure_ascii=False).replace("<", "\\u003c")
    template = (Path(__file__).parent / "gallery.html").read_text()
    page = output / "index.html"
    page.write_text(template.replace("__CAMPAIGN_DATA__", payload))
    return page
