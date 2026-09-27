from django.db import IntegrityError
from django.test import TestCase

from . import make_user


class ProfileModelTests(TestCase):
    def test_profile_defaults_and_unique_nickname(self):
        user = make_user()
        self.assertEqual(user.profile.avatar_key, 'knight-1')
        with self.assertRaises(IntegrityError):
            make_user('player_two', nickname='MountainKnight')
