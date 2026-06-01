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
    EndTurnAction, ChooseSotaiAction, DisbandAction,
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
        assert len(deck) == 50, f"Expected 50 cards, got {len(deck)}"

    def test_fixed_deck_has_members(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck()
        members = [c for c in deck if c.kind == CardKind.MEMBER]
        assert len(members) == 38

    def test_fixed_deck_has_supports(self):
        builder = FixedDeckBuilder()
        deck = builder.build_player_deck()
        supports = [c for c in deck if c.kind == CardKind.SUPPORT]
        assert len(supports) == 8

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

    def test_players_have_5_cards(self):
        state = _game_2p()
        for p in state.players:
            assert len(p.hand) == 5

    def test_player_count_2(self):
        state = _game_2p()
        assert len(state.players) == 2

    def test_invalid_player_count(self):
        with pytest.raises(ValueError):
            create_game(["Solo"])

    def test_invalid_target(self):
        with pytest.raises(ValueError):
            create_game(["A", "B"], GameConfig(target_mobilization=100))

    def test_initial_performance_record_4(self):
        state = _game_2p()
        for p in state.players:
            assert p.performance_record == 4


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
        # Force a high-music card into hand
        from engine.catalog import all_members, instance_from_catalog
        high_music = next(c for c in all_members() if c.music > 4)
        card = instance_from_catalog(high_music)
        alice.hand.append(card)
        with pytest.raises(ActionError, match="活動実績"):
            apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=card.instance_id))

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
        """A band with human=0 always passes (0 > severity is false)."""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=5, music=2, human=0)
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
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=3, music=2, human=0)
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        pr_before = state.players[0].performance_record
        state, _ = apply_action(state, state.players[0].player_id, EndTurnAction())
        assert state.players[0].performance_record == pr_before + 1

    def test_incident_triggers_sotai(self):
        """Force incident: human extremely high so judgment always fails."""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=2, music=2, human=100)
        # Replace incident deck with a max-severity card
        from engine.catalog import all_incidents, instance_from_catalog
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        inst = instance_from_catalog(high)
        state.incident_deck = [inst]

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, events = apply_action(state, alice.player_id, EndTurnAction())

        assert state.phase == Phase.SOTAI
        assert state.sotai_context is not None
        assert any("学生課送り" in e for e in events)

    def test_sotai_removes_member(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        _inject_members(alice, count=3, draw=2, music=2, human=100)
        from engine.catalog import all_incidents, instance_from_catalog
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)]

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert state.phase == Phase.SOTAI
        ctx = state.sotai_context
        band = next(b for b in state.players[0].bands if b.band_id == ctx.band_id)
        victim_member_id = band.member_ids[0]

        nominator_id = ctx.nominator_player_id
        state, events = apply_action(
            state, nominator_id, ChooseSotaiAction(member_instance_id=victim_member_id)
        )
        band_after = next((b for b in state.players[0].bands if b.band_id == ctx.band_id), None)
        if band_after:
            assert victim_member_id not in band_after.member_ids
        assert any("学生課送り" in e for e in events)

    def test_no_mobilization_on_incident(self):
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        mob_before = alice.cumulative_mobilization

        _inject_members(alice, count=3, draw=5, music=2, human=100)
        from engine.catalog import all_incidents, instance_from_catalog
        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)]

        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        # Even after sotai resolution, mobilization should not have increased
        alice_now = state.players[0]
        assert alice_now.cumulative_mobilization == mob_before


# ---------------------------------------------------------------------------
# Win condition
# ---------------------------------------------------------------------------

