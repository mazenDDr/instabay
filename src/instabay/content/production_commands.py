"""FR-04, NFR-07: explicit production drafting, private recording and offline replay."""

import fcntl
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml

from instabay.adapters.cassette import RecordingLLMClient, ReplayLLMClient, load_cassette
from instabay.adapters.llm import CompletionRequest, LLMClient
from instabay.adapters.native_llm import NativeLLMClient
from instabay.content.evidence import ContentEvidence
from instabay.content.production import generate_week
from instabay.core.schemas import BrandConstitution, canonical_hash
from instabay.llm import RunBudget
from instabay.settings import Settings
from instabay.video.direction import ObjectCatalog


def native_client(origin: str, model: str, confirm: bool) -> NativeLLMClient:
    """NFR-04: reject opt-out before opening a provider or creating output files."""
    if not confirm or os.environ.get("INSTABAY_LLM_ENABLED") != "1":
        raise typer.BadParameter(
            "Native generation requires INSTABAY_LLM_ENABLED=1 and --confirm-generation"
        )
    return NativeLLMClient(origin, model, confirm_external=True)


def dry_generation() -> None:
    """FR-09: generation commands cannot use the live Instagram mode."""
    if Settings.from_env().mode != "dry_run":
        raise typer.BadParameter("Generation requires INSTABAY_MODE=dry_run; Instagram is separate")


def private_cassette(path: Path) -> None:
    """NFR-04: native captures cannot be written to public project folders."""
    root, target = Path.cwd().resolve(), path.resolve()
    if target.is_relative_to(root) and not target.is_relative_to(root / "outputs"):
        raise typer.BadParameter("Keep private cassettes under outputs/ or outside the repository")


