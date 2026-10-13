"""Tests de la reconstruction atomique de l'entrepôt (src/warehouse/staging.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.warehouse import staging  # noqa: E402
from src.warehouse.load import build_warehouse, raw_files  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"


def write_db(path: Path, value: int) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE OR REPLACE TABLE t AS SELECT ? AS v", [value])


def read_db(path: Path) -> int:
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute("SELECT v FROM t").fetchone()[0]


def test_succes_remplace_l_entrepot_sans_laisser_de_fichier(tmp_path: Path) -> None:
    db = tmp_path / "entrepot.duckdb"
    write_db(db, 1)

    with staging.staged_rebuild(db) as path:
        assert path != db
        write_db(path, 2)

    assert read_db(db) == 2
    assert not staging.staging_path(db).exists()


def test_echec_laisse_l_entrepot_intact(tmp_path: Path) -> None:
    db = tmp_path / "entrepot.duckdb"
    write_db(db, 1)

    with pytest.raises(RuntimeError), staging.staged_rebuild(db) as path:
        write_db(path, 2)
        raise RuntimeError("panne au milieu de la reconstruction")

    assert read_db(db) == 1
    assert not staging.staging_path(db).exists()


def test_un_reste_de_reconstruction_avortee_est_ignore(tmp_path: Path) -> None:
    db = tmp_path / "entrepot.duckdb"
    write_db(staging.staging_path(db), 99)

    with staging.staged_rebuild(db) as path:
        assert not path.exists()
        write_db(path, 3)

    assert read_db(db) == 3


def test_le_journal_de_l_ancien_fichier_est_supprime(tmp_path: Path) -> None:
    """Un .wal orphelin serait rejoué sur le nouveau fichier et le corromprait."""
    db = tmp_path / "entrepot.duckdb"
    write_db(db, 1)
    wal = db.with_name(db.name + staging.WAL_SUFFIX)
    wal.write_bytes(b"journal de l'ancien fichier")

    with staging.staged_rebuild(db) as path:
        write_db(path, 2)

    assert not wal.exists()
    assert read_db(db) == 2


def test_l_echange_reessaie_tant_que_le_fichier_est_ouvert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "entrepot.duckdb"
    real_replace = os.replace
    calls: list[int] = []

    def flaky_replace(source: Path, target: Path) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("fichier ouvert par le dashboard")
        real_replace(source, target)

    monkeypatch.setattr(staging.os, "replace", flaky_replace)
    monkeypatch.setattr(staging, "REPLACE_DELAY_SECONDS", 0)

    with staging.staged_rebuild(db) as path:
        write_db(path, 4)

    assert len(calls) == 3
    assert read_db(db) == 4


def test_la_reconstruction_ne_fait_pas_grossir_le_fichier(tmp_path: Path) -> None:
    """En place, chaque rechargement laisse des blocs morts ; en staging, aucun."""
    if not raw_files(RAW_DIR):
        pytest.skip(f"aucune page brute dans {RAW_DIR}")
    db = tmp_path / "entrepot.duckdb"

    sizes = []
    for _ in range(2):
        with staging.staged_rebuild(db) as path:
            build_warehouse(db_path=path, raw_dir=RAW_DIR)
        sizes.append(db.stat().st_size)

    # L'insertion parallèle de DuckDB fait varier la taille d'un bloc ou deux ;
    # en place, le second chargement doublait presque le fichier.
    assert sizes[1] <= sizes[0] * 1.05
