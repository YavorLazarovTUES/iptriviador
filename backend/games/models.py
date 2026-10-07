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
        if self.status == self.COMPLETED and self.completed_at is None:
            raise ValidationError('A completed round must have completed_at set.')
        if self.status == self.ACTIVE:
            active_rounds = self.game.rounds.filter(status=self.ACTIVE)
            if self.pk:
                active_rounds = active_rounds.exclude(pk=self.pk)
            if active_rounds.exists():
                raise ValidationError('A game can only have one active round at a time.')

    def __str__(self):
        return f'Round {self.number} of {self.game}'
