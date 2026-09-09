-- Modèle analytique construit au-dessus de raw_offres.
--
-- raw_offres garde chaque offre en JSON plutôt qu'en STRUCT éclaté : les champs
-- optionnels de l'API vont et viennent d'une collecte à l'autre, et un schéma
-- inféré changerait à chaque rechargement. Les colonnes utiles sont extraites
-- ici, une bonne fois, avec ->>.

-- Correspondance département -> région (découpage de 2016).
-- Écrite en une ligne par région plutôt qu'une par département, pour rester
-- lisible. L'apostrophe de « Côte d'Azur » se double : en guillemets doubles,
-- DuckDB lirait un identifiant de colonne.
CREATE OR REPLACE TABLE ref_regions AS
SELECT r.region, unnest(r.departements) AS departement
FROM (VALUES
    ('Auvergne-Rhône-Alpes',       ['01','03','07','15','26','38','42','43','63','69','73','74']),
    ('Bourgogne-Franche-Comté',    ['21','25','39','58','70','71','89','90']),
    ('Bretagne',                   ['22','29','35','56']),
    ('Centre-Val de Loire',        ['18','28','36','37','41','45']),
    ('Corse',                      ['2A','2B']),
    ('Grand Est',                  ['08','10','51','52','54','55','57','67','68','88']),
    ('Hauts-de-France',            ['02','59','60','62','80']),
    ('Île-de-France',              ['75','77','78','91','92','93','94','95']),
    ('Normandie',                  ['14','27','50','61','76']),
    ('Nouvelle-Aquitaine',         ['16','17','19','23','24','33','40','47','64','79','86','87']),
    ('Occitanie',                  ['09','11','12','30','31','32','34','46','48','65','66','81','82']),
    ('Pays de la Loire',           ['44','49','53','72','85']),
    ('Provence-Alpes-Côte d''Azur',['04','05','06','13','83','84']),
    ('Guadeloupe',                 ['971']),
    ('Martinique',                 ['972']),
    ('Guyane',                     ['973']),
    ('La Réunion',                 ['974']),
    ('Mayotte',                    ['976'])
) AS r(region, departements);

CREATE OR REPLACE VIEW offres AS
WITH base AS (
    SELECT
        id,
        offre->>'$.intitule'          AS intitule,
        offre->>'$.entreprise.nom'    AS entreprise,
        offre->>'$.typeContrat'       AS type_contrat,
        -- Les parenthèses autour de ->> ne sont pas décoratives : cet opérateur
        -- se lie plus faiblement que IN, et sans elles DuckDB tente de comparer
        -- la colonne JSON elle-même (« Failed to cast value to numerical »).
        coalesce(TRY_CAST(offre->>'$.alternance' AS BOOLEAN), false)
            OR (offre->>'$.natureContrat')
               IN ('Contrat apprentissage', 'Cont. professionnalisation')
                                      AS est_alternance,
        TRY_CAST(offre->>'$.dateCreation' AS TIMESTAMP) AS date_creation,
        offre->>'$.romeCode'          AS code_rome,
        offre->>'$.experienceLibelle' AS experience,
        offre->>'$.description'       AS description,
        offre->>'$.lieuTravail.libelle'    AS lieu_libelle,
        offre->>'$.lieuTravail.commune'    AS code_insee,
        offre->>'$.lieuTravail.codePostal' AS code_postal,
        offre->>'$.salaire.libelle'        AS salaire_libelle
    FROM raw_offres
),

-- Le département se lit d'abord dans le préfixe du libellé (« 75 - Paris »),
-- seule source qui distingue la Corse (2A/2B) des codes numériques. À défaut,
-- le code INSEE de la commune, puis le code postal. La branche outre-mer est
-- bornée à 97[1-6] : un 9[0-9]{2} plus large avalerait « 912 » dans le code
-- INSEE « 91272 ».
localise AS (
    SELECT *,
        coalesce(
            nullif(regexp_extract(coalesce(lieu_libelle, ''), '^(97[1-6]|2[AB]|[0-9]{2}) - ', 1), ''),
            nullif(regexp_extract(coalesce(code_insee,  ''), '^(97[1-6]|2[AB]|[0-9]{2})',    1), ''),
            nullif(regexp_extract(coalesce(code_postal, ''), '^(97[1-6]|[0-9]{2})',          1), '')
        ) AS departement
    FROM base
),

