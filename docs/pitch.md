# Pitch — Radar Tech FR

Trois usages : les lignes CV, le post LinkedIn, et la préparation d'entretien.
Tous les chiffres viennent de `data/warehouse.duckdb` au 23/09/2026 : 2 789 offres
collectées entre le 3 février et le 18 septembre 2026, 785 entreprises,
18 régions, 110 compétences du dictionnaire, 8 907 liens offre–compétence.

---

## 1. Trois lignes pour le CV

**Radar Tech FR — Observatoire du marché de l'emploi tech** · [démo](https://radar-tech-fr.streamlit.app/) · [code](https://github.com/AndresRocabado/radar-tech-fr)

> Conception et développement d'un pipeline de données de bout en bout sur l'API France Travail : collecte de 2 789 offres (gestion du plafond de pagination par fenêtres de dates, limitation de débit, reprise sur erreur), modélisation SQL dans un entrepôt DuckDB et extraction de 110 compétences par dictionnaire contrôlé.
>
> Dashboard Streamlit en libre accès : volumes, salaires, régions et alternance, recherche sémantique multilingue (sentence-transformers, similitude cosinus) et assistant RAG dont les chiffres sont comptés en SQL, jamais rédigés par le modèle.
>
> Automatisation quotidienne par n8n (Docker), 183 tests automatisés sous intégration continue, sept décisions d'architecture documentées en ADR. Python, DuckDB, SQL, Streamlit, Plotly, Docker.

---

## 2. Post LinkedIn (150 mots)

> J'ai mis en ligne **Radar Tech FR**, un observatoire du marché de l'emploi tech en France.
>
> La question de départ, dont je ne trouvais la réponse nulle part : quelles compétences data, IA et no-code les entreprises recrutent-elles vraiment, et où ?
>
> J'ai donc collecté 2 789 offres réelles via l'API France Travail et construit le pipeline complet : ingestion, entrepôt DuckDB, extraction des compétences, dashboard.
>
> On peut y comparer les volumes par région et par contrat, regarder ce que l'alternance représente vraiment, chercher une offre en langage naturel — « alternance data engineering avec du cloud en région lyonnaise » — et poser une question à un assistant dont tous les chiffres sont comptés en SQL, jamais inventés par un modèle de langue.
>
> La démo est ouverte, sans inscription, et le code est public avec ses limites assumées : une seule source, un historique court.
>
> Les retours m'intéressent, surtout les critiques. 👇
>
> 🔗 radar-tech-fr.streamlit.app
>
> #data #dataengineering #python #duckdb #alternance

---

## 3. Les cinq questions d'entretien les plus probables

### Q1. Pourquoi DuckDB plutôt que PostgreSQL ?

**Parce que la charge est analytique, mono-utilisateur et en lecture seule.**

Des `GROUP BY` sur toute la table, écrits une fois par jour par `load` et lus en
continu par le dashboard, sans aucune écriture concurrente. Sur 2 789 offres
(~32 Mo), PostgreSQL m'aurait demandé un serveur à héberger et à sécuriser et des
identifiants à distribuer à la démo, pour n'utiliser aucun de ses atouts réels :
transactions concurrentes, droits par utilisateur, écritures continues.

DuckDB est colonnaire et embarqué dans un fichier : les agrégations sont
instantanées à cette échelle sans index à maintenir, et surtout la démo
fonctionne après un simple `git clone`, sans service externe ni secret — ce qui
comptait, puisque Streamlit Community Cloud ne fournit aucune base de données.

**Ce que je reconnais :** un seul processus peut écrire à la fois. Ici il n'y en
a qu'un, `load`, lancé par n8n. Et le fichier est un binaire versionné, donc
chaque rechargement alourdit l'historique Git.

**Quand je changerais d'avis :** si plusieurs utilisateurs devaient écrire
(annotations, comptes), ou si l'entrepôt devait être partagé entre plusieurs
applications. PostgreSQL redeviendrait pertinent — ou MotherDuck, pour garder le
même SQL. C'est écrit dans l'ADR 0005.

### Q2. Quelles sont les limites de votre RAG ?

**La principale : il ne compte pas, et c'est délibéré.**

Les chiffres sont agrégés en SQL par DuckDB sur le sous-ensemble retenu, et ce
bloc est la seule source numérique donnée au modèle ; le system prompt lui
interdit d'en produire d'autres. Ce n'est pas de la prudence, c'est une
nécessité : je tronque chaque description à 600 signes pour faire tenir vingt
offres dans la requête, donc même un modèle parfait compterait sur un texte
incomplet.

**Les limites que j'assume, dans l'ordre où elles mordent :**

1. **La récupération est le maillon faible.** Vingt offres les plus proches par
   similitude cosinus. Une question sur une région peu représentée peut ne
   ramener aucune offre pertinente, et le modèle répondra alors sur un
   sous-ensemble mal choisi — avec des chiffres justes portant sur le mauvais
   échantillon. C'est le mode d'échec le plus vicieux, parce qu'il est invisible.
2. **Le mode par défaut de la démo ne rédige pas.** Sans clé d'API, la page
   affiche les statistiques SQL que le modèle aurait reçues, et le dit
   explicitement. La question posée est alors ignorée.
