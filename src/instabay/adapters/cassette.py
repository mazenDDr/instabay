"""NFR-03, NFR-07: private, integrity-checked recording and exact offline replay."""

import fcntl
import json
import os
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Literal

from pydantic import Field, model_validator

from instabay.adapters.llm import Completion, CompletionRequest, LLMClient
from instabay.core.schemas import Boundary, Hash, canonical_hash


def reject_credentials(value: object) -> None:
    """NFR-04: credentials are never accepted as generation/recording content."""
    names = {
        "authorization",
        "access_token",
        "refresh_token",
        "api_key",
        "password",
        "secret",
        "client_secret",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in names:
                raise ValueError("Credential fields cannot be recorded")
            reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            reject_credentials(child)
    elif isinstance(value, str):
        for name, secret in os.environ.items():
            if (
                name.endswith(("_TOKEN", "_API_KEY", "_SECRET", "_PASSWORD"))
                and len(secret) >= 8
                and secret in value
            ):
                raise ValueError("Credential values cannot be recorded")
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return
        if isinstance(parsed, (dict, list)):
            reject_credentials(parsed)


class CassetteEntry(Boundary):
    """NFR-03: preserve raw schema failures and sanitized provider failures separately."""

    request: CompletionRequest
    request_hash: Hash
    completion: Completion | None = None
    response_hash: Hash | None = None
    status: Literal["pending", "complete", "provider_error"] = "pending"
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def integrity(self) -> "CassetteEntry":
        if self.request.prompt_hash != sha256(self.request.prompt.encode()).hexdigest():
            raise ValueError("Recorded prompt integrity differs")
        if self.request_hash != canonical_hash(self.request):
            raise ValueError("Recorded request integrity differs")
        if self.status == "complete":
            if self.completion is None or self.response_hash != canonical_hash(self.completion):
                raise ValueError("Recorded response integrity differs")
            if self.completion.model != self.request.model:
                raise ValueError("Recorded provider identity differs")
        elif self.completion is not None or self.response_hash is not None:
            raise ValueError("Incomplete record cannot contain a successful response")
        reject_credentials(self.model_dump(mode="json"))
        return self


class Cassette(Boundary):
    """NFR-07: an explicit replay source, never an implicit provider fallback."""

    version: Literal[1] = 1
    entries: list[CassetteEntry] = Field(default_factory=list)


def load_cassette(path: Path) -> Cassette:
    """NFR-04: malformed private captures never leak through validation tracebacks."""
    try:
        raw = json.loads(path.read_text())
        reject_credentials(raw)
        return Cassette.model_validate(raw)
    except (ValueError, OSError):
        raise ValueError("Cassette is invalid; private inputs omitted") from None


class RecordingLLMClient:
    """NFR-03: write before each request and atomically record every actual completion."""

    def __init__(self, client: LLMClient, path: Path) -> None:
        self.client, self.path = client, path
        self._lock = RLock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._file_lock = path.with_suffix(path.suffix + ".lock").open("a")
        try:
            fcntl.flock(self._file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._entries = list(load_cassette(path).entries) if path.exists() else []
        except Exception:
            self._file_lock.close()
            raise

    def close(self) -> None:
        """NFR-03: release the single-writer lock after provider calls finish."""
        self._file_lock.close()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(Cassette(entries=self._entries).model_dump_json(indent=2) + "\n")
        temporary.replace(self.path)

    def complete(self, request: CompletionRequest) -> Completion:
        reject_credentials(request.model_dump(mode="json"))
        entry = CassetteEntry(request=request, request_hash=canonical_hash(request))
        with self._lock:
            index = len(self._entries)
            self._entries.append(entry)
            self._save()
        started = perf_counter()
        try:
            completion = self.client.complete(request)
            reject_credentials(completion.model_dump(mode="json"))
            done = CassetteEntry(
                request=request,
                request_hash=entry.request_hash,
                completion=completion,
                response_hash=canonical_hash(completion),
                status="complete",
                latency_ms=(perf_counter() - started) * 1000,
            )
        except Exception:
            with self._lock:
                self._entries[index] = entry.model_copy(
                    update={
                        "status": "provider_error",
                        "latency_ms": (perf_counter() - started) * 1000,
                    }
                )
                self._save()
            raise RuntimeError("Recording provider failed; raw exception omitted") from None
        with self._lock:
            self._entries[index] = done
            self._save()
        return completion


class ReplayLLMClient:
    """NFR-07: replay complete exact requests in recorded order, with no network client."""

    def __init__(self, path: Path) -> None:
        self.cassette = load_cassette(path)
        self._used: set[int] = set()
        self._lock = RLock()

    def complete(self, request: CompletionRequest) -> Completion:
        key = canonical_hash(request)
        with self._lock:
            for index, entry in enumerate(self.cassette.entries):
                if (
                    index not in self._used
                    and entry.request_hash == key
                    and entry.status == "complete"
                ):
                    self._used.add(index)
                    assert entry.completion is not None
                    return entry.completion
        raise LookupError("No unused complete cassette entry for this exact request")
