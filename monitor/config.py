"""Configuração central. Tudo que é específico da TV e das fontes fica aqui."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "docs" / "data"

# Produto monitorado (só este modelo, só 55")
MODELO = "55C6K"
MARCA = "TCL"

def _env(nome: str, padrao: str) -> str:
    """Variável de ambiente, tratando vazia como ausente (no GitHub Actions, vars não definidas chegam como '')."""
    v = os.environ.get(nome, "")
    return v.strip() if v and v.strip() else padrao


# Alvos de preço. Podem ser sobrescritos por variável de ambiente.
ALVO_PIX = float(_env("ALVO_PIX", "2900"))          # à vista / Pix
ALVO_PARCELADO = float(_env("ALVO_PARCELADO", "3000"))  # total parcelado sem juros
QUEDA_MINIMA_PCT = float(_env("QUEDA_MINIMA_PCT", "2"))  # queda vs. última coleta que gera alerta

# Termos de busca usados nos sites de promoção
BUSCAS = ["55c6k", "tcl 55c6k", "tcl c6k 55"]

# --- Lojas com acesso direto (rodam na nuvem) ---
URL_ZOOM = "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k"
URL_KABUM_API = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products/911482"
URL_KABUM_PRODUTO = "https://www.kabum.com.br/produto/911482"
URL_MAGALU_BUSCA = "https://www.magazinevoce.com.br/magazinecanaltechbr/busca/tcl+55c6k/"
URL_MAGALU_PRODUTO = (
    "https://www.magazinevoce.com.br/magazinecanaltechbr/"
    "smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-assistente-4-hdmi-2-usb/p/240162700/et/elit/"
)
# Descoberta de TODOS os anúncios do Magalu (19/09): várias buscas + anúncios vistos nos últimos 14 dias.
MAGALU_TERMOS = ["tcl 55c6k", "55c6k", "tcl c6k 55", "smart tv tcl 55 mini led"]
MAGALU_MAX_BUSCAS = 5            # páginas de busca por rodada (uma por termo + 1 página seguinte)
MAGALU_MAX_REQUISICOES = 12      # teto de requisições ao magazinevoce por rodada (buscas + anúncios)
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

# --- Lojas que exigem IP residencial / navegador real (rodam no PC) ---
URL_AMAZON_PRODUTO = "https://www.amazon.com.br/dp/B0F7JZMVKF"
URL_AMAZON_CARRINHO = "https://www.amazon.com.br/gp/cart/view.html"
URL_AMAZON_LOGIN = "https://www.amazon.com.br/ap/signin?openid.return_to=https%3A%2F%2Fwww.amazon.com.br%2Fgp%2Fcart%2Fview.html&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
URL_AMAZON_BUSCA = "https://www.amazon.com.br/s?k=tcl+55c6k"
ASIN_AMAZON = "B0F7JZMVKF"
# lista de todos os vendedores do anúncio (painel "Outras opções de compra"); responde a HTTP simples
URL_AMAZON_OFERTAS = "https://www.amazon.com.br/gp/product/ajax/aodAjaxMain/?asin={asin}&pc=dp&experienceId=aodAjaxMain"
AMAZON_MAX_CARGAS = 3            # páginas/requisições à Amazon por rodada
URL_CASASBAHIA_PRODUTO = (
    "https://www.casasbahia.com.br/smart-tv-55-tcl-55c6k-4k-qd-mini-led-144hz-sistema-operacional-google-tv/p/55069456"
)
# "/busca/<termo>" diz "não encontramos nada"; a busca do site é "/<termo-com-hífen>/b"
URL_CASASBAHIA_BUSCA = "https://www.casasbahia.com.br/tcl-55c6k/b"
CASASBAHIA_MAX_CARGAS = 3
URL_ML_CATALOGO = "https://www.mercadolivre.com.br/p/MLB48808732"
URL_ML_BUSCA = "https://lista.mercadolivre.com.br/tcl-55c6k"
ML_CATALOGO_ID = "MLB48808732"
ML_MAX_CARGAS = 3                # páginas do ML por rodada (catálogo, busca, conferência de vendedor)
# Anúncio fora do catálogo MAIS BARATO que o catálogo só entra depois de conferir o vendedor na página
# do anúncio: com menos vendas que isto é descartado (19/09: "FEGU2024...", 0 vendas, R$ 2.769).
ML_VENDAS_MINIMAS = 50
PAUSA_ENTRE_PAGINAS_MS = 2500    # pausa entre páginas na mesma janela do Chrome
URL_ALIEXPRESS_BUSCA = "https://pt.aliexpress.com/w/wholesale-tcl-55c6k.html?SearchText=tcl+55c6k&g=y"
URL_SHOPEE_BUSCA = "https://shopee.com.br/search?keyword=tcl%2055c6k"

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
