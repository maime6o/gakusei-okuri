"""
M1 engine unit tests.
Covers: mulligan, draw, play_member, form_band, live success/incident,
        win condition, performance_record gating, judgment formula.
"""
import pytest
import random
from engine.game import create_game, GameConfig
from engine.actions import (
    apply_action, ActionError,
    MulliganAction, DrawAction, PlayMemberAction, FormBandAction,
    EndTurnAction, ChooseSotaiAction, DisbandAction, UseSupportAction, TaibanAction,
)
from engine.models import Phase, CardKind, CardInstance
from engine.deck_builder import FixedDeckBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _game_2p(target: int = 120, seed: int = 42) -> object:
    return create_game(["Alice", "Bob"], GameConfig(target_mobilization=target, seed=seed))


def _skip_mulligan(state):
    """Both players keep their hands."""
    for p in state.players:
        state, _ = apply_action(state, p.player_id, MulliganAction(keep=True))
    return state


def _find_member_in_hand(player, music_max: int = 99):
    for c in player.hand:
        if c.kind == CardKind.MEMBER and c.music <= music_max:
            return c
    return None


def _put_members_on_field(state, player_id: str, count: int):
    """Draw and play 'count' members (using actions freely)."""
    player = state.player_by_id(player_id)
    placed = 0
    # Give unlimited actions for setup
    state.actions_remaining = 99
    for c in list(player.hand):
        if placed >= count:
            break
        if c.kind == CardKind.MEMBER and c.music <= player.performance_record:
            state, _ = apply_action(state, player_id, PlayMemberAction(card_instance_id=c.instance_id))
            placed += 1
    return state, placed


# ---------------------------------------------------------------------------
# Deck builder
# ---------------------------------------------------------------------------

