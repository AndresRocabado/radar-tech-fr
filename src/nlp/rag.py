"""Contexte et consignes envoyés au modèle de langue par la page « Assistant ».

Le modèle ne voit jamais l'entrepôt : il reçoit les statistiques du
sous-ensemble d'offres retenu, comptées en SQL par DuckDB, puis les offres
elles-mêmes. Les chiffres sont donc calculés, jamais déduits d'une lecture des
descriptions, et le system prompt interdit d'en produire d'autres. Le module
reste pur — ni Streamlit, ni DuckDB, ni réseau — pour se tester à la main.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: Longueur retenue de chaque description : de quoi situer le poste, pas plus.
MAX_EXCERPT = 600
#: Phrase imposée au modèle quand le contexte ne suffit pas, reprise telle
#: quelle par la réponse hors ligne.
NO_ANSWER = "Je n'ai pas cette information dans les données."

_NARROW_SPACE = " "
_UNKNOWN = "non renseigné"

SYSTEM_PROMPT = """\
Tu es l'assistant de « Radar Tech FR », un observatoire du marché de l'emploi \
tech en France construit sur les offres publiées par l'API France Travail.

Tu réponds à partir du contexte fourni, et de lui seul. Règles sans exception :

1. Réponds en français, sur un ton factuel, en cinq phrases au plus.
2. Commence par dire sur combien d'offres ta réponse se fonde et sur combien \
d'offres porte la sélection complète : les deux nombres sont donnés dans le \
bloc STATISTIQUES.
3. Ne cite que des chiffres présents dans le bloc STATISTIQUES. N'additionne, \
ne calcule, n'extrapole et n'arrondis rien toi-même. Les offres du bloc OFFRES \
servent à illustrer et à citer des exemples, jamais à être comptées.
4. Si le contexte ne permet pas de répondre, écris exactement « {no_answer} », \
puis indique en une phrase ce qui manque. Vaut aussi pour une question à \
laquelle le contexte ne répond qu'à moitié : réponds sur la partie couverte, \
et emploie cette phrase pour le reste.
5. N'utilise aucune connaissance extérieure au contexte : ni salaire de \
marché, ni classement d'outils, ni entreprise absente des offres.
6. Rappelle que ces chiffres décrivent les offres collectées, pas le marché \
de l'emploi tout entier, dès que la question porte sur une tendance.
""".format(no_answer=NO_ANSWER)


def _int(value: int) -> str:
    """``1234`` -> ``1 234``."""
    return f"{value:,}".replace(",", _NARROW_SPACE)


def _eur(value: float | None) -> str:
    """``35000.0`` -> ``35 000 €``."""
    if value is None:
        return _UNKNOWN
    return f"{value:,.0f}{_NARROW_SPACE}€".replace(",", _NARROW_SPACE)


def _pct(part: int, whole: int) -> str:
    """``12, 20`` -> ``60 %`` ; un ensemble vide n'a pas de part."""
    return "—" if not whole else f"{100 * part / whole:.0f}{_NARROW_SPACE}%"


def _day(value: date | None) -> str:
    """``date(2026, 6, 1)`` -> ``01/06/2026``."""
    return _UNKNOWN if value is None else value.strftime("%d/%m/%Y")


def _counts(pairs: tuple[tuple[str, int], ...]) -> str:
    """``(("Python", 14), …)`` -> ``Python (14), …``."""
    return ", ".join(f"{name} ({_int(count)})" for name, count in pairs) or "aucune"


def _excerpt(text: str | None) -> str:
    """Ramener une description à une ligne d'au plus :data:`MAX_EXCERPT` signes."""
    clean = " ".join((text or "").split())
    return clean if len(clean) <= MAX_EXCERPT else clean[:MAX_EXCERPT].rstrip() + "…"


