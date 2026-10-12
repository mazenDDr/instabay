"""NFR-03: keep reviewable request/output evidence for an explicitly authorized generation run."""

from pathlib import Path
from threading import Lock

from instabay.adapters.llm import Completion, CompletionRequest, LLMClient


class AuditedLLMClient:
    """NFR-03: persist each request before calling the provider; raw drafts stay separate."""

    def __init__(self, client: LLMClient, directory: Path) -> None:
        self.client, self.directory = client, directory
        directory.mkdir(parents=True, exist_ok=True)
        self._count = len(list(directory.glob("*-request.json")))
        self._lock = Lock()

    def complete(self, request: CompletionRequest) -> Completion:
        with self._lock:
            self._count += 1
            ordinal = self._count
        (self.directory / f"{ordinal:03d}-request.json").write_text(
            request.model_dump_json(indent=2) + "\n"
        )
        completion = self.client.complete(request)
        (self.directory / f"{ordinal:03d}-response.json").write_text(
            completion.model_dump_json(indent=2) + "\n"
        )
        return completion
