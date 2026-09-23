# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et le projet la [gestion sémantique de version](https://semver.org/lang/fr/).

## [1.0.0] — 2026-09-23

Première version publique : l'observatoire est déployé, alimenté par 2 789 offres
réelles et couvert par 183 tests.

### Corrigé

- **`load` ne vide plus l'entrepôt versionné.** `python -m src.cli load` lancé
  sans page dans `data/raw/` — l'état d'un dépôt fraîchement cloné, ce dossier
  n'étant pas versionné — exécutait un `CREATE OR REPLACE TABLE` qui remplaçait
  les 2 789 offres par aucune, retournait `0` et sortait avec le code `0`.
  L'échec était donc invisible pour n8n, qui enchaînait sur un entrepôt vide, et
  les pages brutes permettant de revenir en arrière étaient précisément celles
  qui manquaient. La commande lève désormais `EmptyRawDirectoryError` avant de
  toucher à la table et sort en code `1`.

### Ajouté

- `pyproject.toml` : version minimale de Python (3.11) et configuration de
  pytest, qui se lance maintenant depuis n'importe quel dossier.
- Intégration continue GitHub Actions sur Python 3.11 et 3.12, avec le badge
  correspondant en tête du README.
- `src/nlp/nocode.py` : source unique de la famille no-code et du suffixe
  « (terme générique) », auparavant recopiés dans deux modules.
- Un test de non-régression sur la destruction de l'entrepôt, et un test qui
  échoue si `data/skills_taxonomy.yaml` s'écarte des constantes no-code.
- Le détail par mots-clés (`par_recherche`) dans la sortie JSON de `ingest`.

### Supprimé

- `scripts/collect.py`, doublon de `python -m src.cli ingest` : les deux
  appelaient déjà les mêmes fonctions de `src/ingest/run.py`. Son seul apport,
  le tableau par mots-clés, est repris dans la sortie JSON du CLI.
- `FranceTravailClient.get_referentiel()` et `WeeklyReport.previous_week_start`,
  sans aucun appelant ni test.

### Modifié

- Le dashboard n'importe plus ses constantes depuis `src/nlp/report.py`, un
  module dont la responsabilité est l'affichage en console.
- README : version de Python requise, avertissement sur `load`, et précision
  que `pytest` demande `requirements-dev.txt`.

[1.0.0]: https://github.com/AndresRocabado/radar-tech-fr/releases/tag/v1.0.0
