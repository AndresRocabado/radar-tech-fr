# ADR 0007 — Embeddings : paraphrase-multilingual-MiniLM-L12-v2

- **Statut** : acceptée
- **Date** : 2026-09-21

## Contexte

Les pages « Recherche » et « Assistant » encodent une phrase libre et la
comparent aux offres (ADR 0001 et 0002). Les offres sont rédigées en français,
avec un vocabulaire technique souvent anglais (« data engineer », « MLOps »),
et les requêtes mélangent les deux langues. La requête est encodée en ligne,
sur le CPU de Streamlit Community Cloud, sans GPU et avec une mémoire limitée.

Trois familles d'options étaient envisagées : un modèle anglais léger
(`all-MiniLM-L6-v2`), un modèle multilingue plus gros (famille `multilingual-e5`),
et une API d'embeddings payante.

## Décision

`paraphrase-multilingual-MiniLM-L12-v2`, via sentence-transformers
(`src/nlp/model.py`). Il est multilingue, produit 384 dimensions et pèse environ
470 Mo, téléchargés au premier appel.

Un modèle anglais comprend mal le français des descriptions. Un modèle
multilingue plus gros serait plus précis, mais plus lent sur CPU et plus
gourmand en mémoire. Une API payante imposerait une clé et des coûts à chaque
visite de la démo publique, ce que l'ADR 0002 exclut.

## Conséquences

- L'encodage tourne sur CPU : environ 0,10 s par offre hors ligne, et une
  requête encodée en ligne sans délai perceptible.
- Les vecteurs de 384 dimensions restent légers : l'index des 2 789 offres
  pèse environ 4 Mo et se versionne avec l'entrepôt.
- Le modèle lit au plus 128 tokens, alors que les descriptions sont bien plus
  longues : elles sont découpées en tranches puis moyennées (ADR 0001, note).
- Changer de modèle oblige à recalculer tout l'index (`python -m src.cli load
  --embeddings`), car des vecteurs issus de deux modèles ne sont pas comparables.
- **À réévaluer** si la qualité de recherche devient le point faible : un
  modèle `e5` ou `bge` multilingue se testerait en ne changeant que
  `MODEL_NAME`, grâce au `Protocol` `Encoder`.
