"""Command-line tools.

Deliberately able to do the whole analytical job with no web server and no database:
``analyze`` parses a demo and prints the scoreboard. That makes the parser and the
statistics debuggable in isolation, which is where almost every real problem turns out
to live.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated

import typer

from app.config import get_settings

cli = typer.Typer(
    add_completion=False,
    help="CS2 match analytics tools.",
    no_args_is_help=True,
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _fmt(value: object, decimals: int = 1) -> str:
    """Render a metric, showing an em dash for "unknown" rather than a misleading 0."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


@cli.command()
def probe(
    demo: Annotated[Path, typer.Argument(help="Path to a .dem file")],
    out: Annotated[Path | None, typer.Option(help="Write the report here")] = None,
) -> None:
    """Dump everything the parser returns for a demo, and measure the cost.

    Run this before trusting any assumption about the parser's output: column names,
    weapon strings, which datasets a given recording actually contains.
    """
    from app.probe import probe as run_probe

    if not demo.is_file():
        typer.secho(f"no such file: {demo}", fg=typer.colors.RED)
        raise typer.Exit(1)
    report = run_probe(demo)
    target = out or (Path(__file__).resolve().parents[2] / "docs" / "awpy-probe.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report)
    typer.secho(f"wrote {target}", fg=typer.colors.GREEN)


@cli.command()
def analyze(
    demo: Annotated[Path, typer.Argument(help="Path to a .dem file")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON instead of a table")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Parse a demo and print its analytics. No server, no database."""
    _setup_logging(verbose)
    from app.analytics.compute import compute
    from app.parsing import errors as parse_errors
    from app.parsing.awpy_parser import get_parser

    if not demo.is_file():
        typer.secho(f"no such file: {demo}", fg=typer.colors.RED)
        raise typer.Exit(1)

    started = time.perf_counter()
    try:
        normalized = get_parser().parse(str(demo))
    except parse_errors.DemoParseError as exc:
        typer.secho(f"{exc.code}: {exc.user_message}", fg=typer.colors.RED)
        if exc.detail:
            typer.secho(f"  detail: {exc.detail}", fg=typer.colors.YELLOW)
        raise typer.Exit(2) from exc
    analytics = compute(normalized)
    elapsed = time.perf_counter() - started

    if as_json:
        from dataclasses import asdict

        print(
            json.dumps(
                {
                    "meta": asdict(normalized.meta),
                    "round_count": analytics.round_count,
                    "team_a_score": analytics.team_a_score,
                    "team_b_score": analytics.team_b_score,
                    "players": [asdict(p) for p in analytics.players],
                    "availability": {k: asdict(v) for k, v in normalized.availability.items()},
                    "anomalies": [asdict(a) for a in analytics.anomalies],
                },
                indent=2,
                default=str,
            )
        )
        return

    meta = normalized.meta
    team_a = meta.team_a_name or "Team A"
    team_b = meta.team_b_name or "Team B"
    print(
        f"\n  {meta.map_name or 'unknown map'}   "
        f"{team_a} {analytics.team_a_score} - {analytics.team_b_score} {team_b}"
    )
    print(
        f"  {analytics.round_count} scored rounds"
        f"{' (overtime)' if meta.has_overtime else ''}"
        f"   tick rate {meta.tick_rate:g} ({meta.tick_rate_source})"
        f"   parsed in {elapsed:.2f}s"
    )
    print(f"  parser {meta.parser_name} {meta.parser_version}   rosters from {meta.roster_source}")

    header = (
        f"\n  {'player':<24}{'T':>2}{'K':>5}{'D':>5}{'A':>4}{'K/D':>7}{'ADR':>8}"
        f"{'HS%':>7}{'KAST':>7}{'OK':>5}{'OD':>5}{'TD':>5}{'UD':>6}{'EF':>5}"
    )
    print(header)
    print("  " + "-" * (len(header) - 3))
    for p in sorted(analytics.players, key=lambda p: (-p.kills, p.deaths)):
        print(
            f"  {p.name[:23]:<24}{p.team or '?':>2}{p.kills:>5}{p.deaths:>5}{p.assists:>4}"
            f"{_fmt(p.kd, 2):>7}{_fmt(p.adr):>8}{_fmt(p.headshot_pct):>7}"
            f"{_fmt(p.kast):>7}{p.opening_kills:>5}{p.opening_deaths:>5}"
            f"{p.traded_deaths:>5}{_fmt(p.utility_damage):>6}{_fmt(p.enemies_flashed):>5}"
        )

    unusable = {name: entry for name, entry in normalized.availability.items() if not entry.usable}
    if unusable:
        print("\n  unavailable source data (affected metrics show as '—'):")
        for name, entry in sorted(unusable.items()):
            print(f"    {name:<16} {entry.state}: {entry.reason or ''}")
    if analytics.anomalies:
        print("\n  anomalies:")
        for anomaly in analytics.anomalies:
            print(f"    [{anomaly.code}] {anomaly.message}")
    print()


@cli.command()
def ingest(
    demo: Annotated[Path, typer.Argument(help="Path to a .dem file")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Parse a demo and store it in the database, as the server would."""
    _setup_logging(verbose)
    from sqlalchemy.orm import Session

    from app.analytics.compute import compute
    from app.db import get_engine
    from app.ingest import storage
    from app.models import Match, MatchStatus
    from app.parsing import errors as parse_errors
    from app.parsing.awpy_parser import get_parser
    from app.persist.schema_check import init_schema
    from app.persist.writer import persist_match

    settings = get_settings()
    if not demo.is_file():
        typer.secho(f"no such file: {demo}", fg=typer.colors.RED)
        raise typer.Exit(1)

    engine = get_engine()
    init_schema(engine)
    match_id = uuid.uuid4().hex

    with demo.open("rb") as handle:
        stored = storage.store_iter(
            settings,
            match_id,
            iter(lambda: handle.read(1 << 20), b""),
            display_name=demo.name,
        )

    with Session(engine) as session:
        existing = session.query(Match).filter(Match.sha256 == stored.sha256).one_or_none()
        if existing is not None:
            storage.delete_demo(stored.path)
            typer.secho(
                f"already ingested as {existing.id} ({existing.map_name})",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)
        session.add(
            Match(
                id=match_id,
                sha256=stored.sha256,
                original_filename=stored.display_name,
                stored_path=str(stored.path),
                size_bytes=stored.size_bytes,
                source="cli",
                status=MatchStatus.PROCESSING,
            )
        )
        session.commit()

    started = time.perf_counter()
    try:
        normalized = get_parser().parse(str(stored.path))
        analytics = compute(normalized)
    except parse_errors.DemoParseError as exc:
        typer.secho(f"{exc.code}: {exc.user_message}", fg=typer.colors.RED)
        raise typer.Exit(2) from exc

    with Session(engine) as session:
        persist_match(
            session,
            match_id,
            normalized,
            analytics,
            parse_seconds=round(time.perf_counter() - started, 2),
        )
        session.commit()
    typer.secho(
        f"ingested {match_id}: {normalized.meta.map_name} "
        f"{analytics.team_a_score}-{analytics.team_b_score}",
        fg=typer.colors.GREEN,
    )


@cli.command("fetch-fixture")
def fetch_fixture(
    name: Annotated[str | None, typer.Option(help="Fixture name; default is the smallest")] = None,
    list_only: Annotated[bool, typer.Option("--list", help="List fixtures and exit")] = False,
) -> None:
    """Download a public CS2 demo fixture for the integration tests.

    The demos are large and carry real player names, so they are never committed and
    never downloaded implicitly by a test run.
    """
    from app import fixtures

    settings = get_settings()
    settings.ensure_dirs()
    entries = fixtures.load_manifest(settings.fixtures_dir / "manifest.json")
    if not entries:
        typer.secho("the fixture manifest is empty or unreachable", fg=typer.colors.RED)
        raise typer.Exit(1)

    if list_only:
        for entry in sorted(entries, key=lambda e: e.size):
            truth = "with ground truth" if entry.ground_truth else "no ground truth"
            print(
                f"  {entry.size / 1e6:8.1f} MB  {entry.name:<30} {entry.map_name:<12} "
                f"{entry.result or '?':<7} {truth}"
            )
        return

    target = (
        next((e for e in entries if e.name == name), None) if name else fixtures.smallest(entries)
    )
    if target is None:
        typer.secho(f"no fixture named {name!r}", fg=typer.colors.RED)
        raise typer.Exit(1)

    last = [0.0]
    report_interval_s = 2.0

    def progress(done: int, total: int) -> None:
        now = time.time()
        if now - last[0] > report_interval_s:
            last[0] = now
            pct = (done / total * 100) if total else 0
            sys.stderr.write(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB ({pct:.0f}%)")
            sys.stderr.flush()

    typer.echo(f"downloading {target.asset} ({target.size / 1e6:.1f} MB)")
    path = fixtures.ensure(target, settings.fixtures_dir, progress=progress)
    sys.stderr.write("\r" + " " * 50 + "\r")
    typer.secho(f"verified -> {path}", fg=typer.colors.GREEN)


@cli.command("warm-maps")
def warm_maps() -> None:
    """Download and cache the radar images used by the map view."""
    from app.maps.data import available_maps, warm_cache

    settings = get_settings()
    total = len(available_maps(settings))
    warmed = warm_cache(settings)
    typer.secho(f"radar assets ready for {warmed} of {total} maps", fg=typer.colors.GREEN)


@cli.command("list-matches")
def list_matches() -> None:
    """List the matches currently stored in the database."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import get_engine
    from app.models import Match
    from app.persist.schema_check import init_schema

    engine = get_engine()
    init_schema(engine)
    with Session(engine) as session:
        rows = session.scalars(select(Match).order_by(Match.created_at.desc())).all()
    if not rows:
        typer.echo("no matches stored")
        return
    for row in rows:
        score = f"{row.team_a_score}-{row.team_b_score}" if row.team_a_score is not None else "—"
        print(
            f"  {row.id}  {row.status:<10} {row.map_name or '?':<12} {score:<7} "
            f"{row.original_filename or ''}"
        )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
