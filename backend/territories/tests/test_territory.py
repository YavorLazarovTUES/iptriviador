from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player
from territories.models import Territory


class TerritoryModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()

    def test_create_territory_defaults(self):
        territory = Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        self.assertIsNone(territory.owner)
        self.assertEqual(territory.score, 0)
        self.assertEqual(list(self.game.territories.all()), [territory])

    def test_same_name_allowed_in_different_games(self):
        other_game = Game.objects.create()
        Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        Territory.objects.create(game=other_game, name='Northgate', slug='northgate')
        self.assertEqual(Territory.objects.filter(name='Northgate').count(), 2)

    def test_name_must_be_unique_within_a_game(self):
        Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Territory.objects.create(game=self.game, name='Northgate', slug='other-slug')

    def test_slug_must_be_unique_within_a_game(self):
        Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Territory.objects.create(game=self.game, name='Other', slug='northgate')

    def test_score_cannot_be_negative(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Territory.objects.create(game=self.game, name='Northgate', slug='northgate', score=-1)

    def test_owner_can_be_none(self):
        territory = Territory(game=self.game, name='Northgate', slug='northgate')
        territory.full_clean()

    def test_owner_must_belong_to_the_same_game(self):
        other_game = Game.objects.create()
        user = make_user()
        other_player = Player.objects.create(game=other_game, user=user, color=Player.RED)
        territory = Territory(game=self.game, name='Northgate', slug='northgate', owner=other_player)
        with self.assertRaises(ValidationError):
            territory.full_clean()

    def test_owner_from_same_game_is_valid(self):
        user = make_user()
        player = Player.objects.create(game=self.game, user=user, color=Player.RED)
        territory = Territory(game=self.game, name='Northgate', slug='northgate', owner=player)
        territory.full_clean()

    def test_deleting_game_deletes_territories(self):
        territory = Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        self.game.delete()
        self.assertFalse(Territory.objects.filter(pk=territory.pk).exists())

    def test_deleting_owner_sets_owner_to_null(self):
        user = make_user()
        player = Player.objects.create(game=self.game, user=user, color=Player.RED)
        territory = Territory.objects.create(game=self.game, name='Northgate', slug='northgate', owner=player)
        player.delete()
        territory.refresh_from_db()
        self.assertIsNone(territory.owner)


class TerritoryNeighborTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()
        self.north = Territory.objects.create(game=self.game, name='Northgate', slug='northgate')
        self.south = Territory.objects.create(game=self.game, name='Southgate', slug='southgate')

    def test_add_neighbor_is_symmetric(self):
        self.north.add_neighbor(self.south)
        self.assertIn(self.south, self.north.neighbors.all())
        self.assertIn(self.north, self.south.neighbors.all())

    def test_add_neighbor_rejects_self(self):
        with self.assertRaises(ValidationError):
            self.north.add_neighbor(self.north)

    def test_add_neighbor_rejects_different_game(self):
        other_game = Game.objects.create()
        other_territory = Territory.objects.create(game=other_game, name='Eastgate', slug='eastgate')
        with self.assertRaises(ValidationError):
            self.north.add_neighbor(other_territory)
