"""FR-08, FR-09: media QA flags do not trigger pointless caption refinements."""

from instabay.core.schemas import Post


def media_flags(post: Post) -> list[str]:
    """FR-08: missing semantic/video evidence stays visible at human approval."""
    if post.media_status == "concept_only":
        return ["Reel concept only: no video has been rendered"]
    if post.photo_artifact:
        artifact = post.photo_artifact
        if artifact.reference_only:
            return ["Photo reference only: source fidelity, caption and rights review required"]
        flags = ["Owner photo: check the caption describes what is visible"]
        if artifact.generated:
            flags.append("AI camera view included: confirm it still shows the real place")
        from instabay.content.photos import PhotoRecipe

        sources = PhotoRecipe.model_validate(artifact.render_recipe).sources
        small = [
            f"{o.crop.width}x{o.crop.height}"
            for o in sources
            if o.crop.width < 1080 or o.crop.height < 1080
        ]
        if small:
            flags.append(
                f"Low-resolution source ({', '.join(small)}) upscaled: "
                "use the original photo file before posting"
            )
        return flags
    if post.render_artifact:
        flags = []
        if post.render_artifact.qa_status != "passed":
            flags.append("Video QA pending: semantic, continuity and facility review required")
        if post.render_artifact.reference_only:
            flags.append("Video reference only: cannot represent approved property footage")
        return flags
    return []
