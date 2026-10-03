# Monitor TCL 55C6K e 65C6K, PS5 e GTA 6

Vigia o preço e os cupons da **Smart TV TCL C6K (QD-Mini LED) de 55" (55C6K) e de 65" (65C6K)**, do **PS5** (Slim Digital, Slim com leitor, Pro, pacotes com o GTA 6, edições especiais e kits) e do **GTA 6** (Code in Box para PS5, digital Standard e Ultimate, upgrade, gift card da PlayStation e leitor de disco avulso) em lojas confiáveis, no Pelando, no Promobit e em canais do Telegram. Avisa no Telegram e publica um painel no GitHub Pages.

O catálogo dos produtos fica em `monitor/produtos.py` (a fonte única de ids, nomes, metas, termos de busca, códigos de barras, ids por loja e regras do classificador). Cada oferta guarda o id do produto no campo `modelo` (`55C6K`, `65C6K`, `PS5_DIGITAL`, `GTA6_CODE_IN_BOX`...).

- **Nuvem (GitHub Actions, a cada 15 min):** Promobit (busca e as categorias TV e PlayStation 5), Zoom, Magazine Luiza, KaBuM! (anúncios das TVs, lista de consoles PlayStation e o GTA 6), Fast Shop, Loja TCL, Webcontinental, Mais Correios e Americanas (pelo código de barras de todo o catálogo), Carrefour, PlayStation Store, vitrine da loja oficial PlayStation no Mercado Livre, canais públicos do Telegram (no canal oficial do Pelando, `@pelandobr`, também a busca por termo de cada produto, para pegar a postagem que saiu da 1ª página entre uma rodada e outra), cupons.
- **PC (tarefa agendada, a cada 30 min):** Pelando (bloqueia IPs de datacenter), Amazon (TVs e, em fonte própria, PS5 e GTA 6), Casas Bahia (idem), Netshoes (melhor esforço: o Akamai pode recusar o Chrome automatizado), Mercado Livre (catálogos das TVs e do PS5), AliExpress, Shopee e, opcionalmente, grupos privados do Telegram com a sua conta.

Prazo de entrega do GTA 6 (Code in Box e pacotes): KaBuM (cotação de frete), lojas VTEX (simulação de frete), Netshoes (cotação da página) e Amazon (CEP da sessão do Chrome) usam o CEP da variável `CEP_ENTREGA` (`.env` do PC e secret do GitHub; ele nunca vai para log, painel nem dados). Sem ela, vale um CEP de referência de São Paulo e o prazo sai marcado como aproximado. Quando o anúncio diz "envio a partir de 19/11" (ou depois), a oferta já sai como "chega depois do lançamento".

O plano completo com a pesquisa que originou o projeto está em [PLANO.md](PLANO.md).

## O que gera alerta

| Situação | Alerta |
|---|---|
| Qualquer postagem nova no Pelando, Promobit ou canais do Telegram citando a 55C6K ou a 65C6K | 📣 sempre (nos 3 primeiros dias da postagem) |
| Preço de loja caiu ≥ 2 % desde a última coleta | 🔻 |
| Preço ≤ alvo do modelo (55C6K: Pix R$ 2.900 ou parcelado sem juros R$ 3.000; 65C6K: Pix R$ 3.300 ou parcelado R$ 3.500) | 🎯 (repete só se cair mais) |
| Novo menor preço já visto do modelo | 🏆 |
| Cupom novo numa loja que vende a TV, com regra compatível | 🎟️ com o preço da loja |
| Uma fonte falhou 3 vezes seguidas | ⚠️ |
| Todo dia às 9h | ☀️ resumo com todos os preços |

Todo alerta diz o modelo. Os alvos são ajustáveis pelas variáveis `ALVO_PIX` e `ALVO_PARCELADO` (55C6K) e `ALVO_PIX_65` e `ALVO_PARCELADO_65` (65C6K). O painel mostra as duas TVs, uma tabela com quanto a 65" custa a mais que a 55" na mesma loja (à vista e parcelado) e um gráfico de histórico por modelo.

### PS5 e GTA 6

