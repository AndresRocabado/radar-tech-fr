"""Point d'entrée du dashboard : ``streamlit run app.py``.

Les filtres sont dessinés ici, dans le script d'entrée, pour que leur valeur
survive au changement de page.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard import data, sidebar
from src.dashboard.views import nocode, overview, search


def main() -> None:
    """Configurer la page, vérifier l'entrepôt et lancer la navigation."""
    st.set_page_config(page_title="Radar Tech FR", page_icon="📡", layout="wide")

    problem = data.warehouse_problem()
    if problem:
        st.title("Radar Tech FR")
        st.error(problem, icon=":material/error:")
        st.stop()

    filters = sidebar.render(data.filter_options())
    pages = [
        st.Page(lambda: overview.render(filters), title="Vue d'ensemble",
                icon=":material/dashboard:", url_path="vue-d-ensemble", default=True),
        st.Page(lambda: nocode.render(filters), title="No-code & IA",
                icon=":material/bolt:", url_path="no-code-ia"),
        st.Page(lambda: search.render(filters), title="Recherche",
                icon=":material/search:", url_path="recherche"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
