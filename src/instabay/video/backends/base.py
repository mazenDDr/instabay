"""NFR-05: fake first; every motion dependency lives behind this protocol."""

from pathlib import Path
from typing import Protocol

from pydantic import Field

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Boundary


class BackendCaps(Boundary):
    """FR-06: explicit features; unsupported FLF never silently drops an end frame."""

    i2v: bool = True
    flf2v: bool = False
    max_seconds: int = Field(default=5, ge=3)
    resolutions: list[str]
    audio: bool = False
    deterministic: bool = False


class ShotRecipe(Boundary):
    """NFR-03: one shot references its complete parent recipe."""

    recipe: RenderRecipe
    index: int = Field(ge=0)


class ShotResult(Boundary):
    """NFR-06: exact returned local file; native errors never masquerade as a stub."""

    file: str
    seconds: float = Field(ge=0)
    cost_usd: float = Field(default=0, ge=0)


class VideoBackend(Protocol):
    """FR-06, NFR-05: render motion into the provided private working directory."""

    name: str

    def capabilities(self) -> BackendCaps: ...

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult: ...
