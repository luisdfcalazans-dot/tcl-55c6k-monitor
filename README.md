# Monitor TCL 55C6K

Vigia o preço e os cupons da **Smart TV TCL 55C6K (QD-Mini LED, 55")** em lojas confiáveis, no Pelando, no Promobit e em canais do Telegram. Avisa no Telegram e publica um painel no GitHub Pages.

- **Nuvem (GitHub Actions, a cada 15 min):** Promobit, Zoom, Magazine Luiza, KaBuM!, Fast Shop, Loja TCL, Webcontinental, canais públicos do Telegram, cupons.
- **PC (tarefa agendada, a cada 30 min):** Pelando (bloqueia IPs de datacenter), Amazon, Casas Bahia, Mercado Livre, AliExpress, Shopee e, opcionalmente, grupos privados do Telegram com a sua conta.

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

### Confiança nos vendedores (antes de qualquer alerta de preço)

Cada anúncio de loja recebe um veredito (`monitor/confianca.py`), sem atrasar os vendedores conhecidos:

| Veredito | O que acontece |
|---|---|
| **confiável** (lista `monitor/listas_confianca.json`) | alerta na hora, sem checagem nenhuma |
| **reprovado** (lista curada ou reprovado automático) | descartado de cara: sem alerta, mínimo, histórico, painel nem carrinho |
| **suspeito** (vendedor fora da lista com qualquer sinal forte, ou 4+ sinais fracos) | uma mensagem ⚠️ "Anúncio suspeito — possível golpe" com os sinais (repetida só se o preço cair mais 2%); sem 🎯/🏆/🔻, fora do mínimo, histórico, painel, resumo e carrinho |
| **sem risco aparente** (desconhecido que passou) | alerta normal + linha 🔎 com o que foi checado |

Sinais fortes: preço até 80% da loja confiável mais barata (sozinho já torna o anúncio suspeito), "preço cheio" (o do cartão da própria oferta) igual ao de uma loja confiável com desconto enorme só no Pix/1x, homologação Anatel diferente da 55C6K (`00738-24-06714`), tamanho errado e, no Magalu, loja do vendedor sem TV no catálogo (1 requisição, guardada por 7 dias). Sinais fracos: modelo genérico, anúncio sem avaliações, peso de mentira, sem Full, vendedor novo, com poucas vendas ou de outro ramo. O suspeito só vira **reprovado automático** (descartado de cara nas próximas coletas) com 2+ sinais fortes, um deles de identidade (Anatel, tamanho ou catálogo); preço baixo sozinho é reavaliado a cada rodada. A chave do reprovado automático é o vendedor, nunca o anúncio de outro vendedor. Linha do Zoom de loja sem coleta própria passa pela mesma checagem de preço. Para liberar um vendedor suspeito ou reprovado automaticamente, ponha-o em `confiaveis` (a lista curada vence, inclusive no painel); quando a oferta traz o id do vendedor, a lista casa pelo id, não pelo nome de exibição. O texto das listas é neutro: uma empresa listada pode ser vítima (conta invadida), não autora.

No Magalu, vendedor novo que ficou sem checagem nesta rodada (403, limite de 2 vendedores por rodada, página ilegível) e está abaixo da loja confiável mais barata também sai como suspeito ("não deu para checar"), sem virar reprovado: é reavaliado na rodada seguinte. A ficha do anúncio lida numa rodada (Anatel, modelo, avaliações...) fica no state por 7 dias e vale quando a coleta só traz a busca. O cupom da página de um anúncio reprovado ou suspeito não vai ao alerta, ao painel nem ao testador. Se o `listas_confianca.json` tiver erro de sintaxe, valem as entradas de reserva do código (as próprias lojas e o bloqueio curado) e chega um aviso no Telegram (no máximo a cada 6 h).

## Configurar (uma vez)

### 1. Bot do Telegram (2 min)
1. No Telegram, fale com **@BotFather** → `/newbot` → guarde o **token**.
2. Fale com **@userinfobot** → `/start` → guarde o seu **chat id**.
3. Mande qualquer mensagem para o bot novo (bots não iniciam conversa).

### 2. GitHub
1. Crie um repositório **público** e envie este projeto (`git push`).
2. **Settings → Secrets and variables → Actions → Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. (Opcional) **Variables**: `ALVO_PIX`, `ALVO_PARCELADO`, `TELEGRAM_CANAIS_EXTRA` (canais públicos separados por vírgula), `MAGALU_ANUNCIOS_EXTRA` (links de anúncios do Magalu que a busca não mostra, separados por vírgula).
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

Detalhes: o Chrome abre com janela (fora da tela) porque o Akamai da Casas Bahia bloqueia o modo headless; a Amazon é lida por HTTP e, se vier sem preço, pelo Chrome. A Shopee exige login para buscar e fica desligada por padrão (`SHOPEE=1` no `.env` para tentar). O AliExpress inclui a loja da Magalu e a loja oficial TCL quando aparecem na busca.

### 4. Grupos/canais privados do Telegram (opcional)
Canais **públicos** não precisam de nada: adicione o nome em `TELEGRAM_CANAIS_EXTRA`.
Para grupos fechados ou canais privados de que você participa:
1. Crie um app em <https://my.telegram.org/apps> (api_id e api_hash).
2. `python scripts\telegram_login.py` → informe telefone e código → cole as linhas impressas no `.env` do PC.
3. Em `TELEGRAM_CHATS_USUARIO` liste os `@usernames` ou ids que o script mostrou. Já preparado no `.env.example`: `@ENVOLTOTECH` (grupo) e `@AquiSuaPromoBot` (bot que manda ofertas no privado).

## Rodar na mão
```
gh workflow run "monitor 55C6K" -f resumo=true   # nuvem: coleta agora e manda o resumo no Telegram
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
monitor/confianca.py     veredito de cada anúncio (confiável, reprovado, suspeito, sem risco aparente)
monitor/listas_confianca.json  vendedores confiáveis e reprovados (curados)
monitor/estado.py        docs/data/state_*.json, historico_*.csv, latest_*.json
docs/index.html          painel (GitHub Pages)
tests/                   testes com HTML/JSON reais salvos
```
