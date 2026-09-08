"""Offline tests for the France Travail ingestion layer.

Every HTTP call is faked; no test touches the network or sleeps for real.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest import pagination  # noqa: E402
from src.ingest.france_travail import FranceTravailClient  # noqa: E402
from src.ingest.rate_limit import (  # noqa: E402
    FranceTravailAPIError,
    RateLimiter,
    backoff_delay,
    parse_retry_after,
    request_with_retry,
)
from src.ingest.storage import raw_page_filename, slugify  # noqa: E402


def make_response(
    status_code: int = 200,
    *,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> Mock:
    """Build a fake ``requests.Response``."""
    response = Mock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.text = text
    response.content = b"{}" if json_body is not None else b""
    response.json.return_value = json_body if json_body is not None else {}
    return response


def offers_page(count: int, first_id: int = 0) -> dict[str, Any]:
    """Build a search payload holding ``count`` offers."""
    return {"resultats": [{"id": f"OFFER{first_id + i}"} for i in range(count)]}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FranceTravailClient:
    """A client with a pre-warmed token and a temporary raw directory."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    instance = FranceTravailClient(
        client_id="PAR_test", client_secret="secret", raw_dir=tmp_path / "raw"
    )
    instance.auth._access_token = "fake-token"
    instance.auth._expires_at = float("inf")
    return instance


# ----------------------------------------------------------------- pagination


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("offres 0-149/287543", (0, 149, 287543)),
        ("offres 150-299/1200", (150, 299, 1200)),
        (None, (None, None, None)),
        ("", (None, None, None)),
        ("garbage", (None, None, None)),
    ],
)
def test_parse_content_range(header: str | None, expected: tuple[Any, ...]) -> None:
    assert pagination.parse_content_range(header) == expected


def test_page_bounds_clamps_to_the_pagination_ceiling() -> None:
    assert pagination.page_bounds(0, 150) == (0, 149)
    assert pagination.page_bounds(150, 150) == (150, 299)
    # The API rejects a start above 3000, so 3149 is the last reachable index.
    assert pagination.page_bounds(3000, 150) == (3000, 3149)


def test_page_size_is_capped_at_the_api_maximum() -> None:
    # The API answers 400 to a window wider than 150.
    assert pagination.page_bounds(0, 200) == (0, 149)


