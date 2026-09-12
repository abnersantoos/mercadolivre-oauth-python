import json
import os
import tempfile
import time
from pathlib import Path

import requests


class MeliError(RuntimeError):
    """Erro seguro para exibição, sem tokens ou corpo da resposta."""


def atomic_write(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.meli-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            write(stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Client:
    BASE = 'https://api.mercadolibre.com'

    def __init__(self, token_file='tokens.json', session=None, sleep=time.sleep):
        self.token_file = Path(token_file)
        self.session = session or requests.Session()
        self.sleep = sleep
        self.tokens = {}
        if self.token_file.exists():
            self.tokens = json.loads(self.token_file.read_text(encoding='utf-8'))

    def close(self):
        self.session.close()

    def oauth(self, **grant):
        credentials = {key: os.environ.get('MELI_' + key.upper())
                       for key in ('client_id', 'client_secret')}
        if not all(credentials.values()):
            raise MeliError('Defina MELI_CLIENT_ID e MELI_CLIENT_SECRET.')
        # Não repetir POST: authorization code e refresh token podem ser consumidos.
        data = self._request('POST', '/oauth/token', data={**credentials, **grant})
        if not isinstance(data, dict) or not data.get('access_token') or not data.get('refresh_token'):
            raise MeliError('Resposta OAuth incompleta; autentique novamente.')
        atomic_write(self.token_file, lambda f: json.dump(data, f))
        self.tokens = data

    def _request(self, method, path, **kwargs):
        for attempt in range(4):
            try:
                response = self.session.request(method, self.BASE + path,
                                                timeout=(5, 30), allow_redirects=False, **kwargs)
            except requests.RequestException:
                if method == 'GET' and attempt < 3:
                    self.sleep(2 ** attempt)
                    continue
                raise MeliError('Falha de conexão com Mercado Livre.') from None
            if method == 'GET' and (response.status_code == 429 or response.status_code in (500, 502, 503, 504)) and attempt < 3:
                retry = response.headers.get('Retry-After', '')
                delay = int(retry) if retry.isdigit() else 2 ** attempt
                if delay > 60:
                    raise MeliError('Limite da API: aguarde o Retry-After antes de executar novamente.')
                self.sleep(delay)
                continue
            if response.status_code == 401:
                raise Unauthorized('Token expirado ou inválido.')
            if not 200 <= response.status_code < 300:
                raise MeliError(f'Mercado Livre retornou HTTP {response.status_code}.')
            try:
                return response.json()
            except ValueError:
                raise MeliError('Mercado Livre retornou JSON inválido.') from None

    def get(self, path, **params):
        if not self.tokens.get('access_token'):
            raise MeliError('Autentique primeiro com python -m meli auth.')
        for attempt in range(2):
            try:
                return self._request('GET', path, params=params,
                                     headers={'Authorization': 'Bearer ' + self.tokens['access_token']})
            except Unauthorized:
                if attempt or not self.tokens.get('refresh_token'):
                    raise
                self.oauth(grant_type='refresh_token', refresh_token=self.tokens['refresh_token'])

    def seller_id(self):
        user = self.get('/users/me')
        seller = user.get('id') if isinstance(user, dict) else None
        if not isinstance(seller, int) or isinstance(seller, bool) or seller <= 0:
            raise MeliError('Resposta de /users/me inválida.')
        return seller

    def iter_ids(self, seller_id):
        cursor = None
        seen = set()
        for _ in range(100000):
            params = {'search_type': 'scan', 'limit': 100}
            if cursor:
                params['scroll_id'] = cursor
            page = self.get(f'/users/{seller_id}/items/search', **params)
            ids = page.get('results') if isinstance(page, dict) else None
            if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
                raise MeliError('Resposta de busca inválida.')
            if not ids:
                return
            fresh = [i for i in dict.fromkeys(ids) if i not in seen]
            if not fresh:
                raise MeliError('Paginação sem progresso; exportação interrompida.')
            cursor = page.get('scroll_id')
            if not isinstance(cursor, str) or not cursor:
                raise MeliError('Busca scan sem scroll_id; não é seguro declarar a exportação completa.')
            for item_id in fresh:
                seen.add(item_id)
                yield item_id
        raise MeliError('Limite de segurança de páginas atingido.')

    def details(self, ids):
        rows = self.get('/items', ids=','.join(ids))
        if not isinstance(rows, list) or len(rows) != len(ids):
            raise MeliError('Resposta multiget incompleta.')
        by_id = {}
        for row in rows:
            if not isinstance(row, dict) or row.get('code') != 200:
                raise MeliError('Um anúncio falhou no multiget; exportação não concluída.')
            body = row.get('body')
            if not isinstance(body, dict) or body.get('id') not in ids or body['id'] in by_id:
                raise MeliError('Identificação inválida no multiget.')
            by_id[body['id']] = body
        return [by_id[item_id] for item_id in ids]

    def export(self, output):
        if Path(output).resolve() == self.token_file.resolve():
            raise MeliError('A exportação não pode sobrescrever o arquivo de tokens.')
        seller = self.seller_id()
        count = 0

        def write(stream):
            nonlocal count
            stream.write('{"seller_id": ' + str(seller) + ', "items": [')
            batch = []

            def flush():
                nonlocal count
                for item in self.details(batch):
                    if count:
                        stream.write(',')
                    json.dump(item, stream, ensure_ascii=False)
                    count += 1

            for item_id in self.iter_ids(seller):
                batch.append(item_id)
                if len(batch) == 20:
                    flush()
                    batch.clear()
            if batch:
                flush()
            stream.write('], "count": ' + str(count) + ', "complete": true}\n')

        atomic_write(output, write)
        return count


class Unauthorized(MeliError):
    pass