| Produto | Meta Pix | Meta parcelado (total) |
|---|---|---|
| PS5 Slim Digital (com ou sem os 2 jogos digitais) | R$ 3.550 | R$ 3.700 |
| PS5 Slim com leitor | R$ 3.950 | R$ 4.150 |
| PS5 Pro | R$ 5.950 | R$ 6.100 |
| Pacote PS5 Digital + GTA 6 | R$ 4.000 | R$ 4.150 |
| Pacote PS5 com leitor + GTA 6 | R$ 4.300 | R$ 4.450 |
| Edição especial / kit | meta do console-base + valor do extra | idem |
| GTA 6 Code in Box que chega até 18/11 | R$ 345 | R$ 370 |
| GTA 6 Code in Box que chega depois | R$ 300 | R$ 320 |
| GTA 6 digital Standard / Ultimate / upgrade (custo efetivo, com gift card) | R$ 365 / R$ 450 / R$ 85 | idem |
| Gift card PlayStation em loja oficial | 15% de desconto ou mais | idem |
| Leitor de disco avulso | R$ 300 | R$ 320 |

O GTA 6 sai em 19/11/2026; a "versão física" no Brasil é Code in Box (caixa com código, sem disco). Para jogar à meia-noite a caixa tem de chegar até 18/11: todo alerta do GTA físico traz a entrega prevista e se chega a tempo (o prazo vem da loja quando a fonte o lê; sem ele, uma estimativa por loja marcada como aproximada). Toda postagem nova de PS5/GTA 6 vira alerta, com a meta e a distância até ela. Metas por variável: `ALVO_PIX_<ID>` e `ALVO_PARCELADO_<ID>` (ex.: `ALVO_PIX_PS5_DIGITAL`). O painel tem uma seção por família (TVs, PS5, GTA 6) com o melhor à vista e parcelado de cada produto, a tabela por loja, um gráfico por produto e, no GTA 6, todas as formas comparadas pelo custo final. O modo vigia das TVs não afeta o PS5 nem o GTA 6.

### Testador de cupons no carrinho (PC)

`testar_cupons.py` testa, com a conta logada (perfil próprio do Chrome), os cupons conhecidos de cada loja no carrinho do Magalu e do Mercado Livre (na Amazon, só leitura da página do anúncio). Cada cupom é medido com o produto sozinho no carrinho (o cupom vale para o pedido) e só nos produtos em que a regra do cupom cabe (cupom de moda, de TV ou só do GTA 6 não é testado no console). No fim da rodada o carrinho fica com **1 unidade de cada produto principal** que a loja tem: as TVs, o PS5 Digital, o PS5 com leitor, o PS5 Pro e o GTA 6 Code in Box, com o cupom de maior economia. Pacote PS5 + GTA 6, kit/edição especial e gift card da PlayStation só são testados quando são o caminho mais barato para um principal (o preço menos o valor do extra; no gift card, o GTA 6 digital pago com ele) e nunca ficam no carrinho. O robô nunca põe outro produto, nunca mexe em item que não é dos monitorados, nunca passa de 1 unidade por produto e nunca finaliza a compra. A mensagem traz, por produto, o preço + frete, a meta e, no GTA 6, a entrega (a data que o carrinho logado mostra, quando aparece; senão a estimativa da coleta). No modo vigia das TVs o testador continua rodando para o PS5 e o GTA 6.

### Confiança nos vendedores (antes de qualquer alerta de preço)

Cada anúncio de loja recebe um veredito (`monitor/confianca.py`), sem atrasar os vendedores conhecidos:

| Veredito | O que acontece |
|---|---|
| **confiável** (lista `monitor/listas_confianca.json`) | alerta na hora, sem checagem nenhuma |
| **reprovado** (lista curada ou reprovado automático) | descartado de cara: sem alerta, mínimo, histórico, painel nem carrinho |
| **suspeito** (vendedor fora da lista com qualquer sinal forte, ou 4+ sinais fracos) | uma mensagem ⚠️ "Anúncio suspeito — possível golpe" com os sinais (repetida só se o preço cair mais 2%); sem 🎯/🏆/🔻, fora do mínimo, histórico, painel, resumo e carrinho |
| **sem risco aparente** (desconhecido que passou) | alerta normal + linha 🔎 com o que foi checado |

