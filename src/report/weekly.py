"""Weekly market summary: new offers, emerging skills and growth alerts.

The week is the one the offer was *created* in, not the one it was collected
in, like the monthly view of ``src/nlp/skills.sql``. The report covers the last
complete Monday-to-Sunday week and compares it with the week before.

Every threshold lives in the ``rapport`` section of ``config/queries.yaml`` so
that it can be calibrated on real data without touching the code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "queries.yaml"

MEASURES = ("part", "volume")

#: YAML key -> ``ReportSettings`` field.
_CONFIG_KEYS = {
    "mesure": "measure",
    "seuil_croissance_pct": "growth_threshold_pct",
    "min_offres_semaine_precedente": "min_previous_offers",
    "min_offres_emergente": "min_emerging_offers",
    "max_emergentes": "max_emerging",
}

_WEEK_TOTALS = """
SELECT
    count(*) FILTER (WHERE date_creation >= $current AND date_creation < $next),
    count(*) FILTER (WHERE date_creation <  $current),
    count(*) FILTER (WHERE date_creation >= $current AND est_alternance)
FROM offres
WHERE date_creation >= $previous AND date_creation < $next
"""

# An offer citing a skill through both the text and the API fields counts once.
_SKILL_COUNTS = """
SELECT
    c.competence,
    c.famille,
    count(DISTINCT c.offre_id) FILTER (WHERE o.date_creation <  $current),
    count(DISTINCT c.offre_id) FILTER (WHERE o.date_creation >= $current)
FROM offre_competences c
JOIN offres o ON o.id = c.offre_id
WHERE o.date_creation >= $previous AND o.date_creation < $next
GROUP BY c.competence, c.famille
"""


@dataclass(frozen=True)
class ReportSettings:
    """Thresholds of the weekly report, read from the ``rapport`` YAML section."""

    measure: str = "part"
    growth_threshold_pct: float = 20.0
    min_previous_offers: int = 5
    min_emerging_offers: int = 3
    max_emerging: int = 10

    def __post_init__(self) -> None:
        if self.measure not in MEASURES:
            raise ValueError(f"measure must be one of {MEASURES}, got {self.measure!r}")

    @classmethod
    def from_config(cls, path: Path = DEFAULT_CONFIG_PATH) -> ReportSettings:
        """Read the settings, falling back to the defaults for any missing key."""
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        section = config.get("rapport") or {}
        return cls(**{field: section[key] for key, field in _CONFIG_KEYS.items() if key in section})

    def override(self, **values: Any) -> ReportSettings:
        """Return a copy where every non-``None`` value replaces the configured one."""
        return replace(self, **{k: v for k, v in values.items() if v is not None})


@dataclass(frozen=True)
class SkillTrend:
    """One skill over the two compared weeks."""

    competence: str
    famille: str
    previous_offers: int
    current_offers: int
    previous_share_pct: float
    current_share_pct: float
    #: Growth of the configured measure; ``None`` when it was zero last week.
    growth_pct: float | None


@dataclass(frozen=True)
class WeeklyReport:
    """Everything the Markdown and JSON renderings need."""

    week_start: date
    offers: int
    previous_offers: int
    alternance_offers: int
    settings: ReportSettings
    alerts: list[SkillTrend]
    emerging: list[SkillTrend]

    @property
    def previous_week_start(self) -> date:
        return self.week_start - timedelta(weeks=1)

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)


def week_start(day: date) -> date:
    """Return the Monday of the week ``day`` belongs to."""
    return day - timedelta(days=day.weekday())


def last_complete_week(today: date) -> date:
    """Return the Monday of the last week that ended before ``today``."""
    return week_start(today) - timedelta(weeks=1)


def _share(count: int, total: int) -> float:
    return round(100.0 * count / total, 2) if total else 0.0


def _growth(previous: float, current: float) -> float | None:
    return round(100.0 * (current - previous) / previous, 1) if previous else None


def build_weekly_report(
    con: duckdb.DuckDBPyConnection, week: date, settings: ReportSettings
) -> WeeklyReport:
    """Compute the report of the week starting on Monday ``week``."""
    params = {
        "previous": week - timedelta(weeks=1),
        "current": week,
        "next": week + timedelta(weeks=1),
    }
    offers, previous_offers, alternance = con.execute(_WEEK_TOTALS, params).fetchone()

    trends = []
    for competence, famille, before, now in con.execute(_SKILL_COUNTS, params).fetchall():
        previous_share = _share(before, previous_offers)
        current_share = _share(now, offers)
        if settings.measure == "part":
            growth = _growth(previous_share, current_share)
        else:
            growth = _growth(before, now)
        trends.append(
            SkillTrend(competence, famille, before, now, previous_share, current_share, growth)
        )

    alerts = [
        t for t in trends
        if t.previous_offers >= settings.min_previous_offers
        and t.growth_pct is not None
        and t.growth_pct > settings.growth_threshold_pct
    ]
    emerging = [
        t for t in trends
        if t.previous_offers < settings.min_previous_offers
        and t.current_offers >= settings.min_emerging_offers
        and t.current_offers > t.previous_offers
    ]
    alerts.sort(key=lambda t: (-(t.growth_pct or 0.0), t.competence))
    emerging.sort(key=lambda t: (-t.current_offers, t.competence))

    logger.info(
        "Semaine du %s : %d offres, %d alertes, %d émergentes",
        week, offers, len(alerts), len(emerging),
    )
    return WeeklyReport(
        week_start=week,
        offers=offers,
        previous_offers=previous_offers,
        alternance_offers=alternance,
        settings=settings,
        alerts=alerts,
        emerging=emerging[: settings.max_emerging],
    )


def generate(week: date, settings: ReportSettings, db_path: Path = DEFAULT_DB_PATH) -> WeeklyReport:
    """Open the warehouse read-only and compute the report of ``week``."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        return build_weekly_report(con, week_start(week), settings)
