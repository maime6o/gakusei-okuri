"""
Action definitions and the central apply_action() pure function.

apply_action(state, player_id, action) -> (new_state, events)

The returned state is always a deep copy — the input is never mutated.
Events are human-readable Japanese strings for the game log.
"""
from __future__ import annotations
import copy
import random
from typing import Literal, Union
from pydantic import BaseModel

from engine.models import (
    GameState, PlayerState, Phase, Band, CardInstance,
    SotaiContext, PendingProcess, CardKind,
    LiveBandResult, LiveMemberSummary,
)
from engine import hooks


class ActionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Action schemas
# ---------------------------------------------------------------------------

class DrawAction(BaseModel):
    type: Literal["draw"] = "draw"


class PlayMemberAction(BaseModel):
    type: Literal["play_member"] = "play_member"
    card_instance_id: str


class FormBandAction(BaseModel):
    type: Literal["form_band"] = "form_band"
    member_instance_ids: list[str]


class DisbandAction(BaseModel):
    type: Literal["disband"] = "disband"
    band_id: str


class UseSupportAction(BaseModel):
    type: Literal["use_support"] = "use_support"
    card_instance_id: str
    target_band_id: str | None = None


class SetAntiAction(BaseModel):
    type: Literal["set_anti"] = "set_anti"
    card_instance_id: str


class RevealAntiAction(BaseModel):
    """Opponent reveals a face-down anti card during the active player's turn."""
    type: Literal["reveal_anti"] = "reveal_anti"
    card_instance_id: str


class EndTurnAction(BaseModel):
    type: Literal["end_turn"] = "end_turn"


class MulliganAction(BaseModel):
    type: Literal["mulligan"] = "mulligan"
    keep: bool = True


class ChooseSotaiAction(BaseModel):
    """Nominator chooses which member to send to gakusei-ka."""
    type: Literal["choose_sotai"] = "choose_sotai"
    member_instance_id: str


