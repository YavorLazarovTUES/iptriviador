from django.contrib.auth import get_user_model

from accounts.models import Profile

PASSWORD = 'Str0ng-pass-123'


def make_user(username='player_one', nickname='MountainKnight'):
    user = get_user_model().objects.create_user(username, f'{username}@example.com', PASSWORD)
    Profile.objects.create(user=user, nickname=nickname)
    return user
