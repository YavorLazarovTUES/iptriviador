from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion


class Game(models.Model):
    WAITING = 'waiting'
    IN_PROGRESS = 'in_progress'
    FINISHED = 'finished'
    CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (WAITING, 'Waiting'),
        (IN_PROGRESS, 'In Progress'),
        (FINISHED, 'Finished'),
        (CANCELLED, 'Cancelled'),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='games_created',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Game #{self.pk} ({self.status})'


class GamePlayer(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='players')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='game_players',
    )
    player_order = models.PositiveSmallIntegerField()
    score = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['player_order']
        constraints = [
            models.UniqueConstraint(fields=['game', 'user'], name='unique_player_per_game'),
            models.UniqueConstraint(fields=['game', 'player_order'], name='unique_order_per_game'),
        ]

    def __str__(self):
        return f'{self.user} in {self.game}'


class Round(models.Model):
    PENDING = 'pending'
    OPEN = 'open'
    CLOSED = 'closed'
    EVALUATED = 'evaluated'

    ROUND_STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (OPEN, 'Open'),
        (CLOSED, 'Closed'),
        (EVALUATED, 'Evaluated'),
    ]

    CHOICE = 'choice'
    NUMERIC = 'numeric'

    QUESTION_TYPE_CHOICES = [
        (CHOICE, 'Choice'),
        (NUMERIC, 'Numeric'),
    ]

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='rounds')
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=ROUND_STATUS_CHOICES, default=PENDING)
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES)
    choice_question = models.ForeignKey(
        ChoiceQuestion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='rounds',
    )
    numeric_question = models.ForeignKey(
        NumericQuestion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='rounds',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['game', 'number']
        constraints = [
            models.UniqueConstraint(fields=['game', 'number'], name='unique_round_number_per_game'),
        ]

    def clean(self):
        super().clean()
        if self.question_type == self.CHOICE:
            if not self.choice_question_id or self.numeric_question_id:
                raise ValidationError('A choice round must have a choice question and no numeric question.')
        elif self.question_type == self.NUMERIC:
            if not self.numeric_question_id or self.choice_question_id:
                raise ValidationError('A numeric round must have a numeric question and no choice question.')

    def __str__(self):
        return f'Round {self.number} of {self.game}'


class RoundAnswer(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='answers')
    player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='answers')
    selected_option = models.ForeignKey(
        AnswerOption,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='round_answers',
    )
    numeric_value = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    points_awarded = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['round', 'player'], name='unique_answer_per_round_per_player'),
        ]

    def clean(self):
        super().clean()
        if self.selected_option_id and self.numeric_value is not None:
            raise ValidationError('A round answer cannot have both a selected option and a numeric value.')

    def __str__(self):
        return f'Answer by {self.player} in {self.round}'
