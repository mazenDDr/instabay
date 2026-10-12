"""FR-05, NFR-03: ordered photo/carousel previews preserve the complete source composition."""

import sqlite3
from pathlib import Path
from typing import Literal, Protocol, Self

from PIL import Image, ImageOps
from pydantic import Field, model_validator

from instabay.content.evidence import EvidenceBrief
from instabay.core.recipe import RuntimeIdentity
from instabay.core.schemas import Boundary, LocalPhotoPreview, PhotoRenderAttachment, canonical_hash
from instabay.video.direction import ResortObject
from instabay.video.files import RenderError, digest, local_file
from instabay.video.keyframes import runtime_identity


class PhotoRecipe(Boundary):
    """NFR-03: source bytes, rights, ordered images and actual rendering implementation."""

    kind: Literal["reference-photo-layout-v1"] = "reference-photo-layout-v1"
    format: Literal["photo", "carousel"]
    sources: list[ResortObject]
    layout: Literal["contain"] = "contain"
    background: Literal["#e8eeee"] = "#e8eeee"
    width: Literal[1080] = 1080
    height: Literal[1350] = 1350
    runtime: RuntimeIdentity
    story: EvidenceBrief | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def sequence(self) -> Self:
        count = len(self.sources)
        if (self.format == "photo" and count != 1) or (
            self.format == "carousel" and not 2 <= count <= 5
        ):
            raise ValueError("Photo recipe sources must match the planned format")
        if len({s.photo.sha256 for s in self.sources}) != count:
            raise ValueError("Photo recipe cannot repeat the same source bytes")
        if self.story and self.story.media_ids != [s.id for s in self.sources]:
            raise ValueError("Carousel order must match its evidence-bound story")
        if len({s.property_name for s in self.sources}) > 1:
            raise ValueError("One property carousel cannot silently combine different resorts")
        return self

    @property
    def recipe_hash(self) -> str:
        return canonical_hash(self)


class PhotoRenderer(Protocol):
    """NFR-05: image assembly is independent of content generation and storage."""

    def render(self, source: Path, output: Path, recipe: PhotoRecipe) -> None: ...


class ContainPhotoRenderer:
    """FR-05: preserve buildings and shoreline together instead of cropping anonymous textures."""

    def render(self, source: Path, output: Path, recipe: PhotoRecipe) -> None:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            if image.width < 1080 or image.height < 1350:
                raise RenderError("A feed photograph needs sufficient original resolution")
            image = ImageOps.contain(image, (recipe.width, recipe.height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (recipe.width, recipe.height), recipe.background)
        canvas.paste(
            image, ((recipe.width - image.width) // 2, (recipe.height - image.height) // 2)
        )
        canvas.save(output, "JPEG", quality=95, subsampling=0)


class PhotoStudio:
    """NFR-03: store the recipe before image work and verify all inputs/cache bytes."""

    def __init__(
        self, root: Path, directory: Path, db: Path, renderer: PhotoRenderer | None = None
    ) -> None:
        self.root, self.directory = root.resolve(), directory.resolve()
        self.renderer = renderer or ContainPhotoRenderer()
        self.db = db

    def render(self, recipe: PhotoRecipe) -> PhotoRenderAttachment:
        if recipe.runtime != runtime_identity():
            raise RenderError("Photo rendering runtime differs from the stored recipe")
        count = len(recipe.sources)
        if (recipe.format == "photo" and count != 1) or (
            recipe.format == "carousel" and not 2 <= count <= 5
        ):
            raise RenderError("Photograph count does not match its planned format")
        if len({s.photo.sha256 for s in recipe.sources}) != count:
            raise RenderError("A carousel needs different source photographs")
        paths = [local_file(self.root, s.photo) for s in recipe.sources]
        directory = self.directory / recipe.recipe_hash
        directory.mkdir(parents=True, exist_ok=True)
        result_file = directory / "result.json"
        if result_file.exists():
            result = PhotoRenderAttachment.model_validate_json(result_file.read_bytes())
            if result.render_recipe != recipe.model_dump(mode="json"):
                raise RenderError("Cached photo provenance changed")
            for file in result.files:
                if digest(Path(file.file)) != file.file_sha256:
                    raise RenderError("Cached photograph bytes changed")
            return result
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS photo_render_job "
                "(recipe_hash TEXT PRIMARY KEY, recipe_json TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO photo_render_job VALUES (?,?)",
                (recipe.recipe_hash, recipe.model_dump_json()),
            )
        (directory / "recipe.json").write_text(recipe.model_dump_json(indent=2) + "\n")
        files = []
        for i, path in enumerate(paths):
            output = directory / f"photo-{i + 1}.jpg"
            self.renderer.render(path, output, recipe)
            with Image.open(output) as image:
                if image.size != (1080, 1350) or image.mode != "RGB":
                    raise RenderError("Photo renderer returned an invalid feed specification")
            files.append(LocalPhotoPreview(file=str(output), file_sha256=digest(output)))
        result = PhotoRenderAttachment(
            recipe_hash=recipe.recipe_hash,
            render_recipe=recipe.model_dump(mode="json"),
            files=files,
            reference_only=any(s.reference_only for s in recipe.sources),
            generated=any(s.source == "synthetic" for s in recipe.sources),
        )
        result_file.write_text(result.model_dump_json(indent=2) + "\n")
        return result
