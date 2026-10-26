from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Game(models.Model):
    WAITING = 'waiting'
    ACTIVE = 'active'
    COMPLETED = 'completed'

    STATUS_CHOICES = [
        (WAITING, 'Waiting'),
        (ACTIVE, 'Active'),
        (COMPLETED, 'Completed'),
    ]

    REQUIRED_PLAYER_COUNT = 3

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=WAITING)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.pk and self.status == self.ACTIVE:
            if self.players.count() != self.REQUIRED_PLAYER_COUNT:
                raise ValidationError(
                    f'A game can only be active with exactly {self.REQUIRED_PLAYER_COUNT} players.'
                )

    def get_current_round(self):
        return self.rounds.order_by('-number').first()

    def is_active(self):
        return self.status == self.ACTIVE

    def is_completed(self):
        return self.status == self.COMPLETED

    def __str__(self):
        return f'Game #{self.pk} ({self.status})'


class Player(models.Model):
    RED = 'red'
    GREEN = 'green'
    BLUE = 'blue'

    COLOR_CHOICES = [
        (RED, 'Red'),
        (GREEN, 'Green'),
        (BLUE, 'Blue'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='game_players',
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='players')
    score = models.IntegerField(default=0)
    color = models.CharField(max_length=10, choices=COLOR_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'game'], name='unique_user_per_game'),
            models.UniqueConstraint(fields=['game', 'color'], name='unique_color_per_game'),
            models.CheckConstraint(condition=models.Q(score__gte=0), name='player_score_gte_0'),
        ]

    def clean(self):
        super().clean()
        if self.pk is None and self.game_id and self.game.status != Game.WAITING:
            raise ValidationError('Players can only be added to a waiting game.')

    def delete(self, *args, **kwargs):
        if self.game.status != Game.WAITING:
            raise ValidationError('Players can only be removed from a waiting game.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f'{self.user} in {self.game}'


class Round(models.Model):
    CITY_CAPTURE = 'city_capture'
    BATTLE = 'battle'
    CAPITAL_ATTACK = 'capital_attack'
    BONUS = 'bonus'

    TYPE_CHOICES = [
        (CITY_CAPTURE, 'City Capture'),
        (BATTLE, 'Battle'),
        (CAPITAL_ATTACK, 'Capital Attack'),
        (BONUS, 'Bonus'),
    ]

    PENDING = 'pending'
    ACTIVE = 'active'
    COMPLETED = 'completed'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (ACTIVE, 'Active'),
        (COMPLETED, 'Completed'),
    ]

    QUESTION_LIMIT_REACHED = 'question_limit'
    BANK_EXHAUSTED = 'bank_exhausted'

    INCOMPLETE_REASON_CHOICES = [
        (QUESTION_LIMIT_REACHED, 'Question limit reached'),
        (BANK_EXHAUSTED, 'Question bank exhausted'),
    ]

    MAX_QUESTIONS_PER_ROUND = 3
    ANSWER_WINDOW_SECONDS = 10

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='rounds')
    number = models.PositiveIntegerField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    winner = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rounds_won',
    )
    second_place = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rounds_second_place',
    )
    required_places = models.PositiveSmallIntegerField(
        default=1,
        choices=[(1, 'First place only'), (2, 'First and second place')],
    )
    free_territories_at_start = models.PositiveIntegerField(null=True, blank=True)
    incomplete_reason = models.CharField(
        max_length=20, choices=INCOMPLETE_REASON_CHOICES, blank=True, default='',
    )
    rewards_applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['game', 'number']
        constraints = [
            models.UniqueConstraint(fields=['game', 'number'], name='unique_round_number_per_game'),
        ]

    def clean(self):
        super().clean()
        if self.winner_id and self.winner.game_id != self.game_id:
            raise ValidationError('The winner must belong to the same game as the round.')
        if self.second_place_id and self.second_place.game_id != self.game_id:
            raise ValidationError('The second-place player must belong to the same game as the round.')
        if self.second_place_id and self.winner_id and self.second_place_id == self.winner_id:
            raise ValidationError('The second-place player must be different from the winner.')
        if self.status == self.COMPLETED and self.completed_at is None:
            raise ValidationError('A completed round must have completed_at set.')
        if self.status == self.COMPLETED and self.winner_id is None and not self.incomplete_reason:
            raise ValidationError('A completed round without a winner must record an incomplete_reason.')
        if self.status == self.ACTIVE:
            active_rounds = self.game.rounds.filter(status=self.ACTIVE)
            if self.pk:
                active_rounds = active_rounds.exclude(pk=self.pk)
            if active_rounds.exists():
                raise ValidationError('A game can only have one active round at a time.')

    def __str__(self):
        return f'Round {self.number} of {self.game}'


class RoundQuestion(models.Model):
    FIRST_PLACE = 1
    SECOND_PLACE = 2

    TARGET_RANK_CHOICES = [
        (FIRST_PLACE, 'First place'),
        (SECOND_PLACE, 'Second place'),
    ]

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='round_questions')
    sequence = models.PositiveSmallIntegerField()
    target_rank = models.PositiveSmallIntegerField(choices=TARGET_RANK_CHOICES, default=FIRST_PLACE)
    contenders = models.ManyToManyField(Player, related_name='contended_round_questions')
    question = models.ForeignKey(
        'questions.NumericQuestion',
        on_delete=models.PROTECT,
        related_name='round_questions',
    )
    question_text = models.TextField()
    correct_answer = models.IntegerField()
    started_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['round', 'sequence']
        constraints = [
            models.UniqueConstraint(fields=['round', 'sequence'], name='unique_sequence_per_round'),
        ]

    def is_started(self):
        return self.started_at is not None

    def is_open(self, now):
        return self.is_started() and self.resolved_at is None and now < self.deadline

    def __str__(self):
        return f'Question {self.sequence} of {self.round}'


class RoundAnswer(models.Model):
    round_question = models.ForeignKey(RoundQuestion, on_delete=models.CASCADE, related_name='answers')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='round_answers')
    value = models.IntegerField()
    answered_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['round_question', 'player'], name='unique_answer_per_player_per_question'),
        ]

    def clean(self):
        super().clean()
        if self.player_id and self.round_question_id and self.player.game_id != self.round_question.round.game_id:
            raise ValidationError('The answering player must belong to the same game as the round.')

    def elapsed(self):
        return self.answered_at - self.round_question.started_at

    def deviation(self):
        return abs(self.value - self.round_question.correct_answer)

    def __str__(self):
        return f'{self.player} -> {self.value} ({self.round_question})'
