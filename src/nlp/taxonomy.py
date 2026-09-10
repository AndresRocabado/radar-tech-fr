"""Chargement et compilation du dictionnaire contrôlé de compétences.

Ce module ne connaît ni les offres ni DuckDB : il transforme
``data/skills_taxonomy.yaml`` en un jeu d'expressions régulières et sait dire,
pour un texte donné, quelles technologies y sont citées.

Le matching est volontairement littéral. Il n'y a ni lemmatisation ni distance
d'édition : sur un dictionnaire de noms propres, une faute de frappe est moins
probable qu'un faux positif introduit par de l'approximation.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "data" / "skills_taxonomy.yaml"

#: Séparateurs internes d'un terme. « Power BI » est écrit une fois et retrouve
#: « PowerBI », « Power-BI » et « Power_BI » sans qu'on ait à les lister.
_SEPARATORS = re.compile(r"[\s_\-]+")
_SEPARATOR_PATTERN = r"[\s_\-]*"

#: Limites de mot maison. ``\b`` ne convient pas : il tomberait au milieu de
#: « C++ » et de « C# », dont le dernier caractère n'est pas un caractère de
#: mot. Exclure ``#`` à droite empêche « C » de mordre sur le « C » de « C# ».
_LEFT_BOUNDARY = r"(?<![\w#])"
_RIGHT_BOUNDARY = r"(?![\w#])"


def strip_accents(text: str) -> str:
    """Retirer les diacritiques, en conservant la casse.

    La décomposition NFKD ramène aussi les espaces insécables à des espaces
    ordinaires, ce qui évite de rater « Power BI » collé par un ``\\u00a0``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _term_pattern(term: str) -> str:
    """Construire le motif d'un terme unique, séparateurs assouplis."""
    parts = [re.escape(part) for part in _SEPARATORS.split(strip_accents(term)) if part]
    return _SEPARATOR_PATTERN.join(parts)


@dataclass(frozen=True)
class Skill:
    """Une technologie du dictionnaire, prête à être cherchée dans un texte."""

    label: str
    family: str
    pattern: re.Pattern[str]

    def matches(self, text: str) -> bool:
        """Dire si le texte — déjà désaccentué — cite cette technologie."""
        return self.pattern.search(text) is not None


def _alternation(terms: list[str]) -> str:
    """Assembler les termes en une alternance, les plus longs d'abord."""
    return "|".join(sorted((_term_pattern(t) for t in terms), key=len, reverse=True))


def _build_skill(entry: str | dict[str, Any], family: str) -> Skill:
    """Compiler une entrée du YAML, en chaîne simple ou en bloc.

    Les deux régimes de casse cohabitent dans un seul motif, via le groupe à
    portée ``(?i:…)`` : une entrée peut chercher « Integromat » sans égard à la
    casse et « Make » uniquement capitalisé.
    """
    if isinstance(entry, str):
        entry = {"label": entry}

    # Le label est toujours cherché en plus des alias : les entrées dont le nom
    # est ambigu portent une parenthèse (« R (langage) ») qui les rend inertes.
    label = entry["label"]
    sensitive: list[str] = list(entry.get("alias_casse", []))
    insensitive: list[str] = []
    own = [label, *entry.get("alias", [])]
    (sensitive if entry.get("casse", False) else insensitive).extend(own)

    branches = []
    if insensitive:
        branches.append(f"(?i:{_alternation(insensitive)})")
    if sensitive:
        branches.append(_alternation(sensitive))

    pattern = re.compile(f"{_LEFT_BOUNDARY}(?:{'|'.join(branches)}){_RIGHT_BOUNDARY}")
    return Skill(label=label, family=family, pattern=pattern)


class Taxonomy:
    """Le dictionnaire contrôlé, compilé une fois et interrogé N fois."""

    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills

    @classmethod
    def load(cls, path: Path = DEFAULT_TAXONOMY_PATH) -> "Taxonomy":
        """Lire et compiler le YAML.

        Raises:
            ValueError: si un même label apparaît deux fois. Le label est la
                clé d'agrégation du dashboard ; un doublon entre deux familles
                éclaterait silencieusement les comptages.
        """
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        skills = [
            _build_skill(entry, family)
            for family, entries in document["familles"].items()
            for entry in entries
        ]

        counts = Counter(skill.label for skill in skills)
        duplicates = [label for label, n in counts.items() if n > 1]
        if duplicates:
            raise ValueError(f"Labels en double dans {path.name} : {sorted(duplicates)}")

        return cls(skills)

    @property
    def families(self) -> list[str]:
        """Les familles présentes, dans l'ordre du fichier."""
        return list(dict.fromkeys(skill.family for skill in self.skills))

    def find(self, text: str | None) -> list[Skill]:
        """Retourner les technologies citées dans ``text``, sans doublon.

        Le texte est désaccentué une seule fois pour l'ensemble du
        dictionnaire, pas une fois par technologie.
        """
        if not text:
            return []
        normalized = strip_accents(text)
        return [skill for skill in self.skills if skill.matches(normalized)]
