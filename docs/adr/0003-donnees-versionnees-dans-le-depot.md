# ADR 0003 — Déploiement : entrepôt DuckDB et index vectoriel versionnés dans le dépôt

- **Statut** : acceptée
- **Date** : 2026-09-14

## Contexte

Le dashboard est déployé sur Streamlit Community Cloud, qui clone le dépôt
GitHub, installe `requirements.txt` et lance `app.py`. La plateforme ne fournit
ni base de données, ni volume persistant : le conteneur est recréé à chaque
redémarrage, et tout ce qui est écrit pendant l'exécution disparaît.

L'application a besoin de trois fichiers pour fonctionner :

| Fichier                    | Taille  | Rôle                                   |
|----------------------------|--------:|----------------------------------------|
| `data/warehouse.duckdb`    | 2,26 Mo | 55 offres, 129 liens offre–compétence  |
| `data/embeddings.npy`      | 83 Ko   | 55 vecteurs de 384 dimensions          |
| `data/embeddings_ids.json` | 605 o   | l'id de chaque ligne de la matrice      |

Aucun ne peut être reconstruit en ligne : la collecte demande les identifiants
France Travail (que la démonstration publique n'a pas), et le calcul des
embeddings demande ~6 s de CPU par tranche de 55 offres, plus le téléchargement
du modèle.

Trois options étaient envisagées :

1. **Versionner les fichiers tels quels** dans le dépôt.
2. **Publier un extrait Parquet réduit** (colonnes utiles seulement) et adapter
   le chargement du dashboard.
3. **Héberger les données ailleurs** (release GitHub, stockage objet) et les
   télécharger au démarrage.

## Décision

Option 1 : `data/warehouse.duckdb`, `data/embeddings.npy` et
`data/embeddings_ids.json` sont versionnés. `data/raw/` reste ignoré.

Le seuil retenu est **100 Mo** pour l'entrepôt : c'est la taille à partir de
laquelle GitHub refuse un fichier hors Git LFS. L'entrepôt en fait 2,26 Mo, soit
2 % du seuil.

## Justification

**Le volume est négligeable et le déploiement devient trivial.** Aucun code de
téléchargement, aucun secret de stockage, aucune étape de préparation : le
`git clone` de la plateforme suffit à rendre l'application fonctionnelle.

**Un extrait Parquet coûterait plus qu'il ne rapporte à cette échelle.** Il
faudrait deux chemins de données — DuckDB en local, Parquet en ligne — donc deux
comportements à tester, alors que le gain porterait sur 2 Mo. Les pages
« Recherche » et « Assistant » lisent d'ailleurs `raw_offres` (libellé du lieu,
URL de l'offre), ce qui obligerait l'extrait à emporter le brut de toute façon.

**Les données brutes, elles, restent dehors.** `data/raw/` contient les réponses
de l'API telles quelles ; elles sont réingérables, et leur redistribution
relève des conditions d'utilisation de France Travail. L'entrepôt en est un
produit dérivé et agrégé.

**Le dépôt reste lisible.** L'entrepôt est un binaire : chaque rechargement
ajoute une version complète à l'historique, sans diff utile. À 2 Mo et à raison
de quelques rechargements, le coût est sans conséquence.

## Conséquences

- Mettre à jour les données publiées, c'est committer :
  `python -m src.warehouse.load`, `python -m src.nlp.skills`,
  `python -m src.nlp.embeddings`, puis `git add data/ && git push`. Streamlit
  Community Cloud redéploie sur le push.
- **L'entrepôt et l'index doivent être committés ensemble.** Sinon la page
  « Recherche » signale les offres absentes de l'index (`unindexed_count`).
- `.gitignore` ignore toujours `*.duckdb`, avec une exception explicite pour
  `data/warehouse.duckdb` : les bases d'essai locales ne partent pas par
  accident.
- **À réévaluer** quand l'entrepôt approche 100 Mo. Au rythme actuel
  (~43 Ko par offre, brut JSON compris), cela arrive vers 2 300 offres. Deux
  sorties possibles à ce moment-là : cesser de stocker `raw_offres` dans
  l'entrepôt publié, ce qui en retire l'essentiel du poids, ou basculer sur
  l'option 3 (téléchargement au démarrage, mis en cache par
  `st.cache_resource`).
