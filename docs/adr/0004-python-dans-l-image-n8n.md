# ADR 0004 — Automatisation : Python dans l'image n8n plutôt qu'un conteneur de travail séparé

- **Statut** : acceptée
- **Date** : 2026-09-19

## Contexte

n8n orchestre la chaîne décrite dans `docs/automatisation.md` : collecte
quotidienne, reconstruction de l'entrepôt, rapport hebdomadaire envoyé par
e-mail. Le travail lui-même est fait par le code Python du dépôt, exposé par
`src/cli.py` (`ingest`, `load`, `report`). Il faut donc que n8n, qui tourne dans
un conteneur Node.js, puisse déclencher du Python.

Deux options étaient envisagées :

1. **Python dans l'image n8n.** Une image dérivée de `n8nio/n8n` ajoute
   Python et les dépendances de `requirements-pipeline.txt` ; le dépôt est monté
   sur `/workspace` et les nœuds *Execute Command* lancent `python -m src.cli …`.
2. **Un conteneur `radar-worker` séparé.** Une image Python dédiée expose
   les trois commandes derrière une petite API HTTP (`POST /ingest`,
   `POST /load`, `POST /report`) ; n8n reste l'image officielle, sans
   modification, et appelle le worker par des nœuds *HTTP Request*.

## Décision

Option 1 : `Dockerfile.n8n` et `docker-compose.yml`, un seul service.

## L'option écartée est la plus propre

Le conteneur `radar-worker` est l'architecture qu'on attendrait d'un système
en production, et il faut le dire :

- **Séparation des responsabilités.** n8n orchestre, le worker calcule.
  Chaque conteneur a une seule raison de changer : une mise à jour de n8n ne
  touche pas à Python, une nouvelle dépendance Python ne reconstruit pas n8n.
- **L'image n8n reste standard.** Elle se met à jour par un simple changement
  d'étiquette, sans dépendre de ce que contient l'image de base. L'option 1,
  elle, suppose qu'`apk` y soit disponible : si une version future de n8n
  livre une image sans gestionnaire de paquets, le `Dockerfile.n8n` casse.
- **Pas de nœud *Execute Command*.** Ce nœud exécute n'importe quelle
  commande avec les droits du conteneur ; n8n le désactive par défaut depuis
  la version 2.0, et l'option 1 doit le réactiver (`NODES_EXCLUDE: "[]"`).
  Une API qui n'expose que trois routes réduit cette surface à ce qui sert.
- **Un contrat explicite.** Des routes HTTP avec un corps JSON se testent, se
  versionnent et se documentent mieux qu'une ligne de commande dont la sortie
  est lue sur stdout.

## Pourquoi l'option 1 malgré tout

- **Moins de code.** L'option 2 demande un serveur HTTP (FastAPI ou
  équivalent), la gestion des tâches longues (une collecte dure plusieurs
  minutes, au-delà du délai d'une requête HTTP ordinaire : il faudrait une
  file ou un mode asynchrone avec interrogation de l'état), ses tests, et un
  second Dockerfile. L'option 1 réutilise telle quelle la CLI, déjà testée
  (`tests/test_cli.py`) et utilisable à la main.
- **Moins de maintenance.** Un service, une image, un réseau par défaut. Pour
  un projet d'une seule personne, qui tourne sur un seul poste, chaque pièce
  en plus est une pièce à mettre à jour sans personne pour s'en charger.
- **Le risque de sécurité est contenu.** L'interface n8n n'écoute que sur
  `127.0.0.1`, et le seul utilisateur est l'auteur du projet.

## Conséquences

- La sortie standard de `src/cli.py` est un contrat : une seule ligne JSON par
  commande, les journaux sur stderr. `tests/test_cli.py` le vérifie.
- Le conteneur ne reçoit aucun secret par son environnement : les
  identifiants France Travail sont lus par le code dans `/workspace/.env`.
- `load --embeddings` n'est pas disponible dans le conteneur : la pile ML
  (torch, ~2 Go) est volontairement absente de `requirements-pipeline.txt`.

## Conditions pour passer à l'option 2

L'une de ces situations suffit à rouvrir la décision :

- **n8n devient accessible à d'autres personnes**, ou depuis le réseau : le
  nœud *Execute Command* ouvert à plusieurs utilisateurs n'est plus acceptable.
- **n8n est hébergé ailleurs que sur le poste**, en particulier sur n8n Cloud,
  où une image personnalisée n'est pas possible.
- **L'image n8n n'accepte plus l'installation de Python** (pas d'`apk`, image
  durcie) ou une mise à jour de n8n casse le `Dockerfile.n8n` plus d'une fois.
- **Le pipeline doit tourner sans n8n** : planificateur du cloud, CI, autre
  orchestrateur. Une API HTTP servirait alors plusieurs clients.
- **Les traitements deviennent trop lourds pour cohabiter** avec n8n (pile
  ML dans le pipeline, collecte de plusieurs heures) et demandent leurs
  propres limites de mémoire et de CPU.
