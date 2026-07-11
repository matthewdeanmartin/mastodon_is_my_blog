"""`mimb admin …`, `mimb publish`, `mimb doctor`: the admin page for terminal
people. Thin wrappers over the same functions the admin API routes call, so
headless/self-hosted users can run maintenance without the web UI.

Local (single-user) mode only — hosted tenants are managed by the control
plane, and the default-meta-account resolution here would be wrong there.
"""

from __future__ import annotations

import asyncio
import shutil
import sys

from sqlalchemy import select

from mastodon_is_my_blog import tenancy
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_or_create_default_meta_account,
    init_db,
    sync_configured_identities,
)

PROGRESS_STAGE_WIDTH = 24


def print_progress(done: int, total: int | None, stage: str) -> None:
    total_label = total if total is not None else "?"
    print(f"\r{stage:<{PROGRESS_STAGE_WIDTH}} {done}/{total_label}", end="", flush=True)


def finish_progress() -> None:
    print()


def require_local_mode() -> None:
    if tenancy.is_server_mode():
        print("mimb admin commands are for self-hosted (local) mode; hosted tenants are managed by the control plane.")
        raise SystemExit(2)


async def get_context(account: str | None) -> tuple[MetaAccount, MastodonIdentity]:
    """DB up, default meta account, and the identity to operate on (first one,
    or --account matched against the config name / acct)."""
    await init_db()
    from mastodon_is_my_blog.db_init import ensure_schema_stamped

    await ensure_schema_stamped()
    meta = await get_or_create_default_meta_account()
    await sync_configured_identities()

    async with async_session() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id).order_by(MastodonIdentity.id)
        identities = (await session.execute(stmt)).scalars().all()

    if not identities:
        print("No Mastodon account connected. Run `mimb auth login your@handle` first.")
        raise SystemExit(1)

    if account is None:
        return meta, identities[0]

    wanted = account.strip().lower()
    for identity in identities:
        if wanted in {(identity.config_name or "").lower(), identity.acct.lower()}:
            return meta, identity
    names = ", ".join(identity.config_name or identity.acct for identity in identities)
    print(f"No identity matching {account!r}. Available: {names}")
    raise SystemExit(1)


async def run_sync(account: str | None, force: bool) -> int:
    from mastodon_is_my_blog.queries import sync_all_identities

    meta, _ = await get_context(account)
    results = await sync_all_identities(meta, force=force)
    for result in results:
        print(result)
    print("Sync complete.")
    return 0


async def run_download_friends(account: str | None) -> int:
    from mastodon_is_my_blog.queries import sync_all_following_for_identity

    meta, identity = await get_context(account)
    print(f"Downloading full following/follower lists for {identity.acct} …")
    result = await sync_all_following_for_identity(meta.id, identity, on_progress=print_progress, cancelled=lambda: False)
    finish_progress()
    print(f"Done: {result}")
    return 0


async def run_download_notifications(account: str | None) -> int:
    from mastodon_is_my_blog.notification_sync import sync_all_notifications_for_identity

    meta, identity = await get_context(account)
    print(f"Downloading full notification history for {identity.acct} …")
    result = await sync_all_notifications_for_identity(meta.id, identity, on_progress=print_progress, cancelled=lambda: False)
    finish_progress()
    print(f"Done: {result}")
    return 0


async def run_favourites(account: str | None, full: bool) -> int:
    from mastodon_is_my_blog.queries import sync_my_favourites_for_identity

    meta, identity = await get_context(account)
    result = await sync_my_favourites_for_identity(meta.id, identity, full=full)
    print(f"Done: {result}")
    return 0


async def run_rebin(account: str | None) -> int:
    from mastodon_is_my_blog.queries import recompute_account_post_stats

    meta, identity = await get_context(account)
    result = await recompute_account_post_stats(meta.id, identity)
    print(f"Updated {result.get('updated')} accounts ({result.get('total_authors')} with cached posts).")
    return 0


async def run_backfill_flags(account: str | None) -> int:
    from mastodon_is_my_blog.maintenance import backfill_content_flags_for_identity

    meta, identity = await get_context(account)
    result = await backfill_content_flags_for_identity(meta.id, identity.id)
    print(f"Backfilled {result['updated']} posts.")
    return 0


async def run_nlp_backfill_command(account: str | None) -> int:
    from mastodon_is_my_blog.maintenance import run_nlp_backfill
    from mastodon_is_my_blog.text_topics import load_spacy_model

    meta, _ = await get_context(account)
    try:
        nlp = load_spacy_model()
    except Exception as exc:  # noqa: BLE001 - any load failure means the same fix
        print(f"spaCy model not available ({exc}). Install it with: uv run python -m mastodon_is_my_blog.scripts.install_spacy_model")
        return 1
    result = await run_nlp_backfill(meta.id, nlp, print_progress, lambda: False)
    finish_progress()
    print(f"Indexed {result['processed']} of {result['total']} threads.")
    return 0


