from django.core.exceptions import ValidationError
from django.db import models

from games.models import Game, Player
from questions.models import AnswerOption, ChoiceQuestion, NumericQuestion
from territories.models import Territory


class Battle(models.Model):
    """A fight over one already-owned territory between two of the game's
    three players (M08). Mirrors `games.Round`'s pending/active/completed
    lifecycle and incomplete-reason bookkeeping, but always between exactly
    two players (the attacker and the territory's current owner) rather
    than the whole game.
    """

    BATTLE = 'battle'
    CAPITAL_ATTACK = 'capital_attack'

    TYPE_CHOICES = [
        (BATTLE, 'Battle'),
        (CAPITAL_ATTACK, 'Capital Attack'),
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

    MAX_QUESTIONS = 3
    ANSWER_WINDOW_SECONDS = 10

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='battles')
    attacker = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='battles_attacked')
    defender = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='battles_defended')
    territory = models.ForeignKey(Territory, on_delete=models.CASCADE, related_name='battles')
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    winner = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='battles_won',
    )
    incomplete_reason = models.CharField(
        max_length=20, choices=INCOMPLETE_REASON_CHOICES, blank=True, default='',
    )
    rewards_applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.attacker_id and self.defender_id and self.attacker_id == self.defender_id:
            raise ValidationError('The attacker and defender must be different players.')
        if self.attacker_id and self.attacker.game_id != self.game_id:
            raise ValidationError('The attacker must belong to the same game as the battle.')
        if self.defender_id and self.defender.game_id != self.game_id:
            raise ValidationError('The defender must belong to the same game as the battle.')
        if self.territory_id and self.territory.game_id != self.game_id:
            raise ValidationError('The territory must belong to the same game as the battle.')
        if self.winner_id and self.winner_id not in (self.attacker_id, self.defender_id):
            raise ValidationError('The winner must be the attacker or the defender.')
        if self.status == self.COMPLETED and self.completed_at is None:
            raise ValidationError('A completed battle must have completed_at set.')
        if self.status == self.COMPLETED and self.winner_id is None and not self.incomplete_reason:
            raise ValidationError('A completed battle without a winner must record an incomplete_reason.')

    def __str__(self):
        return f'Battle #{self.pk} over {self.territory} ({self.status})'


class BattleQuestion(models.Model):
    """One question step of a battle's sequence (M08).

    A battle starts with a `ChoiceQuestion` and may fall through to one or
    more `NumericQuestion` follow-ups (never back to a choice question).
    Rather than a single generic foreign key, each concrete question model
    gets its own nullable FK plus a `question_type` discriminator: this
    keeps the relation a normal, database-enforced FK (no risk of an
    ambiguous (model, id) pair, since a `ChoiceQuestion` and a
    `NumericQuestion` can share the same primary key without ever being
    confused for one another), at the cost of two columns instead of one -
    an acceptable trade for only two question types. `question_text` (and,
    for a numeric step, `correct_answer`) are snapshotted at creation time,
    the same way `games.RoundQuestion` already does it, so a later edit to
    the question bank never changes what a past battle is shown to have
    asked.
    """

    CHOICE = 'choice'
    NUMERIC = 'numeric'

    QUESTION_TYPE_CHOICES = [
        (CHOICE, 'Choice'),
        (NUMERIC, 'Numeric'),
    ]

    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name='battle_questions')
    sequence = models.PositiveSmallIntegerField()
    question_type = models.CharField(max_length=10, choices=QUESTION_TYPE_CHOICES)
    choice_question = models.ForeignKey(
        ChoiceQuestion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='battle_questions',
    )
    numeric_question = models.ForeignKey(
        NumericQuestion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='battle_questions',
    )
    question_text = models.TextField()
    correct_answer = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['battle', 'sequence']
        constraints = [
            models.UniqueConstraint(fields=['battle', 'sequence'], name='unique_sequence_per_battle'),
        ]

    def clean(self):
        super().clean()
        if self.question_type == self.CHOICE:
            if not self.choice_question_id or self.numeric_question_id:
                raise ValidationError('A choice question step must reference exactly one choice_question.')
        elif self.question_type == self.NUMERIC:
            if not self.numeric_question_id or self.choice_question_id:
                raise ValidationError('A numeric question step must reference exactly one numeric_question.')

    def is_started(self):
        return self.started_at is not None

    def is_open(self, now):
        return self.is_started() and self.resolved_at is None and now < self.deadline

    def __str__(self):
        return f'Question {self.sequence} of {self.battle}'


class BattleAnswer(models.Model):
    """One participant's accepted answer to one `BattleQuestion` (M08).

    A choice step is answered by picking one of the question's own
    `AnswerOption` rows directly (not a copy of it); a numeric step by a
    plain integer `value`. `clean()` enforces that only the field matching
    the step's `question_type` is set, and - for a choice answer - that the
    chosen option actually belongs to this step's `choice_question` (an
    option that exists but belongs to a *different* question is rejected
    even though the row itself is real).
    """

    battle_question = models.ForeignKey(BattleQuestion, on_delete=models.CASCADE, related_name='answers')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='battle_answers')
    selected_option = models.ForeignKey(
        AnswerOption,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='+',
    )
    value = models.IntegerField(null=True, blank=True)
    answered_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['battle_question', 'player'], name='unique_battle_answer_per_player_per_question',
            ),
        ]

    def clean(self):
        super().clean()
        if self.player_id and self.battle_question_id:
            battle = self.battle_question.battle
            if self.player.game_id != battle.game_id:
                raise ValidationError('The answering player must belong to the same game as the battle.')
            if self.player_id not in (battle.attacker_id, battle.defender_id):
                raise ValidationError('Only the battle participants may answer.')

            if self.battle_question.question_type == BattleQuestion.CHOICE:
                if not self.selected_option_id or self.value is not None:
                    raise ValidationError('A choice answer must set selected_option and not value.')
                if self.selected_option.question_id != self.battle_question.choice_question_id:
                    raise ValidationError('The selected option does not belong to this question.')
            elif self.battle_question.question_type == BattleQuestion.NUMERIC:
                if self.value is None or self.selected_option_id:
                    raise ValidationError('A numeric answer must set value and not selected_option.')

    def elapsed(self):
        return self.answered_at - self.battle_question.started_at

    def deviation(self):
        return abs(self.value - self.battle_question.correct_answer)

    def is_correct_choice(self):
        return bool(self.selected_option_id and self.selected_option.is_correct)

    def __str__(self):
        return f'{self.player} -> {self.battle_question}'
