from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player
from territories.models import Capital, Territory


class CapitalModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create()
        self.user = make_user()
        self.player = Player.objects.create(game=self.game, user=self.user, color=Player.RED)
        self.territory = Territory.objects.create(
            game=self.game, name='Northgate', slug='northgate', owner=self.player
        )

    def test_create_capital_defaults_to_full_health(self):
        capital = Capital.objects.create(territory=self.territory, player=self.player)
        self.assertEqual(capital.health, Capital.MAX_HEALTH)

    def test_health_above_max_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Capital.objects.create(territory=self.territory, player=self.player, health=Capital.MAX_HEALTH + 1)

    def test_health_below_min_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Capital.objects.create(territory=self.territory, player=self.player, health=Capital.MIN_HEALTH - 1)

    def test_player_can_have_at_most_one_capital(self):
        Capital.objects.create(territory=self.territory, player=self.player)
        other_territory = Territory.objects.create(
            game=self.game, name='Southgate', slug='southgate', owner=self.player
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Capital.objects.create(territory=other_territory, player=self.player)

    def test_territory_can_have_at_most_one_capital(self):
        Capital.objects.create(territory=self.territory, player=self.player)
        other_user = make_user('player_two', nickname='RiverKnight')
        other_player = Player.objects.create(game=self.game, user=other_user, color=Player.GREEN)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Capital.objects.create(territory=self.territory, player=other_player)

    def test_territory_and_player_must_belong_to_the_same_game(self):
        other_game = Game.objects.create()
        other_user = make_user('player_two', nickname='RiverKnight')
        other_player = Player.objects.create(game=other_game, user=other_user, color=Player.RED)
        capital = Capital(territory=self.territory, player=other_player)
        with self.assertRaises(ValidationError):
            capital.full_clean()

    def test_capital_territory_must_be_owned_by_the_capital_player(self):
        other_user = make_user('player_two', nickname='RiverKnight')
        other_player = Player.objects.create(game=self.game, user=other_user, color=Player.GREEN)
        capital = Capital(territory=self.territory, player=other_player)
        with self.assertRaises(ValidationError):
            capital.full_clean()

    def test_deleting_territory_deletes_capital(self):
        capital = Capital.objects.create(territory=self.territory, player=self.player)
        self.territory.delete()
        self.assertFalse(Capital.objects.filter(pk=capital.pk).exists())

    def test_deleting_player_deletes_capital(self):
        capital = Capital.objects.create(territory=self.territory, player=self.player)
        self.player.delete()
        self.assertFalse(Capital.objects.filter(pk=capital.pk).exists())

    def test_player_without_a_capital_has_clear_access(self):
        self.assertIsNone(getattr(self.player, 'capital', None))
        with self.assertRaises(ObjectDoesNotExist):
            Capital.objects.get(player=self.player)
