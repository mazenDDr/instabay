"""FR-02, FR-04: the owner's reel/post mix and code-ranked photo suggestions for each slot."""

from collections import Counter
from typing import Self

from pydantic import Field, model_validator

from instabay.assets.library import Asset, AssetLibrary
from instabay.core.schemas import Boundary, BrandConstitution, Cadence, PostFormat, Slot

NEEDED: dict[PostFormat, tuple[int, int]] = {"photo": (1, 1), "carousel": (2, 3), "reel": (3, 4)}
CADENCE_KEY = "cadence"
MAX_IMAGES = 5


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
    """FR-04: images reserved for one post; the writer picks and orders them."""

    slot_id: str
    pillar: str
    format: PostFormat
    primary: list[str]
    pool: list[str]
    matching: int
    shortfall: bool
    reason: str
    reused: list[str] = Field(default_factory=list)
    missing: int = Field(default=0, ge=0)


def family(asset: Asset) -> frozenset[str]:
    """FR-04: a photo and every AI shot made from it show the same spot."""
    if asset.origin == "owner":
        return frozenset({asset.id})
    parents = (asset.recipe or {}).get("parents")
    if isinstance(parents, list) and parents:
        return frozenset(str(p) for p in parents)
    return frozenset({asset.parent_id or asset.id})


def suggest_assets(slots: list[Slot], assets: list[Asset]) -> dict[str, Suggestion]:
    """FR-04: every image at most once a week and never two shots of one spot in a post.

    Ranking: same pillar, family not yet used this week, real photo before AI shot, confidence.
    Each post's pool is reserved for it, so the writer's choice cannot collide with another
    post. When fresh images run out, the least-used ones are reused and listed in `reused`;
    `missing` tells autopilot how many new shots would avoid that.
    """
    usable = [a for a in assets if a.usable]
    taken: set[str] = set()
    families_used: Counter[frozenset[str]] = Counter()
    uses: Counter[str] = Counter()
    picked: dict[str, list[Asset]] = {}
    reused: dict[str, list[str]] = {}
    missing: dict[str, int] = {}

    def rank(asset: Asset, pillar: str) -> tuple[int, int, int, float, str]:
        confidence = 1.0 if asset.owner_pillar else asset.model_confidence or 0
        return (
            asset.pillar != pillar,
            families_used[family(asset)],
            asset.origin != "owner",
            -confidence,
            asset.id,
        )

    def compatible(asset: Asset, chosen: list[Asset]) -> bool:
        return all(not (family(asset) & family(other)) for other in chosen)

    for slot in slots:
        pillar, format = slot.arm.pillar, slot.arm.format
        minimum, wanted = NEEDED[format]
        chosen: list[Asset] = []
        for asset in sorted(
            (a for a in usable if a.id not in taken), key=lambda a: rank(a, pillar)
        ):
            if len(chosen) == wanted:
                break
            if compatible(asset, chosen):
                chosen.append(asset)
        fresh = len(chosen)
        missing[slot.id] = max(0, wanted - sum(a.pillar == pillar for a in chosen))
        extra: list[str] = []
        if fresh < minimum:
            for asset in sorted(usable, key=lambda a: (uses[a.id], rank(a, pillar))):
                if len(chosen) == minimum:
                    break
                if asset not in chosen and compatible(asset, chosen):
                    chosen.append(asset)
                    extra.append(asset.id)
        for asset in chosen:
            taken.add(asset.id)
            uses[asset.id] += 1
            families_used[family(asset)] += 1
        picked[slot.id], reused[slot.id] = chosen, extra
    # Spare fresh images widen the writer's choice for posts of the same pillar.
    spare = [a for a in usable if a.id not in taken]
    result = {}
    for slot in slots:
        pillar, format = slot.arm.pillar, slot.arm.format
        minimum, wanted = NEEDED[format]
        chosen = picked[slot.id]
        room = MAX_IMAGES - len(chosen) if format != "photo" else 2
        for asset in sorted(spare, key=lambda a: rank(a, pillar)):
            if room <= 0:
                break
            if asset.pillar == pillar and compatible(asset, chosen):
                chosen = [*chosen, asset]
                spare.remove(asset)
                room -= 1
        primary = [a.id for a in picked[slot.id][:wanted]]
        matching = sum(a.pillar == pillar for a in usable)
        short = len(primary) < minimum or bool(reused[slot.id])
        result[slot.id] = Suggestion(
            slot_id=slot.id,
            pillar=pillar,
            format=format,
            primary=primary,
            pool=[a.id for a in chosen],
            matching=matching,
            shortfall=short or matching < minimum,
            reason=(
                "Not enough usable photos yet"
                if len(primary) < minimum
                else f"reuses {len(reused[slot.id])} photo(s) already used this week"
                if reused[slot.id]
                else f"{matching} {pillar} photo(s) available"
            ),
            reused=reused[slot.id],
            missing=missing[slot.id],
        )
    return result