-- Le salaire arrive en texte libre, sur la grammaire
-- « {Périodicité} de {min} Euros [à {max} Euros] [sur {n} mois|heures] ».
-- Le motif n'est pas ancré à droite : certains libellés traînent un suffixe
-- parasite (« ... Euros - - »).
decoupe AS (
    SELECT *,
        regexp_extract(coalesce(salaire_libelle, ''),
            '^(Annuel|Mensuel|Horaire|Cachet|Autre) de ([0-9][0-9 .,]*[0-9]|[0-9]) *Euro', 1)
            AS periodicite,
        regexp_extract(coalesce(salaire_libelle, ''),
            '^(?:Annuel|Mensuel|Horaire|Cachet|Autre) de ([0-9][0-9 .,]*[0-9]|[0-9]) *Euro', 1)
            AS borne_basse,
        regexp_extract(coalesce(salaire_libelle, ''),
            '^(?:Annuel|Mensuel|Horaire|Cachet|Autre) de [0-9][0-9 .,]* *Euros? à ([0-9][0-9 .,]*[0-9]|[0-9]) *Euro', 1)
            AS borne_haute,
        regexp_extract(coalesce(salaire_libelle, ''), ' sur ([0-9][0-9.,]*) *(mois|heure)', 1)
            AS sur_quantite,
        regexp_extract(coalesce(salaire_libelle, ''), ' sur ([0-9][0-9.,]*) *(mois|heure)', 2)
            AS sur_unite
    FROM localise
),

-- L'espace sépare les milliers (« 35 000.00 »), la virgule est décimale
-- (« 11,65 ») : on retire l'un puis on convertit l'autre.
converti AS (
    SELECT * EXCLUDE (borne_basse, borne_haute, sur_quantite),
        TRY_CAST(replace(replace(borne_basse, ' ', ''), ',', '.') AS DOUBLE) AS montant_bas,
        TRY_CAST(replace(replace(borne_haute, ' ', ''), ',', '.') AS DOUBLE) AS montant_haut,
        TRY_CAST(replace(sur_quantite, ',', '.') AS DOUBLE)                  AS quantite
    FROM decoupe
),

-- Cachet et Autre n'ont pas de période de référence : facteur NULL, donc
-- salaire NULL, plutôt qu'une annualisation inventée.
annualise AS (
    SELECT *,
        CASE periodicite
            WHEN 'Annuel'  THEN 1.0
            WHEN 'Mensuel' THEN coalesce(CASE WHEN sur_unite = 'mois'  THEN quantite END, 12.0)
            WHEN 'Horaire' THEN coalesce(CASE WHEN sur_unite = 'heure' THEN quantite END, 35.0) * 52.0
        END AS facteur_annuel
    FROM converti
)

SELECT
    a.id,
    a.intitule,
    a.entreprise,
    a.type_contrat,
    a.est_alternance,
    a.date_creation,
    a.departement,
    -- Quelques offres ne portent qu'une région en guise de lieu, sans commune
    -- ni code postal : le repli les rattrape.
    coalesce(par_departement.region, par_libelle.region) AS region,
    a.code_rome,
    round(least(a.montant_bas, coalesce(a.montant_haut, a.montant_bas)) * a.facteur_annuel, 2)
        AS salaire_min_annuel,
    round(greatest(a.montant_bas, coalesce(a.montant_haut, a.montant_bas)) * a.facteur_annuel, 2)
        AS salaire_max_annuel,
    a.experience,
    a.description
FROM annualise a
LEFT JOIN ref_regions par_departement USING (departement)
LEFT JOIN (SELECT DISTINCT region FROM ref_regions) par_libelle
       ON par_libelle.region = a.lieu_libelle;
