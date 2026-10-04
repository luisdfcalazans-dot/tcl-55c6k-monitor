"""Configuração central: alvos, endereços das fontes, canais e lojas. O catálogo dos produtos (ids, nomes, metas
padrão, termos de busca, EANs, ids por loja) fica em monitor/produtos.py; os valores das TVs daqui saem dele."""

from __future__ import annotations

import os
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "docs" / "data"

# Produtos monitorados: a TCL 55C6K (desde 13/09), a TCL 65C6K (26/09/2026) e, desde 03/10/2026, o PS5 e o GTA 6 em
# todas as versões/formas (monitor/produtos.py). MODELOS são as duas TVs (as fontes e o carrinho das TVs usam isso).
from .models import MODELO_55 as MODELO, MODELO_65, MODELOS  # noqa: E402  (MODELO: o de sempre; dado sem o campo é dele)
from . import produtos as _produtos  # noqa: E402

MARCA = "TCL"

def _env(nome: str, padrao: str) -> str:
    """Variável de ambiente, tratando vazia como ausente (no GitHub Actions, vars não definidas chegam como '')."""
    v = os.environ.get(nome, "")
    return v.strip() if v and v.strip() else padrao


def _alvo_padrao(pid: str, campo: str) -> str:
    return str(getattr(_produtos.PRODUTOS[pid], campo))


# Alvos de preço. Podem ser sobrescritos por variável de ambiente.
ALVO_PIX = float(_env("ALVO_PIX", _alvo_padrao(MODELO, "alvo_pix")))          # 55C6K: à vista / Pix
ALVO_PARCELADO = float(_env("ALVO_PARCELADO", _alvo_padrao(MODELO, "alvo_parcelado")))  # 55C6K: total parcelado
ALVO_PIX_65 = float(_env("ALVO_PIX_65", _alvo_padrao(MODELO_65, "alvo_pix")))  # 65C6K: Pix (decisão do usuário em 26/09)
ALVO_PARCELADO_65 = float(_env("ALVO_PARCELADO_65", _alvo_padrao(MODELO_65, "alvo_parcelado")))
# Os outros produtos (metas aprovadas pelo usuário em 03/10; catálogo em monitor/produtos.py): ALVO_PIX_<ID> e
# ALVO_PARCELADO_<ID> por variável (ex.: ALVO_PIX_PS5_DIGITAL=3400). Kit e gift card têm a meta calculada por oferta.
ALVOS_PRODUTOS: dict[str, dict[str, float | None]] = {
    pid: {"pix": float(_env(f"ALVO_PIX_{pid}", str(p.alvo_pix))) if p.alvo_pix is not None else None,
          "parcelado": float(_env(f"ALVO_PARCELADO_{pid}", str(p.alvo_parcelado)))
          if p.alvo_parcelado is not None else None}
    for pid, p in _produtos.PRODUTOS.items() if p.familia != _produtos.FAMILIA_TV
}
QUEDA_MINIMA_PCT = float(_env("QUEDA_MINIMA_PCT", "2"))  # queda vs. última coleta que gera alerta

# Modo vigia (03/10/2026): o usuário COMPROU a 65C6K por R$ 3.527 (Pelando, Mais Correios / Ponto Frio). Até VIGIA_ATE só
# sai alerta da 65C6K com preço pelo menos R$ 100 abaixo do que ele pagou (para devolver no prazo de arrependimento e
# recomprar); alertas da 55C6K, de cupom e o resumo diário param, e o testador de cupons não roda.
VIGIA_MODELO = "65C6K"
VIGIA_PRECO_PAGO = float(_env("VIGIA_PRECO_PAGO", "3527"))
VIGIA_LIMITE = float(_env("VIGIA_LIMITE", str(VIGIA_PRECO_PAGO - 100)))
VIGIA_ATE = _env("VIGIA_ATE", "2026-10-17")   # inclusive; ajustar para 7 dias depois da entrega


