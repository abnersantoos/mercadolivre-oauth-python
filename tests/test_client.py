import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from meli.client import Client, MeliError


def response(data, status=200, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=data))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.session = Mock()
        self.sleep = Mock()
        self.client = Client(self.path / 'tokens.json', self.session, self.sleep)
        self.client.tokens = {'access_token': 'old', 'refresh_token': 'refresh'}

    def queue(self, *responses):
        self.session.request.side_effect = responses

    def test_export_multiple_pages_batches_and_duplicate_ids(self):
        ids = [f'MLB{i}' for i in range(25)]
        def batch(values):
            return response([{'code': 200, 'body': {'id': i, 'title': 'ação'}} for i in reversed(values)])
        self.queue(response({'id': 123}), response({'results': ids[:20], 'scroll_id': 'c'}),
                   batch(ids[:20]), response({'results': [ids[19]] + ids[20:], 'scroll_id': 'c'}),
                   response({'results': []}), batch(ids[20:]))
        out = self.path / 'out.json'
        self.assertEqual(self.client.export(out), 25)
        data = json.loads(out.read_text())
        self.assertEqual([x['id'] for x in data['items']], ids)
        self.assertTrue(data['complete'])
        calls = self.session.request.call_args_list
        self.assertEqual(calls[1].kwargs['params'], {'search_type': 'scan', 'limit': 100})
        self.assertEqual(calls[3].kwargs['params']['scroll_id'], 'c')
        self.assertNotIn('status', calls[1].kwargs['params'])

    def test_empty_account(self):
        self.queue(response({'id': 123}), response({'results': []}))
        self.assertEqual(self.client.export(self.path / 'out.json'), 0)

    def test_missing_cursor_fails(self):
        self.queue(response({'results': ['MLB1']}))
        with self.assertRaises(MeliError):
            list(self.client.iter_ids(123))

    def test_repeated_page_fails(self):
        self.queue(response({'results': ['MLB1'], 'scroll_id': 'c'}),
                   response({'results': ['MLB1'], 'scroll_id': 'c'}))
        with self.assertRaises(MeliError):
            list(self.client.iter_ids(123))

    def test_partial_multiget_preserves_previous_export(self):
        out = self.path / 'out.json'
        out.write_text('previous')
        self.queue(response({'id': 123}), response({'results': ['MLB1'], 'scroll_id': 'c'}),
                   response({'results': []}), response([{'code': 404, 'body': {}}]))
        with self.assertRaises(MeliError):
            self.client.export(out)
        self.assertEqual(out.read_text(), 'previous')
        self.assertEqual(list(self.path.glob('.meli-*')), [])

    def test_invalid_multiget(self):
        for payload in ([], [{'code': 200, 'body': {'id': 'OTHER'}}]):
            with self.subTest(payload=payload):
                self.queue(response(payload))
                with self.assertRaises(MeliError):
                    self.client.details(['MLB1'])

    def test_retry_after_and_timeout(self):
        self.queue(response({}, 429, {'Retry-After': '3'}), requests.Timeout(), response({'id': 123}))
        self.assertEqual(self.client.seller_id(), 123)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [3, 2])
        self.assertEqual(self.session.request.call_args.kwargs['timeout'], (5, 30))

    def test_403_not_retried(self):
        self.queue(response({}, 403))
        with self.assertRaises(MeliError):
            self.client.seller_id()
        self.assertEqual(self.session.request.call_count, 1)

    @patch.dict(os.environ, {'MELI_CLIENT_ID': 'client', 'MELI_CLIENT_SECRET': 'secret'})
    def test_refresh_rotation_saved_before_retry(self):
        self.queue(response({}, 401), response({'access_token': 'new', 'refresh_token': 'rotated'}),
                   response({'id': 123}))
        self.assertEqual(self.client.seller_id(), 123)
        self.assertEqual(json.loads(self.client.token_file.read_text())['refresh_token'], 'rotated')
        self.assertEqual(self.session.request.call_args.kwargs['headers']['Authorization'], 'Bearer new')
        if os.name == 'posix':
            self.assertEqual(self.client.token_file.stat().st_mode & 0o777, 0o600)

    @patch.dict(os.environ, {'MELI_CLIENT_ID': 'client', 'MELI_CLIENT_SECRET': 'secret'})
    def test_oauth_post_not_retried(self):
        self.queue(requests.Timeout())
        with self.assertRaises(MeliError):
            self.client.oauth(grant_type='authorization_code', code='secret-code')
        self.assertEqual(self.session.request.call_count, 1)

    def test_export_cannot_overwrite_tokens(self):
        with self.assertRaises(MeliError):
            self.client.export(self.client.token_file)
        self.session.request.assert_not_called()

    def test_invalid_json(self):
        res = response(None)
        res.json.side_effect = ValueError('sensitive')
        self.queue(res)
        with self.assertRaisesRegex(MeliError, 'JSON inválido'):
            self.client.seller_id()


if __name__ == '__main__':
    unittest.main()
