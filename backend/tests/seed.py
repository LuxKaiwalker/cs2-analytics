"""Write a small, fully analysed match into the database.

Used by API tests so they can exercise reading, filtering, pagination and deletion
without parsing a demo. The data comes from the same normalization and computation code
the server uses, so the stored shapes are genuine.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.analytics.compute import compute
from app.models import Match, MatchStatus
from app.parsing.model import NormalizedMatch
from app.persist.writer import persist_match
from tests import factories as f


def sample_match() -> NormalizedMatch:
    """A two-round match with kills, damage, flashes, utility and a bomb plant."""
    ct = [f.player(f"ct{i}") for i in range(1, 6)]
    t = [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [
        f.round_(1, winner_side="CT", reason="ct_win"),
        f.round_(2, winner_side="T", reason="target_bombed"),
    ]
    kills = [
        f.kill(0, 1_500, 1, ct[0], t[0], attacker_side="CT", victim_side="T", headshot=True),
        f.kill(1, 1_700, 1, ct[0], t[1], attacker_side="CT", victim_side="T"),
        f.kill(2, 1_900, 1, t[2], ct[1], attacker_side="T", victim_side="CT"),
        f.kill(3, 2_000, 1, ct[2], t[2], attacker_side="CT", victim_side="T", assister=ct[3]),
        f.kill(4, 11_500, 2, t[0], ct[0], attacker_side="T", victim_side="CT"),
        f.kill(5, 11_600, 2, t[0], ct[1], attacker_side="T", victim_side="CT", weapon="awp"),
    ]
    damages = [
        f.damage(0, 1_500, 1, ct[0], t[0], 100, health_post=0),
        f.damage(1, 1_700, 1, ct[0], t[1], 100, health_post=0),
        f.damage(2, 1_890, 1, t[2], ct[1], 60, health_post=40),
        f.damage(3, 1_900, 1, t[2], ct[1], 55, health_post=0),
        f.damage(4, 1_950, 1, ct[2], t[2], 30, health_post=70, weapon="hegrenade"),
        f.damage(5, 2_000, 1, ct[2], t[2], 90, health_post=0),
        f.damage(6, 11_500, 2, t[0], ct[0], 100, health_post=0),
        f.damage(7, 11_600, 2, t[0], ct[1], 120, health_post=0, weapon="awp"),
    ]
    blinds = [
        f.blind(0, 1_400, 1, ct[3], t[0], 2.5, attacker_side="CT", victim_side="T"),
        f.blind(1, 1_400, 1, ct[3], ct[4], 1.0, attacker_side="CT", victim_side="CT"),
    ]
    utility = [
        f.throw(0, 1_300, 1, ct[3], "flashbang"),
        f.throw(1, 1_940, 1, ct[2], "hegrenade"),
        f.throw(2, 11_200, 2, t[1], "smokegrenade"),
    ]
    objectives = [
        f.objective(0, 11_000, 2, "start_plant", t[1]),
        f.objective(1, 11_300, 2, "finish_plant", t[1], bombsite="A"),
    ]
    return f.match(
        rounds=rounds,
        roster=f.roster_for(rounds, ct, t),
        kills=kills,
        damages=damages,
        blinds=blinds,
        utility=utility,
        objectives=objectives,
    )


def write_sample_match(engine: Engine, match_id: str) -> str:
    """Persist :func:`sample_match` under ``match_id`` and return the id."""
    normalized = sample_match()
    analytics = compute(normalized)
    with Session(engine) as session:
        session.add(
            Match(
                id=match_id,
                sha256=f"{match_id:<64.64}".replace(" ", "0"),
                original_filename="sample.dem",
                stored_path=None,
                size_bytes=1024,
                source="upload",
                status=MatchStatus.PROCESSING,
            )
        )
        session.commit()
        persist_match(session, match_id, normalized, analytics, parse_seconds=0.01)
        session.commit()
    return match_id