def modo_vigia(hoje_iso: str | None = None) -> bool:
    """Ainda dentro da janela de vigia da TV comprada? (vazio em VIGIA_ATE desliga o modo). A vigia vale SÓ para as
    TVs (vigia_afeta): PS5, GTA 6 e o resto do catálogo continuam com alertas, cupons e testador."""
    if not VIGIA_ATE:
        return False
    from datetime import date
    d = hoje_iso or date.today().isoformat()
    return d <= VIGIA_ATE


def vigia_afeta(produto: str | None) -> bool:
    """O modo vigia muda o tratamento deste produto? Só as TVs (a família da TV comprada)."""
    return _produtos.eh_tv(produto or MODELO)


def alvo_pix(modelo: str | None = None) -> float | None:
    """Alvo do Pix/à vista do produto (sem produto: o da 55C6K). Lê o valor do módulo na hora (os testes trocam). Kit e
    gift card: None (a meta é por oferta: produtos.alvos_da_oferta)."""
    if modelo == MODELO_65:
        return ALVO_PIX_65
    if modelo in ALVOS_PRODUTOS:
        return ALVOS_PRODUTOS[modelo]["pix"]
    return ALVO_PIX


def alvo_parcelado(modelo: str | None = None) -> float | None:
    """Alvo do total parcelado sem juros do produto (sem produto: o da 55C6K)."""
    if modelo == MODELO_65:
        return ALVO_PARCELADO_65
    if modelo in ALVOS_PRODUTOS:
        return ALVOS_PRODUTOS[modelo]["parcelado"]
    return ALVO_PARCELADO


def alvos() -> dict[str, dict[str, float | None]]:
    """{modelo de TV: {'pix': alvo, 'parcelado': alvo}} (vai para o latest_<modo>.json e o painel, como antes). As metas
    dos outros produtos vão no catálogo do latest ('produtos', produtos.para_painel) e em alvos_produtos()."""
    return {m: {"pix": alvo_pix(m), "parcelado": alvo_parcelado(m)} for m in MODELOS}


def alvos_produtos() -> dict[str, dict[str, float | None]]:
    """{produto: {'pix', 'parcelado'}} de todo o catálogo (as TVs primeiro; kit e gift card: None, a meta é por oferta)."""
    return {m: {"pix": alvo_pix(m), "parcelado": alvo_parcelado(m)} for m in _produtos.IDS}


# CEP de entrega do usuário (prazo do GTA 6): SÓ da variável de ambiente CEP_ENTREGA (.env do PC, secret do GitHub).
# Nunca vai para código, log, teste, docs/data nem anotações. Sem ele, o CEP de referência (centro de São Paulo, o
# mesmo da pesquisa de 03/10) e o prazo sai marcado como aproximado (Oferta.extra['cep_referencia'] = True).
CEP_REFERENCIA = "01310100"


def cep_entrega() -> tuple[str, bool]:
    """(CEP só com dígitos, é o de referência?). Não imprimir o CEP."""
    cep = re.sub(r"\D", "", os.environ.get("CEP_ENTREGA", ""))
    return (cep, False) if len(cep) == 8 else (CEP_REFERENCIA, True)


# Termos de busca usados nos sites de promoção (BUSCAS é o da 55C6K, como antes). Do catálogo (monitor/produtos.py)
BUSCAS = _produtos.termos_do_produto(MODELO, "promobit")
BUSCAS_65 = _produtos.termos_do_produto(MODELO_65, "promobit")
BUSCAS_POR_MODELO = {MODELO: BUSCAS, MODELO_65: BUSCAS_65}

# Código de barras (EAN) de cada modelo: identifica o tamanho mesmo quando o título do anúncio diz outra coisa
EAN_POR_MODELO = _produtos.eans_por_produto([_produtos.FAMILIA_TV])

