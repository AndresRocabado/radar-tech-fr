-- Agrégation des compétences par famille et par mois.
--
-- Le mois est celui de la création de l'offre, pas celui de la collecte : une
-- collecte unique couvre plusieurs mois de publication, et c'est la date de
-- publication qui porte le signal de marché.
--
-- Le dénominateur est le nombre d'offres publiées dans le mois, toutes offres
-- confondues — y compris celles où le dictionnaire n'a rien reconnu. Sans
-- cela, « part_offres_pct » vaudrait 100 % partout.

CREATE OR REPLACE VIEW agg_competences_famille_mois AS
WITH offres_du_mois AS (
    SELECT
        date_trunc('month', date_creation) AS mois,
        count(*)                           AS offres_publiees
    FROM offres
    WHERE date_creation IS NOT NULL
    GROUP BY 1
)

SELECT
    m.mois,
    c.famille,
    -- Une offre qui cite cinq fois la même famille ne pèse qu'une offre.
    count(DISTINCT c.offre_id)   AS offres_citantes,
    m.offres_publiees,
    round(100.0 * count(DISTINCT c.offre_id) / m.offres_publiees, 1)
                                 AS part_offres_pct,
    count(DISTINCT c.competence) AS competences_distinctes,
    -- Une compétence vue par le texte ET par les champs API compte deux
    -- mentions : l'écart avec offres_citantes mesure le recouvrement.
    count(*)                     AS mentions
FROM offre_competences c
JOIN offres o
  ON o.id = c.offre_id
JOIN offres_du_mois m
  ON m.mois = date_trunc('month', o.date_creation)
GROUP BY m.mois, c.famille, m.offres_publiees
ORDER BY m.mois, offres_citantes DESC;
