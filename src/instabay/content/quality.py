"""FR-08: flag concrete content defects; do not manufacture a calibrated beauty score."""

import re
from difflib import SequenceMatcher

from instabay.content.evidence import EvidenceBrief
from instabay.core.schemas import Boundary, Post


class ContentQualityReport(Boundary):
    """FR-08: inspectable flags and observed diversity; human appeal remains unmeasured."""

    post_id: str
    pillar_intent: str
    evidence_fact_ids: list[str]
    media_ids: list[str]
    flags: list[str]
    human_copy_review: str = "pending"
    engagement_lift: float | None = None


def quality_report(
    post: Post, selection: EvidenceBrief, previous: list[Post]
) -> ContentQualityReport:
    """FR-08: detect repetition, unsupported time/sensory claims and unsubstantiated offers."""
    flags = []
    unsupported = [
        r"\b(?:dawn|sunrise|sunset|morning|warm water|silence|hear|smell)\b",
        r"(?:الفجر|الشروق|الغروب|الصباح|صباح|صوت الأمواج|صمت|استمع|الاستماع|حرارة الماء)",
    ]
    for language, copy in [("en", post.en), ("ar", post.ar)]:
        text = copy.caption + " " + copy.alt_text
        if any(re.search(p, text, re.I) for p in unsupported):
            flags.append(
                f"{language}: time, sound or sensory condition is not established by the source"
            )
        if len(copy.caption.split()) > 100:
            flags.append(f"{language}: caption is too long for the concise creative preset")
        for older in previous:
            old = older.en if language == "en" else older.ar
            if SequenceMatcher(None, copy.caption.casefold(), old.caption.casefold()).ratio() > 0.8:
                flags.append(f"{language}: caption substantially repeats another post")
                break
    return ContentQualityReport(
        post_id=post.id,
        pillar_intent=selection.pillar_intent,
        evidence_fact_ids=list(selection.fact_ids),
        media_ids=list(selection.media_ids),
        flags=flags,
    )
