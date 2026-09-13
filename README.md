# Monitor TCL 55C6K

Vigia o preço e os cupons da **Smart TV TCL 55C6K (QD-Mini LED, 55")** em lojas confiáveis, no Pelando, no Promobit e em canais do Telegram. Avisa no Telegram e publica um painel no GitHub Pages.

- **Nuvem (GitHub Actions, a cada 15 min):** Promobit, Pelando, Zoom, Magazine Luiza, KaBuM!, Fast Shop, Loja TCL, Webcontinental, canais públicos do Telegram, cupons.
- **PC (tarefa agendada, a cada 30 min):** Amazon, Casas Bahia, Mercado Livre, AliExpress, Shopee e, opcionalmente, grupos privados do Telegram com a sua conta.

O plano completo com a pesquisa que originou o projeto está em [PLANO.md](PLANO.md).

## O que gera alerta

| Situação | Alerta |
|---|---|
| Qualquer postagem nova no Pelando, Promobit ou canais do Telegram citando a 55C6K | 📣 sempre (nos 3 primeiros dias da postagem) |
| Preço de loja caiu ≥ 2 % desde a última coleta | 🔻 |
| Preço ≤ alvo (Pix R$ 2.900 ou parcelado sem juros R$ 3.000) | 🎯 (repete só se cair mais) |
| Novo menor preço já visto | 🏆 |
| Cupom novo numa loja que vende a TV, com regra compatível | 🎟️ com o preço da loja |
| Uma fonte falhou 3 vezes seguidas | ⚠️ |
| Todo dia às 9h | ☀️ resumo com todos os preços |

Os alvos são ajustáveis pelas variáveis `ALVO_PIX` e `ALVO_PARCELADO`.

## Configurar (uma vez)

### 1. Bot do Telegram (2 min)
1. No Telegram, fale com **@BotFather** → `/newbot` → guarde o **token**.
2. Fale com **@userinfobot** → `/start` → guarde o seu **chat id**.
3. Mande qualquer mensagem para o bot novo (bots não iniciam conversa).

### 2. GitHub
1. Crie um repositório **público** e envie este projeto (`git push`).
2. **Settings → Secrets and variables → Actions → Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. (Opcional) **Variables**: `ALVO_PIX`, `ALVO_PARCELADO`, `TELEGRAM_CANAIS_EXTRA` (canais públicos separados por vírgula).
4. **Settings → Pages → Source: Deploy from a branch → main / docs**. O painel fica em `https://<usuário>.github.io/<repo>/`.
5. **Actions → monitor 55C6K → Run workflow** para a primeira coleta. A primeira rodada só registra o que existe (uma mensagem de "monitor iniciado"); a partir da segunda chegam as novidades.

### 3. Executor no PC (Amazon, Casas Bahia, Mercado Livre, AliExpress, Shopee)
Requer Python 3.12 e Google Chrome instalados.
```powershell
pip install -r requirements-pc.txt
copy .env.example .env        # edite com token e chat id
python run.py --mode pc --no-notify     # teste
powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1   # agenda a cada 30 min
```
O log fica em `logs\pc.log`. A tarefa faz `git pull`, coleta, e `git push` do estado.

### 4. Grupos/canais privados do Telegram (opcional)
Canais **públicos** não precisam de nada: adicione o nome em `TELEGRAM_CANAIS_EXTRA`.
Para grupos fechados ou canais privados de que você participa:
1. Crie um app em <https://my.telegram.org/apps> (api_id e api_hash).
2. `python scripts\telegram_login.py` → informe telefone e código → cole as linhas impressas no `.env` do PC.
3. Em `TELEGRAM_CHATS_USUARIO` liste os `@usernames` ou ids que o script mostrou.

## Rodar na mão
```
python run.py --mode cloud --no-notify      # só imprime, não envia
python run.py --mode all --so zoom,kabum    # só algumas fontes
python -m pytest -q                         # testes com páginas salvas
```

## Estrutura
```
monitor/config.py        URLs, alvos, canais, lojas
monitor/filtro.py        aceita só 55C6K (rejeita 65/75/85C6K, combos, acessórios, usados)
monitor/sources/*.py     um coletor por fonte
monitor/regras.py        o que vira alerta
monitor/estado.py        docs/data/state_*.json, historico_*.csv, latest_*.json
docs/index.html          painel (GitHub Pages)
tests/                   testes com HTML/JSON reais salvos
```
