import argparse
import getpass
import os
import sys

from .client import Client, MeliError


def main():
    parser = argparse.ArgumentParser(description='Exporta anúncios do vendedor autenticado.')
    parser.add_argument('--token-file', default='tokens.json')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('auth', help='Troca código OAuth e salva tokens localmente.')
    export = commands.add_parser('export', help='Exporta todos os anúncios acessíveis da conta.')
    export.add_argument('--output', default='anuncios.json')
    args = parser.parse_args()
    client = None
    try:
        client = Client(args.token_file)
        if args.command == 'auth':
            redirect = os.environ.get('MELI_REDIRECT_URI')
            if not redirect:
                raise MeliError('Defina MELI_REDIRECT_URI igual à URI cadastrada no aplicativo.')
            code = getpass.getpass('Código OAuth: ').strip()
            if not code:
                raise MeliError('Código OAuth obrigatório.')
            grant = dict(grant_type='authorization_code', code=code, redirect_uri=redirect)
            if os.environ.get('MELI_CODE_VERIFIER'):
                grant['code_verifier'] = os.environ['MELI_CODE_VERIFIER']
            client.oauth(**grant)
            print('Tokens salvos. Não compartilhe o arquivo de tokens.')
        else:
            count = client.export(args.output)
            print(f'Exportação concluída: {count} anúncios em {args.output}.')
        return 0
    except MeliError as error:
        print(f'Operação falhou: {error}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # Não imprimir exceções de bibliotecas: podem conter dados sensíveis.
        print('Operação falhou. Verifique configuração, tokens, permissões e disponibilidade da API. Nenhuma exportação parcial foi publicada.', file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    sys.exit(main())
