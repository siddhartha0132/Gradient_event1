"""Request and response models. These define the OpenAPI schema the client is generated from.

All times are UTC epoch seconds.
"""

from pydantic import BaseModel, Field


class TeamOut(BaseModel):
    id: str
    name: str
    country_code: str | None
    eliminated_in: int | None


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    team: TeamOut | None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    user: UserOut


class Country(BaseModel):
    code: str
    name: str
    team_id: str | None
    team_name: str | None


class ClaimRequest(BaseModel):
    code: str


class ClockOut(BaseModel):
    server_time: float


class ClientConfig(BaseModel):
    probe_internet: bool
    probe_url: str


class GameInfo(BaseModel):
    key: str
    name: str
    # "CD": [0, 5] means I cooperate, they defect: I score 0, they score 5
    payoffs: dict[str, list[int]]


class BlockRulesModel(BaseModel):
    max_modules: int = Field(ge=0, le=10)
    max_blocks: int = Field(ge=1, le=200)
    categories: list[str]


class RoundOut(BaseModel):
    id: str
    index: int
    name: str
    game: GameInfo
    turns: int | None = Field(description="None while the turn count is hidden")
    hide_turns: bool
    noise: float
    repetitions: int
    keep_fraction: float
    keep_count: int | None
    block_rules: BlockRulesModel
    status: str
    opens_at: float | None
    closes_at: float | None
    paused_remaining: float | None
    window_open: bool
    matches_total: int
    matches_done: int


class ModuleIn(BaseModel):
    layout: dict = Field(description="Blockly workspace JSON (Blockly.serialization.workspaces.save)")


class AgentIn(BaseModel):
    """A team's agent: hand-written code (defining strategy) plus block modules."""
    hand_code: str = Field(max_length=50_000)
    modules: list[ModuleIn] = Field(default=[], max_length=10)


class CodeError(BaseModel):
    message: str
    line: int | None = Field(description="Line in the hand-written code")
    module: int | None = Field(description="Index of the block module the error is about")
    kind: str = Field(description="blocks: breaks the block rules; code: fails the sandbox checks")


class ModuleOut(BaseModel):
    name: str
    code: str
    blocks: int


class ValidateOut(BaseModel):
    errors: list[CodeError]
    modules: list[ModuleOut | None] = Field(description="One per module sent, None where it did not compile")
    assembled: str
    rules: BlockRulesModel


class TestResult(BaseModel):
    opponent: str
    score: int
    opponent_score: int


class SubmissionOut(BaseModel):
    id: str
    version: int
    module_count: int
    rule_problems: list[str] = Field(default=[], description="Why this version cannot play in the current round")
    status: str
    errors: list[str]
    test_results: list[TestResult]
    code_sha256: str
    created_at: float
    checked_at: float | None


class ModuleDetail(ModuleOut):
    layout: dict


class SubmissionDetail(SubmissionOut):
    hand_code: str
    modules: list[ModuleDetail]
    code: str = Field(description="The assembled code that runs")


class PracticeRequest(AgentIn):
    opponent: str
    game: str = "prisoners_dilemma"
    turns: int = Field(default=50, ge=1, le=500)
    noise: float = Field(default=0.0, ge=0.0, le=0.5)


class PracticeOut(BaseModel):
    score: int
    opponent_score: int
    my_moves: str
    opponent_moves: str
    forfeit: str | None


class BuiltInBot(BaseModel):
    key: str
    description: str


class StandingOut(BaseModel):
    team_id: str
    team_name: str
    country_code: str | None
    total: int
    penalty: int
    wins: int
    losses: int
    draws: int
    avg_per_turn: float
    rank: int | None
    outcome: str
    reason: str | None


class MatchOut(BaseModel):
    id: str
    round_id: str
    team_a: str
    team_b: str
    repetition: int
    status: str
    score_a: int | None
    score_b: int | None
    forfeit_side: int | None
    forfeit_reason: str | None


class ReplayOut(BaseModel):
    match: MatchOut
    game: GameInfo
    moves_a: str
    moves_b: str


class FairplayIn(BaseModel):
    kind: str = Field(max_length=32)
    detail: str = Field(default="", max_length=500)
    client_ts: float


class FairplayBatch(BaseModel):
    events: list[FairplayIn] = Field(max_length=200)


class FairplayOut(BaseModel):
    id: str
    team_id: str
    team_name: str
    kind: str
    detail: str
    client_ts: float
    server_ts: float


class WindowOpen(BaseModel):
    minutes: float = Field(gt=0, le=24 * 60)


class WindowExtend(BaseModel):
    minutes: float = Field(description="Negative values shorten the window")


class PenaltyIn(BaseModel):
    round_id: str
    points: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class PenaltyOut(BaseModel):
    id: str
    team_id: str
    round_id: str
    points: int
    reason: str
    created_at: float


class Mismatch(BaseModel):
    match_id: str
    team_a: str
    team_b: str
    original: list[int]
    recomputed: list[int]


class VerificationReport(BaseModel):
    total: int
    done: int
    mismatches: list[Mismatch]


class ReviewOut(BaseModel):
    round: RoundOut
    standings: list[StandingOut]
    verification: VerificationReport
    failed_matches: list[MatchOut]
    penalties: list[PenaltyOut]
    blockers: list[str]


class AdminTeamRow(BaseModel):
    team: TeamOut
    usernames: list[str]
    latest_submission_id: str | None
    latest_version: int | None
    latest_status: str | None
    accepted_version: int | None
    fairplay_flags: int


class Ok(BaseModel):
    ok: bool = True
