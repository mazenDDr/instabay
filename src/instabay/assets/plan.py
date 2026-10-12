"""FR-02, FR-04: the owner's reel/post mix and code-ranked photo suggestions for each slot."""

from collections import Counter
from typing import Self

from pydantic import Field, model_validator

from instabay.assets.library import Asset, AssetLibrary
from instabay.core.schemas import Boundary, BrandConstitution, Cadence, PostFormat, Slot

NEEDED: dict[PostFormat, tuple[int, int]] = {"photo": (1, 1), "carousel": (2, 3), "reel": (3, 4)}
CADENCE_KEY = "cadence"


class OwnerCadence(Boundary):
    """FR-02: posts per week split into reels, carousels and single photos by the owner."""

    posts_per_week: int = Field(ge=1, le=7)
    reels_per_week: int = Field(ge=1, le=7)
    carousels_per_week: int = Field(default=0, ge=0, le=6)

    @model_validator(mode="after")
    def fits(self) -> Self:
        if self.reels_per_week + self.carousels_per_week > self.posts_per_week:
            raise ValueError("Reels plus carousels cannot exceed posts per week")
        return self

    @property
    def photos_per_week(self) -> int:
        return self.posts_per_week - self.reels_per_week - self.carousels_per_week

    @classmethod
    def from_brand(cls, brand: BrandConstitution) -> "OwnerCadence":
        c = brand.cadence
        reels = c.posts_per_week - c.min_photos - c.min_carousels
        return cls(
            posts_per_week=c.posts_per_week,
            reels_per_week=max(1, reels),
            carousels_per_week=c.min_carousels,
        )

    def cadence(self, brand: BrandConstitution) -> Cadence:
        """FR-02: exact minimums pin every slot's format; pillar limits are re-checked."""
        cadence = brand.cadence.model_copy(
            update={
                "posts_per_week": self.posts_per_week,
                "min_reels": self.reels_per_week,
                "min_photos": self.photos_per_week,
                "min_carousels": self.carousels_per_week,
            }
        )
        BrandConstitution.model_validate(
            brand.model_dump(mode="json") | {"cadence": cadence.model_dump(mode="json")}
        )
        return Cadence.model_validate(cadence.model_dump(mode="json"))


def load_cadence(library: AssetLibrary, brand: BrandConstitution) -> OwnerCadence:
    stored = library.setting(CADENCE_KEY)
    return OwnerCadence.model_validate(stored) if stored else OwnerCadence.from_brand(brand)


def save_cadence(library: AssetLibrary, brand: BrandConstitution, value: OwnerCadence) -> None:
    value.cadence(brand)
    library.set_setting(CADENCE_KEY, value.model_dump(mode="json"))


class Suggestion(Boundary):
    """FR-04: primary images first, then alternatives the writer may also choose."""

    slot_id: str
    pillar: str
    format: PostFormat
    primary: list[str]
    pool: list[str]
    matching: int
    shortfall: bool
    reason: str


def suggest_assets(slots: list[Slot], assets: list[Asset]) -> dict[str, Suggestion]:
    """FR-04: same-pillar, least-used, most confident and real photos first; deterministic.

    Single photos are not repeated within the week. A pillar without enough photos borrows the
    least-used images from other pillars and is flagged as a shortfall for the owner.
    """
    usable = [a for a in assets if a.usable]
    used: Counter[str] = Counter()
    single: set[str] = set()
    result = {}
    for slot in slots:
        pillar, format = slot.arm.pillar, slot.arm.format
        minimum, wanted = NEEDED[format]
        candidates = [a for a in usable if format != "photo" or a.id not in single]

        def rank(asset: Asset, pillar: str = pillar) -> tuple[int, int, int, float, str]:
            confidence = 1.0 if asset.owner_pillar else asset.model_confidence or 0
            return (
                asset.pillar != pillar,
                used[asset.id],
                asset.origin != "owner",
                -confidence,
                asset.id,
            )

        ranked = sorted(candidates, key=rank)
        matching = sum(a.pillar == pillar for a in ranked)
        primary = [a.id for a in ranked[:wanted]]
        pool = [a.id for a in ranked[: wanted + 2]]
        shortfall = matching < minimum
        for asset_id in primary:
            used[asset_id] += 1
        if format == "photo":
            single.update(primary)
        reason = (
            f"{matching} {pillar} photo(s) available; borrowed from other pillars"
            if shortfall
            else f"{matching} {pillar} photo(s) available"
        )
        result[slot.id] = Suggestion(
            slot_id=slot.id,
            pillar=pillar,
            format=format,
            primary=primary,
            pool=pool,
            matching=matching,
            shortfall=shortfall or len(primary) < minimum,
            reason=reason if len(primary) >= minimum else "Not enough usable photos yet",
        )
    return result