class TestDeckBuilder:
    def test_fixed_deck_50_cards(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck(seed=0)
        # 52 members + 17 supports + 4 antis = 73
        assert len(deck) == 73, f"Expected 73 cards, got {len(deck)}"

    def test_fixed_deck_has_members(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck()
        members = [c for c in deck if c.kind == CardKind.MEMBER]
        assert len(members) == 52

    def test_fixed_deck_has_supports(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck()
        supports = [c for c in deck if c.kind == CardKind.SUPPORT]
        assert len(supports) == 17

    def test_fixed_deck_has_antis(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck()
        antis = [c for c in deck if c.kind == CardKind.ANTI]
        assert len(antis) == 4

    def test_incident_deck_about_30(self):
        builder = FixedDeckBuilder()
        deck = builder.build_incident_deck()
        assert 25 <= len(deck) <= 35

    def test_fixed_deck_different_seeds_same_cards(self):
        b = FixedDeckBuilder()
        d1 = b.build_player_deck(seed=1)
        d2 = b.build_player_deck(seed=2)
        names1 = sorted(c.name for c in d1)
        names2 = sorted(c.name for c in d2)
        assert names1 == names2  # same cards, different order


# ---------------------------------------------------------------------------
# Game creation & phase
# ---------------------------------------------------------------------------

class TestGameCreation:
    def test_phase_is_mulligan(self):
        state = _game_2p()
        assert state.phase == Phase.MULLIGAN

    def test_initial_hand_sizes(self):
        """Player 1 gets 5 cards (first-player disadvantage); others get 6."""
        state = _game_2p()
        assert len(state.players[0].hand) == 5
        assert len(state.players[1].hand) == 6

    def test_player_count_2(self):
        state = _game_2p()
        assert len(state.players) == 2

    def test_invalid_player_count(self):
        with pytest.raises(ValueError):
            create_game(["Solo"])

    def test_invalid_target(self):
        with pytest.raises(ValueError):
            create_game(["A", "B"], GameConfig(target_mobilization=100))

    def test_initial_performance_record_10(self):
        state = _game_2p()
        for p in state.players:
            assert p.performance_record == 10


# ---------------------------------------------------------------------------
# Mulligan
# ---------------------------------------------------------------------------

class TestMulligan:
    def test_keep_does_not_change_hand(self):
        state = _game_2p(seed=1)
        alice = state.players[0]
        hand_before = [c.instance_id for c in alice.hand]
        state, _ = apply_action(state, alice.player_id, MulliganAction(keep=True))
        assert [c.instance_id for c in alice.hand] == hand_before

    def test_redraw_changes_hand(self):
        state = _game_2p(seed=1)
        alice = state.players[0]
        hand_before = {c.instance_id for c in alice.hand}
        state, _ = apply_action(state, alice.player_id, MulliganAction(keep=False))
        hand_after = {c.instance_id for c in alice.hand}
        # Not guaranteed different by seed but should still be 5 cards
        assert len(alice.hand) == 5

    def test_cannot_mulligan_twice(self):
        state = _game_2p()
        alice = state.players[0]
        state, _ = apply_action(state, alice.player_id, MulliganAction(keep=True))
        with pytest.raises(ActionError):
            apply_action(state, alice.player_id, MulliganAction(keep=True))

    def test_game_starts_after_all_mulligan(self):
        state = _game_2p()
        assert state.phase == Phase.MULLIGAN
        state = _skip_mulligan(state)
        assert state.phase == Phase.ACTION

    def test_cannot_draw_during_mulligan(self):
        state = _game_2p()
        alice = state.players[0]
        with pytest.raises(ActionError):
            apply_action(state, alice.player_id, DrawAction())


# ---------------------------------------------------------------------------
# Action phase
# ---------------------------------------------------------------------------

class TestActionPhase:
    def test_draw_costs_1_action(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        before = state.actions_remaining
        state, _ = apply_action(state, alice.player_id, DrawAction())
        assert state.actions_remaining == before - 1

    def test_draw_adds_card_to_hand(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        hand_before = len(alice.hand)
        state, _ = apply_action(state, alice.player_id, DrawAction())
        assert len(state.players[0].hand) == hand_before + 1

    def test_wrong_player_cannot_act(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        bob = state.players[1]
        with pytest.raises(ActionError):
            apply_action(state, bob.player_id, DrawAction())

    def test_out_of_actions_raises(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 0
        with pytest.raises(ActionError):
            apply_action(state, alice.player_id, DrawAction())

    def test_play_member_blocked_by_performance_record(self):
        """Cannot play a member whose music > performance_record."""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        # Force a high-music card into hand (Ichiro has music=299, always > default 10)
        from engine.catalog import all_members, instance_from_catalog
        high_music = next(c for c in all_members() if c.music > 10)
        card = instance_from_catalog(high_music)
        alice.hand.append(card)
        with pytest.raises(ActionError, match="活動実績以上のバンドメンバーです"):
            apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=card.instance_id))

    def test_play_member_blocked_when_record_1_music_2(self):
        """活動実績1のとき、音楽性2のメンバーは出せない。活動実績はマイナスにならない。"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        alice.performance_record = 1
        from engine.catalog import all_members, instance_from_catalog
        music2 = next(c for c in all_members() if c.music == 2)
        card = instance_from_catalog(music2)
        alice.hand.append(card)
        with pytest.raises(ActionError, match="活動実績以上のバンドメンバーです"):
            apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=card.instance_id))
        assert alice.performance_record == 1, "活動実績はマイナスにならない"

    def test_play_member_within_performance_record(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        member = _find_member_in_hand(alice, music_max=4)
        assert member is not None, "No eligible member in hand"
        state, _ = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=member.instance_id))
        assert any(m.instance_id == member.instance_id for m in state.players[0].field_members)

    def test_form_band_needs_3_members(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        # Place 2 members
        placed = 0
        for c in list(alice.hand):
            if placed >= 2:
                break
            if c.kind == CardKind.MEMBER and c.music <= alice.performance_record:
                state, _ = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=c.instance_id))
                placed += 1
        alice_now = state.players[0]
        ids = [m.instance_id for m in alice_now.field_members[:2]]
        with pytest.raises(ActionError, match="3名"):
            apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))

    def test_form_band_success(self):
        state = _game_2p(seed=0)
        state = _skip_mulligan(state)
        state.actions_remaining = 99
        # Give alice many low-music members
        _inject_members(state.players[0], count=3, music=2)
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        assert len(state.players[0].bands) == 1
        assert len(state.players[0].bands[0].member_ids) == 3


# ---------------------------------------------------------------------------
# Live / Judgment logic
# ---------------------------------------------------------------------------

class TestLivePhase:
    def test_live_success_adds_mobilization(self):
        """対応力(12×3=36) >= severity=8 → ライブ成功 → 動員数加算"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=5, music=2, human=12)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        alice = state.players[0]
        mob_before = alice.cumulative_mobilization
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        alice = state.players[0]
        assert alice.cumulative_mobilization > mob_before
        assert any("ライブ成功" in e for e in events)

    def test_live_success_increases_performance_record(self):
        """対応力(12×3=36) >= severity=8 → 活動実績+1"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=3, music=2, human=12)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        pr_before = state.players[0].performance_record
        state, _ = apply_action(state, state.players[0].player_id, EndTurnAction())
        assert state.players[0].performance_record == pr_before + 1

    def test_incident_triggers_auto_sotai(self):
        """対応力が低い(2×3=6) vs severity=8 → 事件発生 → 自動でメンバー除外 → 次プレイヤーへ"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=2, music=2, human=2)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        assert state.phase != Phase.SOTAI
        assert any("学生課送り" in e for e in events)

    def test_incident_auto_removes_one_member(self):
        """事件発生時、自動でバンドからメンバーが1名除外される"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=2, music=2, human=2)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        # バンドが残っていれば2名、消滅していれば0名
        alice_now = state.players[0]
        total_band_members = sum(len(b.members) for b in alice_now.bands)
        assert total_band_members <= 2  # 元3名から1名除外
        assert any("学生課送り" in e for e in events)

    def test_no_mobilization_on_incident(self):
        """事件発生時は動員数が加算されない"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        mob_before = alice.cumulative_mobilization

        _inject_members(alice, count=3, draw=5, music=2, human=2)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        alice_now = state.players[0]
        assert alice_now.cumulative_mobilization == mob_before


# ---------------------------------------------------------------------------
# 大編成ペナルティ（6人以上バンド → 事件2枚）
# ---------------------------------------------------------------------------

class TestLargeband:
    def _setup_band(self, size: int, human: int, severity: int):
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=size, draw=3, music=2, human=human)
        incident = next(c for c in all_incidents() if (c.severity or 0) == severity)
        state.incident_deck = [instance_from_catalog(incident)] * 10
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:size]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        return state, alice.player_id

    def test_5_members_draws_one_incident(self):
        """5人バンドは事件1枚（従来通り）"""
        state, pid = self._setup_band(size=5, human=2, severity=6)
        state, events = apply_action(state, pid, EndTurnAction())
        incident_events = [e for e in events if '事件' in e and '大編成' not in e and 'severity=0' not in e and '山札' not in e]
        assert not any('大編成' in e for e in events)

    def test_6_members_draws_two_incidents(self):
        """6人バンドは事件2枚引き → 事件性は合計値"""
        state, pid = self._setup_band(size=6, human=2, severity=6)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any('大編成ペナルティ' in e for e in events)
        result = state.last_live_results[0]
        # severity=6 の事件2枚 → effective severity は 12（- mods）
        assert result.incident_severity >= 12 - 5  # antis/mods考慮で多少変動あり

    def test_6_members_harder_to_pass(self):
        """6人バンド: human=2×6=12 は severity=6×2=12 とぎりぎり成功"""
        state, pid = self._setup_band(size=6, human=2, severity=6)
        state, events = apply_action(state, pid, EndTurnAction())
        result = state.last_live_results[0]
        # human total = 12, severity total = 12 → 12 >= 12 → success
        assert result.success is True

    def test_6_members_fails_with_insufficient_human(self):
        """6人バンド: human=1×6=6 は severity=6×2=12 に負ける"""
        state, pid = self._setup_band(size=6, human=1, severity=6)
        state, events = apply_action(state, pid, EndTurnAction())
        result = state.last_live_results[0]
        assert result.success is False


# ---------------------------------------------------------------------------
# Win condition
# ---------------------------------------------------------------------------

class TestWinCondition:
    def test_win_when_target_reached(self):
        """対応力(12×3=36) >= severity=8 でライブ成功 → 目標動員数到達 → 勝利"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p(target=80)
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        alice.cumulative_mobilization = 75
        _inject_members(alice, count=3, draw=10, music=2, human=12)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        assert state.phase == Phase.GAME_OVER
        assert state.winner_id == alice.player_id
        assert any("勝利" in e for e in events)


# ---------------------------------------------------------------------------
# Judgment formula boundary tests
# ---------------------------------------------------------------------------

class TestJudgmentBoundary:
    def _setup_with_human(self, human: int, severity: int, num_bands: int = 1):
        """
        Build a state where the band has given human and the incident has given severity.
        Returns (state, alice_player_id).
        """
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        from engine.catalog import all_incidents, instance_from_catalog
        incident_card = next(
            (c for c in all_incidents() if (c.severity or 0) == severity),
            list(all_incidents())[0]
        )
        state.incident_deck = [instance_from_catalog(incident_card)] * 5

        for _ in range(num_bands):
            alice = state.players[0]  # re-fetch from current state before injecting
            _inject_members(alice, count=3, draw=3, music=2, human=human)
            ids = [m.instance_id for m in alice.field_members[-3:]]
            state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))

        return state, alice.player_id

    def test_exactly_equal_is_success(self):
        # 3 members × human=2 → band 対応力合計=6; severity=6 → 6>=6 → success
        state, pid = self._setup_with_human(human=2, severity=6, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any("成功" in e for e in events)

    def test_one_below_is_incident(self):
        # 3 members × human=2 → band 対応力合計=6; severity=7 → 6<7 → incident
        state, pid = self._setup_with_human(human=2, severity=7, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any("事件" in e for e in events)
        assert state.phase != Phase.SOTAI  # auto-resolved

    def test_zero_human_fails_positive_severity(self):
        # 対応力=0 は severity>0 の事件を乗り越えられない
        state, pid = self._setup_with_human(human=0, severity=4, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any("事件" in e for e in events)
        assert state.phase != Phase.SOTAI  # auto-resolved

    def test_multi_band_no_multiplier(self):
        # バンド2個でも乗算なし：各バンドの対応力のみで個別に判定する
        # 3 members × human=2 → 対応力=6; severity=5 → 6>=5 → 各バンド成功
        # 旧式なら 2バンド multiplier=1.17 → jv=7 > 5 で失敗していた
        state, pid = self._setup_with_human(human=2, severity=5, num_bands=2)
        state, events = apply_action(state, pid, EndTurnAction())
        assert state.phase != Phase.SOTAI
        assert not any("学生課送り" in e for e in events)


# ---------------------------------------------------------------------------
# Member roster
# ---------------------------------------------------------------------------

class TestMemberRoster:
    def test_member_count(self):
        """全メンバー種類: 基本24 + バリエーション9 + トークン1 = 34種"""
        from engine.catalog import all_members
        assert len(all_members()) == 34

    def test_ability_members_have_abilities(self):
        """アビリティ持ちメンバーは ability != None"""
        from engine.catalog import all_members
        ability_ids = {4, 5, 10, 12, 14, 17, 18, 19, 20, 21, 22, 23, 24,
                       25, 26, 27, 28, 29, 30, 31, 32, 33}
        for m in all_members():
            if m.id in ability_ids:
                assert m.ability is not None, f"{m.name}(id={m.id}) has no ability"

    def test_no_ability_members(self):
        """能力なしはIchiro(11)と走る足(34)のみ"""
        from engine.catalog import all_members
        no_ability_ids = {11, 34}
        for m in all_members():
            if m.id in no_ability_ids:
                assert m.ability is None, f"{m.name}(id={m.id}) should have no ability"
            elif m.id in {1, 2, 3, 6, 7, 8, 9, 13, 15, 16}:
                assert m.ability is not None, f"{m.name}(id={m.id}) should now have an ability"


# ---------------------------------------------------------------------------
# New ability tests
# ---------------------------------------------------------------------------

class TestNewAbilities:
    def _inst(self, member_id: int):
        from engine.catalog import all_members, instance_from_catalog
        card = next(c for c in all_members() if c.id == member_id)
        return instance_from_catalog(card)

    # --- static (on_band_stat) ---

    def test_tatsube_drunk_draw_boost_and_human_penalty(self):
        """id=19 たつぼー（酔いつぶれる）: draw+4 human-2"""
        from engine import hooks
        inst = self._inst(19)
        d, m, h = hooks.apply_on_band_stat(inst, 5, 5, 5)
        assert d == 9
        assert h == 3

    def test_wano_matsuri_draw_boost(self):
        """id=12 わの祭り: draw+3"""
        from engine import hooks
        inst = self._inst(12)
        d, m, h = hooks.apply_on_band_stat(inst, 5, 5, 5)
        assert d == 8

    def test_ichiro_raw_stats(self):
        """id=11 Ichiro Yamaguchi: 能力なし、生のステータスで圧倒 (draw=50, music=299, human=50)"""
        from engine.catalog import all_members
        card = next(c for c in all_members() if c.id == 11)
        assert card.ability is None
        assert card.draw == 50
        assert card.music == 299
        assert card.human == 50

    def test_sama_d_hangover_music_boost(self):
        """id=23 さまD（二日酔い）: music+5"""
        from engine import hooks
        inst = self._inst(23)
        d, m, h = hooks.apply_on_band_stat(inst, 5, 5, 5)
        assert m == 10

    # --- judgment ---

    def test_tatsube_angry_severity_and_success_bonus(self):
        """id=20 たつぼー（怒れる）: severity+3_success_draw+6"""
        from engine import hooks
        inst = self._inst(20)
        mods = hooks.JudgmentMods()
        ev = hooks.apply_on_judgment(inst, mods)
        assert mods.severity_delta == 3
        assert mods.success_draw_bonus == 6
        assert any("事件性+3" in e for e in ev)

    def test_sama_d_legendary_dual_bonus(self):
        """id=22 さまD（神回）: success_draw+6_success_music+3"""
        from engine import hooks
        inst = self._inst(22)
        mods = hooks.JudgmentMods()
        hooks.apply_on_judgment(inst, mods)
        assert mods.success_draw_bonus == 6
        assert mods.success_music_bonus == 3

    def test_goto_judgment_human_delta(self):
        """id=14 ごとぅさん: human+2 in judgment"""
        from engine import hooks
        inst = self._inst(14)
        mods = hooks.JudgmentMods()
        ev = hooks.apply_on_judgment(inst, mods)
        assert mods.human_delta == 2
        assert any("対応力+2" in e for e in ev)

    # --- on_form ---

    def test_shimachan_on_form_gives_action(self):
        """id=4 しまちゃん: action+1 on band formation"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(4)
        _inject_members(alice, count=2, draw=3, music=2, human=2)
        alice.field_members.append(inst)
        initial_actions = state.actions_remaining
        ids = [m.instance_id for m in alice.field_members]
        state, events = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        # cost=1 action, ability adds +1 → net unchanged
        assert state.actions_remaining == initial_actions
        assert any("まとめ役" in e for e in events)

    # --- on_play ---

    def test_jamu_on_play_draws_extra_card(self):
        """id=5 じゃむさん: draw_card on play"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(5)
        alice.hand.append(inst)
        hand_before = len(alice.hand)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        # played 1 card out, drew 1 back → net 0
        assert len(state.players[0].hand) == hand_before - 1 + 1
        assert any("即興演奏" in e for e in events)

    # --- newly redesigned abilities (gimmick focus) ---

    def test_keisuke_on_play_draws_two(self):
        """id=1 けーすけ: 人脈 → on_play draw2"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(1)
        alice.hand.append(inst)
        hand_before = len(alice.hand)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        # played 1 out, drew 2 back → net +1
        assert len(state.players[0].hand) == hand_before - 1 + 2
        assert any("人脈" in e for e in events)

    def test_tatsube_on_play_reduces_opponent_record(self):
        """id=2 たつぼー: プレッシャー → on_play opponents_record-1"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        bob = state.players[1]
        bob.performance_record = 5
        inst = self._inst(2)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert state.players[1].performance_record == 4
        assert any("プレッシャー" in e for e in events)

    def test_naganagase_on_play_recruits_from_deck(self):
        """id=3 ながながせ: スカウト → on_play recruit_from_deck"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        deck_before = len(alice.deck)
        inst = self._inst(3)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        # deck shrinks by 1 (recruited to field or band)
        alice2 = state.players[0]
        assert len(alice2.deck) == deck_before - 1
        assert any("スカウト" in e for e in events)

    def test_kame_on_form_recruits_from_deck(self):
        """id=6 かめ: 守りのリズム → on_form recruit_from_deck"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(6)
        _inject_members(alice, count=2, draw=3, music=2, human=2)
        alice.field_members.append(inst)
        deck_before = len(alice.deck)
        ids = [m.instance_id for m in alice.field_members]
        state, events = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        alice2 = state.players[0]
        # deck shrinks by 1 and band gains an extra member
        assert len(alice2.deck) == deck_before - 1
        assert any(len(b.members) == 4 for b in alice2.bands)
        assert any("守りのリズム" in e for e in events)

    def test_ohana_on_play_sets_free_member(self):
        """id=7 おはなさん: ドラムで誘う → on_play free_play_member"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(7)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert state.players[0].free_member_play is True
        assert any("ドラムで誘う" in e for e in events)

    def test_sama_d_on_play_mobilization_once(self):
        """id=8 さまD: 伝説の一夜 → on_play mobilization+10_once (fires once)"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        mob_before = alice.cumulative_mobilization
        inst = self._inst(8)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert state.players[0].cumulative_mobilization == mob_before + 10
        assert any("伝説の一夜" in e for e in events)
        # used_once flag is set on the copy in field_members
        inst2 = next(m for m in state.players[0].field_members if m.catalog_id == "member_8")
        assert inst2.used_once is True

    def test_sora_severity_reduction(self):
        """id=9 そらさん: ピンチに強い → severity-2 (maintained)"""
        from engine import hooks
        inst = self._inst(9)
        mods = hooks.JudgmentMods()
        hooks.apply_on_judgment(inst, mods)
        assert mods.severity_delta == -2

    def test_shoishoi_on_play_action_plus_one(self):
        """id=13 しょいしょい: 場のテンション → on_play action+1"""
        state = _game_2p()
        state = _skip_mulligan(state)
        actions_before = state.actions_remaining
        alice = state.players[0]
        inst = self._inst(13)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        # cost 1 action, ability adds 1 → net unchanged
        assert state.actions_remaining == actions_before
        assert any("場のテンション" in e for e in events)

    def test_shio_on_form_recruits_from_deck(self):
        """id=15 しおちゃん: 静かな勧誘 → on_form recruit_from_deck"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        inst = self._inst(15)
        _inject_members(alice, count=2, draw=3, music=2, human=2)
        alice.field_members.append(inst)
        deck_before = len(alice.deck)
        ids = [m.instance_id for m in alice.field_members]
        state, events = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        alice2 = state.players[0]
        assert len(alice2.deck) == deck_before - 1
        assert any(len(b.members) == 4 for b in alice2.bands)
        assert any("静かな勧誘" in e for e in events)

    def test_ucchi_on_play_drains_opponent_mobilization(self):
        """id=16 うっちー: 観客煽り → on_play opponents_mobilization-5"""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        bob = state.players[1]
        bob.cumulative_mobilization = 20
        inst = self._inst(16)
        alice.hand.append(inst)
        state, events = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert state.players[1].cumulative_mobilization == 15
        assert any("観客煽り" in e for e in events)


# ---------------------------------------------------------------------------
# Performance record gating
# ---------------------------------------------------------------------------

class TestPerformanceRecord:
    def test_music_4_card_blocked_at_record_3(self):
        from engine.catalog import all_members, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        alice.performance_record = 3
        card4 = next(c for c in all_members() if c.music == 4)
        inst = instance_from_catalog(card4)
        alice.hand.append(inst)
        with pytest.raises(ActionError, match="活動実績"):
            apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))

    def test_music_4_card_allowed_at_record_10(self):
        from engine.catalog import all_members, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card4 = next(c for c in all_members() if c.music == 4)
        inst = instance_from_catalog(card4)
        alice.hand.append(inst)
        state, _ = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert any(m.instance_id == inst.instance_id for m in state.players[0].field_members)

    def test_performance_record_unlocks_higher_music(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        alice.performance_record = 4
        from engine.catalog import all_members, instance_from_catalog
        card4 = next(c for c in all_members() if c.music == 4)
        inst = instance_from_catalog(card4)
        alice.hand.append(inst)
        state, _ = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert any(m.instance_id == inst.instance_id for m in state.players[0].field_members)


# ---------------------------------------------------------------------------
# last_live_results stale data bug
# ---------------------------------------------------------------------------

class TestLiveResultsCleared:
    def test_last_live_results_cleared_on_next_action(self):
        """再現テスト: ターン終了後、次プレイヤーのアクションで last_live_results が残っていないこと。
        (バグ: DrawAction後も前ターンの結果が残り、LP演出が誤発動していた)"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]

        # Aliceがバンドを組んでライブ成功
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=3, music=2, human=12)
        state.incident_deck = [instance_from_catalog(
            next(c for c in all_incidents() if (c.severity or 0) == 8)
        )] * 5
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        # ライブ結果が存在することを確認
        assert len(state.last_live_results) > 0

        # 次のプレイヤー（Bob）がドローする
        bob = state.players[1]
        state, _ = apply_action(state, bob.player_id, DrawAction())

        # BobのDrawAction後は last_live_results が空でなければならない
        assert state.last_live_results == [], \
            f"DrawAction後も last_live_results が残っている: {state.last_live_results}"


# ---------------------------------------------------------------------------
# LiveBandResult structure
# ---------------------------------------------------------------------------

class TestLiveBandResult:
    def test_success_result_has_correct_fields(self):
        """EndTurn populates last_live_results with a valid LiveBandResult on success.
        対応力(human=12×3=36) >= severity=8 → 成功"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=5, music=2, human=12)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert len(state.last_live_results) == 1
        r = state.last_live_results[0]
        assert r.success is True
        assert r.num_bands == 1
        assert abs(r.multiplier - 1.0) < 1e-9
        assert r.human_total == 36           # 3 members × human=12
        assert r.judgment_value == 36        # no multiplier
        assert r.judgment_value >= r.incident_severity
        assert r.mobilization_gain == r.draw_total
        assert len(r.members) == 3
        assert all(m.kind == "member" for m in r.members)

    def test_incident_result_has_correct_fields(self):
        """EndTurn populates last_live_results with success=False on incident.
        対応力(human=2×3=6) < severity=8 → 失敗"""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=2, music=2, human=2)
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert len(state.last_live_results) == 1
        r = state.last_live_results[0]
        assert r.success is False
        assert r.mobilization_gain == 0
        assert r.music_gain == 0
        assert r.incident_severity == 8
        assert r.judgment_value == 6         # 3 × human=2
        assert r.judgment_value < r.incident_severity

    def test_two_band_failures_auto_remove_two_members(self):
        """
        3 bands: bands 1+2 fail (human=2), band 3 succeeds (human=10).
        Auto-sotai removes 1 member from each failing band in a single EndTurn.
        """
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=6, draw=2, music=2, human=2)   # 3×2=6 < 8 → fail
        _inject_members(alice, count=3, draw=2, music=2, human=10)  # 3×10=30 >= 8 → success

        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5

        alice = state.players[0]
        ids1 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids1))

        alice = state.players[0]
        ids2 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids2))

        alice = state.players[0]
        ids3 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids3))

        alice = state.players[0]
        mob_before = alice.cumulative_mobilization
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        # Both failures resolved automatically — no SOTAI phase
        assert state.phase != Phase.SOTAI
        removal_events = [e for e in events if "が除外" in e]
        assert len(removal_events) == 2, "1 member removed per failing band"
        # Successful band 3 contributed mobilization
        assert state.players[0].cumulative_mobilization > mob_before
        assert any(r.success for r in state.last_live_results), "band 3 should succeed"
        assert state.pending_band_processes == []


