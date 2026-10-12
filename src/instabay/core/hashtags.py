"""FR-05: deterministic tiered hashtags; no LLM selection."""

from instabay.core.schemas import BrandConstitution


def select_hashtags(brand: BrandConstitution, count: int = 10) -> list[str]:
    """FR-05: select 8-15 unique tags, starting with at least one branded tag."""
    if not 8 <= count <= 15:
        raise ValueError("Hashtag target must be between eight and fifteen")
    bank = brand.hashtags
    tags = list(dict.fromkeys(bank.branded + bank.place + bank.niche + bank.broad))
    selected = tags[:count]
    if len(selected) < 8:
        raise ValueError("The brand bank cannot supply eight unique tags")
    return selected
