"""Game initialization — create_game() returns the initial GameState."""
from __future__ import annotations
import random
from pydantic import BaseModel
from typing import Optional

from engine.models import GameState, PlayerState, Phase
from engine.deck_builder import get_builder


class GameConfig(BaseModel):
    target_mobilization: int = 120
    deck_mode: str = "fixed"
    seed: Optional[int] = None
    max_bands: int = 4


def create_game(
    player_names: list[str],
    config: Optional[GameConfig] = None,
) -> GameState:
    if not (2 <= len(player_names) <= 4):
        raise ValueError("プレイヤーは2〜4人です")
    if config is None:
        config = GameConfig()
    if config.target_mobilization not in (80, 120, 160):
        raise ValueError("目標動員数は 80/120/160 から選んでください")

    builder = get_builder(config.deck_mode)
    seed = config.seed

    players: list[PlayerState] = []
    for i, name in enumerate(player_names):
        deck = builder.build_player_deck(seed=(seed + i) if seed is not None else None)
        hand: list = []
        initial_cards = 5 if i == 0 else 6
        for _ in range(initial_cards):
            if deck:
                hand.append(deck.pop())
        pid = f"player_{i}"
        players.append(PlayerState(
            player_id=pid,
            name=name,
            deck=deck,
            hand=hand,
        ))

    incident_deck = builder.build_incident_deck(seed=seed)

    state = GameState(
        phase=Phase.MULLIGAN,
        players=players,
        incident_deck=incident_deck,
        target_mobilization=config.target_mobilization,
        current_player_idx=0,
        actions_remaining=3,
    )
    state.event_log.append(f"ゲーム開始 — 目標動員数:{config.target_mobilization}")
    return state
