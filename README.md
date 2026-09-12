# Mercado Livre — OAuth e exportação de anúncios

Backend Python 3.10+ para exportar os anúncios **do vendedor autenticado**, sem frontend ou servidor web. Mantém os campos retornados por `/items`, incluindo variações quando disponíveis.

## Instalação

```bash
git clone https://github.com/abnersantoos/mercadolivre-oauth-python.git
cd mercadolivre-oauth-python
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Essas funcionalidades estão na contribuição `feat/seller-items-export`; não estarão na branch principal do repositório original até serem integradas.

## Configuração e autenticação

Cadastre o aplicativo no DevCenter e autorize a conta do vendedor usando o fluxo OAuth oficial. A URI de retorno deve coincidir com a cadastrada. Esta ferramenta troca o código obtido nesse fluxo; não implementa uma página de login/callback. Se usar PKCE, preserve o verifier original em `MELI_CODE_VERIFIER`.

Linux/macOS:

```bash
export MELI_CLIENT_ID='seu_client_id'
export MELI_CLIENT_SECRET='seu_client_secret'
export MELI_REDIRECT_URI='sua_uri_cadastrada'
python -m meli auth
```

PowerShell:

```powershell
$env:MELI_CLIENT_ID='seu_client_id'
$env:MELI_CLIENT_SECRET='seu_client_secret'
$env:MELI_REDIRECT_URI='sua_uri_cadastrada'
python -m meli auth
```

O código é solicitado sem eco no terminal. Não coloque tokens no Git. `.env.example` é apenas um modelo, não é carregado automaticamente. O comando antigo `python trocar_code_py` continua disponível.

Os tokens são salvos atomicamente em `tokens.json`, com permissão 0600 em sistemas POSIX. No Windows, proteja o diretório com as permissões da sua conta. O arquivo contém segredos em texto simples: use diretório privado e um cofre de segredos ao integrar em produção. Não execute processos concorrentes usando o mesmo arquivo: a rotação de refresh tokens exige um único escritor.

## Exportar todos os anúncios acessíveis da conta

```bash
python -m meli export --output anuncios.json
# Arquivo de tokens personalizado (opção antes do subcomando):
python -m meli --token-file tokens-loja.json export --output anuncios-loja.json
```

Fluxo:

1. Resolve a conta com `GET /users/me`; não aceita um vendedor arbitrário.
2. Percorre `GET /users/{id}/items/search?search_type=scan&limit=100` com `scroll_id`, sem filtro de status.
3. Consulta `/items?ids=...` em lotes de até 20 IDs, eliminando duplicidades.
4. Grava JSON progressivamente em arquivo temporário e só substitui o destino após concluir a busca e todos os detalhes.

Formato: `{"seller_id":123,"items":[...],"count":25,"complete":true}`.

“Todos” significa todos os anúncios que a API disponibiliza nessa consulta para essa conta e suas permissões. Não representa todos os produtos do marketplace, anúncios excluídos inacessíveis ou uma fotografia transacional: alterações na conta durante a execução podem afetar os resultados. Não há filtro implícito por anúncio ativo no cliente.

## Falhas e limites

- Timeouts de conexão/leitura: 5/30 segundos.
- GET: até 4 tentativas para falhas de conexão, HTTP 429 e 500/502/503/504. Respeita `Retry-After` numérico até 60 segundos; valores maiores interrompem a execução. Datas HTTP usam o backoff padrão.
- HTTP 401: uma renovação OAuth e uma repetição da consulta. Novos tokens são persistidos antes da repetição.
- POST OAuth não é repetido automaticamente, pois códigos e refresh tokens podem ser consumidos.
- HTTP 403, cursor ausente, página sem progresso, JSON inválido ou falha individual no multiget interrompem a exportação. Não são tratados como resultado vazio.
- Arquivo final anterior é preservado em falhas. Reexecute desde o início após resolver a causa; não há retomada por cursor persistido.
- IDs ficam em memória para deduplicação; detalhes são escritos em lotes. Existe um limite defensivo de 100.000 páginas.

## Testes

```bash
python -m unittest discover -s tests -v
```

Testes sem rede cobrem paginação, lotes, deduplicação, conta vazia, erros parciais, preservação do arquivo anterior, retries e rotação de tokens. CI executa a suíte em Python 3.10, 3.12 e 3.13.

## Documentação e validação externa

Referência solicitada: https://developers.mercadolivre.com.br/pt_br/itens-e-buscas

OAuth: https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao

Na preparação desta contribuição (12/09/2026), as páginas de documentação consultadas retornaram 403 ou ficaram indisponíveis. O contrato scan/scroll e multiget implementado precisa ser homologado com uma conta autorizada antes do uso em produção. Os testes usam respostas simuladas; não houve consulta real de anúncios nem autenticação em conta de vendedor.

## Contribuição

Corrige o script original (linha `Python` inválida, dependência `requests` ausente, credenciais embutidas como placeholders, tokens impressos e ausência de timeout). Adiciona cliente reutilizável, CLI, exportação atômica, renovação de tokens, testes e CI. Remove dependências web que não eram usadas pelo código existente. Não modifica anúncios nem publica mudanças na conta do vendedor.
