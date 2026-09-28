# ADR 0005 — Conteneur radar-worker derrière une API HTTP

- **Statut** : acceptée
- **Date** : 2026-09-28
- **Remplace** : [ADR 0004](0004-python-dans-l-image-n8n.md)

## Contexte

L'ADR 0004 avait retenu la solution la plus simple : ajouter Python à l'image
n8n et lancer `python -m src.cli …` depuis des nœuds *Execute Command*. Il
listait aussi les conditions qui rouvriraient la décision, dont celle-ci :

> **L'image n8n n'accepte plus l'installation de Python** (pas d'`apk`, image
> durcie).

C'est arrivé à la première mise en service. L'image officielle est maintenant
une *Docker Hardened Image* :

```
$ docker run --rm --entrypoint /bin/sh n8nio/n8n:latest -c "cat /etc/os-release"
PRETTY_NAME="Docker Hardened Images/Alpine Linux v3.24"
```

Elle ne contient ni Python, ni `apk`, ni aucun autre gestionnaire de paquets,
et le build échoue sur `apk: not found`. Ce n'est pas un défaut à contourner :
l'absence de gestionnaire de paquets est l'objet même d'une image durcie.

Trois suites possibles :

1. **Épingler n8n sur une version antérieure** (`1.70.1` est encore une Alpine
   ordinaire, avec `apk`), et garder le montage de l'ADR 0004.
2. **Copier Python dans l'image durcie** par un `COPY --from=alpine`.
3. **L'option 2 de l'ADR 0004** : un conteneur `radar-worker` séparé, et n8n
   qui l'appelle par HTTP.

## Décision

Option 3 : `Dockerfile.worker`, `src/worker/api.py`, et un service
`radar-worker` dans `docker-compose.yml`. Les nœuds *Execute Command* du
workflow deviennent des nœuds *HTTP Request* vers `http://radar-worker:8000`.

`Dockerfile.n8n` est supprimé : n8n tourne sur son image officielle, sans
modification.

## Justification

**Épingler n8n (option 1)** fige le projet sur une version de fin 2024, sans
correctif de sécurité, et ne fait que retarder la migration : le portfolio
serait à refaire au premier audit de dépendances.

**Copier Python dans l'image durcie (option 2)** revient à défaire à la main ce
que l'image garantit, pour un assemblage qui casserait à la première mise à
jour de l'image de base. Pire que l'option 1 : le bricolage est invisible
jusqu'au jour où il lâche.

**Le worker séparé** est l'architecture que l'ADR 0004 reconnaissait déjà comme
la plus propre. Le changement de contexte n'a fait que supprimer la raison de
ne pas la choisir.

## Ce que la CLI reste

La ligne de commande demeure le contrat unique : chaque route lance
`python -m src.cli <commande>` en sous-processus et renvoie la ligne JSON
qu'elle écrit. Rien n'est réimplémenté dans l'API, et les commandes se lancent
toujours à la main, à l'identique. Le sous-processus a deux autres mérites : la
mémoire d'une collecte est rendue au système à la fin de chaque appel, et un
code de sortie non nul se traduit directement en erreur HTTP — 400 sur une
option refusée (Typer sort avec 2), 504 sur dépassement du délai, 500 sinon.

## Conséquences

Gagné, au-delà du problème d'origine :

- **Plus de nœud *Execute Command*.** `NODES_EXCLUDE: "[]"` disparaît de
  `docker-compose.yml` : n8n garde ses réglages de sécurité par défaut.
- **Le dépôt n'est plus monté dans n8n.** Seul le worker y accède ; n8n ne voit
  ni le code, ni `.env`, ni l'entrepôt. Le montage `./automation:/import:ro`
  reste, en lecture seule, pour importer le workflow en ligne de commande.
- **n8n ne touche plus au disque.** La route `/report` renvoie le Markdown dans
  sa réponse (`contenu_markdown`), ce qui retire du workflow les nœuds
  *Read/Write Files* et *Extract from File*, et avec eux le réglage
  `N8N_RESTRICT_FILE_ACCESS_TO`.
- **L'API n'est pas publiée.** Aucun port exposé sur l'hôte : le worker n'est
  joignable que par n8n, sur le réseau interne de compose.

Payé :

- un service, une image et un Dockerfile de plus à maintenir ;
- ~90 lignes d'API et ses tests (`tests/test_worker_api.py`) ;
- des appels HTTP longs, tenus par un délai explicite sur chaque nœud (une
  heure pour `ingest`) plutôt que par une file de tâches. Suffisant pour trois
  traitements par lots quotidiens ; à revoir si le pipeline devait rendre la
  main tout de suite et être interrogé ensuite.

## Conditions pour revoir cette décision

- **Les commandes dépassent l'heure** ou doivent pouvoir être suivies en cours
  de route : il faudra une exécution asynchrone (`202` plus une route d'état)
  ou une vraie file de tâches.
- **Le worker doit servir plusieurs appelants** ou sortir du poste : il faudrait
  alors une authentification, absente aujourd'hui parce que seul n8n l'atteint,
  sur un réseau privé.
