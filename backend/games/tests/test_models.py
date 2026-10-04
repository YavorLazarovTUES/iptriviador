from django.test import TestCase

from accounts.tests import make_user
from games.models import Game, GamePlayer, Round, RoundAnswer
from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


def make_choice_question(category):
    question = ChoiceQuestion.objects.create(category=category, text='2 + 2?')
    for index in range(4):
        AnswerOption.objects.create(question=question, text=str(index), is_correct=(index == 0))
    return question


class GameModelTests(TestCase):
    def test_create_game_defaults(self):
        user = make_user()
        game = Game.objects.create(created_by=user)
        self.assertEqual(game.status, Game.WAITING)
        self.assertIsNotNone(game.created_at)
        self.assertIsNone(game.started_at)
        self.assertIsNone(game.finished_at)


class GamePlayerModelTests(TestCase):
    def test_create_game_player_defaults(self):
        user = make_user()
        game = Game.objects.create(created_by=user)
        player = GamePlayer.objects.create(game=game, user=user, player_order=1)
        self.assertEqual(player.score, 0)
        self.assertTrue(player.is_active)
        self.assertIsNotNone(player.joined_at)
        self.assertEqual(list(game.players.all()), [player])


class RoundModelTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.game = Game.objects.create(created_by=self.user)
        self.category = Category.objects.create(name='Geography')

    def test_create_choice_round(self):
        question = make_choice_question(self.category)
        round_ = Round.objects.create(
            game=self.game,
            number=1,
            question_type=Round.CHOICE,
            choice_question=question,
        )
        round_.full_clean()
        self.assertEqual(round_.status, Round.PENDING)
        self.assertEqual(list(self.game.rounds.all()), [round_])

    def test_create_numeric_round(self):
        question = NumericQuestion.objects.create(category=self.category, text='2 + 2?', correct_answer=4)
        round_ = Round.objects.create(
            game=self.game,
            number=1,
            question_type=Round.NUMERIC,
            numeric_question=question,
        )
        round_.full_clean()


class RoundAnswerModelTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.game = Game.objects.create(created_by=self.user)
        self.player = GamePlayer.objects.create(game=self.game, user=self.user, player_order=1)
        self.category = Category.objects.create(name='Geography')
        self.question = make_choice_question(self.category)
        self.round = Round.objects.create(
            game=self.game,
            number=1,
            question_type=Round.CHOICE,
            choice_question=self.question,
        )

    def test_create_answer_with_selected_option(self):
        option = self.question.answer_options.first()
        answer = RoundAnswer.objects.create(round=self.round, player=self.player, selected_option=option)
        answer.full_clean()
        self.assertEqual(answer.points_awarded, 0)
        self.assertIsNone(answer.is_correct)
        self.assertEqual(list(self.round.answers.all()), [answer])
        self.assertEqual(list(self.player.answers.all()), [answer])

    def test_create_answer_with_numeric_value(self):
        answer = RoundAnswer.objects.create(round=self.round, player=self.player, numeric_value=42)
        answer.full_clean()