# --- Lojas com acesso direto (rodam na nuvem) ---
URL_ZOOM = "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k"
# o slug da 65" é outro ("qd-mini-led"): o da 55" com 65 no lugar responde 200 com uma página de BUSCA, sem JSON-LD
URL_ZOOM_65 = "https://www.zoom.com.br/tv/smart-tv-qd-mini-led-65-tcl-4k-65c6k"
URLS_ZOOM = {MODELO: URL_ZOOM, MODELO_65: URL_ZOOM_65}
URL_KABUM_API = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products/911482"
URL_KABUM_PRODUTO = "https://www.kabum.com.br/produto/911482"
URL_KABUM_API_BASE = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products/"
URL_KABUM_PRODUTO_BASE = "https://www.kabum.com.br/produto/"
# anúncios da KaBuM por modelo (26/09: a 65" tem dois, Lojas Colombo e Magalu; 938062 é a 65C7K, vizinha)
KABUM_PRODUTOS = {MODELO: ["911482"], MODELO_65: ["911480", "938060"]}
URL_MAGALU_BUSCA = "https://www.magazinevoce.com.br/magazinecanaltechbr/busca/tcl+55c6k/"
URL_MAGALU_PRODUTO = (
    "https://www.magazinevoce.com.br/magazinecanaltechbr/"
    "smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-assistente-4-hdmi-2-usb/p/240162700/et/elit/"
)
# anúncio do Magalu 1P da 65" (a variação 240162600 do mesmo grupo 240162800 da 55"; slug real, o falso dá 404)
URL_MAGALU_PRODUTO_65 = (
    "https://www.magazinevoce.com.br/magazinecanaltechbr/"
    "smart-tv-65-tcl-4k-uhd-miniled-65c6k-120hz-google-tv-aipq-google-assistente-4-hdmi-2-usb/p/240162600/et/elit/"
)
# Descoberta de TODOS os anúncios do Magalu (19/09): várias buscas + anúncios vistos nos últimos 14 dias. A busca da
# 65" (26/09) vem logo depois da principal da 55": ela traz o 1P, a Colombo, a Leonfer e a Webcontinental da 65".
MAGALU_TERMOS = _produtos.termos("magalu", [_produtos.FAMILIA_TV])  # 55" e 65" intercaladas (catálogo)
MAGALU_MAX_BUSCAS = 6            # páginas de busca por rodada (uma por termo + 1 página seguinte)
MAGALU_MAX_REQUISICOES = 16      # teto de requisições ao magazinevoce por rodada (buscas + anúncios; 12 antes da 65")
MAGALU_PAUSA_S = float(_env("MAGALU_PAUSA_S", "1.5"))
# Anúncios que a busca não mostra (URL do magazineluiza.com.br com o slug real). Também por variável:
# MAGALU_ANUNCIOS_EXTRA="https://www.magazineluiza.com.br/.../p/<id>/et/elit/,https://..."
MAGALU_ANUNCIOS_EXTRA: list[str] = [
    u.strip() for u in os.environ.get("MAGALU_ANUNCIOS_EXTRA", "").split(",") if u.strip()
]
LOJAS_VTEX = {
    "Fast Shop": "https://site.fastshop.com.br",
    "Loja TCL": "https://www.lojatcl.com.br",
    "Webcontinental": "https://www.webcontinental.com.br",
}
# busca da API de catálogo VTEX por modelo (ft=<termo>); a Webcontinental dá timeout com consultas seguidas: pausa
VTEX_TERMOS = {MODELO: "55c6k", MODELO_65: "65c6k"}
VTEX_PAUSA_S = float(_env("VTEX_PAUSA_S", "1.5"))

