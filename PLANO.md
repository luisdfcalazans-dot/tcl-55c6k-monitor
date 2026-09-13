# Monitor de preço — TCL 55C6K (QD-Mini LED 55")

Plano de execução baseado em pesquisa feita em 13/09/2026. Todos os endpoints e sites listados como "OK" foram testados hoje, a partir desta máquina.

---

## 1. Resumo da decisão

**Não existe solução pronta que faça o que você quer** (um único modelo, todas as lojas confiáveis do Brasil, sites de promoção e Telegram, acessível de qualquer lugar). O que existe se divide em dois grupos:

| Grupo | Exemplos | Veredito |
|---|---|---|
| Rastreadores genéricos self-hosted | changedetection.io (34k ★), PriceBuddy (1,1k ★), Discount Bandit (741 ★) | Bons para "vigiar uma URL", mas exigem servidor sempre ligado (Docker), não entendem sites de promoção/cupons/Telegram, não têm lojas brasileiras e continuam bloqueados por Akamai (Magalu, Casas Bahia). |
| Projetos brasileiros no GitHub | promo-tracker, Promo-Zeros-Bot, bot-monitor-promocoes, Deal-Hunter, PelandoBot | Todos pessoais (0–1 ★), focados em outros nichos (tênis, hardware). Nenhum é reaproveitável inteiro, mas a **arquitetura** deles é exatamente a certa e vale copiar: GitHub Actions com cron + estado versionado no repo + bot Telegram, custo zero. |

**Recomendação:** construir um projeto pequeno em Python (≈ 600–900 linhas), copiando a arquitetura do `promo-tracker` e os truques de extração que validei hoje. Rodar de graça no GitHub Actions, com um painel estático no GitHub Pages (acessível de qualquer computador/celular) e alertas por bot do Telegram. Um "executor de apoio" opcional no seu PC cobre as 2–3 lojas que bloqueiam IP de datacenter.

---

## 2. O que foi pesquisado e o que funciona

### 2.1 Lojas que vendem a 55C6K — método validado

| Loja | Como coletar | Testado hoje | Preço visto hoje |
|---|---|---|---|
| **Amazon.com.br** (ASIN `B0F7JZMVKF`) | HTML da página do produto (`a-price-whole`, `displayPrice`) | OK do seu IP. **Bloqueia IPs de datacenter** (GitHub Actions) com captcha | R$ 3.278,06 |
| **Magazine Luiza** (produto `240162700`, vendido pelo Magalu) | Site principal responde **403 (Akamai)**. Solução: o espelho `magazinevoce.com.br` entrega o mesmo produto sem bloqueio, com `__NEXT_DATA__` contendo preço Pix (`bestPrice`), vendedor 1P e **cupons ativos com validade** (ex.: `LU250`, R$ 250 OFF até 14/09) | OK | R$ 3.704,05 no Pix (R$ 3.899 lista) |
| **KaBuM!** (código `911482`) | API pública JSON `servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products/911482` (preço base, preço com desconto, oferta ativa com validade) | OK | R$ 3.408,90 base; oferta "Semana do Cliente" R$ 3.159 |
| **Fast Shop** (ref `TK55C6KPTO_PRD`) | API pública VTEX `site.fastshop.com.br/api/catalog_system/pub/products/search?ft=55c6k` | OK | R$ 3.296,81 (API) / R$ 3.099 no Pix (via Zoom) |
| **Loja oficial TCL** (`lojatcl.com.br`, produto `32054`) | API pública VTEX + teaser "8% Pix" | OK | R$ 3.719 (lista 3.999) → ≈ R$ 3.421 Pix |
| **Webcontinental** | API pública VTEX | OK | R$ 3.324,05 |
| **Mercado Livre** (catálogo `MLB48808732`) | Página bloqueia bot ("suspicious traffic"); a API exige OAuth com login único da sua conta ML (`authorization_code` + `refresh_token`). Alternativa: cobrir ML só via Promobit/Pelando/Telegram, que hoje já trazem as ofertas dele (R$ 3.035 com cupom `LIBERAESSA`) | Parcial | R$ 3.035,08 (via Promobit) |
| **Casas Bahia / Ponto / Extra** | 403 (Akamai). Só com navegador real (Playwright no seu PC) ou via sites de promoção | Bloqueado | — |
| Carrefour, Americanas | Não estão vendendo a 55C6K no momento | — | — |
| AliExpress (loja oficial TCL), Shopee | Anti-bot forte. Aparecem no Pelando a R$ 2,4–2,9 mil, mas são importação/marketplace. Sugiro **não** monitorar direto, só registrar quando aparecer no Pelando/Promobit | Opcional | — |

