"""FR-05, FR-08: deterministic caption/claim checks precede the model judge."""

import re
import unicodedata

from instabay.core.schemas import BrandConstitution, Post, RuleResult

TAG = re.compile(r"(?<!\w)[#@]\w+", re.UNICODE)
PRICE = re.compile(
    r"[$€£]|\b(?:EGP|USD|AED|SAR)\b|\d+\s*(?:جنيه|ريال|%|percent)|"
    r"(?:free night|night free|ليلة مجانية|ليلة مجاناً|خصم)",
    re.I,
)


def arabic_script_ratio(text: str) -> float:
    """FR-04: exclude hashtags/mentions, then compare Arabic letters to all letters."""
    letters = [letter for letter in TAG.sub("", text) if letter.isalpha()]
    if not letters:
        return 0
    return sum("ARABIC" in unicodedata.name(letter, "") for letter in letters) / len(letters)


def check_rules(post: Post, brand: BrandConstitution) -> RuleResult:
    """FR-08: check final captions including selected tags and mandatory AI disclosure."""
    violations = []
    for language in ("en", "ar"):
        body = post.en if language == "en" else post.ar
        caption = post.full_caption("en" if language == "en" else "ar")
        if len(caption) > 2200:
            violations.append(f"{language}: final caption exceeds 2200 characters")
        if len(re.findall(r"(?<!\w)#\w+", caption)) > 30:
            violations.append(f"{language}: more than 30 hashtags")
        if len(re.findall(r"(?<!\w)@\w+", caption)) > 20:
            violations.append(f"{language}: more than 20 mentions")
        emoji = sum(
            (0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF)
            and not 0x1F3FB <= ord(c) <= 0x1F3FF
            for c in body.caption
        )
        if emoji > brand.claims_policy.emoji_budget:
            violations.append(f"{language}: emoji budget exceeded")
        text = (body.caption + " " + body.alt_text).casefold()
        if any(term.casefold() in text for term in brand.claims_policy.banned_terms):
            violations.append(f"{language}: banned wording")
        if any(
            term.casefold() in text
            and term.casefold()
            not in {allowed.casefold() for allowed in brand.claims_policy.verified_facilities}
            for term in brand.claims_policy.facility_terms
        ):
            violations.append(f"{language}: unverified facility claim")
        if PRICE.search(text) and post.offer_id not in brand.claims_policy.allowed_offers:
            violations.append(f"{language}: price/offer claim without a verified offer")
    if not set(post.hashtags) & set(brand.hashtags.branded):
        violations.append("At least one branded hashtag is required")
    if len(set(post.hashtags)) != len(post.hashtags):
        violations.append("Selected hashtags must be unique")
    ratio = arabic_script_ratio(post.ar.caption)
    if ratio < 0.9:
        violations.append("Arabic-script ratio is below 0.9")
    if post.format == "reel" and post.brief.reel_concept is None:
        violations.append("Reel slot has no concept")
    return RuleResult(
        post_id=post.id,
        content_hash=post.content_hash,
        passed=not violations,
        violations=violations,
        arabic_ratio=ratio,
    )
