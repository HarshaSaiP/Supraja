from django.test import TestCase

class LandingPageTests(TestCase):
    def test_homepage_renders_home_template_and_links_to_login(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertContains(response, 'href="/login/"')

    def test_portal_login_still_renders_login_template(self):
        response = self.client.get('/login/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login/login.html')
