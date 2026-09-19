"""Markdown and JSON renderings of a :class:`WeeklyReport`.

The Markdown file is the body of the weekly email; the JSON file carries the
same figures for any later automation. Both are named after the ISO week, so a
second run for the same week overwrites them instead of piling up.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .weekly import SkillTrend, WeeklyReport

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "data" / "reports"


def _fr(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _decimal(value: float) -> str:
    """French decimal comma, applied to the number only (never to a label like .NET)."""
    return f"{value:.1f}".replace(".", ",")


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    return ("+" if value >= 0 else "") + _decimal(value) + " %"


def iso_week_label(day: date) -> str:
    """Return ``2026-W37`` for any day of ISO week 37 of 2026."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def email_subject(report: WeeklyReport) -> str:
    """Subject line, flagged when at least one alert fired."""
    prefix = f"[ALERTE x{len(report.alerts)}] " if report.alerts else ""
    return f"{prefix}Radar Tech FR — semaine du {_fr(report.week_start)}"


def report_to_dict(report: WeeklyReport) -> dict[str, Any]:
    """Return a JSON-serialisable dictionary of the report."""
    return {
        "semaine": iso_week_label(report.week_start),
        "debut": report.week_start.isoformat(),
        "fin": report.week_end.isoformat(),
        "offres": {
            "nouvelles": report.offers,
            "semaine_precedente": report.previous_offers,
            "variation_pct": _variation(report.previous_offers, report.offers),
            "alternance": report.alternance_offers,
        },
        "parametres": asdict(report.settings),
        "alertes": [asdict(t) for t in report.alerts],
        "emergentes": [asdict(t) for t in report.emerging],
    }


def _variation(previous: int, current: int) -> float | None:
    return round(100.0 * (current - previous) / previous, 1) if previous else None


def _trend_table(trends: list[SkillTrend], with_growth: bool) -> list[str]:
    header = "| Compétence | Famille | Offres S-1 | Offres S | Part S-1 | Part S |"
    rule = "|---|---|--:|--:|--:|--:|"
    if with_growth:
        header += " Croissance |"
        rule += "--:|"
    lines = [header, rule]
    for t in trends:
        line = (
            f"| {t.competence} | {t.famille} | {t.previous_offers} | {t.current_offers} "
            f"| {_decimal(t.previous_share_pct)} % | {_decimal(t.current_share_pct)} % |"
        )
        if with_growth:
            line += f" {_signed(t.growth_pct)} |"
        lines.append(line)
    return lines


def to_markdown(report: WeeklyReport) -> str:
    """Render the report as the French Markdown body of the weekly email."""
    s = report.settings
    measure = "part des offres" if s.measure == "part" else "nombre d'offres"
    lines = [
        f"# Radar Tech FR — semaine du {_fr(report.week_start)} au {_fr(report.week_end)}",
        "",
        "## Nouvelles offres",
        "",
        f"- **{report.offers}** offres publiées "
        f"({_signed(_variation(report.previous_offers, report.offers))} par rapport aux "
        f"{report.previous_offers} de la semaine précédente)",
        f"- dont **{report.alternance_offers}** en alternance",
        "",
        f"## Alertes : croissance de plus de {s.growth_threshold_pct:g} %",
        "",
        f"Mesure : {measure}. Seules les compétences citées par au moins "
        f"{s.min_previous_offers} offres la semaine précédente sont comparées.",
        "",
    ]
    if report.alerts:
        lines += _trend_table(report.alerts, with_growth=True)
    else:
        lines.append("Aucune alerte cette semaine.")

    lines += [
        "",
        "## Compétences émergentes",
        "",
        f"Moins de {s.min_previous_offers} offres la semaine précédente, "
        f"au moins {s.min_emerging_offers} cette semaine.",
        "",
    ]
    if report.emerging:
        lines += _trend_table(report.emerging, with_growth=False)
    else:
        lines.append("Aucune compétence émergente cette semaine.")

    lines += [
        "",
        "---",
        "",
        "Source : API Offres d'emploi v2 de France Travail. Les semaines sont "
        "celles de création des offres ; une offre retirée avant la collecte "
        "n'est pas comptée.",
        "",
    ]
    return "\n".join(lines)


def write_report(report: WeeklyReport, out_dir: Path = DEFAULT_REPORTS_DIR) -> tuple[Path, Path]:
    """Write ``rapport_<semaine ISO>.md`` and ``.json`` and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"rapport_{iso_week_label(report.week_start)}"
    markdown_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    markdown_path.write_text(to_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return markdown_path, json_path
