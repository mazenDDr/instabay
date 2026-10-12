"""FR-08: optional local Router; HUMAN: install and run only on gpu-box's main environment."""

import importlib
import os
import platform
from pathlib import Path
from typing import Protocol, cast

from pydantic import JsonValue

from instabay.core.schemas import canonical_hash
from instabay.decisions.engine import Answer, DecisionUnavailableError, Question, normalize_answers


class LocalRouter(Protocol):
    """NFR-05: optional heavy dependency remains outside imports and offline tests."""

    def predict(
        self, state: str | dict[str, JsonValue], questions: dict[str, object]
    ) -> object: ...


class LayaLocalEngine:
    """FR-08: lazy import/load, CUDA only, local checkpoints; no implicit model downloads."""

    synthetic = False

    def __init__(
        self, *, revision: str, models: dict[str, Path], confirm_gpu: bool = False
    ) -> None:
        self.revision, self.models, self.confirm_gpu = revision, models, confirm_gpu
        self.engine_id = "laya-local:" + canonical_hash(
            {
                "revision": revision,
                "models": {k: str(v) for k, v in models.items()},
                "device": "cuda",
            }
        )
        self.router: LocalRouter | None = None

    def decide(
        self, state: str | dict[str, JsonValue], questions: dict[str, Question]
    ) -> dict[str, Answer]:
        if (
            not self.confirm_gpu
            or os.environ.get("INSTABAY_DECISIONS_ENABLED") != "1"
            or platform.system() != "Linux"
        ):
            raise DecisionUnavailableError(
                "HUMAN: Laya inference runs on gpu-box with explicit enablement"
            )
        if set(self.models) != {"english", "multilingual"} or any(
            not path.is_dir() for path in self.models.values()
        ):
            raise DecisionUnavailableError(
                "HUMAN: provide both pinned local checkpoints on gpu-box"
            )
        try:
            if self.router is None:
                module = importlib.import_module("laya")
                self.router = cast(
                    LocalRouter,
                    module.Router(
                        device="cuda",
                        models={
                            **{k: str(v) for k, v in self.models.items()},
                            "typed_decisions": None,
                        },
                        max_loaded=1,
                        preload=False,
                        auto_task_detection=False,
                    ),
                )
            raw = self.router.predict(state, {k: v.wire() for k, v in questions.items()})
        except (ImportError, AttributeError, TypeError, RuntimeError, OSError):
            raise DecisionUnavailableError("Optional Laya runtime/checkpoint unavailable") from None
        return normalize_answers(raw, questions)
