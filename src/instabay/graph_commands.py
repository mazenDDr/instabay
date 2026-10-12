"""FR-09 to FR-11: explicit HUMAN-only native commands, separate from fixture demo/cycle."""

from pathlib import Path
from typing import Annotated

import typer
import yaml

from instabay.adapters.graph_http import HttpxGraphTransport, HttpxMediaVerifier
from instabay.adapters.graph_insights import GraphInsights
from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphConfig,
    GraphCredentials,
    GraphRateLimitError,
)
from instabay.adapters.graph_publisher import GraphPublisher
from instabay.repository import Repository


def register_graph_commands(app: typer.Typer) -> None:
    """NFR-04: failures expose safe categories without private input or provider payloads."""

    @app.command("graph-publish")
    def publish(
        post_id: Annotated[str, typer.Option()],
        db: Annotated[Path, typer.Option()],
        config: Annotated[Path, typer.Option()] = Path("config/instagram.example.yaml"),
        confirm_live: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """HUMAN: publish one exact approved, media-ready, non-demo post with your Meta token."""
        _run(post_id, db, config, confirm_live, insights=False)

    @app.command("graph-insights")
    def insights(
        post_id: Annotated[str, typer.Option()],
        db: Annotated[Path, typer.Option()],
        config: Annotated[Path, typer.Option()] = Path("config/instagram.example.yaml"),
        confirm_live: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """HUMAN: ingest a published parent's real counts without bandit learning."""
        _run(post_id, db, config, confirm_live, insights=True)


def _run(post_id: str, db: Path, config_path: Path, confirm_live: bool, *, insights: bool) -> None:
    repository = Repository(db)
    transport: HttpxGraphTransport | None = None
    verifier: HttpxMediaVerifier | None = None
    try:
        # Check approval before even loading native credentials or constructing HTTP clients.
        from sqlmodel import Session

        with Session(repository.engine) as session:
            repository._authorized_post(session, post_id)
        config = GraphConfig.model_validate(yaml.safe_load(config_path.read_text()))
        credentials = GraphCredentials.from_env()
        transport = HttpxGraphTransport(config, credentials, confirm_live=confirm_live)
        if insights:
            batch = GraphInsights(
                repository,
                config,
                transport,
                account_id=credentials.user_id,
                confirm_live=confirm_live,
            ).fetch(post_id)
            typer.echo(batch.model_dump_json())
        else:
            verifier = HttpxMediaVerifier(config)
            receipt = GraphPublisher(
                repository,
                config,
                transport,
                account_id=credentials.user_id,
                confirm_live=confirm_live,
                verifier=verifier,
            ).publish(post_id)
            typer.echo(f"Stored live receipt: post={receipt.post_id}, media={receipt.media_id}")
    except GraphAPIError as error:
        typer.echo(
            f"Graph command stopped: {type(error).__name__}; code={error.code}, "
            f"subcode={error.subcode}.",
            err=True,
        )
        if isinstance(error, GraphRateLimitError) and error.retry_after_s is not None:
            typer.echo(f"Retry after at least {error.retry_after_s:g} seconds.", err=True)
        raise typer.Exit(2) from None
    except (ValueError, KeyError, PermissionError, ConnectionError, RuntimeError, OSError) as error:
        # Do not echo arbitrary YAML/validation/provider errors: they may contain private input.
        typer.echo(
            f"Graph command stopped: {type(error).__name__}. See docs/INSTAGRAM.md.", err=True
        )
        raise typer.Exit(2) from None
    finally:
        if verifier is not None:
            verifier.close()
        if transport is not None:
            transport.close()
        repository.close()
