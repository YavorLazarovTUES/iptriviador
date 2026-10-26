from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Game, Player, Round, RoundAnswer, RoundQuestion


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0

    def has_add_permission(self, request, obj=None):
        if obj is not None and obj.status != Game.WAITING:
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != Game.WAITING:
            return False
        return super().has_delete_permission(request, obj)


class RoundInline(admin.TabularInline):
    model = Round
    extra = 0


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'status', 'player_count')
    list_filter = ('status',)
    inlines = [PlayerInline, RoundInline]
    actions = ['initialize_games']

    @admin.display(description='Players')
    def player_count(self, obj):
        return obj.players.count()

    @admin.action(description='Initialize selected games')
    def initialize_games(self, request, queryset):
        from territories.services import initialize_game

        for game in queryset:
            try:
                initialize_game(game)
            except ValidationError as error:
                self.message_user(request, f'Game #{game.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Game #{game.pk} initialized.', level=messages.SUCCESS)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'color', 'score')
    list_filter = ('game', 'color')
    search_fields = ('user__username',)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            form.base_fields['game'].queryset = Game.objects.filter(status=Game.WAITING)
        return form

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.game.status != Game.WAITING:
            return False
        return super().has_delete_permission(request, obj)


class RoundQuestionInline(admin.TabularInline):
    model = RoundQuestion
    extra = 0
    readonly_fields = (
        'sequence', 'target_rank', 'question', 'question_text', 'correct_answer',
        'started_at', 'deadline', 'resolved_at',
    )
    filter_horizontal = ('contenders',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = (
        'game', 'number', 'type', 'status', 'winner', 'second_place',
        'incomplete_reason', 'created_at', 'completed_at',
    )
    list_filter = ('game', 'type', 'status')
    inlines = [RoundQuestionInline]
    actions = ['start_rounds', 'resolve_rounds']

    @admin.action(description='Start selected pending rounds')
    def start_rounds(self, request, queryset):
        from games.services import InvalidStateError, start_round

        for round_ in queryset:
            try:
                start_round(round_)
            except (ValidationError, InvalidStateError) as error:
                self.message_user(request, f'Round #{round_.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Round #{round_.pk} started.', level=messages.SUCCESS)

    @admin.action(description='Resolve selected rounds (if ready)')
    def resolve_rounds(self, request, queryset):
        from games.services import InvalidStateError, resolve_round

        for round_ in queryset:
            try:
                resolve_round(round_)
            except (ValidationError, InvalidStateError) as error:
                self.message_user(request, f'Round #{round_.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Round #{round_.pk} resolved.', level=messages.SUCCESS)


@admin.register(RoundAnswer)
class RoundAnswerAdmin(admin.ModelAdmin):
    list_display = ('round_question', 'player', 'value', 'answered_at')
    list_filter = ('round_question__round__game',)
    readonly_fields = ('round_question', 'player', 'value', 'answered_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
