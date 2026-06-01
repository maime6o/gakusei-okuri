from __future__ import annotations
from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel, Field
import uuid


def _uid() -> str:
    return str(uuid.uuid4())[:8]


class CardKind(str, Enum):
    MEMBER = "member"
    SUPPORT = "support"
    ANTI = "anti"
    INCIDENT = "incident"


class Phase(str, Enum):
    LOBBY = "lobby"
    MULLIGAN = "mulligan"
    ACTION = "action"
    LIVE_PROCESSING = "live_processing"
    SOTAI = "sotai"
    GAME_OVER = "game_over"


class Ability(BaseModel):
    name: str
    hook: str
    type: str
    effect: str
    note: Optional[str] = None


class CatalogCard(BaseModel):
    id: Optional[int] = None
    name: str
    kind: CardKind
    part: Optional[str] = None
    draw: int = 0
    music: int = 0
    human: int = 0
    ability: Optional[Ability] = None
    phase: Optional[str] = None
    effect: Optional[str] = None
    severity: Optional[int] = None
    description: Optional[str] = None
    copies: int = 1
    weight: float = 1.0


class LiveMemberSummary(BaseModel):
    instance_id: str
    name: str
    kind: str = "member"
    part: Optional[str] = None
    draw: int = 0
    music: int = 0
    human: int = 0


class LiveBandResult(BaseModel):
    band_id: str
    members: List["LiveMemberSummary"]
    draw_total: int
    music_total: int
    human_total: int
    judgment_value: int
    multiplier: float
    num_bands: int
    incident_name: str
    incident_severity: int
    success: bool
    mobilization_gain: int = 0
    music_gain: int = 0


class CardInstance(BaseModel):
    instance_id: str = Field(default_factory=_uid)
    catalog_id: str
    kind: CardKind
    name: str
    part: Optional[str] = None
    draw: int = 0
    music: int = 0
    human: int = 0
    ability: Optional[Ability] = None
    phase: Optional[str] = None
    effect: Optional[str] = None
    severity: Optional[int] = None
    description: Optional[str] = None
    face_down: bool = False
    used_once: bool = False


class Band(BaseModel):
    band_id: str = Field(default_factory=_uid)
    members: List["CardInstance"] = Field(default_factory=list)
    live_draw: int = 0
    live_music: int = 0
    live_human: int = 0
    did_live_this_turn: bool = False

    @property
    def member_ids(self) -> List[str]:
        return [m.instance_id for m in self.members]


class SotaiContext(BaseModel):
    victim_player_id: str
    band_id: str
    nominator_player_id: str
    incident_name: str
    severity: int
    judgment_value: int


class PendingProcess(BaseModel):
    player_id: str
    band_id: str
    base_draw: int = 0
    base_music: int = 0
    base_human: int = 0


class PlayerState(BaseModel):
    player_id: str
    name: str
    deck: List[CardInstance] = Field(default_factory=list)
    hand: List[CardInstance] = Field(default_factory=list)
    field_members: List[CardInstance] = Field(default_factory=list)
    bands: List[Band] = Field(default_factory=list)
    anti_zone: List[CardInstance] = Field(default_factory=list)
    discard: List[CardInstance] = Field(default_factory=list)
    cumulative_mobilization: int = 0
    music_score: int = 0
    performance_record: int = 4
    mulligan_done: bool = False
    cannot_play_member: bool = False


class GameState(BaseModel):
    game_id: str = Field(default_factory=_uid)
    phase: Phase = Phase.LOBBY
    players: List[PlayerState] = Field(default_factory=list)
    current_player_idx: int = 0
    actions_remaining: int = 3
    incident_deck: List[CardInstance] = Field(default_factory=list)
    incident_discard: List[CardInstance] = Field(default_factory=list)
    target_mobilization: int = 120
    winner_id: Optional[str] = None
    event_log: List[str] = Field(default_factory=list)
    sotai_context: Optional[SotaiContext] = None
    pending_band_processes: List[PendingProcess] = Field(default_factory=list)
    last_live_results: List[LiveBandResult] = Field(default_factory=list)

    @property
    def current_player(self) -> PlayerState:
        return self.players[self.current_player_idx]

    def player_by_id(self, player_id: str) -> Optional[PlayerState]:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    def next_player_idx(self, from_idx: Optional[int] = None) -> int:
        base = from_idx if from_idx is not None else self.current_player_idx
        return (base + 1) % len(self.players)
