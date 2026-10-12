"""FR-08, FR-09: media QA flags do not trigger pointless caption refinements."""

from instabay.core.schemas import Post


def media_flags(post: Post) -> list[str]:
    """FR-08: missing semantic/video evidence stays visible at human approval."""
    if post.media_status == "concept_only":
        return ["Reel concept only: no video has been rendered"]
    if post.render_artifact:
        flags = []
        if post.render_artifact.qa_status != "passed":
            flags.append("Video QA pending: semantic, continuity and facility review required")
        if post.render_artifact.reference_only:
            flags.append("Video reference only: cannot represent approved property footage")
        return flags
    return []
