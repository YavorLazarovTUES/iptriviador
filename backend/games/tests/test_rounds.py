from django.utils import timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player, Round


class RoundModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()

    def test_create_round_defaults(self):
        round_ = Round.objects.create(game=self.game, number=1, type=Round.CITY_CAPTURE)
        self.assertEqual(round_.status, Round.PENDING)
        self.assertIsNone(round_.winner)
        self.assertIsNone(round_.completed_at)
        self.assertEqual(list(self.game.rounds.all()), [round_])

    def test_complete_round_records_winner_and_completed_at(self):
        user = make_user()
        player = Player.objects.create(game=self.game, user=user, color=Player.RED)
        round_ = Round.objects.create(game=self.game, number=1, type=Round.BATTLE)

        round_.status = Round.COMPLETED
        round_.winner = player
        round_.completed_at = timezone.now()
        round_.full_clean()
        round_.save()

        self.assertEqual(round_.status, Round.COMPLETED)
        self.assertEqual(round_.winner, player)
        self.assertIsNotNone(round_.completed_at)

    def test_completed_round_requires_completed_at(self):
        round_ = Round(game=self.game, number=1, type=Round.BATTLE, status=Round.COMPLETED)
        with self.assertRaises(ValidationError):
            round_.full_clean()

    def test_winner_must_belong_to_the_same_game(self):
        other_game = Game.objects.create()
        user = make_user()
        other_player = Player.objects.create(game=other_game, user=user, color=Player.RED)
        round_ = Round(
            game=self.game,
            number=1,
            type=Round.BATTLE,
            status=Round.COMPLETED,
            winner=other_player,
            completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            round_.full_clean()

    def test_only_one_active_round_per_game(self):
        Round.objects.create(game=self.game, number=1, type=Round.BATTLE, status=Round.ACTIVE)
        second = Round(game=self.game, number=2, type=Round.BONUS, status=Round.ACTIVE)
        with self.assertRaises(ValidationError):
            second.full_clean()


class RoundConstraintTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()

    def test_round_number_must_be_unique_within_a_game(self):
        Round.objects.create(game=self.game, number=1, type=Round.CITY_CAPTURE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Round.objects.create(game=self.game, number=1, type=Round.BATTLE)

    def test_deleting_game_deletes_rounds(self):
        round_ = Round.objects.create(game=self.game, number=1, type=Round.CITY_CAPTURE)
        self.game.delete()
        self.assertFalse(Round.objects.filter(pk=round_.pk).exists())

    def test_deleting_winner_sets_winner_to_null(self):
        user = make_user()
        player = Player.objects.create(game=self.game, user=user, color=Player.RED)
        round_ = Round.objects.create(
            game=self.game,
            number=1,
            type=Round.BATTLE,
            status=Round.COMPLETED,
            winner=player,
            completed_at=timezone.now(),
        )
        player.delete()
        round_.refresh_from_db()
        self.assertIsNone(round_.winner)


class GameCurrentRoundOrderingTests(TestCase):
    def test_current_round_is_highest_number(self):
        game = Game.objects.create()
        game.rounds.create(number=1, type=Round.CITY_CAPTURE)
        game.rounds.create(number=2, type=Round.BATTLE)
        latest = game.rounds.create(number=3, type=Round.CAPITAL_ATTACK)
        self.assertEqual(game.get_current_round(), latest)