AnyAction = Union[
    DrawAction, PlayMemberAction, FormBandAction, DisbandAction,
    UseSupportAction, SetAntiAction, RevealAntiAction,
    EndTurnAction, MulliganAction, ChooseSotaiAction,
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def apply_action(
    state: GameState,
    player_id: str,
    action: AnyAction,
) -> tuple[GameState, list[str]]:
    """Return (new_state, events). Never mutates state."""
    s = state.model_copy(deep=True)
    # Clear stale live results on every action; EndTurnAction/ChooseSotaiAction repopulate.
    s.last_live_results = []
    events: list[str] = []

    if isinstance(action, MulliganAction):
        return _handle_mulligan(s, player_id, action, events)

    if isinstance(action, ChooseSotaiAction):
        return _handle_sotai(s, player_id, action, events)

    if isinstance(action, RevealAntiAction):
        return _handle_reveal_anti(s, player_id, action, events)

    # All other actions require it to be this player's action phase turn
    if s.phase != Phase.ACTION:
        raise ActionError(f"アクションフェーズではありません (現在: {s.phase})")
    _assert_current_player(s, player_id)

    if isinstance(action, DrawAction):
        return _handle_draw(s, player_id, events)
    if isinstance(action, PlayMemberAction):
        return _handle_play_member(s, player_id, action, events)
    if isinstance(action, FormBandAction):
        return _handle_form_band(s, player_id, action, events)
    if isinstance(action, DisbandAction):
        return _handle_disband(s, player_id, action, events)
    if isinstance(action, UseSupportAction):
        return _handle_use_support(s, player_id, action, events)
    if isinstance(action, SetAntiAction):
        return _handle_set_anti(s, player_id, action, events)
    if isinstance(action, EndTurnAction):
        return _handle_end_turn(s, player_id, events)

    raise ActionError(f"不明なアクション: {action}")


# ---------------------------------------------------------------------------
# Mulligan
# ---------------------------------------------------------------------------

def _handle_mulligan(
    s: GameState, player_id: str, action: MulliganAction, events: list[str]
) -> tuple[GameState, list[str]]:
    if s.phase != Phase.MULLIGAN:
        raise ActionError("マリガンフェーズではありません")
    player = _get_player(s, player_id)
    if player.mulligan_done:
        raise ActionError("すでにマリガン済みです")

    if not action.keep:
        # Return hand to deck, reshuffle, draw 5 again
        player.deck.extend(player.hand)
        player.hand.clear()
        random.shuffle(player.deck)
        for _ in range(5):
            if player.deck:
                player.hand.append(player.deck.pop())
        events.append(f"{player.name}: マリガン（引き直し）")
    else:
        events.append(f"{player.name}: マリガンなし（キープ）")

    player.mulligan_done = True

    # Start game if all players done mulligan
    if all(p.mulligan_done for p in s.players):
        s.phase = Phase.ACTION
        s.current_player_idx = 0
        s.actions_remaining = 3
        events.append("全員マリガン完了 — ゲーム開始！")

    return s, events


# ---------------------------------------------------------------------------
# ACTION phase helpers
# ---------------------------------------------------------------------------

def _handle_draw(
    s: GameState, player_id: str, events: list[str]
) -> tuple[GameState, list[str]]:
    _cost_action(s, 1)
    player = _get_player(s, player_id)
    card = _draw_one(player)
    if card:
        events.append(f"{player.name}: 1枚ドロー（{card.name}）")
    else:
        events.append(f"{player.name}: デッキ切れ — ドローできません")
    return s, events


def _handle_play_member(
    s: GameState, player_id: str, action: PlayMemberAction, events: list[str]
) -> tuple[GameState, list[str]]:
    player = _get_player(s, player_id)
    if player.cannot_play_member:
        raise ActionError("このターンはメンバーを場に出せません（アンチ効果）")

    card = _find_in_hand(player, action.card_instance_id)
    if card.kind != CardKind.MEMBER:
        raise ActionError("メンバーカードではありません")
    if card.music > player.performance_record:
        raise ActionError(
            f"活動実績（{player.performance_record}）不足: {card.name}はmusic={card.music}が必要"
        )

    if player.free_member_play:
        player.free_member_play = False
        events.append("助っ人ヘルプ発動: コスト0でプレイ")
    else:
        _cost_action(s, 1)
    player.hand.remove(card)
    player.field_members.append(card)

    # on_play hooks
    ev = hooks.apply_on_play(card, player, s)
    events.extend(ev)
    events.append(f"{player.name}: {card.name}を場に出した")
    return s, events


def _handle_form_band(
    s: GameState, player_id: str, action: FormBandAction, events: list[str]
) -> tuple[GameState, list[str]]:
    player = _get_player(s, player_id)
    if len(player.bands) >= 4:
        raise ActionError("バンド数の上限（4）に達しています")
    if len(action.member_instance_ids) < 3:
        raise ActionError("バンド結成には最低3名のメンバーが必要です")

    members = []
    for mid in action.member_instance_ids:
        m = _find_in_field(player, mid)
        members.append(m)

    _cost_action(s, 1)
    for m in members:
        player.field_members.remove(m)
    band = Band(members=members)
    player.bands.append(band)

    # on_form hooks
    for m in members:
        ev = hooks.apply_on_form(m, s)
        events.extend(ev)

    names = "、".join(m.name for m in members)
    events.append(f"{player.name}: バンド結成 [{names}]")
    return s, events


def _handle_disband(
    s: GameState, player_id: str, action: DisbandAction, events: list[str]
) -> tuple[GameState, list[str]]:
    player = _get_player(s, player_id)
    band = _find_band(player, action.band_id)
    _cost_action(s, 1)

    members_to_return = list(band.members)
    player.bands.remove(band)
    player.field_members.extend(members_to_return)
    events.append(f"{player.name}: バンド解散")
    return s, events


def _handle_use_support(
    s: GameState, player_id: str, action: UseSupportAction, events: list[str]
) -> tuple[GameState, list[str]]:
    player = _get_player(s, player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card.kind != CardKind.SUPPORT:
        raise ActionError("サポートカードではありません")
    if card.phase != "action":
        raise ActionError(f"このサポートカードはアクションフェーズで使用できません（phase={card.phase}）")

    _cost_action(s, 1)
    player.hand.remove(card)
    player.discard.append(card)

    ev = _apply_support_effect_action(card, player, s)
    events.extend(ev)
    events.append(f"{player.name}: サポート「{card.name}」を使用")
    return s, events


def _handle_set_anti(
    s: GameState, player_id: str, action: SetAntiAction, events: list[str]
) -> tuple[GameState, list[str]]:
    player = _get_player(s, player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card.kind != CardKind.ANTI:
        raise ActionError("アンチカードではありません")

    _cost_action(s, 1)
    player.hand.remove(card)
    card.face_down = True
    player.anti_zone.append(card)
    events.append(f"{player.name}: アンチカードを伏せた")
    return s, events


def _handle_reveal_anti(
    s: GameState, player_id: str, action: RevealAntiAction, events: list[str]
) -> tuple[GameState, list[str]]:
    """Opponent reveals an anti card during active player's live/judgment phase."""
    if s.phase not in (Phase.ACTION, Phase.LIVE_PROCESSING):
        raise ActionError("アンチカードを公開できるフェーズではありません")
    revealer = _get_player(s, player_id)
    if revealer.player_id == s.current_player.player_id:
        raise ActionError("自分のターン中はアンチカードを公開できません")

    card = next(
        (c for c in revealer.anti_zone if c.instance_id == action.card_instance_id),
        None,
    )
    if not card:
        raise ActionError("アンチゾーンにそのカードが見つかりません")

    card.face_down = False
    revealer.anti_zone.remove(card)
    revealer.discard.append(card)
    # Effects are applied during live/judgment processing; record it in log
    events.append(f"{revealer.name}: アンチ「{card.name}」を公開")
    return s, events


def _handle_end_turn(
    s: GameState, player_id: str, events: list[str]
) -> tuple[GameState, list[str]]:
    _assert_current_player(s, player_id)
    player = _get_player(s, player_id)
    events.append(f"{player.name}: ターン終了 → ライブフェーズへ")
    s.last_live_results = []
    s.phase = Phase.LIVE_PROCESSING
    s, ev = _process_live_phase(s, events)
    return s, ev


# ---------------------------------------------------------------------------
# Live / Incident / Judgment processing
# ---------------------------------------------------------------------------

def _process_live_phase(
    s: GameState, events: list[str]
) -> tuple[GameState, list[str]]:
    """Process all bands' lives for the current player sequentially."""
    player = s.current_player
    bands_with_live = player.bands[:]

    if not bands_with_live:
        events.append(f"バンドなし — 追いコンフェーズへ")
        return _end_party(s, events)

    for band in bands_with_live:
        s, events = _process_one_band(s, band.band_id, events)
        if s.phase == Phase.SOTAI:
            return s, events

        # アンコール: 最初に成功したバンドがもう一度ライブを行う
        player = s.current_player
        if (player.encore_pending
                and s.last_live_results
                and s.last_live_results[-1].success):
            player.encore_pending = False
            events.append(f"🎵 アンコール発動！{s.last_live_results[-1].band_id[:6]}が再びステージへ！")
            s, events = _process_one_band(s, band.band_id, events)
            if s.phase == Phase.SOTAI:
                return s, events

    return _end_party(s, events)


def _process_one_band(
    s: GameState, band_id: str, events: list[str]
) -> tuple[GameState, list[str]]:
    player = s.current_player
    band = _find_band(player, band_id)

    # Compute base stats
    members = list(band.members)
    base_draw = sum(m.draw for m in members)
    base_music = sum(m.music for m in members)
    base_human = sum(m.human for m in members)

    # Apply static (on_band_stat) hooks
    for m in members:
        base_draw, base_music, base_human = hooks.apply_on_band_stat(
            m, base_draw, base_music, base_human
        )

    # Apply live-phase support/anti effects (from revealed cards in active turn)
    live_draw, live_music, live_human = _apply_live_effects(
        s, player, base_draw, base_music, base_human, events
    )

    band.live_draw = max(0, live_draw)
    band.live_music = max(0, live_music)
    band.live_human = max(0, live_human)
    band.did_live_this_turn = True

    events.append(
        f"ライブ [{' '.join(m.name for m in members)}] "
        f"draw={band.live_draw} music={band.live_music} 対応力={band.live_human}"
    )

    # Incident check
    incident = _draw_incident(s)
    if incident is None:
        events.append("事件山札が空 — 平和な一日（severity=0として処理）")
        severity = 0
        incident_name = "（なし）"
    else:
        severity = incident.severity or 0
        incident_name = incident.name
        events.append(f"事件: 「{incident_name}」(severity={severity})")

    # Judgment: collect mods
    mods = hooks.JudgmentMods()
    for m in members:
        ev = hooks.apply_on_judgment(m, mods)
        events.extend(ev)

    # Apply judgment-phase anti effects
    for opponent in s.players:
        if opponent.player_id == player.player_id:
            continue
        for anti in opponent.anti_zone:
            if not anti.face_down and anti.phase == "judgment":
                delta = _parse_anti_effect(anti.effect or "")
                mods.human_delta += delta.get("human", 0)
                mods.severity_delta += delta.get("severity", 0)
                events.append(f"アンチ「{anti.name}」発動")

    effective_human = max(0, band.live_human + mods.human_delta)
    effective_severity = max(0, severity + mods.severity_delta - player.pending_severity_reduction)
    if player.pending_severity_reduction > 0:
        events.append(f"顧問の口添え: 事件性-{player.pending_severity_reduction}")
    num_bands = len(player.bands)
    multiplier = 1.0  # 乗算廃止、バンドごとの対応力のみで判定
    judgment_value = effective_human

    events.append(
        f"判定: 対応力({judgment_value}) vs 事件性={effective_severity} "
        f"{'→ 成功' if judgment_value >= effective_severity else '→ 事件発生'}"
    )

    live_success = (judgment_value >= effective_severity)
    raw_draw  = band.live_draw
    raw_music = band.live_music
    mob_gain = (raw_draw  + mods.success_draw_bonus)  if live_success else 0
    mus_gain = (raw_music + mods.success_music_bonus) if live_success else 0

    s.last_live_results.append(LiveBandResult(
        band_id=band_id,
        members=[
            LiveMemberSummary(
                instance_id=m.instance_id,
                name=m.name,
                kind=m.kind.value,
                part=m.part,
                draw=m.draw,
                music=m.music,
                human=m.human,
            )
            for m in members
        ],
        draw_total=raw_draw,
        music_total=raw_music,
        human_total=band.live_human,
        judgment_value=judgment_value,
        multiplier=multiplier,
        num_bands=num_bands,
        incident_name=incident_name,
        incident_severity=effective_severity,
        success=live_success,
        mobilization_gain=mob_gain,
        music_gain=mus_gain,
    ))

    if not live_success:
        events.append(f"⚡ 事件発生！「{incident_name}」— メンバー1名が学生課送りに")
        band.live_draw = 0
        band.live_music = 0

        nominator_idx = s.next_player_idx(s.current_player_idx)
        nominator = s.players[nominator_idx]

        s.sotai_context = SotaiContext(
            victim_player_id=player.player_id,
            band_id=band_id,
            nominator_player_id=nominator.player_id,
            incident_name=incident_name,
            severity=effective_severity,
            judgment_value=judgment_value,
        )
        s.phase = Phase.SOTAI
        remaining = [
            b.band_id for b in player.bands
            if b.band_id != band_id and not b.did_live_this_turn
        ]
        s.pending_band_processes = [
            PendingProcess(player_id=player.player_id, band_id=bid)
            for bid in remaining
        ]
        return s, events

    # Live success
    player.cumulative_mobilization += mob_gain
    player.music_score += mus_gain
    player.performance_record += 1
    events.append(
        f"✅ ライブ成功！ 動員+{mob_gain} 音楽性+{mus_gain} "
        f"活動実績→{player.performance_record}"
    )

    if player.cumulative_mobilization >= s.target_mobilization:
        s.winner_id = player.player_id
        s.phase = Phase.GAME_OVER
        events.append(f"🎉 {player.name} が目標動員数に到達！勝利！")
        return s, events

    return s, events


def _handle_sotai(
    s: GameState, player_id: str, action: ChooseSotaiAction, events: list[str]
) -> tuple[GameState, list[str]]:
    if s.phase != Phase.SOTAI:
        raise ActionError("学生課送りフェーズではありません")
    ctx = s.sotai_context
    if ctx is None:
        raise ActionError("学生課送りコンテキストがありません")
    if player_id != ctx.nominator_player_id:
        raise ActionError("あなたには指名権がありません")

    victim = _get_player(s, ctx.victim_player_id)
    band = _find_band(victim, ctx.band_id)

    target = next(
        (m for m in band.members if m.instance_id == action.member_instance_id), None
    )
    if target is None:
        raise ActionError("そのメンバーはこのバンドにいません")
    # id22「影の薄いギター」は指名対象外
    if target.ability and target.ability.hook == "on_sotai" and "指名対象に選べない" in target.ability.effect:
        raise ActionError(f"{target.name}は「{target.ability.name}」により指名対象に選べません")

    # Remove from band and game
    band.members.remove(target)
    # If band now has fewer than 1 member, disband
    if len(band.members) < 1:
        victim.bands.remove(band)

    nominator = _get_player(s, ctx.nominator_player_id)
    events.append(f"学生課送り: {victim.name}の「{target.name}」が除外（指名: {nominator.name}）")
    s.sotai_context = None

    # Resume pending bands
    pending = s.pending_band_processes[:]
    s.pending_band_processes = []
    s.last_live_results = []
    s.phase = Phase.LIVE_PROCESSING

    for pp in pending:
        s, events = _process_one_band(s, pp.band_id, events)
        if s.phase == Phase.SOTAI:
            return s, events

    return _end_party(s, events)


def _end_party(
    s: GameState, events: list[str]
) -> tuple[GameState, list[str]]:
    """Check win, advance to next player."""
    player = s.current_player

    # Final win check (in case last band succeeded and we re-enter)
    if s.phase == Phase.GAME_OVER:
        return s, events

    for p in s.players:
        if p.cumulative_mobilization >= s.target_mobilization:
            s.winner_id = p.player_id
            s.phase = Phase.GAME_OVER
            events.append(f"🎉 {p.name} が目標動員数 {s.target_mobilization} に到達！勝利！")
            return s, events

    # Reset per-turn flags
    player.cannot_play_member = False
    player.free_member_play = False
    player.pending_live_draw_bonus = 0
    player.pending_live_music_bonus = 0
    player.pending_severity_reduction = 0
    player.encore_pending = False
    for band in player.bands:
        band.did_live_this_turn = False
        band.live_draw = 0
        band.live_music = 0
        band.live_human = 0

    # Advance turn
    s.current_player_idx = s.next_player_idx()
    next_player = s.current_player
    s.actions_remaining = 3
    s.phase = Phase.ACTION

    # Apply cannot_play_member from pending anti effects
    # (「部室の鍵がない」sets this flag; cleared above for the player who just had their turn)

    # on_turn_start hooks (passive – M4; skip for now with log)
    for m in next_player.field_members:
        if m.ability and m.ability.hook == "on_turn_start":
            import logging
            logging.getLogger(__name__).info(
                "未実装アビリティ: %s (%s) [%s]", m.ability.name, m.ability.type, m.name
            )

    events.append(f"--- {next_player.name} のターン開始 (行動:{s.actions_remaining}) ---")
    return s, events


# ---------------------------------------------------------------------------
# Support effects (action-phase only for now)
# ---------------------------------------------------------------------------

def _apply_support_effect_action(
    card: CardInstance, player: "PlayerState", s: "GameState"
) -> list[str]:
    events: list[str] = []
    effect = card.effect or ""
    if effect == "draw2":
        _draw_cards_player(player, 2)
        events.append(f"「{card.name}」: 2枚ドロー")
    elif effect == "redraw_hand":
        count = len(player.hand)
        player.discard.extend(player.hand)
        player.hand.clear()
        _draw_cards_player(player, count)
        events.append(f"「{card.name}」: 手札{count}枚を引き直し")
    elif effect == "free_play_member":
        player.free_member_play = True
        events.append(f"「{card.name}」: 次のメンバーをコスト0でプレイ可能")
    elif effect == "music+3":
        player.pending_live_music_bonus += 3
        events.append(f"「{card.name}」: このターン音楽性+3")
    elif effect == "draw+3":
        player.pending_live_draw_bonus += 3
        events.append(f"「{card.name}」: このターン集客力+3")
    elif effect == "draw+2":
        player.pending_live_draw_bonus += 2
        events.append(f"「{card.name}」: このターン集客力+2")
    elif effect == "severity-2":
        player.pending_severity_reduction += 2
        events.append(f"「{card.name}」: このターン事件性-2")
    elif effect == "encore":
        player.encore_pending = True
        events.append(f"「{card.name}」: 最初に成功したバンドがアンコールで追加ライブ！")
    return events


# ---------------------------------------------------------------------------
# Live-phase effects from support/anti cards
# ---------------------------------------------------------------------------

def _apply_live_effects(
    s: "GameState",
    player: "PlayerState",
    draw: int, music: int, human: int,
    events: list[str],
) -> tuple[int, int, int]:
    """Apply support pending bonuses and revealed anti effects to band stats."""
    if player.pending_live_draw_bonus:
        draw += player.pending_live_draw_bonus
        events.append(f"サポート: 集客力+{player.pending_live_draw_bonus}")
    if player.pending_live_music_bonus:
        music += player.pending_live_music_bonus
        events.append(f"サポート: 音楽性+{player.pending_live_music_bonus}")
    for opponent in s.players:
        if opponent.player_id == player.player_id:
            continue
        for anti in opponent.anti_zone:
            if not anti.face_down and anti.phase == "live":
                delta = _parse_anti_effect(anti.effect or "")
                draw += delta.get("draw", 0)
                music += delta.get("music", 0)
                events.append(f"アンチ「{anti.name}」発動: draw{delta.get('draw',0):+d} music{delta.get('music',0):+d}")
    return draw, music, human


def _parse_anti_effect(effect: str) -> dict[str, int]:
    import re
    result: dict[str, int] = {}
    for m in re.finditer(r"(draw|music|human|severity)([+-]\d+)", effect):
        result[m.group(1)] = int(m.group(2))
    return result


# ---------------------------------------------------------------------------
# Incident deck
# ---------------------------------------------------------------------------

def _draw_incident(s: "GameState") -> CardInstance | None:
    if not s.incident_deck:
        if not s.incident_discard:
            return None
        s.incident_deck = s.incident_discard[:]
        s.incident_discard.clear()
        random.shuffle(s.incident_deck)
    card = s.incident_deck.pop()
    s.incident_discard.append(card)
    return card


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_current_player(s: GameState, player_id: str) -> None:
    if s.current_player.player_id != player_id:
        raise ActionError("あなたの手番ではありません")


def _get_player(s: GameState, player_id: str) -> PlayerState:
    p = s.player_by_id(player_id)
    if p is None:
        raise ActionError(f"プレイヤー {player_id} が見つかりません")
    return p


def _find_in_hand(player: PlayerState, instance_id: str) -> CardInstance:
    card = next((c for c in player.hand if c.instance_id == instance_id), None)
    if card is None:
        raise ActionError(f"手札にカード {instance_id} が見つかりません")
    return card


def _find_in_field(player: PlayerState, instance_id: str) -> CardInstance:
    card = next((c for c in player.field_members if c.instance_id == instance_id), None)
    if card is None:
        raise ActionError(f"場に{instance_id}のメンバーが見つかりません（バンドに入っていませんか？）")
    return card


def _find_band(player: PlayerState, band_id: str) -> Band:
    band = next((b for b in player.bands if b.band_id == band_id), None)
    if band is None:
        raise ActionError(f"バンド {band_id} が見つかりません")
    return band


def _collect_member_instances(player: PlayerState, band: Band) -> list[CardInstance]:
    return list(band.members)


def _draw_one(player: PlayerState) -> CardInstance | None:
    if not player.deck:
        if not player.discard:
            return None
        player.deck = player.discard[:]
        player.discard.clear()
        random.shuffle(player.deck)
    if player.deck:
        card = player.deck.pop()
        player.hand.append(card)
        return card
    return None


def _draw_cards_player(player: PlayerState, n: int) -> None:
    for _ in range(n):
        _draw_one(player)


def _cost_action(s: GameState, cost: int = 1) -> None:
    if s.actions_remaining < cost:
        raise ActionError(f"行動ポイントが足りません（残り{s.actions_remaining}）")
    s.actions_remaining -= cost
