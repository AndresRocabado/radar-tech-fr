"""Command line entry point, the one n8n calls through its Execute Command node.

    python -m src.cli ingest     collect the offers into data/raw/
    python -m src.cli load       rebuild the warehouse and the skills table
    python -m src.cli report     write the weekly Markdown / JSON summary

Contract with n8n: standard output carries exactly one JSON line per command,
which the workflow parses; logs go to standard error. A failure exits non-zero,
which stops the workflow on that node.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from src.nlp.skills import build_skills
from src.report.render import DEFAULT_REPORTS_DIR, email_subject, write_report
from src.report.weekly import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    ReportSettings,
    generate,
    last_complete_week,
)
from src.warehouse.load import EmptyRawDirectoryError, build_warehouse

logger = logging.getLogger("radar")

app = typer.Typer(
    help="Pipeline Radar Tech FR : collecte, entrepôt, rapport hebdomadaire.",
    no_args_is_help=True,
    add_completion=False,
)


def _emit(payload: dict[str, Any]) -> None:
    """Print the single JSON line n8n reads from stdout."""
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str))


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="journal détaillé")] = False,
) -> None:
    """Configure logging on stderr, in UTF-8 even on a Windows console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


@app.command()
def ingest(
    config: Annotated[Path, typer.Option(help="fichier des recherches")] = DEFAULT_CONFIG_PATH,
    limit: Annotated[int | None, typer.Option(help="ne traiter que les N premières recherches")] = None,
    max_results: Annotated[int | None, typer.Option(help="plafond d'offres par recherche")] = None,
    dry_run: Annotated[bool, typer.Option(help="lister les recherches, sans appel")] = False,
) -> None:
    """Collecter les offres France Travail dans data/raw/."""
    # Imported here: the API client pulls in requests, which report and load never need.
    from src.ingest.rate_limit import FranceTravailAPIError
    from src.ingest.run import build_searches, load_config, run_collection
    from src.ingest.tls import enable_system_trust_store

    settings = load_config(config)
    if dry_run:
        _emit({"recherches": [s["motsCles"] for s in build_searches(settings, limit)]})
        return

    enable_system_trust_store()
    try:
        result = run_collection(settings, limit, max_results)
    except FranceTravailAPIError as error:
        logger.error("Collecte interrompue : %s", error)
        raise typer.Exit(code=1) from error

    _emit({
        "recherches": len(result.rows),
        "offres_collectees": sum(count for _, count in result.rows),
        "offres_uniques": len(result.unique_ids),
        # Le détail par mots-clés, pour repérer une recherche qui ne ramène
        # plus rien sans avoir à relire le journal.
        "par_recherche": dict(result.rows),
        "manifeste": result.manifest_path,
    })


@app.command()
def load(
    embeddings: Annotated[
        bool, typer.Option(help="recalculer aussi l'index vectoriel (long, télécharge le modèle)")
    ] = False,
) -> None:
    """Reconstruire l'entrepôt DuckDB et la table des compétences depuis data/raw/."""
    try:
        offers = build_warehouse()
    except EmptyRawDirectoryError as error:
        # Sortie non nulle : le nœud n8n s'arrête là plutôt que d'enchaîner sur
        # un entrepôt vide.
        logger.error("%s", error)
        raise typer.Exit(code=1) from error
    # raw_offres has just been rebuilt: offre_competences must follow, or it
    # would describe the previous load.
    skills = build_skills()
    payload: dict[str, Any] = {"offres": offers, "competences": skills}

    if embeddings:
        from src.nlp.embeddings import build_embeddings  # torch: only when asked

        build_embeddings()
        payload["embeddings"] = True
    _emit(payload)


@app.command()
def report(
    week: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="un jour de la semaine voulue (défaut : la dernière complète)"),
    ] = None,
    threshold: Annotated[float | None, typer.Option(help="seuil d'alerte, en %")] = None,
    min_previous: Annotated[int | None, typer.Option(help="offres minimales la semaine précédente")] = None,
    measure: Annotated[str | None, typer.Option(help="part ou volume")] = None,
    db: Annotated[Path, typer.Option(help="entrepôt DuckDB")] = DEFAULT_DB_PATH,
    out_dir: Annotated[Path, typer.Option(help="dossier de sortie")] = DEFAULT_REPORTS_DIR,
    config: Annotated[Path, typer.Option(help="fichier de configuration")] = DEFAULT_CONFIG_PATH,
) -> None:
    """Écrire le résumé hebdomadaire en Markdown et en JSON."""
    try:
        settings = ReportSettings.from_config(config).override(
            growth_threshold_pct=threshold, min_previous_offers=min_previous, measure=measure
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    day = week.date() if week else last_complete_week(date.today())
    weekly = generate(day, settings, db)
    markdown_path, json_path = write_report(weekly, out_dir)

    _emit({
        "semaine": weekly.week_start,
        "offres": weekly.offers,
        "alertes": len(weekly.alerts),
        "emergentes": len(weekly.emerging),
        "objet": email_subject(weekly),
        "markdown": markdown_path,
        "json": json_path,
    })


if __name__ == "__main__":
    app()
