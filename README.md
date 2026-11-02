# Iron Curtain: event platform (working demo)

This is a working build of the Command Server and the Field Client from *Iron Curtain Technical Specification v1*. It runs on a single machine. The engine and the sandbox come from the prototype (github.com/xenia-creator/iron-curtain).

## Run it

You need [uv](https://docs.astral.sh/uv/) and Node 20 or later.

```bash
# 1. Build the client (the server serves it, so one port runs everything)
cd client
npm install
npm run build

# 2. Create the event and accounts
cd ../server
uv sync
uv run python -m scripts.seed_demo --reset --bots   # 12 teams with countries and demo bots
#   or: uv run python -m scripts.seed_demo --reset  # 12 empty teams that claim countries themselves

# 3. Start the API, the scheduler and 3 workers
uv run python serve.py --workers 3
```

| Who | Where |
|---|---|
| Teams and organisers | `http://<this machine>:8000` |
| Projector | `http://<this machine>:8000/spectate` (log in as `projector`) |
| API docs | `http://<this machine>:8000/api/v1/docs` |

Usernames and passwords are printed by the seed script and saved to `server/data/credentials.csv`.

To work on the client, run `npm run dev` in `client/` and open http://localhost:5173. Vite forwards `/api` requests to the server on port 8000.

## Running an event (organiser)

1. **Command tab**: set a number of minutes and click **Open window**. Teams can submit until the countdown ends. You can extend, shorten, pause or close the window at any time, and every screen updates within a second.
2. When the window closes, each team's latest accepted version is locked in. If a submission made before the deadline is still being tested, the lock waits for it.
3. Click **Start round**. The workers play every pairing, and the War Room and projector show each result as it arrives.
4. The server then re-runs every match near the cut line, plus a random 5% of the rest, each time on a different worker. If any result doesn't match, approval is blocked.
5. Review the standings, issue penalties if needed, then click **Approve and publish**. Fallen nations fade on the map, and after the final round the champion is revealed.

## Block modules (drag and drop)

In the Workspace, a team writes `strategy` by hand and can also build up to N helper **modules** from blocks (**+ Block module**). Each module becomes a Python function `name(my_history, opp_history)` that `strategy` can call. The generated Python appears under the block canvas as the team builds.

- **Blocks**: Moves (return, cooperate/defect), Logic (if/else, compare, and/or, not), History (last move, count defections in the last N moves, turns played, first turn), Math (numbers, arithmetic), Chance (n% chance, random number).
- **Rules per round**: the maximum number of modules, the maximum number of blocks per module, and which categories are allowed. They are set in the seed script (they tighten towards the final) and organisers can change them in the Command tab until the window closes.
- **Enforced on the server**: the server compiles each layout to Python itself and never uses code sent by the browser, so a modified client cannot get past the limits. A team's latest accepted version only plays in a round if it keeps to that round's rules; otherwise the team sits the round out, and its version history warns it beforehand.
- Organisers can see how any bot was built with **View** in the teams table.

## Layout

```
server/
  engine/        games, matches, tournament rules, sandbox (from the prototype), blocks.py (block compiler)
  app/           FastAPI: api/v1 routers, services (business rules), db models, realtime gateway
  scheduler/     window clock and round lifecycle (runs inside the API process, one leader by lease)
  worker/        job loop: test submissions, play matches, verify results
  scripts/       seed_demo, dump_openapi, demo_bots
  serve.py       starts the API and N workers, and restarts any worker that crashes
client/
  src/lib/       typed API client (generated from the server's OpenAPI), realtime, clock sync, live store
  src/features/  auth, workspace (Monaco), blocks (Blockly), map / War Room, replay, admin dashboard, fair play
```

The client's API types are generated from the server schema:

```bash
cd server && uv run python -m scripts.dump_openapi ../client/openapi.json
cd ../client && npm run gen:api
```

## Tests

```bash
cd server && uv run pytest     # engine, block compiler and rules, full rounds through the API, idempotency, reclaiming, WebSocket replay
cd client && npm test          # clock sync and DEFCON logic
```

## How this demo differs from the spec

The demo keeps the spec's guarantees but runs on one machine with fewer moving parts:

| Spec | Demo | Why it's still safe |
|---|---|---|
| PostgreSQL 16, synchronous standby | SQLite (WAL mode) | All access goes through SQLAlchemy, so switching to Postgres means changing the URL and the job-claim query. |
| Redis Streams for jobs | A `jobs` table with leases | A worker claims a job with a 10-second lease. If the worker dies, another worker reclaims the job, and after 3 attempts it is marked dead. The result and the acknowledgement are written in one transaction. |
| Redis Pub/Sub fan-out | The API tails the event log | Any process writes events to `event_log`, and each API process forwards them to its clients. Reconnecting clients get missed events replayed by `seq`. SQLite serialises writes, so `seq` order is commit order. |
| Advisory lock for the scheduler | A lease row in `leases` | Only one scheduler acts at a time, and a standby takes over within 5 seconds. |
| Nginx | uvicorn serves the API and the built client | No rate limiting yet. |

**Not built yet:**
- Pyodide in-browser simulations (practice matches run in the server sandbox instead)
- Block modules calling other modules, and variables or loops in blocks
- The `strategy(state)` agent interface (agents use `strategy(my_history, opp_history)`)
- Three-node deployment, client failover across real nodes (the client already supports `VITE_API_NODES`), Prometheus and Grafana
- Sounds
- The Tier 1 USB boot image

The fair-play internet probe is off by default so development machines aren't flagged. Turn it on with `IC_FAIRPLAY_INTERNET_PROBE=true`.

**Known limits:**
- Each match starts a fresh sandbox process. A 12-team first round (234 matches and about 130 verifications) takes about 25 seconds with 3 workers. Add workers (`--workers`) to speed it up.
- The 2-second match time limit depends on machine load, so a borderline agent could time out on one worker and not on another. Verification would then show a mismatch, and the organiser can re-verify it from the review screen.
