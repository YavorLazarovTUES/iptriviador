from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player


class PlayerModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()
        self.user = make_user()

    def test_create_player_defaults(self):
        player = Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        self.assertEqual(player.score, 0)
        self.assertEqual(list(self.game.players.all()), [player])

    def test_three_players_with_different_users_and_colors(self):
        colors = [Player.RED, Player.GREEN, Player.BLUE]
        for index in range(3):
            user = make_user(f'player_{index}', nickname=f'Knight{index}')
            Player.objects.create(game=self.game, user=user, color=colors[index])
        self.assertEqual(self.game.players.count(), 3)


class PlayerConstraintTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()
        self.user = make_user()

    def test_user_cannot_join_the_same_game_twice(self):
        Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Player.objects.create(game=self.game, user=self.user, color=Player.GREEN)

    def test_color_cannot_repeat_within_a_game(self):
        Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        other_user = make_user('player_two', nickname='ForestKnight')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Player.objects.create(game=self.game, user=other_user, color=Player.RED)

    def test_score_cannot_be_negative(self):
        player = Player(game=self.game, user=self.user, color=Player.RED, score=-1)
        with self.assertRaises(ValidationError):
            player.full_clean()

    def test_deleting_game_deletes_players(self):
        player = Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        self.game.delete()
        self.assertFalse(Player.objects.filter(pk=player.pk).exists())

    def test_deleting_user_deletes_player(self):
        player = Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        self.user.delete()
        self.assertFalse(Player.objects.filter(pk=player.pk).exists())
