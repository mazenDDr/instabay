"""FR-06, NFR-03: typed boundaries for the private photo-motion worker."""

from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from gpu_worker.wan_preview import PreviewSpec
from instabay.core.schemas import Boundary, Hash


class MotionReceipt(Boundary):
    """NFR-04: worker receipts cannot redirect downloads to unrelated private files."""

    recipe_hash: Hash
    directory: str

    @model_validator(mode="after")
    def path(self) -> Self:
        if self.directory != f"outputs/wan-motion/{self.recipe_hash}":
            raise ValueError("Motion receipt directory differs from its recipe")
        return self


class MotionStatus(Boundary):
    """NFR-03: partial jobs cannot claim completion without their recipe receipt."""

    state: Literal["missing", "running", "complete", "failed"]
    exit_code: int | None = None
    receipt: MotionReceipt | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.state == "complete" and (self.exit_code != 0 or self.receipt is None):
            raise ValueError("Completed motion needs a successful stored receipt")
        return self


class CapturedClip(Boundary):
    """NFR-03: exact native output bytes and observed inference timing."""

    file: str
    sha256: Hash
    seed: int = Field(ge=0)
    seconds: float = Field(ge=0, allow_inf_nan=False)


class MotionCapture(Boundary):
    """FR-07: real renderer evidence with explicit generated/reference scope."""

    recipe_hash: Hash
    recipe_file_sha256: Hash
    clips: list[CapturedClip] = Field(min_length=1, max_length=3)
    seconds: float = Field(ge=0, allow_inf_nan=False)
    peak_vram_bytes: int = Field(ge=0)
    ai_disclosure: Literal[True]
    reference_only: Literal[True]
    cost_usd_api_fees: float = Field(ge=0, allow_inf_nan=False)
    quality_status: str


class NativeMotionRecipe(Boundary):
    """NFR-03: pinned motion inputs, weights and measured remote runtime."""

    kind: Literal["experimental-wan-i2v-motion-v1"]
    spec: PreviewSpec
    weights: dict[str, JsonValue]
    runtime: dict[str, JsonValue]
    pipeline_class: Literal["WanImageToVideoPipeline"]
    expand_timesteps: bool
    scheduler: dict[str, JsonValue]
    offload: str
    vae: str
    ai_disclosure: Literal[True]
    reference_only: Literal[True]
    determinism: str