async def run_catchup(account: str | None, mode: str, max_accounts: int | None) -> int:
    from mastodon_is_my_blog import catchup_runner

    meta, identity = await get_context(account)
    job = await catchup_runner.start_job(meta, identity, mode, max_accounts=max_accounts)
    print(f"Catch-up ({mode}) over {job.total} accounts — Ctrl-C to stop.")
    try:
        while job.task is not None and not job.task.done():
            label = job.current_acct or "starting"
            print_progress(job.done, job.total, label[:PROGRESS_STAGE_WIDTH])
            await asyncio.sleep(1)
        if job.task is not None:
            await job.task
    except KeyboardInterrupt:
        job.cancel_event.set()
        print("\nStopping after the current account …")
        if job.task is not None:
            await job.task
    finish_progress()
    print(f"Catch-up finished: {job.done}/{job.total} accounts, {job.errors} errors.")
    return 0 if job.errors == 0 else 1


def run_admin_command(args) -> int:
    require_local_mode()
    command = getattr(args, "admin_command", None)
    account = getattr(args, "account", None)

    if command == "sync":
        return asyncio.run(run_sync(account, force=not args.no_force))
    if command == "download-friends":
        return asyncio.run(run_download_friends(account))
    if command == "download-notifications":
        return asyncio.run(run_download_notifications(account))
    if command == "favourites":
        return asyncio.run(run_favourites(account, full=args.full))
    if command == "rebin":
        return asyncio.run(run_rebin(account))
    if command == "backfill-flags":
        return asyncio.run(run_backfill_flags(account))
    if command == "nlp-backfill":
        return asyncio.run(run_nlp_backfill_command(account))
    if command == "catchup":
        return asyncio.run(run_catchup(account, args.mode, args.max_accounts))

    print("Usage: mimb admin {sync|download-friends|download-notifications|favourites|rebin|backfill-flags|nlp-backfill|catchup} ...")
    return 2


async def run_publish(build_only: bool, pages_workflow: bool, message: str) -> int:
    from mastodon_is_my_blog import blog_publish

    await init_db()
    status = blog_publish.get_publish_status()
    if not status["node_available"] or not status["eleventy_available"]:
        print("Warning: Node.js/Eleventy not found — building the plain fallback page. `make install-blog` gets you the themed blog.")

    result = await blog_publish.build_docs()
    print(f"Built {result['pages']} pages from {result['storm_count']} storms with {result['builder']} into {result['docs_path']}")

    if pages_workflow:
        workflow = blog_publish.create_pages_workflow()
        print(workflow["detail"])

    if build_only:
        return 0

    if not status["git_repo"]:
        print(f"{status['repo_root']} is not a git repository — skipping commit/push. Run from your blog repo, or use --build-only.")
        return 1

    push_result = blog_publish.git_publish(message)
    print(push_result["detail"])
    return 0 if push_result.get("ok") else 1


def run_publish_command(args) -> int:
    require_local_mode()
    return asyncio.run(run_publish(args.build_only, args.pages_workflow, args.message))


def run_doctor_command() -> int:
    """Environment checks; exit 1 if anything critical is broken."""
    failures = 0

    def check(label: str, ok: bool, detail: str = "", critical: bool = True) -> None:
        nonlocal failures
        mark = "ok " if ok else ("FAIL" if critical else "warn")
        print(f"[{mark:>4}] {label}{': ' + detail if detail else ''}")
        if not ok and critical:
            failures += 1

    check("python", True, sys.version.split()[0])

    try:
        from mastodon_is_my_blog.schema_version import describe_database

        info = asyncio.run(describe_database())
        check("database", True, f"{info['backend']} {info['url']} (schema {info['schema_version']})")
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        check("database", False, str(exc))

    try:
        from mastodon_is_my_blog.account_config import list_account_summaries

        summaries = list_account_summaries()
        check(
            "accounts",
            bool(summaries),
            ", ".join(f"{s.name} ({'token' if s.has_access_token else 'no token'})" for s in summaries) or "none — run `mimb auth login`",
            critical=False,
        )
    except Exception as exc:  # noqa: BLE001
        check("accounts/keyring", False, str(exc))

    for binary, critical in (("git", False), ("node", False), ("npm", False)):
        check(binary, shutil.which(binary) is not None, shutil.which(binary) or "not on PATH", critical=critical)

    from mastodon_is_my_blog.blog_build import eleventy_site_dir, find_eleventy_binary

    site_dir = eleventy_site_dir()
    check("eleventy", find_eleventy_binary(site_dir) is not None, str(site_dir), critical=False)

    try:
        import spacy

        ok = spacy.util.is_package("en_core_web_sm")
        check("spacy model", ok, "en_core_web_sm" if ok else "not installed (forum topic words disabled)", critical=False)
    except Exception as exc:  # noqa: BLE001
        check("spacy", False, str(exc), critical=False)

    if failures:
        print(f"{failures} critical problem(s).")
        return 1
    print("All critical checks passed.")
    return 0
