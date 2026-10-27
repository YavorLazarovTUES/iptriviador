import itertools
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from games.models import Game, Round
from games.services import InvalidInputError, InvalidStateError
from games.tests import make_numeric_questions
from territories.models import Capital, CaptureRight, Territory
from territories.services import (
    CAPTURE_REWARD_MULTIPLIER,
    TERRITORY_SCORE_INCREMENT,
    WIN_REWARD,
    _capture_rights_table,
    choose_territory,
    create_city_capture_round,
    free_territory_count,
    start_city_capture_round,
    submit_city_capture_answer,
    try_advance_capture_phase,
)
from territories.tests import make_initialized_game


def now_sequence(base, *offsets_seconds):
    times = [base + timedelta(seconds=offset) for offset in offsets_seconds] or [base]
    return itertools.chain(times, itertools.repeat(times[-1]))


def make_completed_round(game, winner, second_place=None, free_territories_at_start=9, number=1):
    required_places = 2 if second_place is not None else 1
    round_ = Round.objects.create(
        game=game,
        number=number,
        type=Round.CITY_CAPTURE,
        status=Round.COMPLETED,
        winner=winner,
        second_place=second_place,
        required_places=required_places,
        free_territories_at_start=free_territories_at_start,
        completed_at=timezone.now(),
        rewards_applied=True,
    )
    rights_first, rights_second = _capture_rights_table(free_territories_at_start)
    CaptureRight.objects.create(round=round_, player=winner, order=CaptureRight.FIRST, total=rights_first)
    if second_place is not None and rights_second > 0:
        CaptureRight.objects.create(round=round_, player=second_place, order=CaptureRight.SECOND, total=rights_second)
    return round_


def free_neighbor_of(player):
    owned = Territory.objects.filter(game=player.game, owner=player)
    return Territory.objects.filter(game=player.game, owner__isnull=True, neighbors__in=owned).distinct().first()


def free_non_neighbor_of(player):
    owned = Territory.objects.filter(game=player.game, owner=player)
    neighbor_ids = Territory.objects.filter(
        game=player.game, owner__isnull=True, neighbors__in=owned
    ).values_list('pk', flat=True)
    return Territory.objects.filter(game=player.game, owner__isnull=True).exclude(pk__in=neighbor_ids).first()


def pick_choosable_target(player):
    """Mirrors the service's own eligibility rule, for driving test loops."""
    return free_neighbor_of(player) or Territory.objects.filter(game=player.game, owner__isnull=True).first()


class CaptureRightsTableTests(TestCase):
    def test_three_or_more_free_grants_two_and_one(self):
        self.assertEqual(_capture_rights_table(9), (2, 1))
        self.assertEqual(_capture_rights_table(3), (2, 1))

    def test_two_free_grants_two_and_zero(self):
        self.assertEqual(_capture_rights_table(2), (2, 0))

    def test_one_free_grants_one_and_zero(self):
        self.assertEqual(_capture_rights_table(1), (1, 0))

    def test_zero_free_is_rejected(self):
        with self.assertRaises(InvalidStateError):
            _capture_rights_table(0)


class RoundCompletionGrantsRightsAndWinRewardTests(TestCase):
    def test_full_pipeline_creates_rights_and_applies_win_reward(self):
        game, players = make_initialized_game()
        p1, p2, p3 = players
        make_numeric_questions(1, start_answer=10)
        self.assertEqual(free_territory_count(game), 15)

        round_ = start_city_capture_round(create_city_capture_round(game, 1))
        self.assertEqual(round_.required_places, 2)
        self.assertEqual(round_.free_territories_at_start, 15)

        rq = round_.round_questions.get(sequence=1)
        base = rq.started_at
        with mock.patch('games.services.timezone.now') as mock_now:
            mock_now.side_effect = now_sequence(base, 1, 2, 3)
            submit_city_capture_answer(rq, p1, rq.correct_answer)  # dev 0 -> first
            submit_city_capture_answer(rq, p2, rq.correct_answer + 1)  # dev 1 -> second
            submit_city_capture_answer(rq, p3, rq.correct_answer + 5)

        round_.refresh_from_db()
        self.assertEqual(round_.winner, p1)
        self.assertEqual(round_.second_place, p2)
        self.assertTrue(round_.rewards_applied)

        p1.refresh_from_db()
        self.assertEqual(p1.score, WIN_REWARD)

        first_right = CaptureRight.objects.get(round=round_, player=p1)
        self.assertEqual((first_right.order, first_right.total, first_right.used), (CaptureRight.FIRST, 2, 0))
        second_right = CaptureRight.objects.get(round=round_, player=p2)
        self.assertEqual((second_right.order, second_right.total, second_right.used), (CaptureRight.SECOND, 1, 0))
        self.assertFalse(CaptureRight.objects.filter(round=round_, player=p3).exists())


