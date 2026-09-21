# ADR 0006 — Dashboard : Streamlit plutôt qu'un front-end dédié

- **Statut** : acceptée
- **Date** : 2026-09-21

## Contexte

Le dashboard doit montrer des graphiques filtrables, une recherche sémantique
et un assistant conversationnel, et rester accessible publiquement par un lien.
Le projet est mené par une seule personne, dont la valeur ajoutée est la donnée
et non le développement web. Trois options étaient envisagées : Streamlit,
Dash, ou une API FastAPI avec un front-end React.

## Décision

Streamlit (`app.py`), en mode multipage avec `st.navigation` : « Vue
d'ensemble », « No-code & IA », « Recherche » et « Assistant ». Les graphiques
sont faits avec Plotly. Le déploiement se fait sur Streamlit Community Cloud,
qui redéploie à chaque `git push`.

Un front-end React doublerait la base de code (deux langages, une API à
concevoir) sans améliorer l'analyse. Dash couvre les mêmes besoins, mais avec
davantage de code de liaison (callbacks) et sans hébergement gratuit équivalent.

## Conséquences

- Tout le projet reste en Python : les requêtes du dashboard
  (`src/dashboard/queries.py`) sont testées avec `pytest`, comme le pipeline.
- Streamlit rejoue le script entier à chaque interaction. Les lectures
  DuckDB, le modèle d'embeddings et les appels au LLM passent donc par
  `st.cache_data` ou `st.cache_resource`, sans quoi chaque clic
  recalculerait tout.
- Les filtres sont dessinés dans `app.py` pour survivre au changement de page.
- L'hébergement gratuit impose une mémoire limitée, d'où torch en version CPU
  (`requirements.txt`) et un modèle d'embeddings léger (ADR 0007).
- La personnalisation visuelle reste bornée par les composants Streamlit :
  suffisant pour un observatoire, insuffisant pour un produit grand public.
