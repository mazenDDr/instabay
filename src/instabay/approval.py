"""FR-09: bilingual human queue, measured decision time and stored edit diffs."""

from time import perf_counter

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from instabay.core.schemas import ApprovalRequest
from instabay.repository import Repository


def show_post(repository: Repository, post_id: str, console: Console) -> None:
    """FR-09: display final captions, scores, flags and the real available media path."""
    post = repository.post(post_id)
    try:
        review = repository.review(post_id)
    except ValueError:
        review = None
    table = Table(title=post_id, expand=True)
    table.add_column("English", ratio=1)
    table.add_column("العربية", ratio=1, justify="right")
    table.add_row(Text(post.full_caption("en")), Text(post.full_caption("ar")))
    console.print(table)
    if review is not None:
        console.print(
            f"Judge: {review.judge.average:.2f}/5 (3 fixture samples); "
            f"Rules: {'PASS' if review.rules.passed else 'FAIL'}"
        )
        for flag in review.flags:
            console.print(f"Flag: {flag}")
    else:
        console.print(
            "Judge scores belong to the pre-edit content; current copy was edited by a human."
        )
    console.print(f"Media preview: {post.media_path or 'concept only; no rendered video'}")
    console.print("Reference property: The Grand Resort Hurghada; fictional Insta Bay demo.")


def approval_queue(
    repository: Repository, run_id: str, actor: str, console: Console, post_id: str | None = None
) -> int:
    """FR-09: approve/edit/reject are explicit typed inputs; there is no auto-approve path."""
    ids = repository.post_ids(run_id)
    if post_id is not None:
        if post_id not in ids:
            raise ValueError("Post is not in this run")
        ids = [post_id]
    stored = 0
    for current_id in ids:
        post = repository.post(current_id)
        decision = repository.latest_approval(current_id)
        if decision is not None and decision.content_hash == post.content_hash:
            console.print(f"Already reviewed: {current_id} ({decision.decision})")
            continue
        started = perf_counter()
        show_post(repository, current_id, console)
        review = repository.review(current_id)
        while True:
            choice = typer.prompt("Decision: approve / edit / reject").strip().lower()
            if choice in {"approve", "edit", "reject"}:
                break
            console.print("Enter approve, edit, or reject.")
        required_reason = review.flagged or choice == "reject"
        reason = typer.prompt("Reason", default="" if not required_reason else None)
        while required_reason and not reason.strip():
            reason = typer.prompt("Reason is required for flagged or rejected content")
        en_caption = ar_caption = None
        if choice == "edit":
            en_caption = typer.prompt("English caption", default=post.en.caption)
            ar_caption = typer.prompt("Arabic caption", default=post.ar.caption)
        request = ApprovalRequest.model_validate(
            {
                "decision": {"approve": "APPROVED", "edit": "EDITED", "reject": "REJECTED"}[choice],
                "actor": actor,
                "reason": reason,
                "seconds_spent": perf_counter() - started,
                "en_caption": en_caption,
                "ar_caption": ar_caption,
            }
        )
        approval = repository.approve(current_id, request)
        console.print(f"Stored {approval.decision}: {current_id}")
        stored += 1
    return stored
