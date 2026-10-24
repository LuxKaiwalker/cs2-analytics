"""The event feed: filtering, sorting, pagination and ordering guarantees."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.conftest import seed_completed_match


def _events(client: TestClient, match_id: str, query: str = "") -> dict:
    response = client.get(f"/api/matches/{match_id}/events{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_default_feed_is_chronological_and_densely_sequenced(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?limit=200")
    seqs = [e["seq"] for e in page["items"]]
    assert seqs == sorted(seqs)
    assert seqs == list(range(len(seqs))), "seq is dense across the whole match"
    keys = [(e["round_num"], e["tick"]) for e in page["items"]]
    assert keys == sorted(keys)


def test_damage_precedes_the_kill_it_caused_at_the_same_tick(
    client: TestClient, engine: Engine
) -> None:
    """A reading convention, since the demo does not order across event types."""
    match_id = seed_completed_match(engine)
    items = _events(client, match_id, "?limit=200")["items"]
    by_tick: dict[int, list[str]] = {}
    for event in items:
        by_tick.setdefault(event["tick"], []).append(event["event_type"])
    shared = [types for types in by_tick.values() if {"damage", "kill"} <= set(types)]
    assert shared, "the seeded match has a kill and its damage on one tick"
    for types in shared:
        assert types.index("damage") < types.index("kill")


def test_filtering_by_round_restricts_the_feed_and_the_total(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?round_num=2&limit=200")
    assert page["items"], "round 2 has events"
    assert {e["round_num"] for e in page["items"]} == {2}
    assert page["total"] == len(page["items"])
    assert page["total"] < _events(client, match_id, "?limit=200")["total"]


def test_filtering_by_event_type_works(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?event_type=kill&limit=200")
    assert page["items"]
    assert {e["event_type"] for e in page["items"]} == {"kill"}


def test_an_unknown_event_type_is_rejected_with_the_allowed_values(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    response = client.get(f"/api/matches/{match_id}/events?event_type=nonsense")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_filtering_by_player_covers_both_sides_of_a_duel(
    client: TestClient, engine: Engine
) -> None:
    """Filtering by a name should show what they did *and* what happened to them."""
    match_id = seed_completed_match(engine)
    players = client.get(f"/api/matches/{match_id}/players").json()
    victim = next(p for p in players if p["deaths"] > 0)
    page = _events(client, match_id, f"?player_key={victim['player_key']}&limit=200")
    assert page["items"]
    assert all(victim["player_key"] in (e["actor_key"], e["victim_key"]) for e in page["items"])
    assert any(e["victim_key"] == victim["player_key"] for e in page["items"])


def test_minimum_damage_filter_applies_to_the_capped_value(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?min_damage=90&event_type=damage&limit=200")
    assert page["items"]
    assert all(e["damage_health"] >= 90 for e in page["items"])


def test_damage_rows_expose_both_the_raw_and_the_capped_figure(
    client: TestClient, engine: Engine
) -> None:
    """The seeded match contains a 120-damage AWP hit on a 100 HP target."""
    match_id = seed_completed_match(engine)
    items = _events(client, match_id, "?event_type=damage&limit=200")["items"]
    overkill = [e for e in items if e["extra"] and e["extra"]["damage_raw"] > 100]
    assert overkill, "the fixture includes an overkill hit"
    for event in overkill:
        assert event["damage_health"] == 100, "the summable value is capped"
        assert event["extra"]["damage_raw"] > 100, "the reported value is preserved"


def test_search_matches_player_names_and_weapons(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?search=awp&limit=200")
    assert page["items"]
    assert all(
        "awp" in (e["weapon"] or "").lower()
        or "awp" in (e["actor_name"] or "").lower()
        or "awp" in (e["victim_name"] or "").lower()
        for e in page["items"]
    )


def test_pagination_is_stable_and_non_overlapping(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    total = _events(client, match_id, "?limit=200")["total"]
    first = _events(client, match_id, "?limit=5&offset=0")
    second = _events(client, match_id, "?limit=5&offset=5")
    assert first["total"] == second["total"] == total
    assert len(first["items"]) == 5
    ids_a = {e["seq"] for e in first["items"]}
    ids_b = {e["seq"] for e in second["items"]}
    assert ids_a.isdisjoint(ids_b)
    assert max(ids_a) < min(ids_b)


def test_descending_order_is_honoured(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?order=desc&limit=10")
    seqs = [e["seq"] for e in page["items"]]
    assert seqs == sorted(seqs, reverse=True)


def test_sorting_by_damage_is_allowed_and_tie_broken_deterministically(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    page = _events(client, match_id, "?event_type=damage&sort=damage_health&order=desc&limit=50")
    damages = [e["damage_health"] for e in page["items"]]
    assert damages == sorted(damages, reverse=True)
    repeat = _events(client, match_id, "?event_type=damage&sort=damage_health&order=desc&limit=50")
    assert [e["seq"] for e in page["items"]] == [e["seq"] for e in repeat["items"]]


def test_sorting_by_an_arbitrary_column_is_rejected(client: TestClient, engine: Engine) -> None:
    """Only whitelisted columns may be sorted on."""
    match_id = seed_completed_match(engine)
    response = client.get(f"/api/matches/{match_id}/events?sort=extra_json")
    assert response.status_code == 422


def test_limit_is_capped(client: TestClient, engine: Engine) -> None:
    match_id = seed_completed_match(engine)
    assert client.get(f"/api/matches/{match_id}/events?limit=10000").status_code == 422


def test_events_for_an_unknown_match_are_a_404(client: TestClient) -> None:
    assert client.get("/api/matches/missing/events").status_code == 404


def test_event_counts_and_weapon_list_back_the_filter_controls(
    client: TestClient, engine: Engine
) -> None:
    match_id = seed_completed_match(engine)
    counts = client.get(f"/api/matches/{match_id}/events/count").json()
    assert counts["kill"] > 0
    assert counts["damage"] > 0
    assert sum(counts.values()) == _events(client, match_id, "?limit=200")["total"]

    weapons = client.get(f"/api/matches/{match_id}/weapons").json()
    assert "awp" in weapons
    assert weapons == sorted(weapons)
    assert None not in weapons
