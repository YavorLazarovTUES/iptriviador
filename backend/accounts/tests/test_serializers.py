from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.serializers import RegisterSerializer

from . import PASSWORD, make_user


class RegisterSerializerTests(TestCase):
    def test_invalid_registration(self):
        make_user()
        valid = {'username': 'new', 'email': 'new@example.com', 'nickname': 'New',
                 'password': PASSWORD, 'password_confirm': PASSWORD}
        cases = {'username': 'player_one', 'email': 'player_one@example.com',
                 'nickname': 'MountainKnight', 'password_confirm': 'other-pass-123'}
        for field, value in cases.items():
            with self.subTest(field=field):
                serializer = RegisterSerializer(data={**valid, field: value})
                self.assertFalse(serializer.is_valid())
                self.assertIn(field, serializer.errors)
        self.assertEqual(get_user_model().objects.count(), 1)