# ---------------------------------------------------------------------------
# Band composition bonus tests
# ---------------------------------------------------------------------------

class TestBandComposition:
    def _make_member(self, part, gender=None, draw=3, music=1, human=2):
        from engine.models import CardInstance, CardKind
        return CardInstance(
            catalog_id=f"test_{part}",
            kind=CardKind.MEMBER,
            name=f"テスト{part}",
            part=part,
            gender=gender,
            draw=draw,
            music=music,
            human=human,
        )

    def test_three_piece_bonus(self):
        """Gt+Ba+Dr 3人 → 無もなきスリーピース: music+2, human+1"""
        from engine.actions import _band_composition
        members = [
            self._make_member("Gt"),
            self._make_member("Ba"),
            self._make_member("Dr"),
        ]
        name, db, mb, hb = _band_composition(members)
        assert "無もなきスリーピース" in name
        assert mb == 2
        assert hb == 1

    def test_normal_band_bonus(self):
        """2Gt+Ba+Dr 4人 → 通常バンド: music+2, human+3"""
        from engine.actions import _band_composition
        members = [
            self._make_member("Gt"),
            self._make_member("Gt"),
            self._make_member("Ba"),
            self._make_member("Dr"),
        ]
        name, db, mb, hb = _band_composition(members)
        assert "通常バンド" in name
        assert mb == 2
        assert hb == 3

    def test_full_band_bonus(self):
        """Gt+Ba+Dr+Key 4人 → フルバンド: draw+1, music+2, human+2"""
        from engine.actions import _band_composition
        members = [
            self._make_member("Gt"),
            self._make_member("Ba"),
            self._make_member("Dr"),
            self._make_member("Key"),
        ]
        name, db, mb, hb = _band_composition(members)
        assert "フルバンド" in name
        assert db == 1
        assert mb == 2
        assert hb == 2

    def test_full_band_and_girls_band_stack(self):
        """Gt+Ba+Dr+Key の全員female → フルバンド・ガールズバンド スタック"""
        from engine.actions import _band_composition
        members = [
            self._make_member("Gt",  gender="female"),
            self._make_member("Ba",  gender="female"),
            self._make_member("Dr",  gender="female"),
            self._make_member("Key", gender="female"),
        ]
        name, db, mb, hb = _band_composition(members)
        assert "フルバンド" in name
        assert "ガールズバンド" in name
        assert db == 1 + 3   # フル+ガールズ
        assert mb == 2
        assert hb == 2 + 1   # フル+ガールズ

    def test_full_band_not_triggered_without_key(self):
        """Gt+Ba+Dr+Gt はフルバンドにならず通常バンド"""
        from engine.actions import _band_composition
        members = [
            self._make_member("Gt"),
            self._make_member("Gt"),
            self._make_member("Ba"),
            self._make_member("Dr"),
        ]
        name, db, mb, hb = _band_composition(members)
        assert "フルバンド" not in name
        assert "通常バンド" in name

    def test_ohana_is_key_part(self):
        """おはなさん(id=7)のパートがKeyになっている"""
        from engine.catalog import all_members
        ohana = next(c for c in all_members() if c.id == 7)
        assert ohana.part == "Key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_members(
    player,
    count: int = 3,
    draw: int = 3,
    music: int = 2,
    human: int = 1,
) -> None:
    """Directly inject synthetic members onto the player's field."""
    from engine.models import CardInstance, CardKind, Ability
    for i in range(count):
        inst = CardInstance(
            catalog_id=f"test_member_{i}",
            kind=CardKind.MEMBER,
            name=f"テストメンバー{i}",
            part="Gt",
            draw=draw,
            music=music,
            human=human,
        )
        player.field_members.append(inst)


