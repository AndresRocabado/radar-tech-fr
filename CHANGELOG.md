# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et le projet la [gestion sémantique de version](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- `python -m src.cli prune` : liste les pages de `data/raw/` redondantes, en
  simulation seulement. Une page n'est redondante que si chacune de ses offres
  figure, dans une version au moins aussi récente, dans une page conservée ; une
  vérification indépendante refuse tout plan qui ferait perdre une offre.

### Corrigé

- `load` reconstruit l'entrepôt dans un fichier temporaire, substitué d'un bloc
  une fois offres et compétences écrites (`src/warehouse/staging.py`). Le
  fichier ne garde plus de blocs morts (39 Mo → 21 Mo pour 3 729 offres), le
  dashboard ne voit jamais un entrepôt à moitié reconstruit, et un échec laisse
  l'entrepôt en place intact.
- Assistant : le cache de la réponse tient compte du fournisseur, du modèle et
  de la version de l'entrepôt.

### Modifié

- Page « Recherche » : résultats mis en cache, filtrage de l'index par
  dictionnaire id → ligne.
- Modèle par défaut `claude-opus-5-5`, avec un effort explicite.

## [1.1.0] — 2026-10-10

L'entrepôt passe à 3 729 offres, collectées par l'automatisation n8n.

### Ajouté

- Conteneur `radar-worker` (`Dockerfile.worker`, `src/worker/api.py`) : une API
  FastAPI expose `ingest`, `load` et `report` à n8n sur le réseau interne de
  docker-compose. L'image n8n reste l'image officielle, sans modification
  ([ADR 0005](docs/adr/0005-conteneur-radar-worker.md), qui remplace l'ADR 0004).
- Le rapport hebdomadaire est rendu en HTML mis en forme côté Python
  (`src/report/render.py`) ; `/report` renvoie les corps HTML et Markdown de
  l'e-mail.
- Capture du workflow n8n dans `docs/img/`.

### Corrigé

- Devcontainer et CI alignés sur Python 3.12, le plancher imposé par numpy et
  scipy.

### Modifié

- Les ADR DuckDB, Streamlit et embeddings, qui partageaient le numéro 0005 avec
  l'ADR du conteneur, sont renumérotés 0006, 0007 et 0008.
- README : chiffres, limites et pistes mis à jour.

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

- `pyproject.toml` : version minimale de Python (3.12, imposée par numpy et
  scipy) et configuration de pytest, qui se lance maintenant depuis n'importe
  quel dossier.
- Intégration continue GitHub Actions sur Python 3.12 et 3.13, avec le badge
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

[1.1.0]: https://github.com/AndresRocabado/radar-tech-fr/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/AndresRocabado/radar-tech-fr/releases/tag/v1.0.0
