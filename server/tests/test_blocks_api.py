"""Block modules through the API: building, rule enforcement and playing."""

from sqlalchemy import update

from app.db.models import Round

from .conftest import GOOD_BOT, login, wait_for
from .test_blocks import ANGRY, HAND
from .test_flow import API, current, drain


def open_round(client, org):
    rid = current(client, org)["id"]
    client.post(f"{API}/admin/rounds/{rid}/window/open", json={"minutes": 5}, headers=org)
    return rid


def agent(*layouts, hand=HAND):
    return {"hand_code": hand, "modules": [{"layout": layout} for layout in layouts]}


def test_validate_returns_generated_code_and_rules(client):
    team = login(client, "team1")
    out = client.post(f"{API}/practice/validate", json=agent(ANGRY), headers=team).json()
    assert out["errors"] == []
    assert out["modules"][0]["name"] == "is_angry" and out["modules"][0]["blocks"] == 9
    assert "def is_angry(my_history, opp_history):" in out["assembled"]
    assert out["rules"]["max_modules"] == 2  # the round's defaults


def test_block_agent_is_accepted_and_plays(client, db):
    org, team1, team2 = login(client, "organiser"), login(client, "team1"), login(client, "team2")
    rid = open_round(client, org)
    r = client.post(f"{API}/submissions", json=agent(ANGRY), headers=team1)
    assert r.status_code == 202 and r.json()["module_count"] == 1
    client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers=team2)
    drain(db)

    detail = client.get(f"{API}/submissions/{r.json()['id']}", headers=team1).json()
    assert detail["status"] == "accepted"
    assert detail["modules"][0]["layout"] == ANGRY  # the layout is kept so the team can reload it
    assert detail["hand_code"] == HAND and "def is_angry" in detail["code"]

    client.post(f"{API}/admin/rounds/{rid}/window/close", headers=org)
    wait_for(lambda: current(client, org)["status"] == "locked")
    client.post(f"{API}/admin/rounds/{rid}/start", headers=org)
    drain(db)
    wait_for(lambda: current(client, org)["status"] in ("verifying", "review"))
    review = client.get(f"{API}/admin/rounds/{rid}/review", headers=org).json()
    assert all(s["outcome"] != "disqualified" for s in review["standings"])


def test_block_rules_are_enforced_on_submit(client):
    org, team = login(client, "organiser"), login(client, "team1")
    rid = open_round(client, org)
    rules = {"max_modules": 1, "max_blocks": 5, "categories": ["logic", "history"]}
    assert client.put(f"{API}/admin/rounds/{rid}/rules", json=rules, headers=org).status_code == 200
    assert current(client, team)["block_rules"] == rules

    r = client.post(f"{API}/submissions", json=agent(ANGRY, ANGRY), headers=team)
    assert r.status_code == 422 and r.json()["error"]["code"] == "BLOCK_RULES"
    messages = " ".join(e["message"] for e in r.json()["error"]["details"]["errors"])
    assert "at most 1 block module" in messages and "9 blocks" in messages and "math" in messages
    assert client.get(f"{API}/submissions", headers=team).json() == []  # nothing stored

    bad = {"max_modules": 1, "max_blocks": 5, "categories": ["sorcery"]}
    assert client.put(f"{API}/admin/rounds/{rid}/rules", json=bad, headers=org).status_code == 422


def test_version_breaking_a_tighter_round_sits_it_out(client, db):
    org, team1, team2 = login(client, "organiser"), login(client, "team1"), login(client, "team2")
    rid = open_round(client, org)
    client.post(f"{API}/submissions", json=agent(ANGRY), headers=team1)
    client.post(f"{API}/submissions", json={"hand_code": GOOD_BOT}, headers=team2)
    drain(db)
    # The organisers tighten the rules after team1's accepted version was built
    with db() as s:
        s.execute(update(Round).where(Round.id == rid).values(max_blocks=5))
        s.commit()
    client.post(f"{API}/admin/rounds/{rid}/window/close", headers=org)
    wait_for(lambda: current(client, org)["status"] == "locked")
    client.post(f"{API}/admin/rounds/{rid}/start", headers=org)
    drain(db)
    wait_for(lambda: current(client, org)["status"] in ("verifying", "review"))
    review = client.get(f"{API}/admin/rounds/{rid}/review", headers=org).json()
    standings = {s["team_name"]: s for s in review["standings"]}
    assert standings["Team 1"]["outcome"] == "absent"
    assert "breaks this round's block rules" in standings["Team 1"]["reason"]
