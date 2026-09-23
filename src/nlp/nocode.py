"""Conventions de nommage du no-code dans ``data/skills_taxonomy.yaml``.

Deux chaînes, mais elles lient le YAML au SQL de deux modules qui ne se
connaissent pas : ``src/nlp/report.py`` et ``src/dashboard/queries.py``. Écrites
en double, un label renommé dans le YAML faisait tomber leurs comptages à zéro
sans lever la moindre erreur — un ``LIKE`` qui ne correspond plus ne se plaint
pas. ``tests/test_skills.py`` vérifie que le YAML respecte toujours ces valeurs.

Le module n'importe rien, volontairement : le dashboard déployé installe
``requirements.txt``, où PyYAML ne figure pas.
"""

from __future__ import annotations

#: La famille du dictionnaire qui regroupe les outils no-code / low-code.
NOCODE_FAMILY = "nocode_lowcode"

#: Marque des labels qui nomment la pratique et non un outil : « No-code
#: (terme générique) », « Low-code (terme générique) ». Ils sont comptés à part
#: pour ne pas gonfler la part réellement outillée.
GENERIC_MARKER = "(terme générique)"

#: Le motif ``LIKE`` correspondant, tel que DuckDB l'attend.
GENERIC_TERM = f"%{GENERIC_MARKER}%"
