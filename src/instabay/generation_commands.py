"""FR-04: native bilingual previews and real generation through existing approval boundaries."""

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import Field, field_validator

from instabay.adapters.native_llm import NativeLLMClient
from instabay.core.schemas import Boundary, Copy
from instabay.db import SQLiteCallStore
from instabay.llm import LLMService
from instabay.video.shotlist import Overlay


class ReelCopy(Boundary):
    """FR-04, FR-06: native EN/AR captions and three short independent overlays."""

    en: Copy
    ar: Copy
    overlays: list[Overlay] = Field(min_length=3, max_length=3)

    @field_validator("en", "ar")
    @classmethod
    def short_caption(cls, value: Copy) -> Copy:
        if len(value.caption) > 350:
            raise ValueError("Preview captions must fit 350 characters")
        return value

    @field_validator("overlays")
    @classmethod
    def short_overlays(cls, value: list[Overlay]) -> list[Overlay]:
        if any(len(item.en) > 45 or len(item.ar) > 45 for item in value):
            raise ValueError("Preview overlays must fit 45 characters")
        return value


class ArabicPreview(Boundary):
    """FR-04: Arabic-native generation is independently schema-validated."""

    caption: str = Field(min_length=1, max_length=350)
    alt_text: str = Field(min_length=1, max_length=350)
    overlays: list[Annotated[str, Field(min_length=1, max_length=45)]] = Field(
        min_length=3, max_length=3
    )


def register_generation_commands(app: typer.Typer) -> None:
    """FR-09: generation outputs are previews, never human decisions or publications."""

    @app.command("generate-preview")
    def preview(
        model: Annotated[str, typer.Option()],
        origin: Annotated[str, typer.Option()] = "http://127.0.0.1:18765",
        brief: Annotated[Path, typer.Option()] = Path("config/resort-preview.yaml"),
        output: Annotated[Path, typer.Option()] = Path("outputs/resort-preview/copy.json"),
        db: Annotated[Path, typer.Option()] = Path("outputs/resort-preview/llm.sqlite3"),
        confirm_generation: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """FR-04: real model response, exact prompt provenance, logged usage and schema checks."""
        if not confirm_generation:
            raise typer.BadParameter("Native generation requires --confirm-generation")
        client = NativeLLMClient(origin, model, confirm_external=True)
        try:
            with SQLiteCallStore(db) as store:
                before = len(store.calls())
                service = LLMService(
                    client,
                    store,
                    model_overrides={"resort_preview": model, "resort_preview_ar": model},
                )
                result = service.generate(
                    template_name="resort_preview",
                    slot_id="real-resort-preview",
                    inputs=json.loads(json.dumps(yaml.safe_load(brief.read_text()))),
                    output_type=ReelCopy,
                    max_output_tokens=1200,
                )
                arabic = service.generate(
                    template_name="resort_preview_ar",
                    slot_id="real-resort-preview-ar",
                    inputs={
                        "english": result.en.caption,
                        "overlays": [s.en for s in result.overlays],
                    },
                    output_type=ArabicPreview,
                    max_output_tokens=500,
                )
                result = ReelCopy(
                    en=result.en,
                    ar=Copy(caption=arabic.caption, alt_text=arabic.alt_text),
                    overlays=[
                        Overlay(en=old.en, ar=new)
                        for old, new in zip(result.overlays, arabic.overlays, strict=True)
                    ],
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                metadata = {
                    "model": model,
                    "stages": [c.model_dump(mode="json") for c in store.calls()[before:]],
                    "usage": service.usage.model_dump(),
                    "reference_only": True,
                    "note": "Unpublished real-model preview; no calibrated judge or post approval.",
                }
                output.with_name("generation.json").write_text(
                    json.dumps(metadata, indent=2) + "\n"
                )
                typer.echo(
                    f"Real bilingual preview saved to {output}; no post was approved or published."
                )
        finally:
            client.close()
