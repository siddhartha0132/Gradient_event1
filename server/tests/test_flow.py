"""The event end to end through the API, with workers driven by the test."""

import time

from sqlalchemy import select, update

from app.db.models import Job, Match, Submission
from worker.main import process_one

from .conftest import BAD_BOT, GOOD_BOT, MEAN_BOT, NICE_BOT, login, wait_for

API = "/api/v1"


def drain(db, workers=("worker-a", "worker-b")):
    """Run jobs until the queue is empty, alternating workers so verification can run."""
    with db() as session:
        idle = 0
        i = 0
        while idle < len(workers):
            idle = 0 if process_one(session, workers[i % len(workers)]) else idle + 1
            i += 1


def current(client, headers):
    return client.get(f"{API}/rounds/current", headers=headers).json()


def test_country_claims_are_unique(client):
    t1, t2 = login(client, "team1"), login(client, "team2")
    assert client.post(f"{API}/teams/me/country", json={"code": "356"}, headers=t1).status_code == 200
    r = client.post(f"{API}/teams/me/country", json={"code": "356"}, headers=t2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "COUNTRY_TAKEN"
    again = client.post(f"{API}/teams/me/country", json={"code": "076"}, headers=t1)
    assert again.json()["error"]["code"] == "ALREADY_CLAIMED"


def test_roles_are_enforced(client):
    team = login(client, "team1")
    rid = current(client, team)["id"]
    r = client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=team)
    assert r.status_code == 403
    assert client.get(f"{API}/me").status_code == 401


def test_full_round(client, db):
    org = login(client, "organiser")
    teams = [login(client, f"team{i}") for i in range(1, 5)]
    rid = current(client, org)["id"]

    # Closed window rejects submissions
    r = client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers=teams[0])
    assert r.json()["error"]["code"] == "WINDOW_CLOSED"

    assert client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org).status_code == 200

    # A retried submission with the same key is stored once
    key = {"Idempotency-Key": "abc-123"}
    first = client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers={**teams[0], **key})
    second = client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers={**teams[0], **key})
    assert first.status_code == 202 and first.json()["id"] == second.json()["id"]
    client.post(f"{API}/submissions", json={"hand_code": MEAN_BOT}, headers=teams[1])
    client.post(f"{API}/submissions", json={"hand_code": NICE_BOT}, headers=teams[2])
    client.post(f"{API}/submissions", json={"hand_code": BAD_BOT}, headers=teams[3])
    drain(db)

    history = client.get(f"{API}/submissions", headers=teams[0]).json()
    assert [s["version"] for s in history] == [1] and history[0]["status"] == "accepted"
    assert client.get(f"{API}/submissions", headers=teams[3]).json()[0]["status"] == "rejected"
    # A team cannot read another team's code
    assert client.get(f"{API}/submissions/{history[0]['id']}", headers=teams[1]).status_code == 404

    # Pause, extend and resume move the deadline
    client.post(f"{API}/admin/rounds/{rid}/window/pause", headers=org)
    paused = current(client, org)
    assert paused["paused_remaining"] is not None and not paused["window_open"]
    client.post(f"{API}/admin/rounds/{rid}/window/extend", json={"minutes": 1}, headers=org)
    assert current(client, org)["paused_remaining"] > paused["paused_remaining"] + 50
    client.post(f"{API}/admin/rounds/{rid}/window/resume", headers=org)
    assert current(client, org)["window_open"]

    # Closing the window lets the scheduler lock entries
    client.post(f"{API}/admin/rounds/{rid}/window/close", headers=org)
    wait_for(lambda: current(client, org)["status"] == "locked")
    assert client.post(f"{API}/admin/rounds/{rid}/start", headers=org).status_code == 200

    # 3 entrants, 1 repetition: 3 self-play + 3 pairs
    assert current(client, org)["matches_total"] == 6
    drain(db)
    wait_for(lambda: current(client, org)["status"] in ("verifying", "review"))
    drain(db)
    wait_for(lambda: current(client, org)["status"] == "review")

    # Standings stay hidden until approval
    assert client.get(f"{API}/rounds/{rid}/standings", headers=teams[0]).status_code == 403
    review = client.get(f"{API}/admin/rounds/{rid}/review", headers=org).json()
    assert review["blockers"] == []
    assert review["verification"]["total"] > 0 and review["verification"]["mismatches"] == []
    with db() as s:
        checks = s.execute(select(Job.worker_id).where(Job.kind == "verify")).scalars().all()
        originals = s.execute(select(Match.worker_id)).scalars().all()
        assert checks and originals

    assert client.post(f"{API}/admin/rounds/{rid}/approve", headers=org).status_code == 200
    standings = client.get(f"{API}/rounds/{rid}/standings", headers=teams[0]).json()
    outcomes = {s["team_name"]: s["outcome"] for s in standings}
    assert outcomes["Team 4"] == "absent"  # its only submission was rejected
    assert sorted(o for o in outcomes.values() if o in ("advanced", "eliminated")) == \
        ["advanced", "advanced", "eliminated"]
    assert current(client, org)["index"] == 2

    # Fallen teams can no longer submit
    fallen = next(i for i, name in enumerate(["Team 1", "Team 2", "Team 3", "Team 4"])
                  if outcomes[name] != "advanced")
    client.post(f"{API}/admin/rounds/{current(client, org)['id']}/window/open", json={"minutes": 5}, headers=org)
    r = client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers=teams[fallen])
    assert r.json()["error"]["code"] == "TEAM_ELIMINATED"

    # Replays of a published round are open to every team
    matches = client.get(f"{API}/rounds/{rid}/matches", headers=teams[3]).json()
    assert len(matches) == 6
    replay = client.get(f"{API}/matches/{matches[0]['id']}/replay", headers=teams[3]).json()
    assert len(replay["moves_a"]) == 20

    # The WebSocket replays the log from a given seq, filtered to what this user may see
    with client.websocket_connect(f"{API}/ws?token={teams[0]['Authorization'][7:]}&after=0") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        seen = []
        while len(seen) < hello["payload"]["head"]:
            msg = ws.receive_json()
            if msg["type"] == "clock.tick":
                continue
            seen.append(msg)
            if msg["type"] == "standings.published":
                break
    types = [m["type"] for m in seen]
    assert "match.done" in types and "standings.published" in types and "fairplay.flag" not in types
    results = [m for m in seen if m["type"] == "submission.result"]
    assert len(results) == 1  # only its own submission's result
    assert [m["seq"] for m in seen] == sorted(m["seq"] for m in seen)


