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

    elif effect == "action+1":
        state.actions_remaining += 1
        events.append(f"{member.name}の「{ab.name}」: 行動+1")

    elif effect == "performance_record+2":
        player.performance_record += 2
        events.append(f"{member.name}の「{ab.name}」: 活動実績+2")

    elif effect == "opponents_record-1":
        for p in state.players:
            if p.player_id != player.player_id:
                p.performance_record = max(0, p.performance_record - 1)
        names = ", ".join(p.name for p in state.players if p.player_id != player.player_id)
        events.append(f"{member.name}の「{ab.name}」: {names} の活動実績-1")

    elif effect == "recruit_from_deck":
        import random
        candidates = [c for c in player.deck if c.kind == "member"]
        if candidates:
            picked = random.choice(candidates)
            player.deck.remove(picked)
            if player.bands:
                player.bands[0].members.append(picked)
                events.append(f"{member.name}の「{ab.name}」: デッキから「{picked.name}」をバンドに追加")
            else:
                player.field_members.append(picked)
                events.append(f"{member.name}の「{ab.name}」: デッキから「{picked.name}」をフィールドへ追加")
        else:
            events.append(f"{member.name}の「{ab.name}」: デッキにメンバーなし")

    elif effect == "purge_opponent_males":
        import random as _rnd
        candidates = [
            (p, band, m)
            for p in state.players if p.player_id != player.player_id
            for band in p.bands
            for m in band.members if m.gender == "male"
        ]
        if candidates:
            target_p, target_band, target_m = _rnd.choice(candidates)
            target_band.members.remove(target_m)
            if not target_band.members:
                target_p.bands.remove(target_band)
            events.append(f"{member.name}の「{ab.name}」: {target_m.name} を学生課送り")
        else:
            events.append(f"{member.name}の「{ab.name}」: 対象なし")

    elif effect == "draw_per_opponent_female":
        count = sum(
            1
            for p in state.players if p.player_id != player.player_id
            for band in p.bands
            for m in band.members
            if m.gender == "female"
        )
        if count > 0:
            player.pending_live_draw_bonus += count
            events.append(f"{member.name}の「{ab.name}」: 相手バンドfemale {count}名 → 集客力+{count}")
        else:
            events.append(f"{member.name}の「{ab.name}」: 相手バンドにfemaleなし")

    elif effect.startswith("deal_token:"):
        token_name = effect.split(":", 1)[1]
        from engine.models import CardInstance, CardKind
        for p in state.players:
            token = CardInstance(
                catalog_id=f"token_{token_name}",
                kind=CardKind.MEMBER,
                name=token_name,
                part="Gt",
                gender=None,
                draw=0, music=0, human=0,
            )
            p.hand.append(token)
        events.append(f"{member.name}の「{ab.name}」: 全プレイヤーの手札に「{token_name}」を追加")

    elif effect == "draw2":
        _draw_cards(player, 2)
        events.append(f"{member.name}の「{ab.name}」: 2枚ドロー")

    elif effect == "free_play_member":
        player.free_member_play = True
        events.append(f"{member.name}の「{ab.name}」: 次のメンバーをコスト0でプレイ可能")

    elif effect.startswith("opponents_mobilization-"):
        n = int(effect[len("opponents_mobilization-"):])
        names = []
        for p in state.players:
            if p.player_id != player.player_id:
                p.cumulative_mobilization = max(0, p.cumulative_mobilization - n)
                names.append(p.name)
        events.append(f"{member.name}の「{ab.name}」: {', '.join(names)} の動員数-{n}")

    elif effect.startswith("mobilization+") and effect.endswith("_once"):
        if not member.used_once:
            n = int(effect.split("+")[1].split("_")[0])
            player.cumulative_mobilization += n
            member.used_once = True
            events.append(f"{member.name}の「{ab.name}」: 動員数+{n}")

    elif effect == "rewrite_field_gender_male":
        changed = [m for m in player.field_members if m.gender != "male"]
        for m in changed:
            m.gender = "male"
        if changed:
            names = "、".join(m.name for m in changed)
            events.append(f"{member.name}の「{ab.name}」: {names} を男性に書き換え")
        else:
            events.append(f"{member.name}の「{ab.name}」: フィールドに対象なし")

    elif effect == "steal_support":
        import random as _rnd
        targets = [
            (p, c)
            for p in state.players if p.player_id != player.player_id
            for c in p.hand if c.kind == "support"
        ]
        if targets:
            target_p, stolen = _rnd.choice(targets)
            target_p.hand.remove(stolen)
            player.hand.append(stolen)
            events.append(f"{member.name}の「{ab.name}」: {target_p.name} の手札「{stolen.name}」を奪った！")
        else:
            events.append(f"{member.name}の「{ab.name}」: 相手にサポートカードなし")

    elif effect == "opponents_discard_random":
        import random as _rnd
        discarded = []
        for p in state.players:
            if p.player_id == player.player_id:
                continue
            if p.hand:
                card = _rnd.choice(p.hand)
                p.hand.remove(card)
                p.discard.append(card)
                discarded.append(f"{p.name}:「{card.name}」")
        if discarded:
            events.append(f"{member.name}の「{ab.name}」: {' / '.join(discarded)} を捨てさせた")
        else:
            events.append(f"{member.name}の「{ab.name}」: 相手に手札なし")

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

    elif ab.effect == "search_support":
        import random
        player = state.current_player
        candidates = [c for c in player.deck if c.kind == "support"]
        if candidates:
            picked = random.choice(candidates)
            player.deck.remove(picked)
            player.hand.append(picked)
            events.append(f"{member.name}の「{ab.name}」: デッキから「{picked.name}」を手札に追加")
        else:
            events.append(f"{member.name}の「{ab.name}」: デッキにサポートなし")

    elif ab.effect == "recruit_from_deck":
        import random
        player = state.current_player
        candidates = [c for c in player.deck if c.kind == "member"]
        if candidates:
            picked = random.choice(candidates)
            player.deck.remove(picked)
            target_band = next(
                (b for b in player.bands if any(m.instance_id == member.instance_id for m in b.members)),
                None,
            )
            if target_band:
                target_band.members.append(picked)
                events.append(f"{member.name}の「{ab.name}」: デッキから「{picked.name}」をバンドに追加")
            else:
                player.field_members.append(picked)
                events.append(f"{member.name}の「{ab.name}」: デッキから「{picked.name}」をフィールドへ追加")
        else:
            events.append(f"{member.name}の「{ab.name}」: デッキにメンバーなし")

    return events


