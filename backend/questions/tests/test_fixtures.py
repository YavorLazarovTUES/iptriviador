from django.test import TestCase

from questions.models import AnswerOption, Category, ChoiceQuestion, NumericQuestion


class QuestionBankFixtureTests(TestCase):
    fixtures = ['questions/question_bank.json']

    def test_loads_expected_counts(self):
        self.assertEqual(Category.objects.count(), 6)
        self.assertEqual(ChoiceQuestion.objects.count(), 12)
        self.assertEqual(AnswerOption.objects.count(), 48)
        self.assertEqual(NumericQuestion.objects.count(), 12)

    def test_every_choice_question_has_four_answer_options(self):
        for question in ChoiceQuestion.objects.all():
            self.assertEqual(question.answer_options.count(), 4)

    def test_every_choice_question_has_exactly_one_correct_answer(self):
        for question in ChoiceQuestion.objects.all():
            self.assertEqual(question.answer_options.filter(is_correct=True).count(), 1)

    def test_every_numeric_question_has_an_integer_answer(self):
        for question in NumericQuestion.objects.all():
            self.assertIsInstance(question.correct_answer, int)
