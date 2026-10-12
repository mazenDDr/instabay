"""FR-13: factored Thompson sampling, written after the frozen simulator commit."""

import hashlib
import random
from collections.abc import Sequence

from instabay.core.learning import BetaPosterior, Factor
from instabay.core.schemas import Arm, BrandConstitution, PlanningPreferences

PSEUDO_OBSERVATIONS = 20.0


def factor_levels(brand: BrandConstitution) -> dict[Factor, list[str]]:
    """FR-13: available levels come from the brand and fixed typed arm dimensions."""
    return {
        "pillar": [pillar.id for pillar in brand.pillars],
        "format": ["photo", "carousel", "reel"],
        "time_bucket": list(brand.cadence.windows_cairo),
        "hook_style": ["question", "statement", "number"],
    }


def update_posterior(posterior: BetaPosterior, rate: float) -> BetaPosterior:
    """FR-13: §15.9 fractional update, applied only after the persistence fidelity guard."""
    if not 0 <= rate <= 1:
        raise ValueError("Engagement rate must be finite and in [0, 1]")
    return BetaPosterior(
        factor=posterior.factor,
        level=posterior.level,
        alpha=posterior.alpha + PSEUDO_OBSERVATIONS * rate,
        beta=posterior.beta + PSEUDO_OBSERVATIONS * (1 - rate),
    )


def arm_levels(arm: Arm) -> list[tuple[Factor, str]]:
    """FR-13: all four executed factors receive the same bounded observation."""
    return [
        ("pillar", arm.pillar),
        ("format", arm.format),
        ("time_bucket", arm.time_bucket),
        ("hook_style", arm.hook_style),
    ]


class ThompsonOptimizer:
    """FR-13: sample each level once per week, then let the constrained planner choose."""

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def preferences(
        self,
        brand: BrandConstitution,
        posteriors: Sequence[BetaPosterior],
        week_key: str,
    ) -> PlanningPreferences:
        """NFR-03: keyed random draws do not depend on row order or process restarts."""
        index = {(row.factor, row.level): row for row in posteriors}
        if len(index) != len(posteriors):
            raise ValueError("Duplicate factor-level posteriors")
        scores: dict[str, dict[str, float]] = {}
        for factor, levels in factor_levels(brand).items():
            scores[factor] = {}
            for level in levels:
                belief = index.get((factor, level), BetaPosterior(factor=factor, level=level))
                key = f"thompson-v1:{self.seed}:{week_key}:{factor}:{level}"
                rng = random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(), "big"))
                scores[factor][level] = rng.betavariate(belief.alpha, belief.beta)
        return PlanningPreferences.model_validate(scores)
