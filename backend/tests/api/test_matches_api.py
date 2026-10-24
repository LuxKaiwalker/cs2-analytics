"""Reading, filtering, pagination and deletion."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Match,
    MatchEvent,
    MatchPlayer,
    MatchRound,
    MatchRoundPlayer,
    MatchStatus,
)
from tests.conftest import FakeSupervisor, seed_completed_match, set_status, upload


def test_unknown_match_returns_a_structured_404(client: TestClient) -> None:
    response = client.get("/api/matches/doesnotexist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_match_detail_reports_status_availability_and_provenance(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    body = client.get(f"/api/matches/{match_id}").json()
    assert body["status"] == MatchStatus.COMPLETED
    assert body["map_name"] == "de_test"
    assert body["round_count"] == 2
    assert body["parser_name"] == "awpy"
    assert body["tick_rate_source"] == "header"
    assert body["roster_source"] == "snapshots"
    assert "kills" in body["availability"]
    assert body["availability"]["kills"]["state"] == "available"
    # A demo header has no wall-clock date, so the API must not pretend otherwise.
    assert "uploaded_at" in body
    assert "played_at" not in body


def test_scoreboard_is_returned_highest_kills_first(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    players = client.get(f"/api/matches/{match_id}/players").json()
    assert players, "the seeded match has players"
    kills = [p["kills"] for p in players]
    assert kills == sorted(kills, reverse=True)
    assert {"kd", "adr", "kast", "headshot_pct"} <= set(players[0])


def test_unknown_metrics_are_null_not_zero(client: TestClient, engine: Engine) -> None:
    """A player with no kills must show an unknown headshot rate, not 0%."""
    match_id = seed_completed_match(engine)
    players = client.get(f"/api/matches/{match_id}/players").json()
    no_kills = [p for p in players if p["kills"] == 0]
    assert no_kills, "the seeded match has players who did not frag"
    assert all(p["headshot_pct"] is None for p in no_kills)


def test_rounds_include_outcome_economy_and_per_player_rows(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    rounds = client.get(f"/api/matches/{match_id}/rounds").json()
    assert [r["round_num"] for r in rounds] == [1, 2]
    assert rounds[0]["winner_side"] == "CT"
    assert rounds[1]["bomb_planted"] is True
    assert rounds[1]["bombsite"] == "A"
    assert rounds[1]["bomb_exploded"] is True
    assert len(rounds[0]["players"]) == 10
    assert rounds[0]["score_a_after"] + rounds[0]["score_b_after"] == 1


def test_score_progression_is_cumulative_and_sums_to_the_round_count(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    rounds = client.get(f"/api/matches/{match_id}/rounds").json()
    last = rounds[-1]
    assert last["score_a_after"] + last["score_b_after"] == len(rounds)


def test_match_list_paginates_and_reports_the_filtered_total(
    client: TestClient, engine: Engine
) -> None:
    for _ in range(5):
        seed_completed_match(engine)
    page = client.get("/api/matches?limit=2&offset=0").json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    second = client.get("/api/matches?limit=2&offset=2").json()
    assert {i["id"] for i in page["items"]}.isdisjoint({i["id"] for i in second["items"]})


def test_match_list_filters_by_status_and_map(client: TestClient, engine: Engine) -> None:
    completed = seed_completed_match(engine)
    pending = seed_completed_match(engine)
    set_status(engine, pending, MatchStatus.QUEUED)

    done = client.get(f"/api/matches?status={MatchStatus.COMPLETED}").json()
    assert [i["id"] for i in done["items"]] == [completed]
    queued = client.get(f"/api/matches?status={MatchStatus.QUEUED}").json()
    assert [i["id"] for i in queued["items"]] == [pending]
    by_map = client.get("/api/matches?map=de_test").json()
    assert by_map["total"] == 2
    assert client.get("/api/matches?map=de_nowhere").json()["total"] == 0


def test_an_unknown_status_filter_is_rejected(client: TestClient) -> None:
    response = client.get("/api/matches?status=bogus")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_status"


def test_invalid_pagination_returns_the_standard_error_envelope(
    client: TestClient,
) -> None:
    """FastAPI's default 422 body is overridden so the client has one error shape."""
    response = client.get("/api/matches?limit=9999")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["fields"], "the offending field is named"


def test_deleting_a_match_removes_every_derived_row(client: TestClient, engine: Engine) -> None:
    """Also proves SQLite's per-connection foreign-key enforcement is actually on.

    Without the pragma, these cascades silently do nothing and orphaned rows accumulate.
    """
    match_id = seed_completed_match(engine)
    with Session(engine) as session:
        before = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.match_id == match_id)
            )
            for model in (MatchPlayer, MatchRound, MatchRoundPlayer, MatchEvent)
        }
    assert all(count and count > 0 for count in before.values()), before

    assert client.delete(f"/api/matches/{match_id}").status_code == 204

    with Session(engine) as session:
        after = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.match_id == match_id)
            )
            for model in (MatchPlayer, MatchRound, MatchRoundPlayer, MatchEvent)
        }
        assert after == dict.fromkeys(before, 0), after
        assert session.get(Match, match_id) is None
    assert client.get(f"/api/matches/{match_id}").status_code == 404


def test_deleting_removes_the_stored_demo_file(client: TestClient, engine: Engine) -> None:
    response = upload(client)
    match_id = response.json()["id"]
    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        from pathlib import Path

        stored = Path(record.stored_path or "")
    assert stored.exists()
    assert client.delete(f"/api/matches/{match_id}").status_code == 204
    assert not stored.exists(), "the demo file must go with the match"


def test_deleting_a_running_match_cancels_it_first(
    client: TestClient, engine: Engine, fake_supervisor: FakeSupervisor
) -> None:
    """The worker runs out of process precisely so it can be stopped here."""
    match_id = seed_completed_match(engine)
    set_status(engine, match_id, MatchStatus.PROCESSING)
    assert client.delete(f"/api/matches/{match_id}").status_code == 204
    assert fake_supervisor.cancelled == [match_id]


def test_deleting_a_completed_match_does_not_touch_the_worker(
    client: TestClient, engine: Engine, fake_supervisor: FakeSupervisor
) -> None:
    match_id = seed_completed_match(engine)
    client.delete(f"/api/matches/{match_id}")
    assert fake_supervisor.cancelled == []


def test_deleting_an_unknown_match_is_a_404(client: TestClient) -> None:
    assert client.delete("/api/matches/nope").status_code == 404


def test_health_reports_capacity_and_parser_version(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["database"] is True
    assert body["parser"] == "awpy"
    assert body["parser_version"]
    assert body["max_demo_bytes"] > 0
    assert body["schema_version"] >= 1


def test_metrics_endpoint_publishes_definitions_and_the_omitted_rating(
    client: TestClient,
) -> None:
    """The UI's tooltips come from here, and so does the reason there is no rating."""
    body = client.get("/api/metrics").json()
    keys = {m["key"] for m in body["player_metrics"]}
    assert {"kills", "adr", "kast", "headshot_pct", "kd"} <= keys
    adr = next(m for m in body["player_metrics"] if m["key"] == "adr")
    assert adr["denominator"], "a rate metric must state its denominator"
    assert adr["nullable"] is True
    omitted = {m["key"] for m in body["omitted"]}
    assert "hltv_rating" in omitted, "the absence of a rating is explained, not silent"
