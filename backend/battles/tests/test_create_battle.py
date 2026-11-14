from django.test import TestCase

from games.models import Game, Round
from games.services import InvalidInputError, InvalidStateError
from questions.tests import make_choice_questions
from territories.models import Territory

from battles.models import Battle
from battles.services import create_battle
from battles.tests import make_fully_captured_game, owned_neighbor_of, owned_non_neighbor_of


class CreateBattlePreconditionTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(2)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)

    def test_requires_an_active_game(self):
        self.game.status = Game.COMPLETED
        self.game.save()
        with self.assertRaises(InvalidStateError):
            create_battle(self.attacker, self.target)

    def test_requires_the_whole_map_to_be_captured(self):
        # Free some territory that isn't the target and isn't the attacker's own
        # (freeing one of the attacker's territories could coincidentally remove
        # the only adjacency bridge to the target, breaking an unrelated check).
        unrelated_territory = (
            Territory.objects.filter(game=self.game)
            .exclude(pk=self.target.pk)
            .exclude(owner=self.attacker)
            .first()
        )
        unrelated_territory.owner = None
        unrelated_territory.full_clean()
        unrelated_territory.save()
        with self.assertRaises(InvalidStateError):
            create_battle(self.attacker, self.target)

    def test_rejected_while_a_round_is_unfinished(self):
        Round.objects.create(game=self.game, number=1, type=Round.CITY_CAPTURE, status=Round.ACTIVE)
        with self.assertRaises(InvalidStateError):
            create_battle(self.attacker, self.target)

class CreateBattleEmptyChoiceBankTests(TestCase):
    """Its own class, with no `make_choice_questions` call anywhere in it,
    so the global `ChoiceQuestion` bank is genuinely empty for this test."""

    def test_rejected_without_an_unused_choice_question(self):
        game, players = make_fully_captured_game()
        attacker = players[0]
        target = owned_neighbor_of(attacker)
        with self.assertRaises(InvalidStateError):
            create_battle(attacker, target)
        self.assertEqual(Battle.objects.filter(game=game).count(), 0)


class CreateBattleTargetValidationTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(2)
        self.attacker = self.players[0]

    def test_own_territory_is_rejected(self):
        own = Territory.objects.filter(game=self.game, owner=self.attacker).first()
        with self.assertRaises(InvalidInputError):
            create_battle(self.attacker, own)

    def test_free_territory_is_rejected(self):
        target = owned_neighbor_of(self.attacker)
        target.owner = None
        target.full_clean()
        target.save()
        with self.assertRaises(InvalidInputError):
            create_battle(self.attacker, target)

    def test_territory_from_another_game_is_rejected(self):
        other_game, other_players = make_fully_captured_game()
        make_choice_questions(2)
        other_target = owned_neighbor_of(other_players[0])
        with self.assertRaises(InvalidInputError):
            create_battle(self.attacker, other_target)

    def test_non_adjacent_target_is_rejected(self):
        target = owned_non_neighbor_of(self.attacker)
        if target is None:
            self.skipTest('No non-adjacent enemy territory exists for this random map/capital layout.')
        with self.assertRaises(InvalidInputError):
            create_battle(self.attacker, target)

    def test_mismatched_defender_is_rejected(self):
        target = owned_neighbor_of(self.attacker)
        wrong_defender = next(
            p for p in self.players if p.pk not in (self.attacker.pk, target.owner_id)
        )
        with self.assertRaises(InvalidInputError):
            create_battle(self.attacker, target, defender=wrong_defender)

    def test_explicit_correct_defender_is_accepted(self):
        target = owned_neighbor_of(self.attacker)
        battle = create_battle(self.attacker, target, defender=target.owner)
        self.assertEqual(battle.defender_id, target.owner_id)


class CreateBattleSuccessTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(2)
        self.attacker = self.players[0]
        self.target = owned_neighbor_of(self.attacker)

    def test_creates_pending_battle_with_first_choice_question(self):
        battle = create_battle(self.attacker, self.target)
        self.assertEqual(battle.status, Battle.PENDING)
        self.assertEqual(battle.attacker, self.attacker)
        self.assertEqual(battle.defender, self.target.owner)
        self.assertEqual(battle.territory, self.target)
        self.assertEqual(battle.battle_questions.count(), 1)
        first_question = battle.battle_questions.get(sequence=1)
        self.assertEqual(first_question.question_type, 'choice')
        self.assertIsNotNone(first_question.choice_question)
        self.assertIsNone(first_question.started_at)

    def test_capital_target_is_a_capital_attack(self):
        for defender in self.players:
            capital_territory = defender.capital.territory
            attacker = next(
                (p for p in self.players if p.pk != defender.pk and capital_territory.neighbors.filter(owner=p).exists()),
                None,
            )
            if attacker is not None:
                battle = create_battle(attacker, capital_territory)
                self.assertEqual(battle.type, Battle.CAPITAL_ATTACK)
                return
        self.skipTest('No capital territory is adjacent to another player on this random layout.')

    def test_ordinary_target_is_a_battle(self):
        ordinary_target = (
            Territory.objects.filter(game=self.game, neighbors__owner=self.attacker)
            .exclude(owner=self.attacker)
            .exclude(capital__isnull=False)
            .distinct()
            .first()
        )
        if ordinary_target is None:
            self.skipTest('Every enemy neighbor of this attacker happens to be a capital on this random layout.')
        battle = create_battle(self.attacker, ordinary_target)
        self.assertEqual(battle.type, Battle.BATTLE)
