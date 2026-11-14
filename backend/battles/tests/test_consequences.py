from django.test import TestCase

from games.services import InvalidStateError
from questions.tests import make_choice_questions
from territories.models import Territory
from territories.services import CAPTURE_REWARD_MULTIPLIER, TERRITORY_SCORE_INCREMENT, WIN_REWARD

from battles.models import Battle
from battles.services import apply_battle_result, create_battle, start_battle, submit_choice_answer
from battles.tests import make_fully_captured_game, owned_neighbor_of


def _finish_with_winner(battle, winner, loser, step=None):
    """Drive the battle's own first question to a one-correct-answer win for `winner`."""
    step = step or battle.battle_questions.get(sequence=1)
    correct_option = step.choice_question.answer_options.get(is_correct=True)
    wrong_option = step.choice_question.answer_options.filter(is_correct=False).first()
    submit_choice_answer(step, winner, correct_option)
    submit_choice_answer(step, loser, wrong_option)
    battle.refresh_from_db()
    return battle


class SuccessfulAttackConsequenceTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(1)
        self.attacker = self.players[0]
        self.target = next(
            t for t in Territory.objects.filter(game=self.game, neighbors__owner=self.attacker)
            .exclude(owner=self.attacker).exclude(capital__isnull=False).distinct()
        )
        self.defender = self.target.owner
        self.attacker_initial_score = self.attacker.score
        self.target_initial_score = self.target.score
        self.battle = start_battle(create_battle(self.attacker, self.target))

    def test_attacker_wins_captures_the_territory_and_increases_its_score(self):
        _finish_with_winner(self.battle, self.attacker, self.defender)
        apply_battle_result(self.battle)

        self.target.refresh_from_db()
        self.attacker.refresh_from_db()
        self.assertEqual(self.target.owner_id, self.attacker.pk)
        self.assertGreater(self.target.score, self.target_initial_score)
        self.assertEqual(self.target.score, self.target_initial_score + TERRITORY_SCORE_INCREMENT)
        expected_reward = WIN_REWARD + self.target.score * CAPTURE_REWARD_MULTIPLIER
        self.assertEqual(self.attacker.score, self.attacker_initial_score + expected_reward)

    def test_defender_wins_preserves_owner_and_score(self):
        defender_initial_score = self.defender.score
        _finish_with_winner(self.battle, self.defender, self.attacker)
        apply_battle_result(self.battle)

        self.target.refresh_from_db()
        self.defender.refresh_from_db()
        self.assertEqual(self.target.owner_id, self.defender.pk)
        self.assertEqual(self.target.score, self.target_initial_score)
        self.assertEqual(self.defender.score, defender_initial_score + WIN_REWARD)

    def test_no_winner_changes_nothing(self):
        step = self.battle.battle_questions.get(sequence=1)
        wrong_a, wrong_b = step.choice_question.answer_options.filter(is_correct=False)[:2]
        submit_choice_answer(step, self.attacker, wrong_a)
        submit_choice_answer(step, self.defender, wrong_b)
        self.battle.refresh_from_db()
        self.assertIsNone(self.battle.winner)
        self.assertEqual(self.battle.status, Battle.COMPLETED)

        apply_battle_result(self.battle)

        self.target.refresh_from_db()
        self.attacker.refresh_from_db()
        self.assertEqual(self.target.owner_id, self.defender.pk)
        self.assertEqual(self.target.score, self.target_initial_score)
        self.assertEqual(self.attacker.score, self.attacker_initial_score)


class CapitalAttackConsequenceTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(1)
        self.defender = None
        self.attacker = None
        for candidate_defender in self.players:
            capital_territory = candidate_defender.capital.territory
            candidate_attacker = next(
                (p for p in self.players if p.pk != candidate_defender.pk
                 and capital_territory.neighbors.filter(owner=p).exists()),
                None,
            )
            if candidate_attacker is not None:
                self.defender = candidate_defender
                self.attacker = candidate_attacker
                self.target = capital_territory
                break
        if self.attacker is None:
            self.skipTest('No capital territory is adjacent to another player on this random layout.')
        self.capital = self.target.capital
        self.capital_health_before = self.capital.health
        self.attacker_initial_score = self.attacker.score
        self.defender_initial_score = self.defender.score
        self.battle = start_battle(create_battle(self.attacker, self.target))

    def test_capital_attack_win_grants_reward_without_touching_the_capital(self):
        _finish_with_winner(self.battle, self.attacker, self.defender)
        apply_battle_result(self.battle)

        self.target.refresh_from_db()
        self.capital.refresh_from_db()
        self.attacker.refresh_from_db()
        self.assertEqual(self.target.owner_id, self.defender.pk)
        self.assertEqual(self.capital.player_id, self.defender.pk)
        self.assertEqual(self.capital.health, self.capital_health_before)
        self.assertEqual(self.attacker.score, self.attacker_initial_score + WIN_REWARD)

    def test_capital_defense_win_also_leaves_the_capital_untouched(self):
        _finish_with_winner(self.battle, self.defender, self.attacker)
        apply_battle_result(self.battle)

        self.target.refresh_from_db()
        self.capital.refresh_from_db()
        self.defender.refresh_from_db()
        self.assertEqual(self.target.owner_id, self.defender.pk)
        self.assertEqual(self.capital.health, self.capital_health_before)
        self.assertEqual(self.defender.score, self.defender_initial_score + WIN_REWARD)


class ApplyBattleResultIntegrityTests(TestCase):
    def setUp(self):
        self.game, self.players = make_fully_captured_game()
        make_choice_questions(1)
        self.attacker = self.players[0]
        self.target = next(
            t for t in Territory.objects.filter(game=self.game, neighbors__owner=self.attacker)
            .exclude(owner=self.attacker).exclude(capital__isnull=False).distinct()
        )
        self.defender = self.target.owner
        self.battle = start_battle(create_battle(self.attacker, self.target))
        _finish_with_winner(self.battle, self.attacker, self.defender)

    def test_cannot_apply_before_completion(self):
        make_choice_questions(1)
        pending_battle = create_battle(self.players[1], owned_neighbor_of(self.players[1]))
        with self.assertRaises(InvalidStateError):
            apply_battle_result(pending_battle)

    def test_repeated_apply_does_not_repeat_the_reward(self):
        apply_battle_result(self.battle)
        self.attacker.refresh_from_db()
        score_after_first_apply = self.attacker.score

        apply_battle_result(self.battle)  # no-op
        self.attacker.refresh_from_db()
        self.assertEqual(self.attacker.score, score_after_first_apply)

    def test_owner_mismatch_refuses_without_partial_result(self):
        # Simulate a different, concurrent battle having already captured
        # the same territory before this one's result is applied.
        self.target.owner = self.players[2]
        self.target.full_clean()
        self.target.save()
        attacker_score_before = self.attacker.score

        with self.assertRaises(InvalidStateError):
            apply_battle_result(self.battle)

        self.battle.refresh_from_db()
        self.attacker.refresh_from_db()
        self.target.refresh_from_db()
        self.assertFalse(self.battle.rewards_applied)
        self.assertEqual(self.attacker.score, attacker_score_before)
        self.assertEqual(self.target.owner_id, self.players[2].pk)
        # The battle's own resolved winner is untouched by the refused apply.
        self.assertEqual(self.battle.winner_id, self.attacker.pk)