### 2.2 Comparadores e histórico

| Fonte | Como | Testado |
|---|---|---|
| **Zoom / Buscapé** (produto `13992267`) | A página traz JSON-LD `Product` com **todas as 6 ofertas** (loja + preço) e o texto "média de 40 dias: R$ 3.079,12". Um único GET cobre Webcontinental, Fast Shop, KaBuM, Amazon e Magalu | OK |
| Keepa (Amazon.com.br) | Extensão gratuita para ver histórico da Amazon; API é paga (≈ €19/mês). Não vale para automação | Só consulta manual |

### 2.3 Sites de promoção

| Site | Como | Testado |
|---|---|---|
| **Promobit** | API pública `api.promobit.com.br/search?q=tcl 55c6k` → JSON com `active_offers`/`finished_offers` (preço, cupom, loja, data, slug). Categoria TV: `/promocoes/tv/s/` (`__NEXT_DATA__.serverOffers`). **Cupons por loja**: `/cupons/loja/magazine-luiza/` etc. → `serverCoupons` com código, desconto, regras e validade | OK |
| **Pelando** | Busca renderida no servidor: `pelando.com.br/busca/55c6k` (cards com `data-deal-id`, título, preço, loja, marca "Expirado"). **Cupons por loja**: `/cupons-de-descontos/magalu`, `/amazon`, `/mercado-livre`… com o código no HTML (`card__cta-hidden-text`, `data-status="active"`) | OK |
| Hardmob (fórum Promoções) | HTML aberto, dá para filtrar títulos | OK, opcional |
| Gatry | Renderizado por JS, pouco valor extra | Pular |

Histórico de postagens da 55C6K nesses sites (preços já vistos): R$ 2.419 (Amazon), 2.569, 2.659, 2.754, 2.840 (Magalu com cupom `ESQUENTA320` no Pix, ~07/09), 2.849, 2.910 (Magalu com cupom `TECNOBLOG250` no Pix, 10/09), 2.939, 2.990, 3.035 (ML). Ou seja: **abaixo de R$ 2.900 em loja confiável é promoção real; abaixo de R$ 2.600 é o piso histórico.**

### 2.4 Telegram

Canais **públicos** podem ser lidos sem conta, pela prévia web `https://t.me/s/<canal>` (HTML com texto, data e id da mensagem). Validados hoje:

| Canal | O que é |
|---|---|
| `ctofertaseletroetv` | Canaltech Ofertas — Eletro e TVs (cupons exclusivos, muita TCL) |
| `achadosdotb` | Achados do Tecnoblog (cupons exclusivos, ex.: `TECNOBLOG250`) |
| `cupons_desconto` | Canal oficial do Promobit |
| `hardmob_promo` | hardMOB Promoções |
| `promotop`, `vrlofertas`, `tecnanofertas`, `ofertasdodia`, `Postou_Achou` | Canais gerais de ofertas |

Grupos fechados ou canais privados exigem uma conta de usuário (biblioteca Telethon, sessão salva como segredo). O Pelando só tem grupos no WhatsApp (sem API viável; fica de fora).

### 2.5 Cupons

Três camadas, todas cobertas pelas fontes acima:
1. **Cupons da própria loja** (aparecem no JSON do Magazine Você e nos teasers VTEX).
2. **Cupons agregados** (Promobit `/cupons/loja/…`, Pelando `/cupons-de-descontos/…`).
3. **Cupons exclusivos de mídia** (Tecnoblog, Canaltech, Promobit) — chegam pelos canais do Telegram e pelas postagens dos sites.

O alerta de cupom só dispara quando o cupom é de uma loja que vende a 55C6K **e** a regra do cupom cobre o preço da TV (ex.: "acima de R$ 1.000" ✔, "compras até R$ 300" ✘).

---

## 3. Arquitetura proposta