# --- Lojas que exigem IP residencial / navegador real (rodam no PC) ---
URL_AMAZON_PRODUTO = "https://www.amazon.com.br/dp/B0F7JZMVKF"
URL_AMAZON_CARRINHO = "https://www.amazon.com.br/gp/cart/view.html"
URL_AMAZON_LOGIN = "https://www.amazon.com.br/ap/signin?openid.return_to=https%3A%2F%2Fwww.amazon.com.br%2Fgp%2Fcart%2Fview.html&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
URL_AMAZON_BUSCA = "https://www.amazon.com.br/s?k=tcl+55c6k"
URL_AMAZON_BUSCA_65 = "https://www.amazon.com.br/s?k=tcl+65c6k"
ASIN_AMAZON = "B0F7JZMVKF"
ASIN_AMAZON_65 = "B0F7K7B2PD"
ASINS_AMAZON = {MODELO: ASIN_AMAZON, MODELO_65: ASIN_AMAZON_65}
URLS_AMAZON_BUSCA = {MODELO: URL_AMAZON_BUSCA, MODELO_65: URL_AMAZON_BUSCA_65}
# a própria Amazon como vendedora (merchantID da página; o bloco fixado do painel de ofertas não traz link seller=)
AMAZON_1P_ID = "A1ZZFT5FULY4LN"
# lista de todos os vendedores do anúncio (painel "Outras opções de compra"); responde a HTTP simples
URL_AMAZON_OFERTAS = "https://www.amazon.com.br/gp/product/ajax/aodAjaxMain/?asin={asin}&pc=dp&experienceId=aodAjaxMain"
AMAZON_MAX_CARGAS = 3            # páginas/requisições à Amazon por rodada, POR MODELO
URL_CASASBAHIA_PRODUTO = (
    "https://www.casasbahia.com.br/smart-tv-55-tcl-55c6k-4k-qd-mini-led-144hz-sistema-operacional-google-tv/p/55069456"
)
URL_CASASBAHIA_PRODUTO_65 = (
    "https://www.casasbahia.com.br/smart-tv-65-tcl-65c6k-4k-qd-mini-led-144hz-com-sistema-operacional-google-tv/p/55069453"
)
# "/busca/<termo>" diz "não encontramos nada"; a busca do site é "/<termo-com-hífen>/b"
URL_CASASBAHIA_BUSCA = "https://www.casasbahia.com.br/tcl-55c6k/b"
URL_CASASBAHIA_BUSCA_65 = "https://www.casasbahia.com.br/tcl-65c6k/b"
SKUS_CASASBAHIA = {MODELO: "55069456", MODELO_65: "55069453"}
URLS_CASASBAHIA_PRODUTO = {MODELO: URL_CASASBAHIA_PRODUTO, MODELO_65: URL_CASASBAHIA_PRODUTO_65}
URLS_CASASBAHIA_BUSCA = {MODELO: URL_CASASBAHIA_BUSCA, MODELO_65: URL_CASASBAHIA_BUSCA_65}
CASASBAHIA_MAX_CARGAS = 5        # item de cada modelo, busca de cada modelo e o sku mais barato achado (3 antes da 65")
URL_ML_CATALOGO = "https://www.mercadolivre.com.br/p/MLB48808732"
URL_ML_BUSCA = "https://lista.mercadolivre.com.br/tcl-55c6k"
ML_CATALOGO_ID = "MLB48808732"
ML_CATALOGO_ID_65 = "MLB50368907"   # vizinho perigoso: o catálogo da 65C7K é MLB49823182
URL_ML_CATALOGO_65 = "https://www.mercadolivre.com.br/p/MLB50368907"
URL_ML_BUSCA_65 = "https://lista.mercadolivre.com.br/tcl-65c6k"
ML_CATALOGOS = {MODELO: ML_CATALOGO_ID, MODELO_65: ML_CATALOGO_ID_65}
URLS_ML_CATALOGO = {MODELO: URL_ML_CATALOGO, MODELO_65: URL_ML_CATALOGO_65}
URLS_ML_BUSCA = {MODELO: URL_ML_BUSCA, MODELO_65: URL_ML_BUSCA_65}
# páginas do ML por rodada: catálogo e busca de cada modelo e uma conferência de vendedor (3 antes da 65"). O ML marca
# perfil automatizado: com o 1º bloqueio a rodada para (as páginas seguintes não são pedidas)
ML_MAX_CARGAS = 5
# Anúncio fora do catálogo MAIS BARATO que o catálogo só entra depois de conferir o vendedor na página
# do anúncio: com menos vendas que isto é descartado (19/09: "FEGU2024...", 0 vendas, R$ 2.769).
ML_VENDAS_MINIMAS = 50
PAUSA_ENTRE_PAGINAS_MS = 2500    # pausa entre páginas na mesma janela do Chrome
URL_ALIEXPRESS_BUSCA = "https://pt.aliexpress.com/w/wholesale-tcl-55c6k.html?SearchText=tcl+55c6k&g=y"
URL_ALIEXPRESS_BUSCA_65 = "https://pt.aliexpress.com/w/wholesale-tcl-65c6k.html?SearchText=tcl+65c6k&g=y"
URLS_ALIEXPRESS_BUSCA = {MODELO: URL_ALIEXPRESS_BUSCA, MODELO_65: URL_ALIEXPRESS_BUSCA_65}
URL_SHOPEE_BUSCA = "https://shopee.com.br/search?keyword=tcl%2055c6k"
URL_SHOPEE_BUSCA_65 = "https://shopee.com.br/search?keyword=tcl%2065c6k"
URLS_SHOPEE_BUSCA = {MODELO: URL_SHOPEE_BUSCA, MODELO_65: URL_SHOPEE_BUSCA_65}

