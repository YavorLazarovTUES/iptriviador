from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Game, Player, Round


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0


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


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ('game', 'number', 'type', 'status', 'winner', 'created_at', 'completed_at')
    list_filter = ('game', 'type', 'status')
