from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from games.services import InvalidStateError

from .models import Battle, BattleAnswer, BattleQuestion
from .services import apply_battle_result, resolve_battle, start_battle


class BattleQuestionInline(admin.TabularInline):
    model = BattleQuestion
    extra = 0
    readonly_fields = (
        'sequence', 'question_type', 'choice_question', 'numeric_question', 'question_text',
        'correct_answer', 'started_at', 'deadline', 'resolved_at',
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Battle)
class BattleAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'game', 'territory', 'type', 'status', 'attacker', 'defender', 'winner',
        'incomplete_reason', 'rewards_applied', 'created_at', 'completed_at',
    )
    list_filter = ('game', 'type', 'status')
    search_fields = ('territory__name',)
    inlines = [BattleQuestionInline]
    actions = ['start_battles', 'resolve_battles', 'apply_results']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Start selected pending battles')
    def start_battles(self, request, queryset):
        for battle in queryset:
            try:
                start_battle(battle)
            except (ValidationError, InvalidStateError) as error:
                self.message_user(request, f'Battle #{battle.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Battle #{battle.pk} started.', level=messages.SUCCESS)

    @admin.action(description='Resolve selected battles (if ready)')
    def resolve_battles(self, request, queryset):
        for battle in queryset:
            try:
                resolve_battle(battle)
            except (ValidationError, InvalidStateError) as error:
                self.message_user(request, f'Battle #{battle.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Battle #{battle.pk} resolved.', level=messages.SUCCESS)

    @admin.action(description='Apply result for selected completed battles')
    def apply_results(self, request, queryset):
        for battle in queryset:
            try:
                apply_battle_result(battle)
            except (ValidationError, InvalidStateError) as error:
                self.message_user(request, f'Battle #{battle.pk}: {" ".join(error.messages)}', level=messages.ERROR)
            else:
                self.message_user(request, f'Battle #{battle.pk}: result applied.', level=messages.SUCCESS)


@admin.register(BattleAnswer)
class BattleAnswerAdmin(admin.ModelAdmin):
    list_display = ('battle_question', 'player', 'selected_option', 'value', 'answered_at')
    list_filter = ('battle_question__battle__game',)
    readonly_fields = ('battle_question', 'player', 'selected_option', 'value', 'answered_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