class TerritoryChoiceAdjacencyTests(TestCase):
    def setUp(self):
        self.game, self.players = make_initialized_game()
        self.p1, self.p2, self.p3 = self.players
        self.round_ = make_completed_round(self.game, winner=self.p1, second_place=self.p2)

    def test_valid_neighbor_is_choosable(self):
        target = free_neighbor_of(self.p1)
        self.assertIsNotNone(target)
        before_score = target.score
        result = choose_territory(self.round_, self.p1, target)
        self.assertEqual(result.owner_id, self.p1.pk)
        self.assertEqual(result.score, before_score + TERRITORY_SCORE_INCREMENT)

    def test_non_neighbor_is_rejected_when_a_free_neighbor_exists(self):
        target = free_non_neighbor_of(self.p1)
        self.assertIsNotNone(target)
        with self.assertRaises(InvalidInputError):
            choose_territory(self.round_, self.p1, target)
        target.refresh_from_db()
        self.assertIsNone(target.owner)

    def test_exception_allows_any_free_territory_without_a_free_neighbor(self):
        capital_territory = Capital.objects.get(player=self.p1).territory
        for neighbor in capital_territory.neighbors.all():
            neighbor.owner = self.p3
            neighbor.full_clean()
            neighbor.save()

        target = Territory.objects.filter(game=self.game, owner__isnull=True).first()
        self.assertIsNotNone(target)
        result = choose_territory(self.round_, self.p1, target)
        self.assertEqual(result.owner_id, self.p1.pk)

    def test_second_pick_may_be_adjacent_to_the_just_captured_territory(self):
        first_pick = free_neighbor_of(self.p1)
        choose_territory(self.round_, self.p1, first_pick)

        first_pick.refresh_from_db()
        second_target = Territory.objects.filter(
            game=self.game, owner__isnull=True, neighbors=first_pick
        ).first()
        if second_target is not None:
            result = choose_territory(self.round_, self.p1, second_target)
            self.assertEqual(result.owner_id, self.p1.pk)


class CaptureRightDenialTests(TestCase):
    def setUp(self):
        self.game, self.players = make_initialized_game()
        self.p1, self.p2, self.p3 = self.players
        self.round_ = make_completed_round(self.game, winner=self.p1, second_place=self.p2)

    def test_player_without_rights_is_denied(self):
        target = free_neighbor_of(self.p3)
        with self.assertRaises(InvalidStateError):
            choose_territory(self.round_, self.p3, target)

    def test_second_place_cannot_choose_before_first_finishes(self):
        target = free_neighbor_of(self.p2)
        self.assertIsNotNone(target)
        with self.assertRaises(InvalidStateError):
            choose_territory(self.round_, self.p2, target)

    def test_second_place_can_choose_once_first_is_done(self):
        right = CaptureRight.objects.get(round=self.round_, player=self.p1)
        right.used = right.total
        right.save()

        target = free_neighbor_of(self.p2)
        self.assertIsNotNone(target)
        result = choose_territory(self.round_, self.p2, target)
        self.assertEqual(result.owner_id, self.p2.pk)

    def test_exceeding_the_granted_count_is_denied(self):
        right = CaptureRight.objects.get(round=self.round_, player=self.p1)
        first = free_neighbor_of(self.p1)
        choose_territory(self.round_, self.p1, first)
        right.refresh_from_db()
        self.assertEqual(right.used, 1)

        second = pick_choosable_target(self.p1)
        choose_territory(self.round_, self.p1, second)
        right.refresh_from_db()
        self.assertEqual(right.used, 2)

        third = Territory.objects.filter(game=self.game, owner__isnull=True).first()
        with self.assertRaises(InvalidStateError):
            choose_territory(self.round_, self.p1, third)

    def test_a_territory_that_is_not_free_is_denied_and_does_not_spend_a_right(self):
        already_owned = Territory.objects.filter(game=self.game, owner__isnull=False).first()
        right = CaptureRight.objects.get(round=self.round_, player=self.p1)
        with self.assertRaises(InvalidStateError):
            choose_territory(self.round_, self.p1, already_owned)
        right.refresh_from_db()
        self.assertEqual(right.used, 0)