```
GitHub (repo público, grátis)
├── .github/workflows/monitor.yml   cron a cada 15 min
├── monitor/
│   ├── sources/          um coletor por fonte (retorna ofertas normalizadas)
│   │   ├── promobit_api.py      promobit_cupons.py
│   │   ├── pelando_busca.py     pelando_cupons.py
│   │   ├── zoom_jsonld.py
│   │   ├── magalu_magazinevoce.py
│   │   ├── kabum_api.py
│   │   ├── vtex.py              (Fast Shop, Loja TCL, Webcontinental)
│   │   ├── telegram_public.py   (t.me/s/…)
│   │   └── amazon_html.py, casasbahia_playwright.py   ← só no executor do PC
│   ├── filtro.py         aceita SÓ 55C6K (regex + lista negativa: 65/75/85/98C6K, C655, combos, soundbar, usado)
│   ├── regras.py         quando alertar
│   ├── notificar.py      Telegram Bot API
│   └── estado.py         data/state.json + data/historico.csv (versionados no repo)
├── docs/index.html       painel estático (GitHub Pages) lendo data/latest.json
└── tests/                HTML/JSON salvos de cada fonte → o teste quebra antes do site "quebrar" o monitor
```

**Fluxo a cada execução (≈ 30 s):** coletar em todas as fontes → filtrar só 55C6K → normalizar (preço à vista, preço Pix, cupom, loja, URL, data) → comparar com o estado → gerar alertas → gravar estado/histórico → `git commit` → GitHub Pages atualiza sozinho.

**Regras de alerta (Telegram):**
- Novo **menor preço histórico** em loja confiável.
- Preço ≤ **preço-alvo** que você definir (sugestão inicial: R$ 2.900 no Pix).
- **Novo cupom** aplicável a uma loja que tem a TV (com o preço estimado já com o cupom).
- **Nova postagem** no Pelando / Promobit / canais do Telegram mencionando a 55C6K (com preço e link).
- Resumo diário às 9h (opcional) e aviso quando algum coletor falhar 3 vezes seguidas (para você saber que um site mudou).

**Acesso de qualquer computador:**
- **Painel** em `https://<seu-usuario>.github.io/<repo>/` — tabela de preço por loja, gráfico do histórico, cupons ativos, últimas menções, hora da última coleta.
- **Telegram** no celular/PC para os alertas.
- O próprio `data/historico.csv` no GitHub, se quiser abrir no Excel.

**Onde roda:**
- **GitHub Actions** (nuvem, grátis em repo público, mínimo 5 min entre execuções). Cobre todas as fontes, exceto Amazon e Casas Bahia, que bloqueiam IP de datacenter.
- **Executor no seu PC (opcional, Fase 4):** tarefa do Agendador do Windows a cada 30 min rodando Amazon (HTML) e Casas Bahia (Playwright com Chrome real), e fazendo push no mesmo repo. Enquanto ele não existir, Amazon vem pelo Zoom (que já lista o preço da Amazon) e Casas Bahia pelos sites de promoção.

---

## 4. Etapas de execução

| Fase | Entrega | Esforço |
|---|---|---|
| **0. Preparação** | Criar repo público, bot no @BotFather, `chat_id`, segredos no GitHub, estrutura do projeto | 30 min |
| **1. Núcleo** | Coletores por API/JSON (Promobit, KaBuM, VTEX ×3, Zoom, Magazine Você) + filtro estrito 55C6K + estado + alertas Telegram + workflow de 15 min | 1 dia |
| **2. Promoções e cupons** | Pelando (busca + cupons), cupons Promobit, canais públicos do Telegram, regras de cupom aplicável | ½ dia |
| **3. Painel** | Página estática no GitHub Pages com tabela, gráfico e cupons; `latest.json` gerado a cada execução | ½ dia |
| **4. Executor no PC** | Amazon HTML + Casas Bahia via Playwright + (opcional) Mercado Livre via OAuth + (opcional) grupos privados via Telethon; tarefa agendada no Windows | ½ dia |
| **5. Robustez** | Testes com fixtures de cada fonte, revalidação de ofertas expiradas, alerta de coletor quebrado, throttling educado (1 req/fonte/execução) | ½ dia |

Total: ≈ 3 dias de trabalho, custo mensal R$ 0.

---

## 5. Riscos e como lidar

| Risco | Mitigação |
|---|---|
| Site muda HTML/JSON | Teste por fonte com arquivo salvo; alerta "coletor X falhou 3×"; cada coletor é isolado (um quebrar não derruba o resto) |
| Bloqueio anti-bot | Cabeçalhos de navegador, 1 requisição por fonte a cada 15 min (volume de um usuário normal), sem proxy pago; fontes bloqueadas ficam no executor do PC |
| GitHub desliga cron após 60 dias sem commits | Os commits de estado a cada execução já evitam isso |
| Falso positivo (65C6K, combo com soundbar, TV usada) | Lista negativa explícita + teste unitário com os títulos reais coletados hoje |
| Cupom que não se aplica | Só alerta se a regra do cupom (valor mínimo/máximo, categoria) for compatível; mostra o texto da regra no alerta |
| Termos de uso | Uso pessoal, baixo volume, só dados públicos; nada de contornar captcha |

