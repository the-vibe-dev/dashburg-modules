import logging
import os
import typer
from typing import Annotated
from rich import print
from core.config import settings
from core.logging import setup_logging
from core.http_client import init_async_client, shutdown_async_client
from core.orchestrator import run_end_to_end, RunParams, run_auto_discovery, generate_top_ideas_from_db
from storage.repository import get_counts, rawpost_counts_by_source, list_run_events, provider_stats
from storage.db import init_db

app = typer.Typer(add_completion=False)

@app.command("db-init")
def db_init(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Delete existing DB file and recreate (required after schema changes).",
        is_flag=True,
    )
):
    """Initialize SQLite DB."""
    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    if reset:
        # only supports sqlite file URLs in this MVP
        if settings.database_url.startswith("sqlite:///"):
            db_path = settings.database_url.replace("sqlite:///", "")
            if os.path.exists(db_path):
                os.remove(db_path)
    init_db()
    print("[green]DB initialized.[/green]")
    shutdown_async_client()

@app.command("run")
def run(
    query: Annotated[str, typer.Option("--query", help="Search query", is_flag=False)],
    topic: Annotated[str, typer.Option("--topic", help="Topic label", is_flag=False)] = "general",
    limit: Annotated[int, typer.Option("--limit", help="Total ingestion limit across sources", is_flag=False)] = 40,
    enable_youtube: Annotated[bool, typer.Option("--enable-youtube", help="Enable optional YouTube search scraping", is_flag=True)] = False,
    enable_x_trends: Annotated[bool, typer.Option("--enable-x-trends", help="Enable optional X trends Playwright source", is_flag=True)] = False,
):
    """Run end-to-end scan -> pains -> clusters -> scoring -> ideas -> reports."""
    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    res = run_end_to_end(
        RunParams(
            query=query,
            topic=topic,
            limit=limit,
            enable_youtube=enable_youtube,
            sources={"x_trends": bool(enable_x_trends)},
        )
    )
    print("[bold]Run complete[/bold]")
    for k, v in res.items():
        print(f" - {k}: {v}")
    shutdown_async_client()

@app.command("auto-scan")
def auto_scan(
    ideas_per_run: int = typer.Option(5, help="Ideas per discovery run"),
    target_topics: int = typer.Option(20, help="Target topics to discover"),
):
    """Run auto-discovery and short scans across discovered topics."""
    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    res = run_auto_discovery(ideas_per_run=ideas_per_run, target_topics=target_topics)
    print("[bold]Auto-scan complete[/bold]")
    for k, v in res.items():
        print(f" - {k}: {v}")
    shutdown_async_client()

@app.command("diagnose")
def diagnose():
    """Print DB counts and source breakdown."""
    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    counts = get_counts()
    sources = rawpost_counts_by_source()
    print("[bold]DB Counts[/bold]")
    for k, v in counts.items():
        print(f" - {k}: {v}")
    print("[bold]RawPost by source[/bold]")
    for k, v in sources.items():
        print(f" - {k}: {v}")
    events = list_run_events(limit=5)
    if events:
        print("[bold]Recent run events[/bold]")
        for e in events:
            print(f" - {e.created_at} {e.stage_name} {e.status} in={e.input_count} out={e.output_count} err={e.error_message}")
    calls = provider_stats(limit=5)
    if calls:
        print("[bold]Recent provider calls[/bold]")
        for c in calls:
            print(f" - {c.created_at} {c.provider} {c.operation} ok={c.success} cache={c.cache_hit} retries={c.retries} err={c.error_message}")
        total = len(calls)
        cache_hits = len([c for c in calls if c.cache_hit])
        if total:
            print(f" - cache_hit_rate: {cache_hits/total:.2%}")
    shutdown_async_client()

@app.command("rebuild")
def rebuild(
    query: Annotated[str, typer.Option("--query", help="Search query", is_flag=False)],
    topic: Annotated[str, typer.Option("--topic", help="Topic label", is_flag=False)] = "general",
    limit: Annotated[int, typer.Option("--limit", help="Total ingestion limit across sources", is_flag=False)] = 40,
    enable_youtube: Annotated[bool, typer.Option("--enable-youtube", help="Enable optional YouTube search scraping", is_flag=True)] = False,
    enable_x_trends: Annotated[bool, typer.Option("--enable-x-trends", help="Enable optional X trends Playwright source", is_flag=True)] = False,
):
    """Deterministic end-to-end rebuild: ingestion -> extraction -> clustering -> scoring -> ideas -> report."""
    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    res = run_end_to_end(
        RunParams(
            query=query,
            topic=topic,
            limit=limit,
            enable_youtube=enable_youtube,
            sources={"x_trends": bool(enable_x_trends)},
        )
    )
    print("[bold]Rebuild complete[/bold]")
    for k, v in res.items():
        print(f" - {k}: {v}")
    shutdown_async_client()


@app.command("top-from-db", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def top_from_db(ctx: typer.Context):
    """Generate top ideas from existing DB clusters without re-ingesting data."""
    ideas = 8
    clusters = 80
    args = list(ctx.args)
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--ideas" and i + 1 < len(args):
            ideas = int(args[i + 1])
            i += 2
            continue
        if token.startswith("--ideas="):
            ideas = int(token.split("=", 1)[1])
            i += 1
            continue
        if token == "--clusters" and i + 1 < len(args):
            clusters = int(args[i + 1])
            i += 2
            continue
        if token.startswith("--clusters="):
            clusters = int(token.split("=", 1)[1])
            i += 1
            continue
        # positional fallback: top-from-db 8 80
        if token.isdigit() and ideas == 8:
            ideas = int(token)
        elif token.isdigit() and clusters == 80:
            clusters = int(token)
        i += 1

    log_file = os.path.join(settings.data_dir, "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    init_async_client()
    res = generate_top_ideas_from_db(ideas=ideas, cluster_limit=clusters)
    print("[bold]Top From DB[/bold]")
    print(f" - clusters: {res['clusters']}")
    print(f" - ideas: {res['ideas']}")
    print("[bold]cluster_label | opportunity_score | idea_name[/bold]")
    for row in res.get("items", [])[:ideas]:
        print(f" - {row['cluster_label'][:55]} | {row['opportunity_score']:.2f} | {row['idea_name']}")
    shutdown_async_client()

if __name__ == "__main__":
    app()