class JudgmentMods(object):
    """Accumulated judgment-phase modifications for a single band's live."""

    __slots__ = (
        "human_delta", "severity_delta", "success_draw_bonus", "success_music_bonus",
        "force_failure", "force_success", "self_remove_ids",
    )

    def __init__(self) -> None:
        self.human_delta = 0
        self.severity_delta = 0
        self.success_draw_bonus = 0
        self.success_music_bonus = 0
        self.force_failure = False
        self.force_success = False
        self.self_remove_ids: list[str] = []


def apply_on_judgment(
    member: "CardInstance",
    mods: JudgmentMods,
    incident_name: str = "",
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

    if effect == "force_success":
        mods.force_success = True
        events.append(f"{member.name}の「{ab.name}」: ライブ強制成功！")
        return events

    # 特定の事件でライブ強制失敗＋自身除外  例: "fail_on_留年_self_remove"
    if effect.startswith("fail_on_") and effect.endswith("_self_remove"):
        trigger = effect[len("fail_on_"):-len("_self_remove")]
        if incident_name == trigger:
            mods.force_failure = True
            mods.self_remove_ids.append(member.instance_id)
            events.append(f"{member.name}の「{ab.name}」: 「{incident_name}」発生 → ライブ強制失敗、{member.name}は学生課へ")
        return events

    # human±N or severity±N
    deltas = _parse_delta(effect)
    mods.human_delta += deltas.get("human", 0)
    mods.severity_delta += deltas.get("severity", 0)

    if deltas.get("human", 0) != 0:
        events.append(f"{member.name}の「{ab.name}」: 判定時対応力{deltas['human']:+d}")
    if deltas.get("severity", 0) != 0:
        events.append(f"{member.name}の「{ab.name}」: 判定時事件性{deltas['severity']:+d}")

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
