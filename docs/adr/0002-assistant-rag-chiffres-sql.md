# ADR 0002 — Assistant RAG : chiffres comptés en SQL, fournisseur LLM optionnel

- **Statut** : acceptée
- **Date** : 2026-09-13

## Contexte

La page « Assistant » répond en français à une question libre sur les offres
collectées (« quelles compétences reviennent le plus en alternance ? »). Deux
risques, distincts, pèsent sur une telle page dans un projet de portfolio :

1. **Le modèle invente des chiffres.** Une réponse qui annonce « 38 % des
   offres citent Python » est indiscernable d'une réponse juste pour qui lit le
   dashboard, et fausse la démonstration entière.
2. **La démonstration publique coûte de l'argent et expose une clé.** Le
   dashboard est déployé sur Streamlit Community Cloud : chaque visiteur
   pourrait déclencher des appels facturés, et la clé devrait vivre quelque
   part.

Trois architectures étaient envisagées :

1. **Tout au modèle** : lui donner les offres et le laisser compter.
2. **RAG classique** : récupérer les offres proches de la question, et rien
   d'autre.
3. **Text-to-SQL** : le modèle écrit la requête, l'entrepôt l'exécute.

## Décision

Récupération vectorielle **plus** agrégats SQL pré-calculés, et fournisseur
choisi dans `.env` avec un mode hors ligne par défaut.

La question est encodée par le modèle de l'ADR 0001 ; les 20 offres les plus
proches sont retenues parmi celles que retiennent les filtres de la barre
latérale (`src/dashboard/assistant.py`). DuckDB compte ensuite ce sous-ensemble
— volumes, part d'alternance, salaire médian, période, régions, contrats, top
compétences — et ce bloc de chiffres est la **seule** source numérique donnée
au modèle. Le system prompt (`src/nlp/rag.py`) lui interdit d'en produire
d'autres, lui impose de dire sur combien d'offres il se fonde, et lui impose la
phrase « Je n'ai pas cette information dans les données » quand le contexte ne
suffit pas.

`LLM_PROVIDER` vaut `mock` par défaut : la réponse est alors rédigée à partir
du seul bloc de chiffres, sans sortie réseau. `LLM_PROVIDER=anthropic` appelle
l'API Claude avec `LLM_API_KEY` (`src/nlp/llm.py`).

## Justification

**Les offres montrées sont tronquées par construction**, donc impossibles à
compter. Chaque description est ramenée à 600 signes pour que vingt offres
tiennent dans une requête ; même un modèle parfait qui compterait sur ce texte
compterait sur un texte incomplet. L'option 1 est donc fausse par
construction, pas seulement risquée.

**L'option 2 laisse la question quantitative sans réponse.** Les questions qui
valent la peine d'être posées à un observatoire du marché sont des questions de
volume et de proportion. Un RAG qui ne rapporte que du texte y répond « à vue
de nez », c'est-à-dire mal.

**L'option 3 déplace le risque sans le réduire.** Une requête écrite par le
modèle peut être syntaxiquement valide et sémantiquement fausse (mauvaise
jointure, double comptage d'une offre à plusieurs compétences), et l'erreur est
alors invisible. Les agrégats livrés ici sont écrits une fois, testés
(`tests/test_assistant.py`), et partagent les CTE de filtrage du reste du
dashboard : une offre comptée sur la page « Assistant » est comptée comme sur la
page « Vue d'ensemble ».

**Le mode `mock` n'est pas un bouchon de test, c'est le mode de la
démonstration.** Il répond avec le bloc de chiffres que le modèle aurait reçu,
et dit explicitement qu'il ne rédige pas. Le visiteur voit donc la vraie
récupération, les vraies statistiques et le vrai contexte ; seule manque la
rédaction. Aucune clé n'a besoin d'exister pour que la page fonctionne, et le
dépôt n'en contient aucune (`.env` + `os.getenv()`, comme pour France Travail).

## Conséquences

- Le bloc de chiffres est rendu **une seule fois** (`Stats.as_text()`) et sert
  à la fois de contexte au modèle et de corps à la réponse hors ligne : les
  deux modes ne peuvent pas diverger sur un chiffre.
- La réponse hors ligne ignore la question posée. C'est assumé et affiché : la
  page indique toujours d'où vient la réponse qu'elle montre.
- Une clé absente, un fournisseur inconnu ou un appel en échec ne cassent pas
  la page : elle l'explique en français et retombe sur le récapitulatif.
- Les appels passent par `st.cache_data`, indexé sur la question et les
  filtres. Sans cela, Streamlit rejouant le script à chaque interaction, la
  même question serait facturée plusieurs fois.
- Le sous-ensemble est fixé à 20 offres. Au-delà, le contexte grossit plus vite
  que la réponse ne s'améliore ; en deçà, une question régionale peut ne
  ramener aucune offre pertinente.
- **À réévaluer** si la page doit citer ses sources offre par offre (il
  faudrait alors numéroter les citations et les vérifier), ou tenir une
  conversation à plusieurs tours (il faudrait gérer l'historique et son coût).