class CaptureScoringTests(TestCase):
    def setUp(self):
        self.game, self.players = make_initialized_game()
        self.p1, self.p2, self.p3 = self.players
        self.round_ = make_completed_round(self.game, winner=self.p1, second_place=self.p2)

    def test_first_capture_scores_from_zero_and_rewards_both_ranks(self):
        p1_before = self.p1.score
        p2_before = self.p2.score

        first_target = free_neighbor_of(self.p1)
        self.assertEqual(first_target.score, 0)
        choose_territory(self.round_, self.p1, first_target)
        first_target.refresh_from_db()
        self.p1.refresh_from_db()
        self.assertEqual(first_target.score, TERRITORY_SCORE_INCREMENT)
        self.assertEqual(self.p1.score, p1_before + TERRITORY_SCORE_INCREMENT * CAPTURE_REWARD_MULTIPLIER)

        right = CaptureRight.objects.get(round=self.round_, player=self.p1)
        right.used = right.total
        right.save()

        second_target = free_neighbor_of(self.p2)
        choose_territory(self.round_, self.p2, second_target)
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.score, p2_before + TERRITORY_SCORE_INCREMENT * CAPTURE_REWARD_MULTIPLIER)

    def test_capturing_does_not_double_count_another_players_score(self):
        p3_before = self.p3.score
        target = free_neighbor_of(self.p1)
        choose_territory(self.round_, self.p1, target)
        self.p3.refresh_from_db()
        self.assertEqual(self.p3.score, p3_before)


class CapturePhaseAdvancementTests(TestCase):
    def setUp(self):
        self.game, self.players = make_initialized_game()
        self.p1, self.p2, self.p3 = self.players
        make_numeric_questions(1, start_answer=10)
        self.round_ = make_completed_round(self.game, winner=self.p1, second_place=self.p2)

    def test_blocked_while_rights_remain(self):
        self.assertIsNone(try_advance_capture_phase(self.game))
        self.assertEqual(self.game.rounds.count(), 1)

    def test_creates_next_city_capture_once_rights_are_used(self):
        for right in CaptureRight.objects.filter(round=self.round_):
            for _ in range(right.total):
                target = pick_choosable_target(right.player)
                choose_territory(self.round_, right.player, target)

        next_round = try_advance_capture_phase(self.game)
        self.assertIsNotNone(next_round)
        self.assertEqual(next_round.number, 2)
        self.assertEqual(next_round.type, Round.CITY_CAPTURE)
        self.assertEqual(next_round.free_territories_at_start, free_territory_count(self.game))

    def test_ends_when_the_map_is_full(self):
        for right in CaptureRight.objects.filter(round=self.round_):
            for _ in range(right.total):
                target = pick_choosable_target(right.player)
                choose_territory(self.round_, right.player, target)

        remaining = list(Territory.objects.filter(game=self.game, owner__isnull=True))
        for territory in remaining:
            territory.owner = self.p3
            territory.score = 1
            territory.full_clean()
            territory.save()

        self.assertEqual(free_territory_count(self.game), 0)
        self.assertIsNone(try_advance_capture_phase(self.game))
        self.assertEqual(self.game.rounds.count(), 1)
        self.game.refresh_from_db()
        self.assertTrue(self.game.is_active())


class IncompleteSecondPlaceTests(TestCase):
    def test_unresolved_second_place_grants_no_second_right_and_keeps_first_intact(self):
        game, players = make_initialized_game()
        p1, p2, p3 = players
        round_ = Round.objects.create(
            game=game,
            number=1,
            type=Round.CITY_CAPTURE,
            status=Round.COMPLETED,
            winner=p1,
            second_place=None,
            required_places=2,
            free_territories_at_start=9,
            incomplete_reason=Round.BANK_EXHAUSTED,
            completed_at=timezone.now(),
            rewards_applied=True,
        )
        CaptureRight.objects.create(round=round_, player=p1, order=CaptureRight.FIRST, total=2)

        self.assertFalse(CaptureRight.objects.filter(round=round_, order=CaptureRight.SECOND).exists())
        right = CaptureRight.objects.get(round=round_, player=p1)
        self.assertEqual(right.total, 2)

        target = free_neighbor_of(p1)
        result = choose_territory(round_, p1, target)
        self.assertEqual(result.owner_id, p1.pk)