def _inject_support(player, name: str, effect: str) -> "CardInstance":
    """Inject a synthetic support card into the player's hand and return it."""
    from engine.models import CardInstance, CardKind
    card = CardInstance(
        catalog_id=f"test_support_{name}",
        kind=CardKind.SUPPORT,
        name=name,
        effect=effect,
        phase="action",
    )
    player.hand.append(card)
    return card


# ---------------------------------------------------------------------------
# Support card effects
# ---------------------------------------------------------------------------

class TestSupportEffects:
    def test_draw2_adds_two_cards(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "差し入れ", "draw2")
        before = len(alice.hand)
        state, events = apply_action(state, alice.player_id,
                                     UseSupportAction(card_instance_id=card.instance_id))
        assert len(state.players[0].hand) == before - 1 + 2  # used 1, drew 2

    def test_redraw_hand_replaces_hand(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "打ち上げで結束", "redraw_hand")
        before = len(alice.hand)  # includes the support card
        state, events = apply_action(state, alice.player_id,
                                     UseSupportAction(card_instance_id=card.instance_id))
        # used card leaves hand (goes to discard), then (before-1) cards were discarded
        # and (before-1) new cards drawn — net hand size equals before-1
        assert len(state.players[0].hand) == before - 1

    def test_free_play_member_sets_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "助っ人ヘルプ", "free_play_member")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].free_member_play is True

    def test_free_play_member_does_not_cost_action(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        support = _inject_support(alice, "助っ人ヘルプ", "free_play_member")
        # use the support (costs 1 action)
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=support.instance_id))
        actions_after_support = state.actions_remaining
        # find a playable member
        member = _find_member_in_hand(state.players[0])
        if member is None:
            _inject_members(state.players[0], count=1, music=1)
            member = state.players[0].field_members[-1]
            state.players[0].field_members.pop()
            state.players[0].hand.append(member)
            member = state.players[0].hand[-1]
        state, _ = apply_action(state, alice.player_id,
                                PlayMemberAction(card_instance_id=member.instance_id))
        # action count should be unchanged (free play consumed the flag, not an action)
        assert state.actions_remaining == actions_after_support
        assert state.players[0].free_member_play is False

    def test_music_bonus_sets_pending_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "練習スタジオ確保", "music+3")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].pending_live_music_bonus == 3

    def test_draw_bonus_3_sets_pending_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "ビラ配り", "draw+3")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].pending_live_draw_bonus == 3

    def test_draw_bonus_2_sets_pending_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "機材車", "draw+2")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].pending_live_draw_bonus == 2

    def test_severity_reduction_sets_pending_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "顧問の口添え", "severity-2")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].pending_severity_reduction == 2

    def test_encore_sets_pending_flag(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card = _inject_support(alice, "アンコール", "encore")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))
        assert state.players[0].encore_pending is True

    def test_pending_flags_cleared_after_turn(self):
        """All pending bonuses reset to zero when the turn ends."""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]

        state.actions_remaining = 99
        _inject_support(alice, "練習スタジオ確保", "music+3")
        _inject_support(alice, "ビラ配り", "draw+3")
        _inject_support(alice, "顧問の口添え", "severity-2")
        _inject_support(alice, "アンコール", "encore")
        for card in list(alice.hand):
            if card.kind == CardKind.SUPPORT:
                state, _ = apply_action(state, alice.player_id,
                                        UseSupportAction(card_instance_id=card.instance_id))

        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        a = state.players[0]
        assert a.pending_live_music_bonus == 0
        assert a.pending_live_draw_bonus == 0
        assert a.pending_severity_reduction == 0
        assert a.encore_pending is False

    def test_severity_reduction_applied_in_live(self):
        """顧問の口添え reduces effective severity by 2 during judgment."""
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]

        state.actions_remaining = 99
        # severity=6 incident; human=4 per member × 3 = 12 >= 6 → passes without reduction
        # Set human low so it fails WITHOUT reduction but passes WITH -2 reduction
        # severity=5, human per member=1 → total human=3 → 3 < 5 → fail WITHOUT reduction
        # With reduction: effective severity = 5-2 = 3 → 3 >= 3 → success
        _inject_members(alice, count=3, draw=2, music=2, human=1)
        state.incident_deck = [instance_from_catalog(
            next(c for c in all_incidents() if (c.severity or 0) == 5)
        )] * 5

        card = _inject_support(alice, "顧問の口添え", "severity-2")
        state, _ = apply_action(state, alice.player_id,
                                UseSupportAction(card_instance_id=card.instance_id))

        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert len(state.last_live_results) > 0
        assert state.last_live_results[0].success is True


