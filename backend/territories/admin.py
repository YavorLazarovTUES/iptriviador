from django.contrib import admin

from .models import Capital, Territory


@admin.register(Territory)
class TerritoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'game', 'slug', 'owner', 'score')
    list_filter = ('game', 'owner')
    search_fields = ('name', 'slug')
    readonly_fields = ('game', 'name', 'slug', 'neighbors', 'owner')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Capital)
class CapitalAdmin(admin.ModelAdmin):
    list_display = ('player', 'territory', 'health')
    list_filter = ('territory__game',)
    search_fields = ('player__user__username', 'territory__name')
    readonly_fields = ('territory', 'player')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
