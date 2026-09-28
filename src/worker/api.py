"""HTTP surface of the pipeline, called by n8n over the Docker network.

One route per command of :mod:`src.cli`, which stays the single contract: each
route runs ``python -m src.cli <command>`` as a subprocess and returns the JSON
line it prints. Nothing is reimplemented here, so the commands behave the same
whether they are called by hand or by the workflow.

Why a separate container rather than Python inside the n8n image:
``docs/adr/0005-conteneur-radar-worker.md``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("radar.worker")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: A full collection takes minutes; the ceiling is there to release the worker
#: if a command ever hangs, not to cut a normal run short.
COMMAND_TIMEOUT_S = 3600

#: Lines of the command log kept in an error response, enough to see the cause
#: without returning the whole run.
JOURNAL_LINES = 20

app = FastAPI(
    title="Radar Tech FR — worker",
    description="Exécute les commandes du pipeline pour n8n.",
    version="1.0.0",
)


class IngestOptions(BaseModel):
    """Options of ``src.cli ingest``."""

    limit: int | None = None
    max_results: int | None = None
    dry_run: bool = False


class LoadOptions(BaseModel):
    """Options of ``src.cli load``."""

    embeddings: bool = False


class ReportOptions(BaseModel):
    """Options of ``src.cli report``."""

    week: date | None = None
    threshold: float | None = None
    min_previous: int | None = None
    measure: str | None = None


def build_flags(options: BaseModel) -> list[str]:
    """Turn an options model into command line flags.

    ``dry_run=True`` becomes ``--dry-run``; a false boolean and an unset option
    are both left out, so the command keeps its own defaults.
    """
    flags: list[str] = []
    for name, value in options.model_dump(exclude_none=True).items():
        flag = f"--{name.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                flags.append(flag)
        elif isinstance(value, date):
            flags += [flag, value.isoformat()]
        else:
            flags += [flag, str(value)]
    return flags


def _tail(text: str) -> list[str]:
    return text.strip().splitlines()[-JOURNAL_LINES:]


def run_command(command: str, options: BaseModel) -> dict[str, Any]:
    """Run one command and return the JSON payload it printed.

    Raises:
        HTTPException: 400 when the options are refused, 504 on timeout, 500
            when the command fails or prints something unreadable.
    """
    argv = [sys.executable, "-m", "src.cli", command, *build_flags(options)]
    logger.info("Lancement de %s", " ".join(argv[2:]))

    try:
        process = subprocess.run(
            argv,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as error:
        logger.error("%s dépasse %d s", command, COMMAND_TIMEOUT_S)
        raise HTTPException(
            status_code=504,
            detail={"commande": command, "erreur": f"délai de {COMMAND_TIMEOUT_S} s dépassé"},
        ) from error

    for line in _tail(process.stderr):
        logger.info("[%s] %s", command, line)

    if process.returncode != 0:
        # Typer sort avec le code 2 sur une option refusée : c'est la requête
        # qui est fautive, pas le pipeline.
        status = 400 if process.returncode == 2 else 500
        raise HTTPException(
            status_code=status,
            detail={
                "commande": command,
                "code_sortie": process.returncode,
                "journal": _tail(process.stderr),
            },
        )

    lines = process.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as error:
        logger.error("Sortie illisible de %s : %r", command, process.stdout[-500:])
        raise HTTPException(
            status_code=500,
            detail={"commande": command, "erreur": "sortie JSON illisible"},
        ) from error


@app.get("/health")
def health() -> dict[str, str]:
    """Sonde de démarrage du conteneur."""
    return {"statut": "ok"}


@app.post("/ingest")
def ingest(options: IngestOptions | None = None) -> dict[str, Any]:
    """Collecter les offres France Travail dans data/raw/."""
    return run_command("ingest", options or IngestOptions())


@app.post("/load")
def load(options: LoadOptions | None = None) -> dict[str, Any]:
    """Reconstruire l'entrepôt DuckDB et la table des compétences."""
    return run_command("load", options or LoadOptions())


@app.post("/report")
def report(options: ReportOptions | None = None) -> dict[str, Any]:
    """Écrire le rapport hebdomadaire et retourner son Markdown.

    Le contenu du fichier est renvoyé dans ``contenu_markdown`` : n8n compose
    l'e-mail à partir de la réponse, sans accès au disque.
    """
    payload = run_command("report", options or ReportOptions())
    markdown_path = Path(payload["markdown"])
    return payload | {"contenu_markdown": markdown_path.read_text(encoding="utf-8")}
