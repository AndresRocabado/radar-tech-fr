"""Lecture de ``offre_competences`` : classement et part du no-code.

Deux chiffres seulement, mais reproductibles : le top des compétences et la
proportion d'offres citant du no-code / low-code. Ils vivent ici plutôt que
dans ``skills.py`` pour que l'extraction reste indépendante de sa restitution.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from src.nlp.nocode import GENERIC_TERM, NOCODE_FAMILY

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"

_TOP_SKILLS = """
SELECT
    competence,
    famille,
    count(DISTINCT offre_id) AS offres,
    round(100.0 * count(DISTINCT offre_id) / (SELECT count(*) FROM offres), 1) AS part_pct
FROM offre_competences
GROUP BY competence, famille
ORDER BY offres DESC, competence
LIMIT ?
"""

_NOCODE_SHARE = """
SELECT
    (SELECT count(*) FROM offres) AS offres_total,
    count(DISTINCT offre_id) FILTER (WHERE competence NOT LIKE ?) AS offres_outil,
    count(DISTINCT offre_id) AS offres_famille
FROM offre_competences
WHERE famille = ?
"""


def top_skills(
    con: duckdb.DuckDBPyConnection, limit: int = 30
) -> list[tuple[str, str, int, float]]:
    """Les compétences les plus citées, comptées en offres distinctes."""
    return con.execute(_TOP_SKILLS, [limit]).fetchall()


def nocode_share(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int]:
    """Retourner ``(offres_total, offres_citant_un_outil, offres_citant_la_famille)``.

    Le deuxième chiffre ne retient que les outils nommés (Power Automate, n8n,
    Airtable…) ; le troisième y ajoute les offres qui ne disent que « no-code »
    ou « low-code » sans nommer d'outil.
    """
    row = con.execute(_NOCODE_SHARE, [GENERIC_TERM, NOCODE_FAMILY]).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def print_report(db_path: Path = DEFAULT_DB_PATH, limit: int = 30) -> None:
    """Afficher le classement et la part du no-code sur la sortie standard."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        classement = top_skills(con, limit)
        total, outil, famille = nocode_share(con)

    print(f"Top {limit} des compétences ({total} offres distinctes)\n")
    print(f"{'#':>3}  {'Compétence':<28} {'Famille':<18} {'Offres':>6} {'Part':>7}")
    for rank, (competence, family, offres, part) in enumerate(classement, start=1):
        print(f"{rank:>3}  {competence:<28} {family:<18} {offres:>6} {part:>6.1f}%")

    def pct(count: int) -> str:
        return f"{100.0 * count / total:.1f}%" if total else "n/a"

    print(f"\nNo-code / low-code sur {total} offres")
    print(f"  au moins un outil nommé      : {outil:>3} offres  ({pct(outil)})")
    print(f"  outil ou terme générique     : {famille:>3} offres  ({pct(famille)})")


def main() -> None:
    """Point d'entrée de ``python -m src.nlp.report``."""
    print_report()


if __name__ == "__main__":
    main()