# --- PS5 e GTA 6: lojas e endereços (pesquisa e checagem ao vivo de 03/10/2026) ---
_NAO_TV = (_produtos.FAMILIA_PS5, _produtos.FAMILIA_GTA6, _produtos.FAMILIA_ACESSORIO)
# Lojas VTEX lidas pelo código de barras (EAN), num pedido só (vários fq do mesmo campo são OU): a busca por texto perde
# anúncios (Mais Correios: ft=65c6k achou 1, o EAN achou 3). fonte -> (loja, URL, reserva quando a principal falha
# [403 do Cloudflare num IP de nuvem], só o PS5/GTA 6?). Mais Correios e Americanas com o catálogo todo (TVs também);
# Fast Shop e Webcontinental só com o PS5/GTA 6 (as TVs delas continuam na busca de sempre, fontes vtex.<loja>).
LOJAS_VTEX_EAN = {
    "maiscorreios": ("Mais Correios", "https://www.maiscorreios.com.br",
                     "https://maiscorreios.vtexcommercestable.com.br", False),
    "americanas": ("Americanas", "https://www.americanas.com.br", "", False),
    "vtex.fastshop.ps5": ("Fast Shop", LOJAS_VTEX["Fast Shop"], "", True),
    "vtex.webcontinental.ps5": ("Webcontinental", LOJAS_VTEX["Webcontinental"], "", True),
}
# KaBuM: a lista de consoles PlayStation (um pedido traz todos os PS5 da loja, com vendedor e oferta) e a cotação de
# frete (sem login) para o prazo do GTA 6 com o CEP
URL_KABUM_LISTA_CONSOLES = "https://www.kabum.com.br/gamer/playstation/consoles-playstation"
URL_KABUM_FRETE = "https://servicespub.prod.api.aws.grupokabum.com.br/shipping/v4/quotation"
# Magalu (magazinevoce): as buscas do PS5/GTA 6 já trazem preço, vendedor e o cupom do anúncio (seller.tags)
MAGALU_TERMOS_PRODUTOS = _produtos.termos("magalu", _NAO_TV)
MAGALU_PRODUTOS_MAX_REQUISICOES = 4
# Carrefour: busca e página do produto por HTTP (a API VTEX dá 403); a página de cada produto traz vendedor e parcelado
URL_CARREFOUR_BUSCA = "https://www.carrefour.com.br/busca/playstation%205"
URL_CARREFOUR_PRODUTO = "https://www.carrefour.com.br/produto/p-{sku}"   # o slug não importa, só o sku no fim
CARREFOUR_MAX_PRODUTOS = 6
CARREFOUR_PAUSA_S = float(_env("CARREFOUR_PAUSA_S", "1.0"))
# PlayStation Store (preço no JSON-LD da página do produto)
URL_PSSTORE_PRODUTO = "https://store.playstation.com/pt-br/product/{id}"
# Mercado Livre: vitrine da loja oficial PlayStation (official_store_id 1473), um pedido por rodada; a lista com filtro
# de loja e a API dão antirrobô/403
URL_ML_LOJA_PLAYSTATION = "https://www.mercadolivre.com.br/loja/playstation"
# Telegram: busca por termo (t.me/s/<canal>?q=<termo>) nos canais de muito volume: pega a postagem que saiu da 1ª
# página entre uma rodada e outra (o @pelandobr posta 7 a 10 por hora; a nuvem roda com intervalos de horas)
TELEGRAM_CANAIS_BUSCA = [c.strip().lstrip("@") for c in _env("TELEGRAM_CANAIS_BUSCA", "pelandobr").split(",") if c.strip()]
# Promobit: subcategorias lidas pela página (pegam a postagem antes de a busca indexar)
URL_PROMOBIT_PS5 = "https://www.promobit.com.br/promocoes/playstation-5/s/"
# --- só no PC (Chrome) ---
URL_NETSHOES_BUSCA = "https://www.netshoes.com.br/busca?q=playstation+5"
NETSHOES_MAX_PRECOS = 12        # consultas de preço (dentro da página, sem abrir outra) por rodada
URLS_AMAZON_BUSCA_PRODUTOS = (
    "https://www.amazon.com.br/s?k=grand+theft+auto+vi+playstation+5",
    "https://www.amazon.com.br/s?k=console+playstation+5",
)
AMAZON_MAX_CARGAS_PRODUTOS = 4  # páginas do PS5/GTA 6 por rodada (a do GTA e as buscas), além das das TVs
AMAZON_MAX_PAINEIS_PRODUTOS = 8  # painéis de ofertas (vendedor dos preços da busca) por rodada: 1 por produto + 1; HTTP, Chrome se falhar
CASASBAHIA_MAX_CARGAS_PRODUTOS = 3
# catálogos do ML abertos no Chrome do PC depois dos das TVs (só se a rodada não levou bloqueio)
ML_CATALOGOS_PRODUTOS = {"PS5_DIGITAL": "MLB57081243"}