def test_jobs_are_reclaimed_then_given_up(client, db):
    org = login(client, "organiser")
    team = login(client, "team1")
    rid = current(client, org)["id"]
    client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org)
    client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers=team)

    from worker.main import claim
    with db() as s:
        for attempt in range(1, 4):
            job = claim(s, f"dying-worker-{attempt}")  # claims, then "dies" without acking
            assert job.attempts == attempt
            assert claim(s, "other") is None  # the lease still holds
            s.execute(update(Job).values(leased_until=time.time() - 1))  # lease expires
            s.commit()
        assert process_one(s, "survivor")  # fourth attempt is over the limit
        assert s.scalar(select(Job.status)) == "dead"
        submission = s.scalar(select(Submission))
        assert submission.status == "rejected" and "Could not be checked" in submission.errors[0]


def test_match_results_are_written_once(client, db):
    org = login(client, "organiser")
    teams = [login(client, f"team{i}") for i in (1, 2)]
    rid = current(client, org)["id"]
    client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org)
    for t, code in zip(teams, (GOOD_BOT, MEAN_BOT)):
        client.post(f"{API}/submissions", json={"hand_code": code}, headers=t)
    drain(db)
    client.post(f"{API}/admin/rounds/{rid}/window/close", headers=org)
    wait_for(lambda: current(client, org)["status"] == "locked")
    client.post(f"{API}/admin/rounds/{rid}/start", headers=org)

    from worker.main import handle_match
    with db() as s:
        match = s.scalar(select(Match).where(Match.team_a != Match.team_b))
        handle_match(s, match.id, "first")
        s.commit()
        handle_match(s, match.id, "slow-duplicate")  # e.g. a reclaimed job finishing late
        s.commit()
        s.refresh(match)
        assert match.worker_id == "first" and match.status == "done"


def test_invalid_round_actions_are_refused_cleanly(client):
    org = login(client, "organiser")
    rid = current(client, org)["id"]
    assert client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org).status_code == 200
    again = client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_ROUND_STATE"
    assert "is open" in again.json()["error"]["message"]
    start = client.post(f"{API}/admin/rounds/{rid}/start", headers=org)
    assert start.status_code == 409
