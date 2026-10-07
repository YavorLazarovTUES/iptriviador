from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player


class GameModelTests(TestCase):
    def test_create_game_defaults(self):
        game = Game.objects.create()
        self.assertEqual(game.status, Game.WAITING)
        self.assertIsNotNone(game.created_at)

    def test_is_active_and_is_completed(self):
        game = Game.objects.create()
        self.assertFalse(game.is_active())
        self.assertFalse(game.is_completed())

        game.status = Game.ACTIVE
        self.assertTrue(game.is_active())
        self.assertFalse(game.is_completed())

        game.status = Game.COMPLETED
        self.assertFalse(game.is_active())
        self.assertTrue(game.is_completed())


class GameStartTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()

    def _add_players(self, count):
        colors = [Player.RED, Player.GREEN, Player.BLUE]
        for index in range(count):
            user = make_user(f'player_{index}', nickname=f'Knight{index}')
            Player.objects.create(game=self.game, user=user, color=colors[index])

    def test_game_can_become_active_with_exactly_three_players(self):
        self._add_players(3)
        self.game.status = Game.ACTIVE
        self.game.full_clean()
        self.game.save()
        self.assertEqual(self.game.status, Game.ACTIVE)

    def test_game_cannot_become_active_with_fewer_than_three_players(self):
        self._add_players(2)
        self.game.status = Game.ACTIVE
        with self.assertRaises(ValidationError):
            self.game.full_clean()


class GameCurrentRoundTests(TestCase):
    def test_get_current_round_returns_round_with_highest_number(self):
        game = Game.objects.create()
        game.rounds.create(number=1, type='city_capture')
        latest = game.rounds.create(number=3, type='battle')
        game.rounds.create(number=2, type='bonus')
        self.assertEqual(game.get_current_round(), latest)

    def test_get_current_round_returns_none_without_rounds(self):
        game = Game.objects.create()
        self.assertIsNone(game.get_current_round())
