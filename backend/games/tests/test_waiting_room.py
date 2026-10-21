from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player, WaitingEntry
from games.waiting_room import form_game


def make_waiting(count):
    for i in range(count):
        WaitingEntry.objects.create(user=make_user(f'user{i}', nickname=f'User{i}'))


class FormGameTests(TestCase):
    def test_five_waiting(self):
        make_waiting(5)
        game = form_game()
        self.assertEqual(game.status, Game.WAITING)
        players = Player.objects.filter(game=game)
        self.assertEqual(players.count(), 3)
        self.assertEqual({p.color for p in players}, {Player.RED, Player.GREEN, Player.BLUE})
        self.assertTrue(all(p.score == 0 for p in players))
        self.assertEqual(WaitingEntry.objects.count(), 2)
        self.assertFalse(WaitingEntry.objects.filter(user__in=[p.user for p in players]).exists())

    def test_two_waiting(self):
        make_waiting(2)
        self.assertIsNone(form_game())
        self.assertEqual(Game.objects.count(), 0)
        self.assertEqual(Player.objects.count(), 0)
        self.assertEqual(WaitingEntry.objects.count(), 2)
