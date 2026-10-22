"""Smoke tests for the Streamlit UI, with ``streamlit.testing.AppTest``.

Each page is drawn once on the synthetic warehouse of ``dashboard_data``,
written to a temporary ``.duckdb`` file that ``RADAR_DB_PATH`` points to. No
query is typed, so « Recherche » and « Assistant » never load the language
model: the versioned ``data/embeddings.npy`` is enough, and CI downloads nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_data import make_warehouse  # noqa: E402

from src.dashboard.data import DB_PATH_ENV  # noqa: E402

#: Large enough for a cold DuckDB connection on a CI runner.
TIMEOUT = 30

PAGES = {
    "overview": "Vue d'ensemble",
    "nocode": "No-code & IA",
    "profile": "Mon profil",
    "search": "Recherche",
    "assistant": "Assistant",
}


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A synthetic warehouse on disk, as the dashboard reads it."""
    path = tmp_path_factory.mktemp("warehouse") / "warehouse.duckdb"
    with duckdb.connect(str(path)) as con:
        make_warehouse(con)
    return path


@pytest.fixture(autouse=True)
def environment(warehouse: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the dashboard at the synthetic warehouse, with the mock LLM."""
    monkeypatch.setenv(DB_PATH_ENV, str(warehouse))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)


def _render_page(page: str) -> None:
    # AppTest runs this function's source as a standalone script: the imports
    # must live inside it.
    import importlib

    from src.dashboard.filtering import Filters

    importlib.import_module(f"src.dashboard.views.{page}").render(Filters())


@pytest.mark.parametrize("page", PAGES)
def test_chaque_page_se_dessine_sans_erreur(page: str) -> None:
    at = AppTest.from_function(_render_page, args=(page,), default_timeout=TIMEOUT).run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value == PAGES[page]


def test_application_complete() -> None:
    """Sidebar and navigation around the default page, as ``streamlit run`` draws them."""
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value == PAGES["overview"]
    assert len(at.sidebar) > 0


def test_entrepot_absent_explique_en_francais(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "absent.duckdb"))
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception, at.exception
    assert "introuvable" in at.error[0].value
