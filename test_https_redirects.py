import unittest
import os
import tempfile

from test_helpers import create_isolated_test_app


class HttpsRedirectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='toolib_https_test_')
        db_path = os.path.join(self.temp_dir.name, 'test_https_redirects.db')
        self.app = create_isolated_test_app(db_path, FORCE_HTTPS_REDIRECTS=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_public_http_get_redirects_to_https(self):
        response = self.client.get('/project/demo/', base_url='http://share.example.com')

        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers['Location'], 'https://share.example.com/project/demo/')

    def test_forwarded_http_origin_redirects_to_forwarded_https_host(self):
        response = self.client.get(
            '/project/demo/?view_id=7',
            base_url='https://internal.local',
            headers={
                'X-Forwarded-Proto': 'http',
                'X-Forwarded-Host': 'old-link.example.com',
            },
        )

        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response.headers['Location'],
            'https://old-link.example.com/project/demo/?view_id=7',
        )

    def test_localhost_http_is_not_redirected(self):
        response = self.client.get('/', base_url='http://localhost:5000')

        self.assertEqual(response.status_code, 200)

    def test_ipv6_localhost_http_is_not_redirected(self):
        response = self.client.get('/', base_url='http://[::1]:5000')

        self.assertEqual(response.status_code, 200)

    def test_https_request_is_not_redirected(self):
        response = self.client.get('/', base_url='https://share.example.com')

        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
