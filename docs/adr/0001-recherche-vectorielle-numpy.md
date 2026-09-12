# ADR 0001 — Recherche sémantique : similitude cosinus en numpy plutôt que DuckDB VSS

- **Statut** : acceptée
- **Date** : 2026-09-11

## Contexte

La page « Recherche » classe les offres par proximité de sens avec une phrase
libre. Chaque offre est encodée par `paraphrase-multilingual-MiniLM-L12-v2`
(384 dimensions, multilingue, léger). Il faut stocker ces vecteurs et retrouver
les 10 plus proches d'une requête.

Deux options étaient envisagées :

1. **L'extension VSS de DuckDB** (index HNSW), qui garderait les vecteurs dans
   l'entrepôt.
2. **Un fichier `.npy` et une similitude cosinus exhaustive en numpy.**

## Décision

Option 2 : `data/embeddings.npy` (vecteurs normalisés) et
`data/embeddings_ids.json` (l'id de chaque ligne, dans le même ordre).
Les vecteurs étant de norme 1, la similitude cosinus se réduit à un produit
matriciel suivi d'un tri (`src/nlp/search.py`).

## Justification

**Le volume ne justifie pas d'index approché.** Mesures sur le poste de
développement (CPU 12 threads), vecteurs `float32` de 384 dimensions :

| Offres  | Mémoire | Temps par requête |
|--------:|--------:|------------------:|
| 55      | 0,1 Mo  | 0,03 ms           |
| 10 000  | 15 Mo   | 1,3 ms            |
| 100 000 | 154 Mo  | 14 ms             |

La collecte actuelle compte 55 offres. Même à 100 000, la recherche exhaustive
reste bien en dessous du temps d'encodage de la requête elle-même.

**VSS ajoute de la friction sans bénéfice à cette échelle :**

- l'extension se télécharge au premier `INSTALL vss`, ce qui échoue derrière
  un proxy qui inspecte le HTTPS (cas du poste de développement) ;
- la persistance d'un index HNSW sur disque reste expérimentale
  (`SET hnsw_enable_experimental_persistence = true`), avec un risque de
  corruption documenté en cas d'arrêt brutal ;
- le dashboard ouvre l'entrepôt en lecture seule, alors que l'index HNSW doit
  être construit en écriture ;
- HNSW donne un résultat approché, là où numpy donne le classement exact.

## Conséquences

- L'index vit à côté de l'entrepôt, pas dedans : il se reconstruit avec
  `python -m src.nlp.embeddings` après chaque rechargement. La page
  « Recherche » signale les offres de l'entrepôt absentes de l'index.
- Les filtres du dashboard s'appliquent en restreignant les candidats avant le
  tri (`top_k(..., allowed=...)`), sans SQL vectoriel.
- **À réévaluer** au-delà de quelques centaines de milliers d'offres, ou si
  l'index doit se mettre à jour offre par offre plutôt que d'un bloc.

## Note : descriptions plus longues que la fenêtre du modèle

Le modèle lit au plus 128 tokens. Sur la collecte actuelle, le texte d'une
offre en compte 441 en moyenne (médiane 408, maximum 1 036), et 51 offres sur
55 dépassent la fenêtre : tronquer ferait perdre les trois quarts du texte.
Plutôt que de le tronquer, `src/nlp/embeddings.py`
la découpe en tranches de 126 tokens (128 moins les deux tokens spéciaux),
encode chaque tranche, et retient la moyenne normalisée des tranches. Le texte
encodé est « intitulé. lieu — région », puis la description : le lieu répond
aux requêtes géographiques (« en région lyonnaise »).

Coût mesuré : 0,10 s par offre sur CPU, soit ~6 s pour la collecte actuelle et
~17 min pour 10 000 offres. Le calcul se fait par lots, hors du dashboard.
