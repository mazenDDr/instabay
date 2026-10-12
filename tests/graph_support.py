"""NFR-07: synthetic frozen brand/media/approvals for offline Graph contracts only."""

import hashlib
from datetime import date
from pathlib import Path

from instabay.adapters.graph_http import StubMediaVerifier
from instabay.adapters.graph_models import GraphConfig
from instabay.adapters.graph_publisher import GraphPublisher
from instabay.adapters.graph_transport import FixtureGraphTransport
from instabay.core.hashtags import select_hashtags
from instabay.core.planner import plan_week
from instabay.core.schemas import (
    ApprovalRequest,
    Brief,
    Copy,
    MediaAsset,
    MediaManifest,
    Post,
    PostFormat,
    ReelConcept,
    WorkflowInput,
    canonical_hash,
)
from instabay.repository import Repository
from tests.support import demo_brand, save_review

GRAPH_CONFIG = GraphConfig(media_hosts=("cdn.example.org",))
FIXTURES = Path("tests/fixtures/graph")


def media(format: PostFormat) -> MediaManifest:
    image = MediaAsset(
        url="https://cdn.example.org/photo.jpg",
        content_sha256=hashlib.sha256(b"jpeg").hexdigest(),
        kind="image",
        size_bytes=4,
        width=1080,
        height=1350,
        mime_type="image/jpeg",
        color_space="sRGB",
    )
    assets = [image]
    recipe: dict[str, object] = {"backend": "wan", "seed": 42}
    if format == "carousel":
        assets.append(image.model_copy(update={"url": "https://cdn.example.org/photo2.jpg"}))
    elif format == "reel":
        assets = [
            MediaAsset(
                url="https://cdn.example.org/reel.mp4",
                content_sha256=hashlib.sha256(b"video").hexdigest(),
                kind="video",
                size_bytes=5,
                width=1080,
                height=1920,
                mime_type="video/mp4",
                duration_s=10,
                fps=24,
                video_codec="h264",
                audio_codec="aac",
                audio_sample_rate=48000,
                moov_at_front=True,
            )
        ]
    return MediaManifest.model_validate(
        {
            "format": format,
            "assets": assets,
            "verified_by": "synthetic-test-human",
            "reference_only": False,
            "generated": format == "reel",
            "cover": image if format == "reel" else None,
            "render_recipe": recipe if format == "reel" else None,
            "recipe_hash": canonical_hash(recipe) if format == "reel" else None,
        }
    )


def live_post(
    repository: Repository, format: PostFormat = "photo", *, approved: bool = True
) -> Post:
    brand = demo_brand()
    digest = repository.register_brand(brand, actor="synthetic-test-human")
    request = WorkflowInput(run_id="graph-fixture-w42", week_start=date(2026, 10, 12), demo=False)
    repository.start_run(request, digest)
    slots = plan_week(brand, digest, request.run_id, request.week_start)
    if format == "carousel":
        first = slots[0]
        slots[0] = first.model_copy(update={"arm": first.arm.model_copy(update={"format": format})})
    repository.save_slots(slots)
    slot = next(slot for slot in slots if slot.arm.format == format)
    post = Post(
        id=slot.id,
        slot_id=slot.id,
        brand_hash=digest,
        format=format,
        brief=Brief(
            angle="quiet",
            hook="number",
            key_message="A slower moment",
            visual_description="Terracotta arches and palms",
            photo_uri="reference.jpg",
            cta="save",
            must_not=["unverified claims"],
            reel_concept=ReelConcept(
                hook="quiet",
                shots=["arches"],
                overlay_en="light",
                overlay_ar="ضوء",
                audio="quiet",
                cta="save",
                cover="arches",
            )
            if format == "reel"
            else None,
        ),
        en=Copy(
            caption="Three reasons to slow down: light, shade, quiet.", alt_text="Arches and palms"
        ),
        ar=Copy(caption="ثلاث لحظات على مهل: ضوء، وظلال، وهدوء.", alt_text="أقواس ونخيل"),
        hashtags=select_hashtags(brand),
        prompt_hashes={"copy_en": "a" * 64, "copy_ar": "b" * 64},
        media_status="rendered" if format == "reel" else "ready",
        media_manifest=media(format),
        ai_disclosure=format == "reel",
    )
    repository.save_post(post)
    save_review(repository, post)
    if approved:
        repository.approve(
            post.id,
            ApprovalRequest(
                decision="APPROVED",
                actor="synthetic-test-human",
                reason="Offline contract only",
                seconds_spent=1,
            ),
        )
    return post


def publisher(
    repository: Repository, scenario: str, *, sleeps: list[float] | None = None
) -> tuple[GraphPublisher, FixtureGraphTransport]:
    transport = FixtureGraphTransport(FIXTURES / f"{scenario}.json")
    return GraphPublisher(
        repository,
        GRAPH_CONFIG,
        transport,
        account_id="1000",
        confirm_live=True,
        verifier=StubMediaVerifier(),
        sleep=(sleeps if sleeps is not None else []).append,
    ), transport