def test_split_window_halves_the_period() -> None:
    halves = pagination.split_window("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z")
    assert halves == (
        ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        ("2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
    )


def test_split_window_refuses_a_window_that_is_already_narrow() -> None:
    assert pagination.split_window("2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z") is None


def test_default_window_spans_the_lookback() -> None:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert pagination.default_window(30, now=now) == (
        "2026-01-30T00:00:00Z",
        "2026-03-01T00:00:00Z",
    )


# ---------------------------------------------------------------- rate limit


def test_rate_limiter_sleeps_once_the_window_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    clock = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr("src.ingest.rate_limit.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("src.ingest.rate_limit.time.sleep", slept.append)

    limiter = RateLimiter(max_calls=2, period=1.0)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert slept and slept[0] == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("header", "expected"), [("30", 30.0), ("0", 0.0), ("Wed, 21 Oct 2026 07:28:00 GMT", None), (None, None)]
)
def test_parse_retry_after(header: str | None, expected: float | None) -> None:
    assert parse_retry_after(header) == expected


def test_backoff_grows_and_stays_bounded() -> None:
    assert 0.0 <= backoff_delay(0) <= 0.5
    assert 0.0 <= backoff_delay(3) <= 4.0
    assert backoff_delay(20) <= 60.0


def test_request_with_retry_honours_retry_after_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("src.ingest.rate_limit.time.sleep", slept.append)
    session = Mock()
    session.request.side_effect = [
        make_response(429, headers={"Retry-After": "7"}),
        make_response(200, json_body={"ok": True}),
    ]

    response = request_with_retry(session, "GET", "https://example.test", RateLimiter())

    assert response.status_code == 200
    assert slept == [7.0]


def test_request_with_retry_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ingest.rate_limit.time.sleep", lambda _s: None)
    session = Mock()
    session.request.return_value = make_response(503, text="unavailable")

    with pytest.raises(FranceTravailAPIError) as error:
        request_with_retry(session, "GET", "https://example.test", RateLimiter(), max_attempts=3)

    assert error.value.status_code == 503
    assert session.request.call_count == 3


def test_request_with_retry_does_not_retry_client_errors() -> None:
    session = Mock()
    session.request.return_value = make_response(400, text="bad request")

    response = request_with_retry(session, "GET", "https://example.test", RateLimiter())

    assert response.status_code == 400
    assert session.request.call_count == 1


# ---------------------------------------------------------------------- auth


def test_token_is_cached_until_it_expires(tmp_path: Path) -> None:
    session = Mock()
    session.request.return_value = make_response(
        200, json_body={"access_token": "abc", "expires_in": 1499}
    )
    client = FranceTravailClient(
        client_id="PAR_x", client_secret="s", session=session, raw_dir=tmp_path
    )

    assert client.auth.token == "abc"
    assert client.auth.token == "abc"
    assert session.request.call_count == 1


def test_expired_token_triggers_a_refresh(tmp_path: Path) -> None:
    session = Mock()
    session.request.side_effect = [
        make_response(200, json_body={"access_token": "first", "expires_in": 0}),
        make_response(200, json_body={"access_token": "second", "expires_in": 1499}),
    ]
    client = FranceTravailClient(
        client_id="PAR_x", client_secret="s", session=session, raw_dir=tmp_path
    )

    assert client.auth.token == "first"
    assert client.auth.token == "second"


def test_invalid_scope_falls_back_to_the_legacy_form(tmp_path: Path) -> None:
    session = Mock()
    session.request.side_effect = [
        make_response(400, text='{"error":"invalid_scope"}'),
        make_response(200, json_body={"access_token": "ok", "expires_in": 1499}),
    ]
    client = FranceTravailClient(
        client_id="PAR_x", client_secret="s", session=session, raw_dir=tmp_path
    )

    assert client.auth.token == "ok"
    assert client.auth.scope.startswith("application_PAR_x ")


def test_missing_credentials_are_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ingest.france_travail.load_dotenv", lambda: None)
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    monkeypatch.delenv("FT_CLIENT_SECRET", raising=False)

    with pytest.raises(ValueError, match="FT_CLIENT_ID"):
        FranceTravailClient()


# -------------------------------------------------------------------- search


def test_search_paginates_until_the_total_is_reached(client: FranceTravailClient) -> None:
    client._session.request = Mock(
        side_effect=[
            make_response(206, json_body=offers_page(150, 0), headers={"Content-Range": "offres 0-149/230"}),
            make_response(200, json_body=offers_page(80, 150), headers={"Content-Range": "offres 150-229/230"}),
        ]
    )

    offers = client.search_offers(motsCles="data engineer", natureContrat="E2")

    assert len(offers) == 230
    assert client._session.request.call_count == 2


def test_search_deduplicates_offers_by_id(client: FranceTravailClient) -> None:
    client._session.request = Mock(
        side_effect=[
            make_response(206, json_body=offers_page(150, 0), headers={"Content-Range": "offres 0-149/300"}),
            make_response(200, json_body=offers_page(150, 0), headers={"Content-Range": "offres 150-299/300"}),
        ]
    )

    offers = client.search_offers(motsCles="data analyst")

    assert len(offers) == 150


def test_search_stops_at_max_results(client: FranceTravailClient) -> None:
    client._session.request = Mock(
        return_value=make_response(
            206, json_body=offers_page(150), headers={"Content-Range": "offres 0-149/900"}
        )
    )

    offers = client.search_offers(motsCles="machine learning", max_results=150)

    assert len(offers) == 150
    assert client._session.request.call_count == 1


def test_search_returns_nothing_on_an_empty_result_set(client: FranceTravailClient) -> None:
    client._session.request = Mock(return_value=make_response(204))

    assert client.search_offers(motsCles="inexistant") == []


def test_oversized_search_is_split_into_date_windows(client: FranceTravailClient) -> None:
    # The first page advertises 5000 offers, above the 3150 ceiling, so the
    # client must fall back to narrower minCreationDate/maxCreationDate windows.
    client._session.request = Mock(
        return_value=make_response(
            206, json_body=offers_page(150), headers={"Content-Range": "offres 0-149/5000"}
        )
    )

    client.search_offers(motsCles="data", lookback_days=2)

    windows = [
        (call.kwargs["params"].get("minCreationDate"), call.kwargs["params"].get("maxCreationDate"))
        for call in client._session.request.call_args_list
    ]
    assert windows[0] == (None, None), "la première requête explore la fenêtre complète"
    assert any(minimum is not None for minimum, _ in windows), "aucun découpage par date"


def test_a_search_below_the_ceiling_is_never_split(client: FranceTravailClient) -> None:
    client._session.request = Mock(
        return_value=make_response(
            200, json_body=offers_page(10), headers={"Content-Range": "offres 0-9/10"}
        )
    )

    client.search_offers(motsCles="power platform")

    params = client._session.request.call_args.kwargs["params"]
    assert "minCreationDate" not in params


def test_the_window_travels_in_the_range_query_parameter(client: FranceTravailClient) -> None:
    # Measured against the live API: a Range request header is ignored, only the
    # `range` query parameter moves the window.
    client._session.request = Mock(
        side_effect=[
            make_response(206, json_body=offers_page(150, 0), headers={"Content-Range": "offres 0-149/300"}),
            make_response(200, json_body=offers_page(150, 150), headers={"Content-Range": "offres 150-299/300"}),
        ]
    )

    client.search_offers(motsCles="low-code")

    calls = client._session.request.call_args_list
    assert [call.kwargs["params"]["range"] for call in calls] == ["0-149", "150-299"]
    assert all("Range" not in call.kwargs["headers"] for call in calls)


def test_search_stops_if_the_api_stops_honouring_the_window(client: FranceTravailClient) -> None:
    # The API keeps answering with page one; without a guard we would loop over
    # the same 150 offers until the ceiling.
    client._session.request = Mock(
        return_value=make_response(
            206, json_body=offers_page(150, 0), headers={"Content-Range": "offres 0-149/400"}
        )
    )

    offers = client.search_offers(motsCles="low-code")

    assert len(offers) == 150
    assert client._session.request.call_count == 2


def test_pages_are_written_verbatim_to_the_raw_directory(client: FranceTravailClient) -> None:
    payload = offers_page(3)
    client._session.request = Mock(
        return_value=make_response(200, json_body=payload, headers={"Content-Range": "offres 0-2/3"})
    )

    client.search_offers(motsCles="power platform", natureContrat="FS")

    written = list(client.raw_dir.glob("*.json"))
    assert len(written) == 1
    assert written[0].name.startswith("offres_power-platform_fs_0000_")


# ------------------------------------------------------------------- storage


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("data engineer", "data-engineer"),
        ("automatisation", "automatisation"),
        ("no-code", "no-code"),
        ("Développeur & Données", "developpeur-donnees"),
        ("", "sans-mots-cles"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_raw_page_filename_separates_natures_and_pages() -> None:
    first = raw_page_filename("data engineer", "E2", 0, "20260908T101500Z")
    second = raw_page_filename("data engineer", "FS", 150, "20260908T101500Z")

    assert first == "offres_data-engineer_e2_0000_20260908T101500Z.json"
    assert second == "offres_data-engineer_fs_0150_20260908T101500Z.json"
