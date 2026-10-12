"""NFR-07: minimal fixture output shapes derived from SPEC §15, not agent logic."""

from pydantic import BaseModel, ConfigDict, Field


class BriefFixture(BaseModel):
    """FR-04: language-neutral worked-example brief shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    angle: str
    hook: str
    key_message: str
    visual: str
    cta: str
    must_not: list[str]


class CopyFixture(BaseModel):
    """FR-04: each writer returns its own native caption and alt text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    caption: str = Field(min_length=1, max_length=2200)
    alt_text: str = Field(min_length=1)


class JudgeFixture(BaseModel):
    """FR-08: worked-example judge envelope; calibration comes in later phases."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    scores: dict[str, int]
    average: float = Field(ge=1, le=5)
    samples: int = Field(gt=0)
    passed: bool
    fixes: list[str]
