"""Configuração central. Tudo que é específico da TV e das fontes fica aqui."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "docs" / "data"

# Produtos monitorados: a TCL 55C6K (desde 13/09) e a TCL 65C6K (pedido de 26/09/2026), só esses dois modelos.
# Os nomes e as polegadas ficam em monitor/models.py (MODELOS, POLEGADAS); aqui ficam alvos e endereços por modelo.
from .models import MODELO_55 as MODELO, MODELO_65, MODELOS  # noqa: E402  (MODELO: o de sempre; dado sem o campo é dele)

MARCA = "TCL"

def _env(nome: str, padrao: str) -> str:
    """Variável de ambiente, tratando vazia como ausente (no GitHub Actions, vars não definidas chegam como '')."""
    v = os.environ.get(nome, "")
    return v.strip() if v and v.strip() else padrao


# Alvos de preço. Podem ser sobrescritos por variável de ambiente.
ALVO_PIX = float(_env("ALVO_PIX", "2900"))          # 55C6K: à vista / Pix
ALVO_PARCELADO = float(_env("ALVO_PARCELADO", "3000"))  # 55C6K: total parcelado sem juros
ALVO_PIX_65 = float(_env("ALVO_PIX_65", "3300"))          # 65C6K: à vista / Pix (decisão do usuário em 26/09)
ALVO_PARCELADO_65 = float(_env("ALVO_PARCELADO_65", "3500"))  # 65C6K: total parcelado sem juros
QUEDA_MINIMA_PCT = float(_env("QUEDA_MINIMA_PCT", "2"))  # queda vs. última coleta que gera alerta


def alvo_pix(modelo: str | None = None) -> float:
    """Alvo do Pix/à vista do modelo (sem modelo: o da 55C6K). Lê o valor do módulo na hora (os testes trocam)."""
    return ALVO_PIX_65 if modelo == MODELO_65 else ALVO_PIX


def alvo_parcelado(modelo: str | None = None) -> float:
    """Alvo do total parcelado sem juros do modelo (sem modelo: o da 55C6K)."""
    return ALVO_PARCELADO_65 if modelo == MODELO_65 else ALVO_PARCELADO


def alvos() -> dict[str, dict[str, float]]:
    """{modelo: {'pix': alvo, 'parcelado': alvo}} (vai para o latest_<modo>.json e o painel)."""
    return {m: {"pix": alvo_pix(m), "parcelado": alvo_parcelado(m)} for m in MODELOS}


# Termos de busca usados nos sites de promoção (BUSCAS é o da 55C6K, como antes)
BUSCAS = ["55c6k", "tcl 55c6k", "tcl c6k 55"]
BUSCAS_65 = ["65c6k", "tcl 65c6k", "tcl c6k 65"]
BUSCAS_POR_MODELO = {MODELO: BUSCAS, MODELO_65: BUSCAS_65}

# Código de barras (EAN) de cada modelo: identifica o tamanho mesmo quando o título do anúncio diz outra coisa
EAN_POR_MODELO = {"7899968301747": MODELO, "7899968301754": MODELO_65}

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
MAGALU_TERMOS = ["tcl 55c6k", "tcl 65c6k", "55c6k", "tcl c6k 55", "smart tv tcl 55 mini led"]
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

# --- Sites de promoção ---
PROMOBIT_CUPONS_LOJAS = [
    "magazine-luiza", "amazon", "mercado-livre", "kabum", "casas-bahia",
    "fastshop", "aliexpress", "shopee",
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
    "webcontinental": "Webcontinental",
    "ponto": "Ponto", "pontofrio": "Ponto", "ponto frio": "Ponto", "extra": "Extra",
    "carrefour": "Carrefour", "americanas": "Americanas",
}
