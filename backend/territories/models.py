from django.core.exceptions import ValidationError
from django.db import models

from games.models import Game, Player

CAPITAL_MIN_HEALTH = 0
CAPITAL_MAX_HEALTH = 3


class Territory(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='territories')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    neighbors = models.ManyToManyField('self', blank=True)
    owner = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='territories',
    )
    score = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = 'territories'
        constraints = [
            models.UniqueConstraint(fields=['game', 'name'], name='unique_territory_name_per_game'),
            models.UniqueConstraint(fields=['game', 'slug'], name='unique_territory_slug_per_game'),
            models.CheckConstraint(condition=models.Q(score__gte=0), name='territory_score_gte_0'),
        ]

    def clean(self):
        super().clean()
        if self.owner_id and self.owner.game_id != self.game_id:
            raise ValidationError('The owner must belong to the same game as the territory.')

    def add_neighbor(self, other):
        if other.pk == self.pk:
            raise ValidationError('A territory cannot be its own neighbor.')
        if other.game_id != self.game_id:
            raise ValidationError('Neighboring territories must belong to the same game.')
        self.neighbors.add(other)

    def __str__(self):
        return f'{self.name} ({self.game})'


class Capital(models.Model):
    MIN_HEALTH = CAPITAL_MIN_HEALTH
    MAX_HEALTH = CAPITAL_MAX_HEALTH

    territory = models.OneToOneField(Territory, on_delete=models.CASCADE, related_name='capital')
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name='capital')
    health = models.IntegerField(default=CAPITAL_MAX_HEALTH)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(health__gte=CAPITAL_MIN_HEALTH) & models.Q(health__lte=CAPITAL_MAX_HEALTH),
                name='capital_health_range',
            ),
        ]

    def clean(self):
        super().clean()
        if self.territory_id and self.player_id:
            if self.territory.game_id != self.player.game_id:
                raise ValidationError('The capital territory and player must belong to the same game.')
            if self.territory.owner_id != self.player_id:
                raise ValidationError('The capital territory must be owned by the capital player.')

    def __str__(self):
        return f'Capital of {self.player} at {self.territory}'