# --- Sites de promoção ---
PROMOBIT_CUPONS_LOJAS = [
    "magazine-luiza", "amazon", "mercado-livre", "kabum", "casas-bahia",
    "fastshop", "aliexpress", "shopee",
    # lojas do PS5 / GTA 6 / gift card (pesquisa de 03/10/2026; "mais-correios" dá 404 no Promobit)
    "netshoes", "americanas", "nuuvem", "hype-games",
]
PELANDO_CUPONS_LOJAS = ["magalu", "amazon", "mercado-livre", "aliexpress", "shopee"]

# --- Telegram: canais públicos (lidos pela prévia web t.me/s/<canal>, sem conta) ---
TELEGRAM_CANAIS_PUBLICOS = [
    "ctofertaseletroetv",   # Canaltech Ofertas — Eletro e TVs
    "achadosdotb",          # Achados do Tecnoblog
    "cupons_desconto",      # Promobit oficial
    "hardmob_promo",        # hardMOB Promoções
    "promotop",
    "vrlofertas",
    "tecnanofertas",
    "ofertasdodia",
    "Postou_Achou",
    # canais que o usuário segue
    "xaviertechpromo",      # XAVIER TECH - Promoções
    "tecnoarthardware",     # TecnoArt (Promoções de Hardware)
    "IskandarSouza",        # Iskandar Souza - Promoções
    "pobregram",            # Pobregram
    "escolhasegura",        # EscolhaSegura // Grupo de Ofertas
    "peperaiohardware",     # PEPERAIO HARDWARE OFERTAS
    "LOOPechinchas",        # Loop Ofertas
    "ofertasmundoconectado",  # Ofertas Mundo Conectado
    "cacadoresofertas",     # Caçadores de Ofertas
    "pelandobr",            # canal OFICIAL do Pelando: repete os posts (lido da nuvem; o site bloqueia datacenter)
    # @ENVOLTOTECH é grupo e @AquiSuaPromoBot é bot: só via conta (TELEGRAM_CHATS_USUARIO, no PC)
]
# Canais extras podem ser adicionados sem mexer no código: TELEGRAM_CANAIS_EXTRA="canal1,canal2"
TELEGRAM_CANAIS_PUBLICOS += [
    c.strip().lstrip("@") for c in os.environ.get("TELEGRAM_CANAIS_EXTRA", "").split(",") if c.strip()
]

