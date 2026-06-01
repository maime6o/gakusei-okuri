"""
In-memory room registry.
Repository-pattern thin abstraction: swap out for a persistent store later
by replacing the functions below without touching main.py.

WARNING: All room data is lost on server restart / Render sleep+wake.
         This is documented in README.md.
"""
from __future__ import annotations
import random
import string
from typing import Optional
from engine.models import GameState


_rooms: dict[str, "Room"] = {}


class Room:
    def __init__(self, code: str, host_name: str, target_mobilization: int = 120) -> None:
        self.code = code
        self.host_name = host_name
        self.target_mobilization = target_mobilization
        self.player_names: list[str] = [host_name]
        self.state: Optional[GameState] = None
        # ws connections: player_id -> list of websocket objects
        self.connections: dict[str, list] = {}

    def add_player(self, name: str) -> bool:
        if len(self.player_names) >= 4:
            return False
        if name in self.player_names:
            return False
        self.player_names.append(name)
        return True

    def is_started(self) -> bool:
        return self.state is not None

    def player_id_for(self, name: str) -> Optional[str]:
        if self.state is None:
            return None
        for p in self.state.players:
            if p.name == name:
                return p.player_id
        return None


# --- Repository functions ---

def generate_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=5))
        if code not in _rooms:
            return code


def create_room(host_name: str, target_mobilization: int = 120) -> Room:
    code = generate_code()
    room = Room(code=code, host_name=host_name, target_mobilization=target_mobilization)
    _rooms[code] = room
    return room


def get_room(code: str) -> Optional[Room]:
    return _rooms.get(code.upper())


def delete_room(code: str) -> None:
    _rooms.pop(code.upper(), None)


def list_rooms() -> list[dict]:
    return [
        {
            "code": r.code,
            "players": r.player_names,
            "started": r.is_started(),
            "target": r.target_mobilization,
        }
        for r in _rooms.values()
    ]