Sinais fortes: preço até 80% da loja confiável mais barata do mesmo modelo (sozinho já torna o anúncio suspeito), "preço cheio" (o do cartão da própria oferta) igual ao de uma loja confiável com desconto enorme só no Pix/1x, homologação Anatel diferente da C6K (`00738-24-06714`, a mesma nas duas medidas), tamanho da ficha diferente do modelo e, no Magalu, loja do vendedor sem TV no catálogo (1 requisição, guardada por 7 dias). Sinais fracos: modelo genérico, anúncio sem avaliações, peso de mentira, sem Full, vendedor novo, com poucas vendas ou de outro ramo. O suspeito só vira **reprovado automático** (descartado de cara nas próximas coletas) com 2+ sinais fortes, um deles de identidade (Anatel, tamanho ou catálogo); preço baixo sozinho é reavaliado a cada rodada. A chave do reprovado automático é o vendedor, nunca o anúncio de outro vendedor. Linha do Zoom de loja sem coleta própria passa pela mesma checagem de preço. Para liberar um vendedor suspeito ou reprovado automaticamente, ponha-o em `confiaveis` (a lista curada vence, inclusive no painel); quando a oferta traz o id do vendedor, a lista casa pelo id, não pelo nome de exibição. O texto das listas é neutro: uma empresa listada pode ser vítima (conta invadida), não autora.

No Magalu, vendedor novo que ficou sem checagem nesta rodada (403, limite de 2 vendedores por rodada, página ilegível) e está abaixo da loja confiável mais barata também sai como suspeito ("não deu para checar"), sem virar reprovado: é reavaliado na rodada seguinte. A ficha do anúncio lida numa rodada (Anatel, modelo, avaliações...) fica no state por 7 dias e vale quando a coleta só traz a busca. O cupom da página de um anúncio reprovado ou suspeito não vai ao alerta, ao painel nem ao testador. Se o `listas_confianca.json` tiver erro de sintaxe, valem as entradas de reserva do código (as próprias lojas e o bloqueio curado) e chega um aviso no Telegram (no máximo a cada 6 h).

## Configurar (uma vez)

### 1. Bot do Telegram (2 min)
1. No Telegram, fale com **@BotFather** → `/newbot` → guarde o **token**.
2. Fale com **@userinfobot** → `/start` → guarde o seu **chat id**.
3. Mande qualquer mensagem para o bot novo (bots não iniciam conversa).

### 2. GitHub
1. Crie um repositório **público** e envie este projeto (`git push`).
2. **Settings → Secrets and variables → Actions → Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e (opcional) `CEP_ENTREGA`, o CEP de entrega para o prazo do GTA 6.
3. (Opcional) **Variables**: `ALVO_PIX`, `ALVO_PARCELADO`, `ALVO_PIX_65`, `ALVO_PARCELADO_65`, `TELEGRAM_CANAIS_EXTRA` (canais públicos separados por vírgula), `MAGALU_ANUNCIOS_EXTRA` (links de anúncios do Magalu que a busca não mostra, separados por vírgula).
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
monitor/produtos.py      catálogo dos produtos (TVs, PS5, GTA 6...) e o classificador de títulos e de mensagens
monitor/filtro.py        aceita só 55C6K e 65C6K e diz qual (rejeita 75/85C6K, vizinhos como 65C7K, combos, acessórios, usados)
monitor/sources/*.py     um coletor por fonte (entrega.py: prazo de entrega do GTA 6, dias úteis, datas por extenso)
monitor/regras.py        o que vira alerta
monitor/confianca.py     veredito de cada anúncio (confiável, reprovado, suspeito, sem risco aparente)
monitor/listas_confianca.json  vendedores confiáveis e reprovados (curados)
monitor/estado.py        docs/data/state_*.json, historico_*.csv, latest_*.json
monitor/carrinho.py      adaptadores do carrinho (Magalu, Mercado Livre, Amazon só leitura) do testador de cupons
testar_cupons.py         testador de cupons no carrinho (TVs, PS5, GTA 6)
docs/index.html          painel (GitHub Pages)
tests/                   testes com HTML/JSON reais salvos
```