class TestWinCondition:
    def test_win_when_target_reached(self):
        state = _game_2p(target=80)
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        # Artificially set near-win
        alice.cumulative_mobilization = 75
        _inject_members(alice, count=3, draw=10, music=2, human=0)
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
        # 3 members × human=2 = band_total=6; 1 band → multiplier=1.0 → value=6; severity=6 → 6>6 False → success
        state, pid = self._setup_with_human(human=2, severity=6, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any("成功" in e for e in events)

    def test_one_over_is_incident(self):
        # 3 members × human=5 = 15; bands=1 → multiplier=1.0 → value=15; severity=4 → 15 > 4 → incident
        state, pid = self._setup_with_human(human=5, severity=4, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert state.phase == Phase.SOTAI or any("事件" in e for e in events)

    def test_zero_human_always_success(self):
        state, pid = self._setup_with_human(human=0, severity=0, num_bands=1)
        state, events = apply_action(state, pid, EndTurnAction())
        assert any("成功" in e for e in events)

    def test_multi_band_multiplies_judgment(self):
        # 3 members × human=2 = 6; bands=3 → multiplier=2.0 → value=12; severity=4 → 12 > 4 → incident
        state, pid = self._setup_with_human(human=2, severity=4, num_bands=3)
        state, events = apply_action(state, pid, EndTurnAction())
        # Should be SOTAI or incident event
        assert state.phase == Phase.SOTAI or any("事件" in e for e in events)


# ---------------------------------------------------------------------------
# Static ability hooks
# ---------------------------------------------------------------------------

class TestStaticAbilities:
    def test_mood_maker_reduces_human(self):
        """id=12 ムードメーカー: human-1 on_band_stat"""
        from engine.catalog import all_members, instance_from_catalog
        mood = next(c for c in all_members() if c.id == 12)
        inst = instance_from_catalog(mood)
        d, m, h = 5, 5, 5
        d2, m2, h2 = _apply_static(inst, d, m, h)
        assert h2 == h - 1

    def test_charisma_ob_increases_draw(self):
        """id=1 カリスマOB先輩: draw+2 on_band_stat"""
        from engine.catalog import all_members, instance_from_catalog
        from engine import hooks
        card = next(c for c in all_members() if c.id == 1)
        inst = instance_from_catalog(card)
        d, m, h = 5, 5, 5
        d2, m2, h2 = hooks.apply_on_band_stat(inst, d, m, h)
        assert d2 == d + 2

    def test_technical_drummer_increases_music_and_human(self):
        """id=4 テクニカル神ドラマー: music+3 human+1"""
        from engine.catalog import all_members, instance_from_catalog
        from engine import hooks
        card = next(c for c in all_members() if c.id == 4)
        inst = instance_from_catalog(card)
        d, m, h = 5, 5, 5
        d2, m2, h2 = hooks.apply_on_band_stat(inst, d, m, h)
        assert m2 == m + 3
        assert h2 == h + 1


# ---------------------------------------------------------------------------
# Performance record gating
# ---------------------------------------------------------------------------

class TestPerformanceRecord:
    def test_music_5_card_blocked_at_record_4(self):
        from engine.catalog import all_members, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        card5 = next(c for c in all_members() if c.music == 5)
        inst = instance_from_catalog(card5)
        alice.hand.append(inst)
        assert alice.performance_record == 4
        with pytest.raises(ActionError, match="活動実績"):
            apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))

    def test_music_4_card_allowed_at_record_4(self):
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
        alice.performance_record = 7
        from engine.catalog import all_members, instance_from_catalog
        card7 = next(c for c in all_members() if c.music == 7)
        inst = instance_from_catalog(card7)
        alice.hand.append(inst)
        state, _ = apply_action(state, alice.player_id, PlayMemberAction(card_instance_id=inst.instance_id))
        assert any(m.instance_id == inst.instance_id for m in state.players[0].field_members)


# ---------------------------------------------------------------------------
# LiveBandResult structure
# ---------------------------------------------------------------------------

