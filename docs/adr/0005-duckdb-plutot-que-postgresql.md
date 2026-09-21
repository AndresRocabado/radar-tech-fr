# ADR 0005 — Entrepôt : DuckDB plutôt que PostgreSQL

- **Statut** : acceptée
- **Date** : 2026-09-21

## Contexte

Le projet stocke les réponses brutes de l'API France Travail, les modélise en
SQL (vue `offres`, table `offre_competences`, agrégats) et les sert à un
dashboard. La charge est analytique : des `GROUP BY` sur toute la table, écrits
une fois par jour par `load` et lus en continu par le dashboard, sans aucune
écriture concurrente. L'entrepôt compte 2 789 offres, soit environ 32 Mo.

La démonstration est hébergée sur Streamlit Community Cloud, qui ne fournit
aucune base de données (voir l'ADR 0003).

## Décision

DuckDB, dans un seul fichier : `data/warehouse.duckdb`. Le JSON brut est
chargé tel quel dans `raw_offres` et déplié en SQL (`offre->>'$.lieuTravail.libelle'`).
Le dashboard l'ouvre en lecture seule.

PostgreSQL a été écarté. Il demanderait un serveur à héberger et à sécuriser,
ainsi que des identifiants à distribuer à la démo, pour une volumétrie qui
n'utilise aucun de ses atouts : transactions concurrentes, droits par
utilisateur et écritures en continu.

## Conséquences

- La démo fonctionne après un simple `git clone`, sans service externe ni secret.
- Le moteur est colonnaire : les agrégations du dashboard restent instantanées
  à cette échelle, sans index à maintenir.
- Un seul processus peut écrire à la fois. Il n'y en a qu'un, `load`, lancé par n8n.
- Le fichier est un binaire versionné : chaque rechargement alourdit
  l'historique Git. Le seuil de révision reste celui de l'ADR 0003, soit 100 Mo.
- **À réévaluer** si plusieurs utilisateurs doivent écrire (annotations,
  comptes), ou si l'entrepôt doit être partagé par plusieurs applications :
  PostgreSQL, ou MotherDuck pour garder le même SQL, redeviendrait pertinent.