# --- Telegram: grupos/canais privados via conta de usuário (só no PC, opcional) ---
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION", "")
TELEGRAM_CHATS_USUARIO = [
    c.strip() for c in os.environ.get("TELEGRAM_CHATS_USUARIO", "").split(",") if c.strip()
]

# --- Notificação ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MAX_ALERTAS_POR_EXECUCAO = int(_env("MAX_ALERTAS_POR_EXECUCAO", "15"))
HORA_RESUMO_DIARIO = int(_env("HORA_RESUMO_DIARIO", "9"))  # hora de Brasília; -1 desliga

# Nomes canônicos de loja (usados para casar cupons com ofertas)
LOJAS_CANONICAS = {
    "magazine luiza": "Magazine Luiza", "magalu": "Magazine Luiza", "magazineluiza": "Magazine Luiza",
    "amazon": "Amazon", "amazon.com.br": "Amazon",
    "mercado livre": "Mercado Livre", "mercadolivre": "Mercado Livre", "mercado-livre": "Mercado Livre",
    "kabum": "KaBuM!", "kabum!": "KaBuM!",
    "casas bahia": "Casas Bahia", "casasbahia": "Casas Bahia", "casas-bahia": "Casas Bahia",
    "fast shop": "Fast Shop", "fastshop": "Fast Shop", "fast-shop": "Fast Shop",
    "aliexpress": "AliExpress", "shopee": "Shopee",
    "loja tcl": "Loja TCL", "tcl": "Loja TCL", "semp tcl": "Loja TCL", "tcl semp": "Loja TCL",
    "webcontinental": "Webcontinental", "maiscorreios": "Mais Correios", "mais correios": "Mais Correios", "maiscorreios.com.br": "Mais Correios",
    "ponto": "Ponto", "pontofrio": "Ponto", "ponto frio": "Ponto", "extra": "Extra",
    "carrefour": "Carrefour", "americanas": "Americanas",
    # PS5 e GTA 6 (pesquisa de 03/10/2026): lojas confiáveis e as que só aparecem pelas postagens
    "netshoes": "Netshoes", "playstation store": "PlayStation Store", "ps store": "PlayStation Store",
    "store.playstation.com": "PlayStation Store", "nuuvem": "Nuuvem", "hype games": "Hype", "hypegames": "Hype",
    "sams club": "Sam's Club", "sam's club": "Sam's Club", "samsclub": "Sam's Club", "terabyte": "Terabyte",
    "terabyteshop": "Terabyte", "inpower": "Inpower", "havan": "Havan", "loja vivo": "Loja Vivo",
    "pichau": "Pichau", "ibyte": "iBYTE", "eneba": "Eneba", "ubiqplay": "UbiqPlay", "tiktok shop": "TikTok Shop",
}