@dataclass(frozen=True)
class Offer:
    """Une offre du sous-ensemble, telle qu'elle est présentée au modèle."""

    id: str
    title: str | None
    company: str | None
    place: str | None
    contract: str | None
    apprenticeship: bool
    salary_min: float | None
    salary_max: float | None
    created: date | None
    description: str | None

    def _salary(self) -> str:
        low = self.salary_min if self.salary_min is not None else self.salary_max
        high = self.salary_max if self.salary_max is not None else self.salary_min
        if low is None:
            return "salaire non renseigné"
        return f"{_eur(low)} par an" if high == low else f"{_eur(low)} à {_eur(high)} par an"

    def as_text(self, rank: int) -> str:
        """Le bloc de deux lignes décrivant l'offre, précédé de son rang."""
        contract = self.contract or _UNKNOWN
        head = " | ".join([
            self.title or "intitulé inconnu",
            self.company or "entreprise non nommée",
            self.place or "lieu non renseigné",
            f"{contract}, alternance" if self.apprenticeship else contract,
            self._salary(),
            f"publiée le {_day(self.created)}",
        ])
        return f"[{rank}] {head}\n    {_excerpt(self.description)}"


@dataclass(frozen=True)
class Stats:
    """Statistiques du sous-ensemble, comptées en SQL et non par le modèle."""

    offers: int
    filtered_offers: int
    apprenticeships: int
    with_salary: int
    median_salary: float | None
    first_day: date | None
    last_day: date | None
    regions: tuple[tuple[str, int], ...] = ()
    contracts: tuple[tuple[str, int], ...] = ()
    skills: tuple[tuple[str, int], ...] = ()

    def as_text(self, title: str = "STATISTIQUES") -> str:
        """Les chiffres du sous-ensemble, seule source autorisée des deux côtés.

        Le même bloc sert de contexte au modèle et de corps à la réponse hors ligne.
        """
        salary = (
            f"{_eur(self.median_salary)} (médiane calculée sur les "
            f"{_int(self.with_salary)} offres qui affichent un salaire)"
            if self.with_salary
            else "aucune offre du sous-ensemble n'affiche de salaire"
        )
        return "\n".join([
            title,
            f"- Offres de ce sous-ensemble : {_int(self.offers)}",
            f"- Offres de la sélection complète (filtres de la barre latérale) : "
            f"{_int(self.filtered_offers)}",
            f"- Alternances : {_int(self.apprenticeships)} "
            f"({_pct(self.apprenticeships, self.offers)} du sous-ensemble)",
            f"- Salaire annuel brut : {salary}",
            f"- Publiées entre le {_day(self.first_day)} et le {_day(self.last_day)}",
            f"- Régions : {_counts(self.regions)}",
            f"- Types de contrat : {_counts(self.contracts)}",
            f"- Compétences les plus citées : {_counts(self.skills)}",
        ])


@dataclass(frozen=True)
class Context:
    """Question posée et matière rassemblée pour y répondre."""

    question: str
    stats: Stats
    offers: tuple[Offer, ...] = ()


def user_prompt(context: Context) -> str:
    """Le message envoyé au modèle : statistiques, offres, puis question."""
    offers = "\n".join(
        offer.as_text(rank) for rank, offer in enumerate(context.offers, start=1)
    ) or "Aucune offre ne correspond à la question dans la sélection."
    return (
        f"{context.stats.as_text()}\n\n"
        f"OFFRES (les plus proches de la question, par ordre de pertinence)\n"
        f"{offers}\n\n"
        f"QUESTION\n{context.question}"
    )


def mock_answer(context: Context) -> str:
    """Réponse hors ligne, réduite aux seules statistiques SQL.

    Le mode par défaut : la démonstration tourne sans clé ni crédits, et rien
    n'est lu dans les descriptions — au prix d'une réponse qui ignore la question.
    """
    stats = context.stats
    if not stats.offers:
        return (
            f"{NO_ANSWER} Aucune offre de la sélection ne se rapproche de cette "
            "question : élargissez les filtres de la barre latérale."
        )
    return "\n\n".join([
        f"Réponse construite sans modèle de langue, à partir des {_int(stats.offers)} "
        f"offres les plus proches de votre question, sur les "
        f"{_int(stats.filtered_offers)} offres de la sélection.",
        stats.as_text("**Ce que disent ces offres**"),
        f"Au-delà de ces chiffres, « {NO_ANSWER.rstrip('.')} » : ce mode récapitule, "
        "il ne rédige pas. Renseignez `LLM_PROVIDER` et `LLM_API_KEY` pour obtenir "
        "une réponse rédigée à partir du même contexte.",
    ])
