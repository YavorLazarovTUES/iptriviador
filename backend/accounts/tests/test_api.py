from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from . import PASSWORD, make_user

ME = '/api/auth/me/'


class AuthApiTests(APITestCase):
    def login(self, password=PASSWORD):
        return self.client.post('/api/auth/login/', {'username': 'player_one', 'password': password})

    def test_register(self):
        data = {'username': 'player_one', 'email': 'p@example.com', 'nickname': 'MountainKnight',
                'password': PASSWORD, 'password_confirm': PASSWORD}
        response = self.client.post('/api/auth/register/', data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['profile'], {'nickname': 'MountainKnight', 'avatar_key': 'knight-1'})
        self.assertNotIn('password', response.data)
        user = get_user_model().objects.get(username='player_one')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.profile.nickname, 'MountainKnight')

    def test_invalid_registration_returns_errors(self):
        response = self.client.post('/api/auth/register/', {'username': 'x'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data['errors'])

    def test_login_and_me(self):
        make_user('other', 'Other')
        user = make_user()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get(ME)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], user.id)

    def test_failed_login(self):
        make_user()
        response = self.login('wrong')
        self.assertEqual(response.status_code, 400)
        self.assertIn('errors', response.data)
        self.assertEqual(self.client.get(ME).status_code, 403)

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(ME).status_code, 403)

    def test_update_profile(self):
        user = make_user()
        self.client.force_authenticate(user)
        response = self.client.patch(ME, {'nickname': 'NewKnight', 'avatar_key': 'knight-3', 'is_staff': True})
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual((user.profile.nickname, user.profile.avatar_key), ('NewKnight', 'knight-3'))
        self.assertFalse(user.is_staff)

    def test_logout(self):
        make_user()
        self.login()
        self.assertEqual(self.client.post('/api/auth/logout/').status_code, 204)
        self.assertEqual(self.client.get(ME).status_code, 403)

    def test_csrf(self):
        make_user()
        client = APIClient(enforce_csrf_checks=True)
        client.login(username='player_one', password=PASSWORD)
        self.assertEqual(client.patch(ME, {'nickname': 'A'}).status_code, 403)
        token = client.get('/api/auth/csrf/').cookies['csrftoken'].value
        self.assertEqual(client.patch(ME, {'nickname': 'A'}, HTTP_X_CSRFTOKEN=token).status_code, 200)
