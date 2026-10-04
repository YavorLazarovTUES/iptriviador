from django.contrib import admin

from .models import Game, GamePlayer, Round, RoundAnswer


class GamePlayerInline(admin.TabularInline):
    model = GamePlayer
    extra = 0


class RoundInline(admin.TabularInline):
    model = Round
    extra = 0


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_by', 'status', 'created_at', 'started_at', 'finished_at')
    list_filter = ('status',)
    search_fields = ('created_by__username',)
    inlines = [GamePlayerInline, RoundInline]


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('game', 'user', 'player_order', 'score', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('user__username',)


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ('game', 'number', 'status', 'question_type', 'started_at', 'finished_at')
    list_filter = ('status', 'question_type')


@admin.register(RoundAnswer)
class RoundAnswerAdmin(admin.ModelAdmin):
    list_display = ('round', 'player', 'is_correct', 'points_awarded', 'submitted_at')
    list_filter = ('is_correct',)
