import itertools
import random
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, Player
from territories.map_definition import get_map_definition
from territories.models import Capital, Territory
from territories.services import initialize_game


def make_game_with_players(count=3):
    game = Game.objects.create()
    colors = [Player.RED, Player.GREEN, Player.BLUE, 'yellow']
    players = []
    for index in range(count):
        user = make_user(f'player_{index}', nickname=f'Knight{index}')
        players.append(Player.objects.create(game=game, user=user, color=colors[index]))
    return game, players


class InitializeGameSuccessTests(TestCase):
    def setUp(self):
        self.game, self.players = make_game_with_players(3)
        self.definition = get_map_definition()

    def test_activates_the_game(self):
        initialize_game(self.game)
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, Game.ACTIVE)

    def test_creates_exactly_the_project_map_territories(self):
        initialize_game(self.game)
        territories = list(self.game.territories.all())
        self.assertEqual(len(territories), len(self.definition['territories']))
        expected_names = {entry['name'] for entry in self.definition['territories']}
        self.assertEqual({t.name for t in territories}, expected_names)

    def test_neighbors_match_the_project_definition(self):
        initialize_game(self.game)
        by_slug = {t.slug: t for t in self.game.territories.all()}
        for slug, expected_neighbor_slugs in self.definition['adjacency'].items():
            actual_neighbor_slugs = {n.slug for n in by_slug[slug].neighbors.all()}
            self.assertEqual(actual_neighbor_slugs, expected_neighbor_slugs)

    def test_creates_exactly_three_capitals_one_per_player(self):
        initialize_game(self.game)
        capitals = Capital.objects.filter(territory__game=self.game)
        self.assertEqual(capitals.count(), 3)
        self.assertEqual({c.player_id for c in capitals}, {p.id for p in self.players})
        for capital in capitals:
            self.assertEqual(capital.health, Capital.MAX_HEALTH)
            self.assertEqual(capital.territory.owner_id, capital.player_id)

    def test_capitals_are_mutually_non_neighboring(self):
        initialize_game(self.game)
        capital_territories = [c.territory for c in Capital.objects.filter(territory__game=self.game)]
        for a, b in itertools.combinations(capital_territories, 2):
            self.assertNotIn(b, a.neighbors.all())

    def test_non_capital_territories_are_neutral_with_zero_score(self):
        initialize_game(self.game)
        capital_slugs = {c.territory.slug for c in Capital.objects.filter(territory__game=self.game)}
        for territory in self.game.territories.all():
            self.assertEqual(territory.score, 0)
            if territory.slug not in capital_slugs:
                self.assertIsNone(territory.owner)

    def test_player_scores_are_unchanged(self):
        initialize_game(self.game)
        for player in self.players:
            player.refresh_from_db()
            self.assertEqual(player.score, 0)

    def test_no_rounds_are_created(self):
        initialize_game(self.game)
        self.assertEqual(self.game.rounds.count(), 0)

    def test_randomly_selects_among_the_available_capital_triples(self):
        with mock.patch('territories.services.random.choice', wraps=random.choice) as choice_mock:
            initialize_game(self.game)
        self.assertTrue(choice_mock.called)


class InitializeGameValidationTests(TestCase):
    def test_rejects_too_few_players(self):
        game, _players = make_game_with_players(2)
        with self.assertRaises(ValidationError):
            initialize_game(game)
        self.assertEqual(game.territories.count(), 0)

    def test_rejects_too_many_players(self):
        game, _players = make_game_with_players(4)
        with self.assertRaises(ValidationError):
            initialize_game(game)
        self.assertEqual(game.territories.count(), 0)

    def test_rejects_an_already_active_game(self):
        game, _players = make_game_with_players(3)
        initialize_game(game)
        with self.assertRaises(ValidationError):
            initialize_game(game)

    def test_rejects_a_completed_game(self):
        game = Game.objects.create(status=Game.COMPLETED)
        with self.assertRaises(ValidationError):
            initialize_game(game)

    def test_second_initialization_attempt_does_not_duplicate_data(self):
        game, _players = make_game_with_players(3)
        initialize_game(game)
        territory_count_before = game.territories.count()
        capital_count_before = Capital.objects.filter(territory__game=game).count()

        with self.assertRaises(ValidationError):
            initialize_game(game)

        self.assertEqual(game.territories.count(), territory_count_before)
        self.assertEqual(Capital.objects.filter(territory__game=game).count(), capital_count_before)

    def test_failed_attempt_leaves_no_partial_territories(self):
        game, _players = make_game_with_players(3)
        with mock.patch('territories.services.find_capital_triples', return_value=[]):
            with self.assertRaises(ValidationError):
                initialize_game(game)

        game.refresh_from_db()
        self.assertEqual(game.status, Game.WAITING)
        self.assertEqual(game.territories.count(), 0)
        self.assertEqual(Capital.objects.filter(territory__game=game).count(), 0)

    def test_failed_attempt_during_territory_creation_rolls_back(self):
        game, _players = make_game_with_players(3)
        with mock.patch.object(Territory, 'full_clean', side_effect=ValidationError('boom')):
            with self.assertRaises(ValidationError):
                initialize_game(game)

        game.refresh_from_db()
        self.assertEqual(game.status, Game.WAITING)
        self.assertEqual(game.territories.count(), 0)