---

## 6. Decisões que preciso de você antes de começar

1. **Preço-alvo** para o alerta "compra agora" (sugestão: R$ 2.900 no Pix; "excelente" abaixo de R$ 2.600).
2. **Repositório público no GitHub** está OK? (É o que dá o cron grátis; só dados públicos ficam lá, tokens ficam em Secrets.)
3. **Executor no PC** (Fase 4) — quer? Ele cobre Amazon e Casas Bahia de verdade, mas depende do PC ligado.
4. **Mercado Livre direto** via OAuth (você cria um app com sua conta ML, login único) ou só via sites de promoção?
5. **AliExpress (loja oficial TCL)**: ignorar totalmente ou registrar quando aparecer nos sites de promoção?
6. **Canais/grupos extras do Telegram** que você já segue e quer incluir (me mande os links).

---

## 7. Fontes consultadas

Projetos: [changedetection.io](https://github.com/dgtlmoon/changedetection.io) · [PriceBuddy](https://github.com/jez500/pricebuddy) · [Discount Bandit](https://github.com/Cybrarist/Discount-Bandit) · [promo-tracker](https://github.com/hallyssonrhuan/promo-tracker) · [Promo-Zeros-Bot](https://github.com/Ismaelzero0/Promo-Zeros-Bot) · [bot-monitor-promocoes](https://github.com/Lbfte/bot-monitor-promocoes) · [Deal-Hunter](https://github.com/samuelmel/Deal-Hunter) · [PelandoBot](https://github.com/GustavoJST/PelandoBot) · [telegram-keyword-monitor](https://github.com/security-hab/telegram-keyword-monitor) · [Tracker-Price](https://github.com/Darlan0307/Tracker-Price)

Lojas e comparadores: [Amazon](https://www.amazon.com.br/dp/B0F7JZMVKF) · [Magazine Luiza](https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-assistente-4-hdmi-2-usb/p/240162700/et/elit/) · [KaBuM](https://www.kabum.com.br/produto/911482/) · [Fast Shop](https://site.fastshop.com.br/smart-tv-4k-tcl-qd-mini-led-55%E2%80%9D-polegadas-com-hdmi-2-1--dolby-vision-iq--subwoofer--144hz-vrr-e-wi-fi---55c6k-tk55c6kpto_prd/p) · [Loja TCL](https://www.lojatcl.com.br/smart-tv-tcl-55-polegadas-qled-mini-led-4k-c6k-wifi-bluetooth-google-tv-4-hdmi-144hz-hdr10-55c6k/p) · [Mercado Livre](https://www.mercadolivre.com.br/p/MLB48808732) · [Casas Bahia](https://www.casasbahia.com.br/smart-tv-55-tcl-55c6k-4k-qd-mini-led-144hz-sistema-operacional-google-tv/p/55069456) · [Zoom](https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k) · [Buscapé](https://www.buscape.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k) · [API pública VTEX](https://dev.to/antonio_fernandorincond/a-api-publica-de-catalogo-da-vtex-que-quase-ninguem-usa-40li) · [Keepa](https://keepa.com/api-docs/) · [Autenticação Mercado Livre](https://developers.mercadolivre.com.br/en_us/authentication-and-authorization)

Promoções e cupons: [Promobit](https://www.promobit.com.br/oferta/smart-tv-tcl-55c6k/) · [Pelando](https://www.pelando.com.br/d/smart-tv-tcl-55c6k-qled-mini-led-4k-6af1) · [Tecnoblog Achados](https://tecnoblog.net/achados/tv-tcl-mini-led-55-sai-r-1-mil-mais-barata-com-nosso-cupom-exclusivo/) · [Canaltech grupos](https://ofertas.canaltech.com.br/grupos-de-oferta/) · [Tudocelular](https://www.tudocelular.com/android/noticias/n254560/smart-tv-tcl-55c6k-oferta-desconto-amazon-parcelad.html)

Infra: [GitHub Actions cron](https://cronuru.com/guides/github-actions-scheduled-workflows) · [Bloqueio de Amazon em datacenter](https://proxyvibe.dev/en/blog/amazon-scraping-guide/) · [Anti-bot Cloudflare/Akamai](https://github.com/pim97/anti-detect-browser-tools-tech-comparison)