def register_production_commands(app: typer.Typer) -> None:
    """FR-09: generated output enters review, never automatic publishing."""

    @app.command("animate-photos")
    def animate(
        scenes: Annotated[Path, typer.Option()],
        output: Annotated[Path, typer.Option()] = Path("outputs/photo-motion"),
        confirm_gpu: Annotated[bool, typer.Option()] = False,
        max_minutes: Annotated[float, typer.Option(min=1)] = 45,
        seed: Annotated[int, typer.Option(min=0)] = 2500,
    ) -> None:
        """FR-06: animate the approved source catalog before loading the caption model."""
        from instabay.video.catalog_motion import animate_catalog

        dry_generation()
        catalog = ObjectCatalog.model_validate(yaml.safe_load(scenes.read_text()))
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        with (output / ".motion.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = animate_catalog(
                catalog,
                Path.cwd(),
                output,
                confirm_gpu=confirm_gpu,
                max_minutes=max_minutes,
                seed=seed,
            )
        typer.echo(f"Prepared {len(result.objects)} photo scenes: {output / 'catalog.json'}")

    @app.command("generate")
    def generate(
        brand: Annotated[Path, typer.Option()],
        evidence: Annotated[Path, typer.Option()],
        model: Annotated[str, typer.Option()],
        run_id: Annotated[str, typer.Option()],
        week_start: Annotated[str, typer.Option()],
        output: Annotated[Path, typer.Option()] = Path("outputs/production"),
        scenes: Annotated[Path | None, typer.Option()] = None,
        origin: Annotated[str, typer.Option()] = "http://127.0.0.1:18765",
        replay: Annotated[Path | None, typer.Option()] = None,
        confirm_generation: Annotated[bool, typer.Option()] = False,
        draft_only: Annotated[bool, typer.Option()] = False,
        max_calls: Annotated[int, typer.Option(min=1)] = 70,
        max_tokens: Annotated[int, typer.Option(min=1)] = 200000,
        max_cost_usd: Annotated[float, typer.Option(min=0)] = 1,
    ) -> None:
        """FR-04: generate a non-demo mixed week from an already human-frozen brand."""
        dry_generation()
        output = output.resolve()
        root = Path.cwd().resolve()
        if not output.is_relative_to(root):
            raise typer.BadParameter("Keep generation state under the project root")
        # Check the stored brand before starting a model or a recording.
        constitution = BrandConstitution.model_validate(yaml.safe_load(brand.read_text()))
        proof = ContentEvidence.model_validate(yaml.safe_load(evidence.read_text()))
        catalog = (
            ObjectCatalog.model_validate(yaml.safe_load(scenes.read_text()))
            if scenes
            else proof.objects(root)
        )
        native = None
        recording = None
        if replay:
            client: LLMClient = ReplayLLMClient(replay)
        else:
            native = native_client(origin, model, confirm_generation)
            client = native
        try:
            output.mkdir(parents=True, exist_ok=True)
            with (output / ".generation.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not replay:
                    recording = RecordingLLMClient(client, output / "cassette.json")
                    client = recording
                result = generate_week(
                    brand=constitution,
                    evidence=proof,
                    catalog=catalog,
                    root=root,
                    output=output,
                    run_id=run_id,
                    week_start=date.fromisoformat(week_start),
                    model=model,
                    client=client,
                    budget=RunBudget(
                        max_calls=max_calls, max_tokens=max_tokens, max_cost_usd=max_cost_usd
                    ),
                    replay=replay is not None,
                    draft_only=draft_only,
                )
            typer.echo(f"{result.status}: {len(result.post_ids)} non-demo posts; no publishing.")
            typer.echo(f"Review: {output / 'review/index.html'}")
        finally:
            if recording:
                recording.close()
            if native:
                native.close()

    @app.command("record")
    def record(
        requests: Annotated[Path, typer.Option()],
        model: Annotated[str, typer.Option()],
        output: Annotated[Path, typer.Option()] = Path("outputs/cassettes/recording.json"),
        origin: Annotated[str, typer.Option()] = "http://127.0.0.1:18765",
        confirm_generation: Annotated[bool, typer.Option()] = False,
        max_calls: Annotated[int, typer.Option(min=1)] = 70,
        max_tokens: Annotated[int, typer.Option(min=1)] = 200000,
        max_cost_usd: Annotated[float, typer.Option(min=0)] = 1,
    ) -> None:
        """NFR-07: HUMAN-invoked capture of exact request files for private offline replay."""
        dry_generation()
        private_cassette(output)
        files = sorted(requests.glob("*-request.json")) if requests.is_dir() else [requests]
        if not files or len(files) > max_calls:
            raise typer.BadParameter("Request count is empty or exceeds the recording budget")
        if (
            not requests.is_dir()
            and isinstance(json.loads(requests.read_text()), dict)
            and "entries" in json.loads(requests.read_text())
        ):
            batch = [e.request for e in load_cassette(requests).entries]
        else:
            batch = [CompletionRequest.model_validate_json(p.read_bytes()) for p in files]
        if not batch or len(batch) > max_calls:
            raise typer.BadParameter("Recording request count exceeds its budget")
        if any(r.model != model for r in batch):
            raise typer.BadParameter("All recorded requests must use the configured pinned model")
        from instabay.adapters.cassette import reject_credentials

        for request in batch:
            reject_credentials(request.model_dump(mode="json"))
        native = native_client(origin, model, confirm_generation)
        recorder = None
        try:
            recorder = RecordingLLMClient(native, output)
            binding = output.with_suffix(".requests.json")
            identities = [canonical_hash(r) for r in batch]
            if binding.exists() and json.loads(binding.read_text()) != identities:
                raise ValueError("Recording requests changed; choose a new cassette")
            binding.write_text(json.dumps(identities) + "\n")
            existing = load_cassette(output).entries if output.exists() else []
            completed = Counter(e.request_hash for e in existing if e.status == "complete")
            used_calls = len(existing)
            used_tokens = sum(
                e.completion.input_tokens + e.completion.output_tokens
                for e in existing
                if e.completion
            )
            used_cost = sum(e.completion.cost_usd for e in existing if e.completion)
            for request in batch:
                identity = canonical_hash(request)
                if completed[identity]:
                    completed[identity] -= 1
                    continue
                if used_calls >= max_calls or used_tokens >= max_tokens or used_cost > max_cost_usd:
                    raise ValueError("Recording budget exhausted")
                result = recorder.complete(request)
                used_calls += 1
                used_tokens += result.input_tokens + result.output_tokens
                used_cost += result.cost_usd
                if used_tokens > max_tokens or used_cost > max_cost_usd:
                    raise ValueError("Recording budget exceeded; completion retained")
            typer.echo(
                f"Recorded {len(batch)} requests to private cassette {output}; no publishing."
            )
        finally:
            if recorder:
                recorder.close()
            native.close()