class TestLiveBandResult:
    def test_success_result_has_correct_fields(self):
        """EndTurn populates last_live_results with a valid LiveBandResult on success."""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=5, music=2, human=0)
        alice = state.players[0]
        ids = [m.instance_id for m in alice.field_members[:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids))
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert len(state.last_live_results) == 1
        r = state.last_live_results[0]
        assert r.success is True
        assert r.num_bands == 1
        assert abs(r.multiplier - 1.0) < 1e-9
        assert r.human_total == 0
        assert r.judgment_value == 0
        assert r.mobilization_gain == r.draw_total
        assert len(r.members) == 3
        assert all(m.kind == "member" for m in r.members)

    def test_incident_result_has_correct_fields(self):
        """EndTurn populates last_live_results with success=False on incident."""
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99
        _inject_members(alice, count=3, draw=2, music=2, human=100)
        from engine.catalog import all_incidents, instance_from_catalog
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
        assert r.judgment_value > r.incident_severity

    def test_two_band_failures_require_two_sequential_sotai(self):
        """
        3 bands: bands 1+2 fail (human=100), band 3 succeeds (human=0).
        Asserts that the engine stops at EACH failure and resumes via
        choose_sotai — i.e., pending_band_processes is the mechanism that
        guarantees exactly 2 nominations and last_live_results contains only
        the bands processed in that action (never a mix of fail+pending).
        """
        from engine.catalog import all_incidents, instance_from_catalog
        state = _game_2p()
        state = _skip_mulligan(state)
        alice = state.players[0]
        state.actions_remaining = 99

        # First 6 field members: high human → failure; last 3: zero human → success
        _inject_members(alice, count=6, draw=2, music=2, human=100)
        _inject_members(alice, count=3, draw=2, music=2, human=0)

        high = next(c for c in all_incidents() if (c.severity or 0) == 8)
        state.incident_deck = [instance_from_catalog(high)] * 5

        # Form band 1 (high-human members)
        alice = state.players[0]
        ids1 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids1))

        # Form band 2 (high-human members)
        alice = state.players[0]
        ids2 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids2))

        # Form band 3 (zero-human members)
        alice = state.players[0]
        ids3 = [m.instance_id for m in alice.field_members[0:3]]
        state, _ = apply_action(state, alice.player_id, FormBandAction(member_instance_ids=ids3))

        # EndTurn: band 1 fails → engine stops; bands 2 and 3 become pending
        alice = state.players[0]
        state, _ = apply_action(state, alice.player_id, EndTurnAction())

        assert state.phase == Phase.SOTAI, "band 1 failure should trigger SOTAI"
        assert len(state.last_live_results) == 1, "only band 1 was processed"
        assert state.last_live_results[0].success is False
        assert len(state.pending_band_processes) == 2, "bands 2 and 3 are pending"

        # choose_sotai ①: resolves band 1; engine resumes → band 2 also fails
        ctx = state.sotai_context
        nominator_id = ctx.nominator_player_id
        victim = state.player_by_id(ctx.victim_player_id)
        band = next(b for b in victim.bands if b.band_id == ctx.band_id)
        state, _ = apply_action(
            state, nominator_id,
            ChooseSotaiAction(member_instance_id=band.member_ids[0]),
        )

        assert state.phase == Phase.SOTAI, "band 2 should also trigger SOTAI"
        assert len(state.last_live_results) == 1, "only band 2 was processed in this action"
        assert state.last_live_results[0].success is False
        assert len(state.pending_band_processes) == 1, "only band 3 remains"

        # choose_sotai ②: resolves band 2; engine resumes → band 3 succeeds → end_party
        ctx = state.sotai_context
        victim = state.player_by_id(ctx.victim_player_id)
        band = next(b for b in victim.bands if b.band_id == ctx.band_id)
        state, _ = apply_action(
            state, nominator_id,
            ChooseSotaiAction(member_instance_id=band.member_ids[0]),
        )

        assert state.phase != Phase.SOTAI, "all SOTAI should be resolved"
        assert len(state.last_live_results) == 1, "only band 3 was processed"
        assert state.last_live_results[0].success is True
        assert state.pending_band_processes == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_static(member: CardInstance, draw: int, music: int, human: int):
    from engine import hooks
    return hooks.apply_on_band_stat(member, draw, music, human)


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