# ---------------------------------------------------------------------------
# TaibanAction
# ---------------------------------------------------------------------------

def _setup_taiban_state(my_music: int, opp_music: int):
    """Return (state, alice_band_id, bob_band_id) with bands having given music totals."""
    state = _game_2p()
    state = _skip_mulligan(state)
    state.actions_remaining = 99
    alice = state.players[0]
    bob = state.players[1]
    _inject_members(alice, count=3, draw=2, music=my_music, human=2)
    _inject_members(bob, count=3, draw=2, music=opp_music, human=2)
    ids_a = [m.instance_id for m in alice.field_members[:3]]
    state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids_a))
    alice_band_id = state.players[0].bands[-1].band_id
    # Re-fetch bob from the new state (apply_action returns a deep copy)
    bob = state.players[1]
    from engine.models import Band
    bob_band = Band(members=list(bob.field_members[:3]))
    for m in bob_band.members:
        bob.field_members.remove(m)
    bob.bands.append(bob_band)
    bob_band_id = bob_band.band_id
    return state, alice_band_id, bob_band_id


class TestTaibanAction:
    def test_taiban_win_transfers_mobilization(self):
        state, my_bid, opp_bid = _setup_taiban_state(my_music=3, opp_music=1)
        alice = state.players[0]
        bob = state.players[1]
        alice.cumulative_mobilization = 0
        bob.cumulative_mobilization = 20
        state, events = apply_action(state, alice.player_id,
                                     TaibanAction(my_band_id=my_bid, opponent_band_id=opp_bid))
        # my_music=3*3=9, steal=9*2=18, bob has 20 → steal 18
        assert state.players[0].cumulative_mobilization == 18
        assert state.players[1].cumulative_mobilization == 2
        assert state.taiban_result["result"] == "win"
        assert any("勝利" in e for e in events)

    def test_taiban_lose_no_transfer(self):
        state, my_bid, opp_bid = _setup_taiban_state(my_music=1, opp_music=3)
        alice = state.players[0]
        bob = state.players[1]
        bob.cumulative_mobilization = 20
        state, events = apply_action(state, alice.player_id,
                                     TaibanAction(my_band_id=my_bid, opponent_band_id=opp_bid))
        assert state.players[1].cumulative_mobilization == 20
        assert state.taiban_result["result"] == "lose"
        assert any("敗北" in e for e in events)

    def test_taiban_steal_capped_at_opponent_mobilization(self):
        state, my_bid, opp_bid = _setup_taiban_state(my_music=3, opp_music=1)
        alice = state.players[0]
        bob = state.players[1]
        bob.cumulative_mobilization = 5  # steal would be 18 but capped at 5
        state, _ = apply_action(state, alice.player_id,
                                TaibanAction(my_band_id=my_bid, opponent_band_id=opp_bid))
        assert state.players[1].cumulative_mobilization == 0
        assert state.players[0].cumulative_mobilization == 5
        assert state.taiban_result["steal"] == 5

    def test_taiban_invalid_band_id_raises(self):
        state, my_bid, _ = _setup_taiban_state(my_music=3, opp_music=1)
        alice = state.players[0]
        with pytest.raises(ActionError, match="バンドが見つかりません"):
            apply_action(state, alice.player_id,
                         TaibanAction(my_band_id=my_bid, opponent_band_id="nonexistent"))

    def test_taiban_result_cleared_on_next_action(self):
        state, my_bid, opp_bid = _setup_taiban_state(my_music=3, opp_music=1)
        state, _ = apply_action(state, state.players[0].player_id,
                                TaibanAction(my_band_id=my_bid, opponent_band_id=opp_bid))
        assert state.taiban_result is not None
        # Next action clears it
        state, _ = apply_action(state, state.players[0].player_id, DrawAction())
        assert state.taiban_result is None
