from django.core.exceptions import ValidationError
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class BaseQuestion(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='%(class)ss',
    )
    text = models.TextField()

    class Meta:
        abstract = True

    def __str__(self):
        return self.text


class ChoiceQuestion(BaseQuestion):
    REQUIRED_ANSWER_COUNT = 4

    def clean(self):
        super().clean()
        if self.pk:
            options = list(self.answer_options.all())
            if len(options) != self.REQUIRED_ANSWER_COUNT:
                raise ValidationError(
                    f'A choice question must have exactly {self.REQUIRED_ANSWER_COUNT} answer options.'
                )
            correct_count = sum(1 for option in options if option.is_correct)
            if correct_count != 1:
                raise ValidationError('A choice question must have exactly one correct answer option.')


class NumericQuestion(BaseQuestion):
    correct_answer = models.IntegerField()


class AnswerOption(models.Model):
    question = models.ForeignKey(
        ChoiceQuestion,
        on_delete=models.CASCADE,
        related_name='answer_options',
    )
    text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.text
