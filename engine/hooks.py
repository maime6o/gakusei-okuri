"""
Hook registry for card abilities.

MVP implements: static (on_band_stat), on_play, judgment (on_judgment), on_form.
Unimplemented types log a warning and are no-ops.

Implemented ability effect codes (see catalog.json):
  on_band_stat / static:
    draw+N, music+N, human+N, draw-N, music-N, human-N
    Compound: "A_B" e.g. "draw+2_human+2"

  on_play / on_play:
    "draw_card"            - player draws 1 card
    "mobilization+N_once"  - add N to cumulative mobilization (once per game)

  on_form / on_play:
    "action+1"             - add 1 to actions_remaining

  on_judgment / judgment:
    "human+N"  "human-N"   - modify band human before judgment
    "severity+N" "severity-N" - modify incident severity
    "success_draw+N"       - on success, add N to band draw (extra mobilization)
    "success_music+N"      - on success, add N to band music (extra music score)
    "success_draw+N_once"  - same but only once per game per card instance

  M4 / unimplemented: conditional, activated, special, passive
"""
from __future__ import annotations
import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.models import CardInstance, PlayerState, GameState

logger = logging.getLogger(__name__)

_UNIMPLEMENTED_TYPES = {"conditional", "activated", "special", "passive"}


def _parse_delta(code: str) -> dict[str, int]:
    """Parse 'draw+2_human-1' into {'draw': 2, 'human': -1}."""
    result: dict[str, int] = {}
    for part in code.split("_"):
        m = re.fullmatch(r"(draw|music|human|severity)([+-]\d+)", part)
        if m:
            result[m.group(1)] = int(m.group(2))
    return result


def apply_on_band_stat(
    member: "CardInstance",
    band_draw: int,
    band_music: int,
    band_human: int,
) -> tuple[int, int, int]:
    """Return (draw, music, human) after applying static ability."""
    if not member.ability:
        return band_draw, band_music, band_human
    ab = member.ability
    if ab.type in _UNIMPLEMENTED_TYPES:
        logger.info("未実装アビリティ: %s (%s) [%s]", ab.name, ab.type, member.name)
        return band_draw, band_music, band_human
    if ab.hook not in ("on_band_stat",):
        return band_draw, band_music, band_human

    deltas = _parse_delta(ab.effect)
    band_draw += deltas.get("draw", 0)
    band_music += deltas.get("music", 0)
    band_human += deltas.get("human", 0)
    return band_draw, band_music, band_human


def apply_on_play(
    member: "CardInstance",
    player: "PlayerState",
    state: "GameState",
) -> list[str]:
    """Side-effect: mutates player/state. Returns event log entries."""
    events: list[str] = []
    if not member.ability:
        return events
    ab = member.ability
    if ab.type in _UNIMPLEMENTED_TYPES:
        logger.info("未実装アビリティ: %s (%s) [%s]", ab.name, ab.type, member.name)
        return events
    if ab.hook not in ("on_play",):
        return events

    effect = ab.effect

    if effect == "draw_card":
        _draw_cards(player, 1)
        events.append(f"{member.name}の「{ab.name}」: 1枚ドロー")

    elif effect.startswith("mobilization+") and effect.endswith("_once"):
        if not member.used_once:
            n = int(effect.split("+")[1].split("_")[0])
            player.cumulative_mobilization += n
            member.used_once = True
            events.append(f"{member.name}の「{ab.name}」: 動員数+{n}")

    return events


def apply_on_form(
    member: "CardInstance",
    state: "GameState",
) -> list[str]:
    """Called when a band containing this member is formed."""
    events: list[str] = []
    if not member.ability:
        return events
    ab = member.ability
    if ab.type in _UNIMPLEMENTED_TYPES:
        logger.info("未実装アビリティ: %s (%s) [%s]", ab.name, ab.type, member.name)
        return events
    if ab.hook not in ("on_form",):
        return events

    if ab.effect == "action+1":
        state.actions_remaining += 1
        events.append(f"{member.name}の「{ab.name}」: 行動+1")

    return events


class JudgmentMods(object):
    """Accumulated judgment-phase modifications for a single band's live."""

    __slots__ = ("human_delta", "severity_delta", "success_draw_bonus", "success_music_bonus")

    def __init__(self) -> None:
        self.human_delta = 0
        self.severity_delta = 0
        self.success_draw_bonus = 0
        self.success_music_bonus = 0


def apply_on_judgment(
    member: "CardInstance",
    mods: JudgmentMods,
) -> list[str]:
    """Accumulate judgment mods from a member's ability. Mutates mods in place."""
    events: list[str] = []
    if not member.ability:
        return events
    ab = member.ability
    if ab.type in _UNIMPLEMENTED_TYPES:
        logger.info("未実装アビリティ: %s (%s) [%s]", ab.name, ab.type, member.name)
        return events
    if ab.hook not in ("on_judgment",):
        return events

    effect = ab.effect

    # human±N or severity±N
    deltas = _parse_delta(effect)
    mods.human_delta += deltas.get("human", 0)
    mods.severity_delta += deltas.get("severity", 0)

    # success bonuses
    if "success_draw+" in effect:
        once = effect.endswith("_once")
        if once and member.used_once:
            return events
        n_str = effect.split("success_draw+")[1].split("_")[0]
        mods.success_draw_bonus += int(n_str)
        if once:
            member.used_once = True
        events.append(f"{member.name}の「{ab.name}」: ライブ成功時に動員+{n_str}")

    if "success_music+" in effect:
        n_str = effect.split("success_music+")[1].split("_")[0]
        mods.success_music_bonus += int(n_str)
        events.append(f"{member.name}の「{ab.name}」: ライブ成功時に音楽性+{n_str}")

    # severity+N for「炎上系シンガー」- always apply (not success-conditional)
    if "severity+" in effect and "success" not in effect:
        events.append(f"{member.name}の「{ab.name}」: 判定時severity+{deltas.get('severity',0)}")

    return events


# --- helpers ---

def _draw_cards(player: "PlayerState", n: int) -> None:
    for _ in range(n):
        if not player.deck:
            player.deck = player.discard[:]
            player.discard.clear()
            import random
            random.shuffle(player.deck)
        if player.deck:
            player.hand.append(player.deck.pop())
