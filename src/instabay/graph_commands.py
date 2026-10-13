"""FR-09 to FR-11: explicit HUMAN-only native commands, separate from fixture demo/cycle."""

import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import typer
import yaml
from sqlmodel import Session, select

from instabay.adapters.graph_account import ACCOUNT_DB, AccountStore, analyze, fetch_account
from instabay.adapters.graph_http import HttpxGraphTransport, HttpxMediaVerifier, graph_request
from instabay.adapters.graph_insights import GraphInsights
from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphConfig,
    GraphCredentials,
    GraphRateLimitError,
    LiveConfigurationError,
)
from instabay.adapters.graph_publisher import GraphPublisher
from instabay.adapters.media_tunnel import manifest, photo_files, public_files, ready
from instabay.core.schemas import ApprovalRequest, Post, Review
from instabay.core.tables import PublicationRow
from instabay.graph import evidence_review
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

    @app.command("instagram-post")
    def instagram_post(
        post_id: Annotated[str, typer.Option()],
        db: Annotated[Path, typer.Option()],
        actor: Annotated[str, typer.Option(help="Your name, stored with the approval")],
        config: Annotated[Path, typer.Option()] = Path("config/instagram.example.yaml"),
        confirm_live: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """HUMAN: publish one photo/carousel post now through a temporary public tunnel."""
        _post_now(post_id, db, actor, config, confirm_live)

    @app.command("graph-check")
    def check(
        config: Annotated[Path, typer.Option()] = Path("config/instagram.example.yaml"),
        out: Annotated[Path, typer.Option()] = ACCOUNT_DB,
        limit: Annotated[int, typer.Option(min=1, max=100)] = 25,
        confirm_live: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """HUMAN: read-only. Check the token and read your recent posts with their insights."""
        transport: HttpxGraphTransport | None = None
        try:
            settings = GraphConfig.model_validate(yaml.safe_load(config.read_text()))
            credentials = GraphCredentials.from_env()
            transport = HttpxGraphTransport(settings, credentials, confirm_live=confirm_live)
            snapshot = fetch_account(transport, settings, credentials.user_id, limit=limit)
        except GraphAPIError as error:
            typer.echo(
                f"Instagram check stopped: {type(error).__name__}; code={error.code}, "
                f"subcode={error.subcode}. Code 190 means the token is invalid or expired.",
                err=True,
            )
            raise typer.Exit(2) from None
        except (ValueError, KeyError, PermissionError, ConnectionError, OSError) as error:
            typer.echo(f"Instagram check stopped: {type(error).__name__}: {_safe(error)}", err=True)
            raise typer.Exit(2) from None
        finally:
            if transport is not None:
                transport.close()
        AccountStore(out).save(snapshot)
        summary = analyze(snapshot)
        typer.echo(
            f"Connected to @{snapshot.username} ({snapshot.account_type or 'account'}): "
            f"{snapshot.followers if snapshot.followers is not None else '?'} followers, "
            f"{snapshot.media_count if snapshot.media_count is not None else '?'} posts."
        )
        typer.echo(
            f"Read {summary['posts']} recent posts; {summary['with_insights']} have insights. "
            f"Saved to {out}. Open Insights in the studio to see them."
        )
        for media in snapshot.media:
            if media.insights_error:
                typer.echo(f"  no insights for {media.id}: {media.insights_error}")


def _run(post_id: str, db: Path, config_path: Path, confirm_live: bool, *, insights: bool) -> None:
    repository = Repository(db)
    transport: HttpxGraphTransport | None = None
    verifier: HttpxMediaVerifier | None = None
    try:
        # Check approval before even loading native credentials or constructing HTTP clients.
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


def _recheck(repository: Repository, post: Post) -> Review:
    """FR-08: the new revision gets the same checks as the week did, before any approval."""
    run_id = repository._post_run(post.slot_id)
    previous = []
    for slot in repository.slots(run_id):
        if slot.id == post.slot_id:
            break
        previous.append(repository.post(slot.id))
    review = evidence_review(post, repository.brand(post.brand_hash), previous)
    repository.save_review(review)
    return review


def _safe(error: Exception) -> str:
    """NFR-04: only our own configuration messages are echoed; never provider bodies."""
    if isinstance(error, LiveConfigurationError):
        return str(error)
    return "see docs/INSTAGRAM.md"


def _post_now(post_id: str, db: Path, actor: str, config_path: Path, confirm_live: bool) -> None:
    """FR-09, FR-10: attach the exact bytes, ask for approval of that snapshot, then publish."""
    repository = Repository(db)
    transport: HttpxGraphTransport | None = None
    verifier: HttpxMediaVerifier | None = None
    try:
        settings = GraphConfig.model_validate(yaml.safe_load(config_path.read_text()))
        credentials = GraphCredentials.from_env()
        transport = HttpxGraphTransport(settings, credentials, confirm_live=confirm_live)
        with Session(repository.engine) as session:
            if session.exec(
                select(PublicationRow).where(PublicationRow.post_id == post_id)
            ).first():
                raise ValueError("This post was already published")
        post = repository.post(post_id)
        files = photo_files(post, Path.cwd())
        profile = graph_request(transport, "GET", f"/{credentials.user_id}", {"fields": "username"})
        username = str(profile.get("username", ""))
        typer.echo(f"Opening a temporary public link for {len(files)} photo(s)...")
        with public_files(files) as base:
            settings = settings.model_copy(update={"media_hosts": (urlsplit(base).hostname,)})
            post = ready(post, manifest(post, files, base, actor))
            repository.save_post(post)
            review = _recheck(repository, post)
            if not review.rules.passed:
                raise ValueError("Checks failed: " + "; ".join(review.rules.violations))
            typer.echo("\n--- Caption that will be posted ---")
            typer.echo(GraphPublisher.caption(post))
            typer.echo("--- Review notes ---")
            for flag in review.flags:
                typer.echo(f"- {flag}")
            typer.echo("--- Photos ---")
            for path, asset in zip(files, post.media_manifest.assets, strict=True):  # type: ignore[union-attr]
                typer.echo(f"{path}  ({asset.width}x{asset.height})")
            started = time.monotonic()
            typed = typer.prompt(
                f"\nThis posts publicly to @{username}. Type {username} to approve and publish "
                "(anything else cancels)"
            )
            if typed.strip().lstrip("@") != username:
                typer.echo("Cancelled. Nothing was posted. The post now waits for approval again.")
                return
            repository.approve(
                post_id,
                ApprovalRequest(
                    decision="APPROVED", actor=actor, seconds_spent=time.monotonic() - started
                ),
            )
            typer.echo("Approved. Publishing (Instagram may take a minute to process)...")
            verifier = HttpxMediaVerifier(settings)
            receipt = GraphPublisher(
                repository,
                settings,
                transport,
                account_id=credentials.user_id,
                confirm_live=confirm_live,
                verifier=verifier,
            ).publish(post_id)
            link = graph_request(transport, "GET", f"/{receipt.media_id}", {"fields": "permalink"})
        typer.echo(f"Published to @{username}: {link.get('permalink', receipt.media_id)}")
        typer.echo("The temporary link is closed. Instagram keeps its own copy of the photo.")
    except GraphAPIError as error:
        typer.echo(
            f"Instagram stopped the post: {type(error).__name__}; code={error.code}, "
            f"subcode={error.subcode}. Code 10 or 200 means the token lacks "
            "instagram_business_content_publish.",
            err=True,
        )
        raise typer.Exit(2) from None
    except (ValueError, RuntimeError, PermissionError, ConnectionError, OSError) as error:
        # Our own messages only: Graph errors are numeric and tokens never enter exceptions.
        typer.echo(f"Post stopped: {error}", err=True)
        raise typer.Exit(2) from None
    finally:
        if verifier is not None:
            verifier.close()
        if transport is not None:
            transport.close()
        repository.close()
