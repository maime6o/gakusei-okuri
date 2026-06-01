from __future__ import annotations
import random
from abc import ABC, abstractmethod
from typing import List, Optional
from engine.models import CardInstance, CardKind
from engine import catalog as cat


class DeckBuilder(ABC):
    @abstractmethod
    def build_player_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        ...

    @abstractmethod
    def build_incident_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        ...


class FixedDeckBuilder(DeckBuilder):
    """Deterministic deck from catalog copies field. Same deck for all players."""

    def build_player_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        cards: List[CardInstance] = []
        for c in cat.all_members():
            for _ in range(c.copies):
                cards.append(cat.instance_from_catalog(c))
        for c in cat.all_supports():
            for _ in range(c.copies):
                cards.append(cat.instance_from_catalog(c))
        for c in cat.all_antis():
            for _ in range(c.copies):
                cards.append(cat.instance_from_catalog(c))
        rng = random.Random(seed)
        rng.shuffle(cards)
        return cards

    def build_incident_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        cards: List[CardInstance] = []
        for c in cat.all_incidents():
            for _ in range(c.copies):
                cards.append(cat.instance_from_catalog(c))
        rng = random.Random(seed)
        rng.shuffle(cards)
        return cards


class RandomDeckBuilder(DeckBuilder):
    """Future: weighted random 50-card deck from full pool. Interface only for now."""

    MIN_MEMBERS = 35
    MAX_SUPPORT_ANTI = 15
    MAX_SAME_NAME = 3
    MIN_LOW_MUSIC = 8  # music<=4 members to avoid early-game stall

    def build_player_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        # TODO(M4): implement weighted random draw respecting constraints
        raise NotImplementedError("RandomDeckBuilder not yet implemented; use FixedDeckBuilder")

    def build_incident_deck(self, seed: Optional[int] = None) -> List[CardInstance]:
        # TODO(M4): same as fixed for now
        return FixedDeckBuilder().build_incident_deck(seed)


def get_builder(mode: str = "fixed") -> DeckBuilder:
    if mode == "random":
        return RandomDeckBuilder()
    return FixedDeckBuilder()