3. **La similitude n'est pas la pertinence.** Le score classe les offres entre
   elles ; il ne dit pas qu'une offre est bonne dans l'absolu.
4. **L'index vectoriel peut retarder sur l'entrepôt**, parce que n8n ne le
   recalcule pas (torch est absent de l'image Docker). La page signale les
   offres filtrées absentes de l'index plutôt que de faire comme si de rien
   n'était.
5. **Pas de citation offre par offre, pas de conversation multi-tours.** Je
   montre les offres utilisées dans un volet dépliant, mais je ne relie pas
   chaque phrase à sa source.

**Ce que j'ai écarté, et pourquoi :** le text-to-SQL. Une requête écrite par un
modèle peut être syntaxiquement valide et sémantiquement fausse — mauvaise
jointure, double comptage d'une offre à plusieurs compétences — et l'erreur est
alors indétectable. Mes agrégats sont écrits une fois, testés, et partagent les
CTE de filtrage du reste du dashboard : une offre comptée sur la page
« Assistant » est comptée comme sur la page « Vue d'ensemble ». ADR 0002.

### Q3. L'API plafonne à 3 150 offres par recherche. Comment récupérez-vous davantage ?

**En découpant par fenêtres de dates, récursivement.**

Je pagine par tranches de 150 offres via l'en-tête `Range`. Quand une recherche
annonce un total au-dessus du plafond, je coupe sa fenêtre de création en deux et
je collecte chaque moitié, jusqu'à une profondeur maximale. Les fenêtres se
recouvrent parfois : je dédoublonne par `id` dans un dictionnaire, donc une offre
vue deux fois n'est comptée qu'une.

Trois précautions autour : un limiteur à 8 requêtes/seconde alors que l'API en
autorise 10, une marge délibérée pour que la dérive d'horloge ou une reprise ne
me fassent pas dépasser ; des tentatives avec backoff exponentiel et *jitter* sur
les 429 et les 5xx, en respectant `Retry-After` quand il est présent ; et un
arrêt net si l'API cesse d'honorer la fenêtre demandée, pour ne pas collecter
indéfiniment la même page.

Le dédoublonnage final se fait aussi à l'entrée de l'entrepôt : la matrice de
recherche croise chaque mot-clé avec chaque nature de contrat, donc la même offre
arrive plusieurs fois, et je ne garde que la copie dont la `dateActualisation`
est la plus récente.

### Q4. Comment extrayez-vous les compétences ? Pourquoi pas du NER ou un LLM ?

**Un dictionnaire contrôlé de 110 technologies, compilé en expressions
régulières.** Chaque entrée porte ses alias, et les séparateurs sont assouplis :
« Power BI » est écrit une fois et retrouve « PowerBI », « Power-BI »,
« Power_BI ». Le texte est désaccentué une seule fois pour tout le dictionnaire.

Deux détails qui font la différence sur du texte réel : des limites de mot
maison, parce que `\b` tomberait au milieu de « C++ » et de « C# » ; et une
sensibilité à la casse par entrée, pour que « Make » ne soit cherché que
capitalisé — sinon chaque « make » d'une phrase anglaise devient un faux positif.

**Pourquoi pas de NER ou de LLM :** parce que le coût d'erreur n'est pas
symétrique. Sur un observatoire, un faux positif est bien plus grave qu'un
oubli : il produit un chiffre faux que personne ne peut vérifier. Un dictionnaire
est déterministe, testable — j'ai des tests sur les alias, la casse, les faux
positifs — et reproductible à l'identique.

**La limite, que j'annonce dans le README :** la taxonomie est fermée. Une
technologie absente de la liste est invisible, et c'est justement une
technologie émergente qui a le plus de chances d'y manquer. Avec plus de temps,
j'ajouterais une passe NER en complément du dictionnaire — pour détecter les
candidats, pas pour les compter directement.

### Q5. Vous versionnez un fichier binaire `.duckdb` dans Git. C'est inhabituel — assumé ?

**Oui, et j'en connais le prix.**

Streamlit Community Cloud n'offre ni base de données ni stockage persistant : le
dépôt est la seule source possible. Le fichier fait quelques mégaoctets, et le
versionner est ce qui rend la démo utilisable après un `git clone`, sans clé et
sans service externe. Le seuil que je me suis fixé pour reconsidérer est 100 Mo
(ADR 0003). Au-delà, je passerais à un stockage objet avec un fichier Parquet, ou
à MotherDuck pour garder le même SQL.

**Le piège que ça crée, et que j'ai corrigé :** `data/raw/` est ignoré par Git
alors que l'entrepôt est versionné. Après un clone, on a donc l'entrepôt sans les
pages qui permettent de le reconstruire — et `load` faisait un
`CREATE OR REPLACE TABLE` avant de vérifier qu'il avait quelque chose à charger.
Résultat : 2 789 offres remplacées par zéro, sans exception, avec un code de
sortie 0 que n8n interprétait comme un succès. La commande refuse désormais de
s'exécuter dans cet état, et un test de non-régression le vérifie.

C'est l'exemple que je donnerais si on me demande un bug que j'ai trouvé
moi-même : il ne se voyait pas en développement, parce qu'en développement
`data/raw/` est toujours plein.
