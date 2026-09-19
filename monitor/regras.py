"""Decide o que vira alerta. Cada alerta é uma mensagem HTML pronta para o Telegram."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from typing import Optional

from . import config
from .estado import Estado, conta_como_preco, e_agregador, lojas_diretas, marca_cupom
from .models import Cupom, Oferta
from .util import dias_desde, fmt_preco, loja_canonica, parse_preco, sem_acentos

# Teto (F3): "até R$ X", "máximo (de) R$ X", "no máximo R$ X", "compra máxima de R$ X". Como na main, o teto limita a
# COMPRA ou o ITEM ("compras até R$ 600", "itens de até R$ 99", "VÁLIDO PARA PRODUTOS ATÉ R$ 500", "pedidos de no máximo
# R$ 300", "carrinhos de até R$ 300", "compras de R$ 200 até R$ 499", "TVs até R$ 2.000"): se ele é menor que o preço
# da TV, o cupom não serve para ela. A exceção é o teto do DESCONTO, quando o valor é o próprio desconto: logo depois
# de uma palavra de desconto ("Economize até R$ 300", "desconto (máximo) de (até) R$ 500", "ganhe até", "cupom de até",
# "cashback de até", "limitado até", "frete grátis até"), de um desconto em % ("25% OFF até R$ 800", "20% OFF, máximo
# R$ 60", "10% (máximo R$ 50)") ou seguido de "OFF"/"de desconto"/"de volta" ("até R$ 300 OFF"). "R$ 20 OFF até R$ 99"
# (desconto fixo) continua sendo teto da compra.
_RE_TETO = re.compile(r"\b(?:ate|(?:no\s+)?maxim[oa](?:\s+d[eoa])?)\s*(?:de\s+)?r\$\s?(\d[\d.]*(?:,\d{1,2})?)")
_RE_TETO_DO_DESCONTO_ANTES = re.compile(
    r"(?:\beconomi\w*|\bganh\w*|\bdescontos?|\bcupo(?:m|ns)|\bvouchers?|\bcashback|\babatimentos?|\breembolsos?|"
    r"\bbonus|\bcreditos?|\bfretes?|\bentregas?|\bgratis|\blimit\w*|\btetos?|\bvolta|%(?:\s*off\b)?)"
    r"(?:\s*[,(:\-–]\s*|\s+(?:de|do|da|no|na|o|a|um|uma|valor|total|maxim[oa]|limite|e)\b)*\s*$")
_RE_TETO_DO_DESCONTO_DEPOIS = re.compile(
    r"^\s*(?:off\b|(?:de|em)\s+(?:descontos?|volta|cashback|economia|abatimento|creditos?|bonus)\b)")
_RE_FIM_DE_FRASE_ANTES = re.compile(r"[;|!?]|\.(?!\d)")
_RE_ACIMA = re.compile(r"(?:acima de|a partir de|m[íi]nimo(?: de)?|compras?\s+(?:de|a partir de))\s*R\$\s?([\d.]+)", re.I)
# compra mínima (no texto já normalizado): o _RE_ACIMA da main e "compra mínima (de) R$ X", que ele não lia
_RE_MINIMO_DA_COMPRA = re.compile(
    r"(?:acima de|a partir de|minim[oa](?: de)?|compras?\s+(?:de|a partir de))\s*r\$\s?([\d.]+)")
# "R$ 350 OFF em R$ 3500": o valor depois de "OFF em" é a compra mínima
_RE_MINIMO_EM = re.compile(r"\b(?:off|desconto)\s+em\s+r\$\s?([\d.]+)", re.I)
_CATEGORIAS_FORA = [
    "moda", "roupa", "beleza", "perfum", "maquiagem", "supermercado", "mercado ", "bebida", "cerveja", "vinho", "livro",
    "brinquedo", "pet ", "petshop", "games", "celular", "smartphone", "iphone", "notebook", "moveis", "cama",
    "mesa e banho", "esporte", "treino", "bike", "calcado", "tenis", "infantil", "papelaria", "farmacia", "saude",
    "cuidados pessoais", "automotivo", "ferramenta", "jardim", "primeira compra", "novos clientes", "entrega", "frete",
    "app ", "aplicativo", "selecionados", "marca ", "cozinha", "eletroportateis", "geladeira", "fogao", "lavadora",
    "ar-condicionado", "ar condicionado", "informatica", "audio", "fone", "relogio", "oculos", "bolsa", "joia",
]
_CATEGORIAS_DENTRO = [
    "tv", "televis", "eletronic", "tecnolog", "site todo", "loja toda", "todo o site", "todo site", "qualquer", "suas compras",
    "em compras", "no site", "todos os produtos", "primeira compra no site",
]
# Marcas e produtos que não são a TV: se aparecem no título/regra (palavra inteira) ou dentro do código, o cupom não serve
_MARCAS_OUTRAS = [
    "dyson", "jbl", "asus", "aoc", "ps5", "playstation", "xbox", "nintendo", "motorola", "moto", "oppo", "xiaomi",
    "galaxy", "iphone", "apple", "tablet", "lenovo", "edifier", "britania", "dinoxx", "haiflex", "beauty", "decor",
    "decoracao", "conta nova", "contas novas", "novos usuarios", "novo usuario", "whatsapp", "zap", "cashback",
    "edge", "signature", "gta", "gamer", "shark", "robo", "nivea", "livro", "livros", "leia", "audio", "selecao",
    "pet", "cama", "notebook", "monitor", "ssd", "placa de video", "processador", "mouse", "teclado", "headset",
    "cadeira", "fone", "caixa de som", "smartwatch", "relogio", "perfume", "cerveja", "vinho", "suplemento", "whey",
    "fralda", "bebe", "brinquedo", "pneu", "prime day", "pra casa", "para casa",
    # cosméticos que aparecem em cupons do Mercado Livre com título genérico (ISDIN15, MANTECORP14...)
    "isdin", "mantecorp", "avene", "garnier", "loreal", "maybelline",
]
_CODIGO_OUTRAS = [m for m in _MARCAS_OUTRAS if " " not in m and len(m) >= 3]
_RE_EM_X = re.compile(r"\boff\s+em\s+(.{3,60})$")
_RE_EM_TUDO = re.compile(r"\bem tudo\b(?!\s+(?:pra|para)\b)")
# ---- cupom: o texto diz que serve para a TV? (rodada 4: regras gerais, não um padrão por exemplo) ----
# (a) Exclusão não é o escopo do cupom. "exceto (na categoria) X", "não (é) válido para X", "não vale para X", "não se
#     aplica a X", "exclui X", "com exceção de X", ", menos X", ", fora X" saem do texto (até o fim da frase, ou até
#     a vírgula que abre outra condição: "Exceto Celulares, em compras acima de R$ 5.000") antes de qualquer análise de
#     categoria, marca, tamanho ou cliente novo: "Válido em todo o site, exceto na categoria Supermercado" é o site todo.
#     Só quando a exclusão tira a própria TV ("exceto TVs", "exceto eletrônicos", "exceto TCL") o cupom não serve; uma
#     exclusão de TVs de outra marca ou de outro tamanho ("exceto TVs Samsung", "exceto TVs de 32 polegadas") não tira a
#     55C6K.
# (b) Contam TODOS os alvos do texto, não só o último. Alvo é o que vem depois de "em", "na/no", "para" ou "categoria".
#     Ele só diz onde o cupom vale quando está ligado ao desconto ou à validade ("20% OFF em Casa", "R$ 79 em Casa",
#     "Válido em todo o site", "válido para X", "na categoria X", "Em Itens Selecionados" no começo da regra); "receba
#     em casa", "pagamento em Pix", "MERCADO EM ALTA" e "para você/para usar" não dizem. Um alvo de TV (TV, TVs,
#     Smart TV, televisor, eletrônicos, eletro, tecnologia, áudio e vídeo) ou do site todo, em qualquer lugar, basta
#     para a categoria servir.
#     Alvos neutros (Pix, boleto, cartão, app, site, loja, compras, pedidos, carrinho, promoção, ofertas, frete...) não
#     são categoria. Categoria que não é TV só recusa quando é declarada e nenhum alvo é de TV/site todo:
#       - nome de categoria conhecido (_NOMES_DE_CATEGORIA: casa, moda, periféricos, acessórios, beleza...);
#       - qualquer nome em "na categoria X" (declaração explícita) e em "OFF em X" do título (a mesma posição que o
#         código anterior já tratava como categoria), sem as palavras neutras e os qualificadores de venda/entrega/
#         pagamento (lista fechada: "vendidos", "realizadas", "disponíveis", "parceladas"). Particípio que diz o que é
#         o produto ("Renovados", "Usados", "Importados", "Congelados") é categoria; vendedor que não é a própria loja
#         ("vendidos pela loja parceira X", "por terceiros") também;
#       - seleção com nome ("em Selecionados Cacife", "produtos participantes da promoção Imprime Junto").
#     Um alvo com nome desconhecido fora dessas posições ("Válido em uma única compra") não recusa.
# (c) Lista ou faixa de tamanhos ("50, 55 e 65 polegadas", "50", 55" e 65"", "50 pol. a 65 pol.", "55 a 85", "a partir
#     de 50", "50 ou mais") serve quando o 55 está nela. Uma TV de outro tamanho (ou modelo TCL com outro tamanho no
#     nome, "65C6K") só recusa quando o cupom não fala também de TVs em geral. Tamanho precisa de polegada, de
#     especificação/modelo logo depois ou de lista explícita: data, hora, limite e quantidade não são tamanho. Kit só
#     recusa quando é o produto do anúncio (no título, sem TV nem "compras").
# (d) Frete e app não são categorias. Cupom só de frete (sem R$ ou % de desconto no preço) não é desconto na TV.
# (e) Cupom de loja oficial, de marca ou de outra loja ("na Loja Oficial LG", "na loja Samsung", "na Netshoes") só
#     serve quando a marca é a TCL.
# Cliente novo continua recusando, mas só com as palavras explícitas da restrição ("clientes novos", "novos
# cadastros", "quem nunca comprou", "1ª compra"), menos quando o texto diz que vale também/inclusive para quem já é
# cliente ou que não é exclusivo dele.
# Os valores também são lidos sem as exclusões. Teto: "até/máximo R$ X" limita a compra ou o item (como na main),
# salvo quando o valor é o próprio desconto ("Economize até R$ 300", "25% OFF até R$ 800"); se o teto é menor que o
# preço da TV, o cupom não serve. Mínimo: "acima de", "a partir de", "compra/pedido mínimo(a)", "OFF em R$ X"; num
# cupom progressivo (em faixas) vale o menor mínimo.

# texto UTF-8 que uma coleta antiga leu como cp1252: "vÃ¡lido" -> "válido", "1Âª Compra" -> "1ª Compra"
_RE_MOJIBAKE = re.compile("[ÂÃ][-¿ŒœŠšŸŽžƒˆ˜"
                          "–—‘-„†-•…‰‹›€™]")


def _conserta_mojibake(s: str) -> str:
    def um(m: re.Match) -> str:
        for cod in ("cp1252", "latin-1"):
            try:
                return m.group(0).encode(cod).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return m.group(0)

    return _RE_MOJIBAKE.sub(um, s or "")


def _norm(s: str) -> str:
    """Minúsculo, sem acento, sem mojibake; quebra de linha vira fim de frase ("|")."""
    t = sem_acentos(_conserta_mojibake(s)).lower()
    # "Áudio e Vídeo" é a categoria onde ficam as TVs (e "audio" sozinho é marca/produto de outra coisa)
    t = re.sub(r"\baudio\s*(?:e|&|,|/)\s*video\b", "tv e video", t)
    # Mercado Pago é meio de pagamento (como Pix), não loja nem a categoria "mercado"
    t = re.sub(r"\bmercado\s*pago\b", "pagamento", t)
    # "novos e usados" é qualquer produto: a condição (usado, seminovo...) só restringe quando vem sozinha
    t = re.sub(r"\bnov[oa]s?\s*(?:e|ou|/|,)\s*(?:usad|seminov|recondicionad|renovad|reembalad)\w*"
               r"|\b(?:usad|seminov|recondicionad|renovad|reembalad)\w*\s*(?:e|ou|/|,)\s*nov[oa]s?\b", " ", t)
    t = re.sub(r"\s*\n\s*", " | ", t)
    return re.sub(r"[ \t\r\f\v]+", " ", t).strip()


# nome da loja no texto não é categoria ("Mercado Livre" não é o "mercado" das compras de supermercado)
_RE_LOJA_NO_TEXTO = re.compile(
    r"\b(?:(?:em|na|no|da|do|pela|pelo)\s+)?(?:mercado\s*livre|magazine\s+luiza|magalu|amazon|aliexpress|kabum|"
    r"shopee|fast\s*shop|casas\s+bahia)\b!?")
# (a) exclusões, até o fim da frase ("." de número não fecha a frase: "R$ 1.999") ou até a vírgula que abre outra
#     condição: "Exceto Celulares, em compras acima de R$ 5.000" e "excluído o valor do frete, com desconto máximo de
#     R$500" (a compra mínima e o teto continuam valendo); "exceto Supermercado, Farmácia e Pet" é uma lista só. Um
#     número depois da vírgula só abre condição quando é quantidade/percentual ("Exceto Celulares, 1 uso por CPF"); a
#     lista de tamanhos continua na exclusão ("Exceto TVs 32, 43 e 50 polegadas")
_NOVA_CONDICAO = (r",\s*(?:em|na|no|nas|nos|para|pra|com|acima|a\s+partir|partir|valid|vale|limit|pedido|compra|minim|"
                  r"maxim|ate|cupom|desconto|uso|use|aplique|r\$|"
                  r"\d+\s*(?:%|x\b|vez|vezes\b|usos?\b|unidades?\b|pecas?\b|itens?\b|por\b|dias?\b|meses\b|horas?\b))")
_FIM_DA_FRASE = r"(?:(?!" + _NOVA_CONDICAO + r")[^.;!?|()]|\.(?=\d))*"
_RE_EXCLUSAO = re.compile(
    r"\b(?:exceto|excepto|excluindo|exclui|excluid[oa]s?|sem\s+contar|nao\s+(?:e\s+|sao\s+)?valid[oa]s?|nao\s+vale|"
    r"nao\s+se\s+aplica|nao\s+contempla|nao\s+inclui|(?:com|a)\s+excecao\s+d[eoa]s?)\b" + _FIM_DA_FRASE
    + r"|(?:,|\b(?:tudo|site|loja|produtos|categorias))\s*\b(?:menos|fora)\b" + _FIM_DA_FRASE)
# o que conta como TV num alvo (b) e numa exclusão (a)
_RE_TV = re.compile(r"\btvs?\b|televis|smart\s*tvs?\b|eletronic|\beletro\b|tecnolog")
_RE_TV_EXCLUIDA = re.compile(_RE_TV.pattern + r"|\btcl\b|c6k")
_RE_OUTRA_MARCA_DE_TV = re.compile(r"\b(?:samsung|lg|philco|sony|aoc|hisense|philips|panasonic|multilaser|britania|"
                                   r"toshiba|jvc|roku|xiaomi)\b")
# nome de sistema/aparelho que tem "TV" mas não é uma TV ("Smart TV TCL 50 P7L com Google TV")
_RE_NAO_E_TV = re.compile(r"\b(?:google|android|fire|apple|roku)\s+tv\b|\btv\s+box\b|\btv\s+stick\b")
# acessório de TV não é TV: "Acessórios para TV", "Suporte de TV", "Controle remoto para Smart TV"
_RE_ACESSORIO_DE_TV = re.compile(
    r"\b(?:acessorios?|suportes?|racks?|paineis|painel|controles?|cabos?|antenas?|conversor(?:es)?|capas?|moveis|"
    r"estantes?|protetor(?:es)?|peliculas?|home\s+theaters?|soundbars?|caixas?\s+de\s+som|adaptador(?:es)?)"
    r"(?:\s+[a-z0-9]+){0,2}?\s+(?:para|pra|p/|de|da|do)\s+(?:a\s+|sua\s+|seu\s+)?(?:smart\s*)?tvs?\b")
_RE_SITE_TODO = re.compile(r"site todo|todo o site|todo site|loja toda|toda a loja|toda loja|todas as categorias|"
                           r"todos os produtos|\bem tudo\b(?!\s+(?:pra|para)\b)")
# (c) tamanhos: "Smart TV TCL 50 QLED" é outra TV; "Smart TV TCL 50, 55 e 65 polegadas", "55 a 85", "a partir de 50"
#     e "50 ou mais" incluem a 55". Uma lista de tamanhos é uma sequência de números de 2 dígitos, cada um com ou sem
#     a marca de polegada (50" / 50'' / 50 pol. / 50 polegadas), separados por vírgula, "e", "ou", "/", "-", "a", "até"
#     ou só espaço: "50", 55" e 65"", "50 55 e 65 polegadas", "50 pol. a 65 pol.". Número seguido de %, x, k, Hz,
#     R$... não é tamanho.
#     Rodada 5: o número depois de "Smart TV(s)"/"TV(s)" só é tamanho com a polegada, com uma especificação de TV logo
#     depois ("Smart TV 50 4K UHD", "Smart TV TCL 50 QLED", "Smart TV TCL 65 C7K"), com o modelo ("65C6K") ou numa
#     lista explícita de tamanhos ("Smart TVs 32 e 43", "de 50 a 65"). Data, hora, limite de uso e quantidade
#     ("Smart TVs até 30/09", "hoje até às 23:59", "válido até dia 25", "para os primeiros 50 clientes", "em até 10
#     vezes") não são tamanho. Título e regra são lidos separados (a data da regra não é o tamanho da TV do título).
_POLEGADA = r"(?:\s*(?:\"|''|'|”|″)|\s*pol(?:egadas?|\.|\b))"
# (data "30/09" e hora "23:59" não são tamanho: o número seguido de "/mês" ou ":minutos" fica de fora)
_NUM_TAMANHO = (r"(?<![\d.,])\d{2}(?:(?=pol)|(?![a-z\d]))(?![.,]\d)(?!\s*(?:%|x\b|k\b|hz\b|mil\b|reais\b|anos?\b|"
                r"meses\b|dias\b|"
                r"horas?\b|gb\b|tb\b|w\b|watts?\b|cm\b|mm\b|kg\b|litros?\b|unidades?\b|pecas?\b))"
                r"(?!\s*/\s*(?:0?[1-9]|1[0-2])(?!\d))(?!\s*:\s*\d)")
_LISTA_TAMANHOS = (_NUM_TAMANHO + _POLEGADA + r"?(?:(?:\s*(?:,|/|-|–|\be\b|\bou\b|\ba\b|\bate\b)\s*|\s+)"
                   + _NUM_TAMANHO + _POLEGADA + r"?)*")
_POS_TAMANHOS = (r"(?P<pos>\s*(?:\+|ou\s+mais|ou\s+maior\w*|ou\s+superior\w*|ou\s+acima|ou\s+menos|ou\s+menor\w*|"
                 r"ou\s+inferior\w*|para\s+cima)?)")
# a TV e até 3 palavras antes dos números ("Smart TV TCL", "Smart TVs de", "TVs a partir de", "TVs acima de")
_RE_SMART_TV_TAMANHOS = re.compile(
    r"\b(?P<smart>smart\s*)?(?:tvs?|televisor(?:es)?|televis(?:ao|oes))\s+"
    r"(?P<pre>(?:(?:[a-z][a-z0-9]*|\dk)\s+){0,3}?)(?P<nums>" + _LISTA_TAMANHOS + r")" + _POS_TAMANHOS)
# tamanho sem a palavra TV (numa exclusão: "exceto 32" e 43""): só com a polegada
_RE_TAMANHO_SOLTO = re.compile(r"(?P<pre>\b(?:[a-z]+\s+){0,2}?)(?P<nums>" + _LISTA_TAMANHOS + r")" + _POS_TAMANHOS)
_RE_TEM_POLEGADA = re.compile(_POLEGADA)
# série de modelo TCL sem o tamanho ("C6K", "C7K", "P7L", "QM7K", "C845", "S5400A"): 55C6K é a TV monitorada
_SERIE_TCL = r"(?:qm\d{1,2}[a-z]?|[cpqs]\d[a-z]{1,2}|[cpqs]\d{3,4}[a-z]?)"
# modelo TCL com o tamanho no nome ("Smart TV TCL 65C6K", "50P7K", "43S5K", "32S5400A")
_RE_MODELO_TCL = re.compile(r"(?:\b(?:smart\s*)?tvs?\s+(?:[a-z0-9]+\s+){0,3}?)?\b(\d{2})[cpqs]\d{1,4}[a-z]{0,2}\b")
_RE_SERIE_TCL = re.compile(r"\b(?P<tam>\d{2})?\s?(?P<serie>" + _SERIE_TCL + r")\b")
# especificação de TV logo depois do número: é o tamanho ("Smart TV 50 4K UHD", "Smart TV TCL 50 QLED 4K P7L",
# "Smart TV TCL 65 C7K")
_RE_ESPEC_DE_TV = re.compile(r"\s*(?:\d\s*k|uhd|ultra\s*hd|full\s*hd|fhd|hd|qled|oled|neo\s*qled|mini\s*led|led|qd|"
                             r"nanocell|crystal|hdr|" + _SERIE_TCL + r")\b")
# depois da lista: data ("19 e 20 de setembro", "30/09"), hora ("23h", "23:59")
_RE_DATA_HORA_DEPOIS = re.compile(r"\s*(?:de\s+)?(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\b|\s*[/:]\s*\d"
                                  r"|\s*h\b")
_RE_KIT = re.compile(r"\bkit\b")
# só para quem nunca comprou, e só com as palavras explícitas da restrição: "(1ª Compra / APP)", "nas 4 primeiras
# compras", "no primeiro pedido pelo app", "compras pela primeira vez", "novos clientes", "clientes novos", "novos
# usuários", "contas novas", "novos cadastros", "para quem (ainda) não/nunca comprou", "ainda não comprou", "quem
# ainda não é cliente". Frete e app não são categoria (d), então o cliente novo tem de ser reconhecido por si. A regra
# do Pelando é texto livre de quem postou: "quem ainda não usou, corre", "liberado pela primeira vez", "quem nunca
# usou cupom" não dizem que o cupom é só de cliente novo ("quem nunca usou o app" diz: é o usuário novo do app)
_PESSOA_NOVA = r"(?:clientes?|usuarios?|contas?|cadastros?|compradores?|consumidores?)"
_RE_SO_NOVOS = re.compile(
    r"\b(?:1a|1o|primeir[oa]s?)\s+(?:compras?|pedidos?)\b|\bcompr\w*\s+pela\s+primeira\s+vez\b"
    r"|\bnov[oa]s?\s+" + _PESSOA_NOVA + r"\b|\b" + _PESSOA_NOVA + r"\s+nov[oa]s?\b"
    r"|\bquem\s+(?:ainda\s+)?(?:nunca|nao)\s+(?:comprou|compraram|pediu|pediram|"
    r"(?:fez|fizeram)\s+(?:uma\s+|nenhuma\s+|a\s+primeira\s+)?(?:compras?|pedidos?)|e\s+cliente|tem\s+conta|"
    r"tinha\s+conta)\b"
    r"|\b(?:nunca|ainda\s+nao)\s+(?:comprou|compraram|fez\s+(?:uma\s+|nenhuma\s+)?compra)\b"
    r"|\bquem\s+(?:ainda\s+)?(?:nunca|nao)\s+(?:usou|baixou|instalou)\s+(?:o\s+)?(?:app|aplicativo)\b"
    r"|\bsem\s+compras?\s+anteriores\b")
# "novos clientes e antigos", "clientes novos ou antigos", "novos compradores e quem já comprou": vale para todo mundo
_RE_NOVOS_E_ANTIGOS = re.compile(r"^\s*(?:e|ou|&|/)\s+(?:\w+\s+)?(?:antig|atuais|recorrentes|ja\s+cadastrad|veteran|"
                                 r"quem\s+ja\b|(?:os\s+)?que\s+ja\b|ja\s+(?:e\s+|sao\s+)?clientes?\b)")
# seleção sem dizer qual: "itens selecionados", "em Selecionados", "lista selecionada", "produtos participantes",
# "produtos do link", "lista de itens". É a seleção de PRODUTOS: "Cupom selecionado para você" não é
_RE_SELECAO = re.compile(
    r"\bselecionad[oa]s\b|\bselecionas\b"
    r"|\b(?:produtos?|itens?|ofertas?|categorias?|modelos?|marcas?|lista|anuncios?)\s+(?:[a-z]+\s+){0,2}?selecionad[oa]s?\b"
    r"|\b(?:produtos|itens)\b[^.;|]{0,40}?\bparticipantes?\b|\b(?:produtos|itens) do link\b|\blista de itens\b"
    r"|\bmais\s+vendid[oa]s\b|\b(?:itens|produtos)\s+(?:marcad|sinalizad|identificad)[oa]s\b")
_PALAVRAS_DE_SELECAO = {"selecionado", "selecionados", "selecionada", "selecionadas", "selecionas", "participante",
                        "participantes", "link", "lista", "campanha"}
# (b) palavras de um alvo que não são categoria: condição de pagamento/compra, promoção, frete, app, loja, quantidade...
_NEUTRAS = set("""
o a os as de da do das dos e ou um uma uns umas sua suas seu seus meu meus minha minhas nosso nossa todo toda todos
todas cada qualquer quaisquer mais voce
compra compras pedido pedidos produto produtos item itens carrinho site loja lojas app aplicativo pix boleto cartao
cartoes credito debito pagamento pagamentos promocao promocoes promo promos oferta ofertas frete fretes gratis cupom
cupons voucher vouchers codigo desconto descontos off valor total usar uso utilizar finalizacao resgate area pagina
carteira elegivel elegiveis estoque dobro destaque especial especiais geral gerais participar conta minima minimo alta
diversos diversas varios varias milhares centenas muitos muitas outros outras demais principais oficial oficiais
""".split())
# nomes de categoria de loja (que não é TV): recusam o cupom quando são o alvo declarado do desconto
_NOMES_DE_CATEGORIA = re.compile(
    r"\b(?:moda|roupas?|vestuario|lingerie|praia|calcados?|sapatos?|tenis|bolsas?|malas?|mochilas?|acessorios?|"
    r"bijuterias?|joias?|relogios?|oculos|beleza|perfum\w*|maquiagem|cosmeticos?|dermocosmeticos?|cuidados\s+pessoais|"
    r"higiene|cabelos?|supermercado|mercado|mercearia|alimentos?|bebidas?|cervejas?|vinhos?|chocolates?|livros?|"
    r"livraria|papelaria|escritorio|brinquedos?|infantil|bebes?|fraldas?|pets?|petshop|racao|games|consoles?|"
    r"celulares?|smartphones?|iphones?|tablets?|notebooks?|computadores?|informatica|perifericos|hardware|"
    r"impressoras?|moveis|colchoes?|cama|mesa\s+e\s+banho|banho|decor\w*|casa|cozinha|utilidades|eletroportateis|"
    r"eletrodomesticos|geladeiras?|refrigeradores?|fogao|fogoes|lavadoras?|micro-?ondas|ar[- ]condicionado|"
    r"climatizacao|ventiladores?|limpeza|jardim|jardinagem|ferramentas?|construcao|iluminacao|automotivo|pneus?|"
    r"esportes?|fitness|treino|suplementos?|bikes?|bicicletas?|camping|farmacia|drogaria|saude|entregas?|"
    r"instrumentos\s+musicais|musica|"
    # condição do produto: a 55C6K monitorada é nova
    r"usad[oa]s|seminov[oa]s?|recondicionad[oa]s?|renovad[oa]s|reembalad[oa]s?|open\s*box|outlet|vitrine|"
    r"mostruario)\b")
# qualificador de VENDA/ENTREGA/PAGAMENTO num alvo aberto não é categoria: "compras realizadas (no app)", "itens
# vendidos e entregues (pela Amazon)", "produtos disponíveis", "pedidos feitos até 30/09". É uma lista fechada: um
# particípio que diz O QUE é o produto ("Renovados", "Recondicionados", "Usados", "Importados", "Congelados",
# "Personalizados") é categoria, como a main já lia
_QUALIFICADORES = set("""
vendido vendidos vendida vendidas entregue entregues realizado realizados realizada realizadas feito feitos feita feitas
efetuado efetuados efetuada efetuadas pago pagos paga pagas finalizado finalizados finalizada finalizadas disponivel
disponiveis elegivel elegiveis anunciado anunciados anunciada anunciadas comprado comprados comprada compradas enviado
enviados enviada enviadas faturado faturados faturada faturadas oferecido oferecidos oferecida oferecidas parcelado
parcelados parcelada parceladas aplicavel aplicaveis valido validos valida validas
""".split())
# palavras que abrem e fecham um alvo ("em TVs em promoção", "em compras acima de R$ 3.000", "em Casa com cupom").
# "para" não fecha: "produtos para sua casa tech" e "Tudo Pra Casa" são o alvo inteiro
_RE_INTRODUTOR = re.compile(r"\b(?:em|na|no|nas|nos|para|pra|categorias?)\b")
_RE_FIM_DO_ALVO = re.compile(
    r"\b(?:em|na|no|nas|nos|com|acima|a\s+partir|partir|limitad[oa]s?|limite|ate|minim[oa]|maxim[oa]|sem|"
    r"usando|aplicando|ao|aos|pel[oa]s?|por|que|valid[oa]s?|vale|categorias?|ganhe|economize|off|desconto)\b|\+")
_RE_PARA_FORTE = re.compile(r"\b(?:valid[oa]s?|vale|somente|apenas|exclusiv[oa]s?|so)\s*$")
# "para" + pessoa ou verbo diz a quem/para quê, não onde o cupom vale
_RE_PARA_QUEM = re.compile(
    r"(?:voce|voces|vc|quem|todos|todas|mim|nos|ele|ela|eles|elas|usar|utilizar|comprar|aproveitar|economizar|"
    r"renovar|garantir|presentear|decorar|equipar|montar|curtir|assistir|ganhar|pagar|resgatar|ativar|aplicar|"
    r"finalizar|receber|levar|investir)\b")
# cliente novo "inclusive" / "também" não é cupom só de cliente novo
_RE_NOVOS_TAMBEM = re.compile(r"(?:\b(?:inclusive|tambem|mesmo|antig\w+|todos|todas)\b[^.;|]{0,20}"
                              r"|\bnao\s+(?:e\s+|eh\s+)?(?:necessario|preciso|precisa|exclusiv\w*|so|somente|apenas|"
                              r"restrit\w*)\b[^.;|]{0,25})$")
# (b) o alvo é do desconto/cupom: "20% OFF em", "R$ 79 em", "de desconto em", "Economize 10% em", "válido em/para"
_RE_GOVERNO = re.compile(
    r"(?:\boff|\bdescontos?|%|r\$\s?\d+|\d+\s*reais|\bcupo(?:m|ns)|\bvouchers?|\bvalid[oa]s?|\bvale|\bvalendo|"
    r"\baplicave(?:l|is)|\bsomente|\bapenas|\bexclusiv[oa]s?|\bso|\beconomiz\w*|\bganhe|\bcashback)"
    r"(?:\s+(?:de|ate|mais))*\s*$")
_RE_DELIMITADOR = re.compile(r"[.;:!?|()\[\]]|\s[-–]\s")
# (d) cupom de frete: "frete grátis", "R$ 20 OFF no frete", "entrega grátis"; e o que resta de desconto no preço
_RE_FRETE = re.compile(r"\bfretes?\b|\bentregas?\s+gratis\b")
_RE_DESCONTO_NO_FRETE = re.compile(
    r"(?:r\$\s?[\d.,]+|\d{1,3}(?:[.,]\d{1,2})?\s*%)\s*(?:off\s+|de\s+desconto\s+)?(?:n[oa]|d[oa]|em|sobre\s+o)\s+"
    r"(?:valor\s+d[oa]\s+)?fretes?|fretes?\s+gratis|entregas?\s+gratis|desconto\s+(?:n[oa]|d[oa])\s+fretes?|"
    r"cupom\s+de\s+fretes?")
_RE_CONDICAO_DE_VALOR = re.compile(
    r"(?:acima\s+de|a\s+partir\s+de|partir\s+de|minim[oa](?:\s+de)?|(?:compras?|pedidos?)\s+(?:de|acima\s+de)|"
    r"limite(?:\s+de)?|limitad[oa]\s+a|maxim[oa](?:\s+de)?|ate|em|de)\s*r\$\s?[\d.,]+\+?")
_RE_TEM_DESCONTO = re.compile(r"r\$\s?\d|\d\s*%")
# palavras de categoria soltas no texto (a regra do código anterior), sem frete/app (d), "entrega" (é frete), a
# seleção e o cliente novo (que têm regra própria)
_CATEGORIAS_FORA_TEXTO = [c for c in _CATEGORIAS_FORA if c not in (
    "frete", "app ", "aplicativo", "selecionados", "entrega", "primeira compra", "novos clientes")]
# (e) cupom de uma marca, da loja oficial dela ou de outra loja só vale lá: "na Loja Oficial LG", "em Loja Oficial
#     Philco", "na loja Samsung", "em Smart TVs Samsung", "produtos da Electrolux", "na Netshoes". Só serve quando a
#     marca é a TCL ("Loja Oficial TCL", "em TCL", "TVs TCL", "Smart TVs Samsung, LG e TCL")
_MARCAS_DE_OUTRA_LOJA = (
    r"samsung|lg|philco|sony|hisense|philips|panasonic|multilaser|britania|toshiba|jvc|aoc|xiaomi|electrolux|"
    r"brastemp|consul|mondial|arno|oster|midea|gree|elgin|dell|lenovo|acer|positivo|motorola|apple|netshoes|zattini|"
    r"kanui|centauro|dafiti|shoptime|submarino|americanas|pontofrio|ponto\s+frio")
_RE_LOJA_OFICIAL = re.compile(r"\bloja\s+oficial\s+(?:d[aoe]\s+)?(?P<nome>[a-z0-9][a-z0-9&+-]*)?")
_RE_LOJA_DE_MARCA = re.compile(
    r"(?:\blojas?|\b(?:n[ao]s?|em|para|pra)(?:\s+(?:as|os|a|o))?(?:\s+(?:smart\s*)?tvs?(?:\s+[a-z0-9]+){0,2}?)?"
    r"|\b(?:produtos?|itens?|linha|marca)\b[^.;:|!?]{0,30}?\bd[aoe]s?)\s+(?P<nome>" + _MARCAS_DE_OUTRA_LOJA + r")\b")
_NAO_E_NOME_DE_LOJA = _NEUTRAS | _QUALIFICADORES | _PALAVRAS_DE_SELECAO | {
    "com", "sem", "no", "na", "nos", "nas", "em", "para", "pra", "por", "pelo", "pela", "que", "ate", "acima", "partir",
    "tcl", "semp"}


def _num(s: str) -> Optional[float]:
    try:
        return float(s.replace(".", ""))
    except ValueError:
        return None


def _reais(s: str) -> Optional[float]:
    """'3.000' -> 3000.0; '99,90' -> 99.9."""
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _tetos_da_compra(t: str) -> list[tuple[float, bool]]:
    """Os tetos da compra/do item no texto (já normalizado e sem exclusões), cada um com 'é o fim de uma faixa' ("de
    R$ 800 até R$ 1.999"); os tetos do desconto ficam de fora."""
    out: list[tuple[float, bool]] = []
    for m in _RE_TETO.finditer(t):
        antes = t[max(0, m.start() - 80):m.start()]
        fins = list(_RE_FIM_DE_FRASE_ANTES.finditer(antes))
        if fins:
            antes = antes[fins[-1].end():]
        if _RE_TETO_DO_DESCONTO_ANTES.search(antes) or _RE_TETO_DO_DESCONTO_DEPOIS.match(t[m.end():]):
            continue
        v = _reais(m.group(1))
        if v:
            out.append((v, bool(re.search(r"\b(?:de|entre)\s+r\$\s?\d[\d.,]*\s*$", antes))))
    return out


# mínimo de outra coisa que não o cupom ("Frete grátis acima de R$ 99", "parcele sem juros acima de R$ 100"): sem
# desconto no preço antes dele na mesma frase
_RE_DESCONTO_NO_PRECO = re.compile(r"r\$\s?\d[\d.,]*\s*(?:off|de\s+desconto)\b|\d\s*%|\bdescontos?\s+de\b")
_RE_MINIMO_DE_OUTRA_COISA = re.compile(r"\bfretes?\b|\bentregas?\b|\bparcel\w*|\bjuros\b")


def _minimos_da_compra(t: str) -> list[float]:
    """Os mínimos da compra no texto (já normalizado e sem exclusões), do menor ao maior: "acima de", "a partir de",
    "compra/pedido mínimo(a)", "OFF em R$ X". O mínimo só do frete ou do parcelamento não conta."""
    out = []
    for rx in (_RE_MINIMO_DA_COMPRA, _RE_MINIMO_EM):
        for m in rx.finditer(t):
            v = _num(m.group(1))
            if not v:
                continue
            antes = re.split(r"[;|!?]|\.(?!\d)|,(?!\d)", t[max(0, m.start() - 60):m.start()])[-1]
            if _RE_MINIMO_DE_OUTRA_COISA.search(antes) and not _RE_DESCONTO_NO_PRECO.search(antes):
                continue
            out.append(v)
    return sorted(out)


def _motivo_marca(texto: str, codigo: str) -> str:
    """'marca/produto: x' quando o cupom é de outra marca ou produto; '' quando não."""
    for w in _MARCAS_OUTRAS:
        if re.search(r"\b" + re.escape(w) + r"\b", texto):
            return f"marca/produto: {w}"
    for w in _CODIGO_OUTRAS:
        if w in codigo:
            return f"código de outra marca: {w}"
    return ""


def _sem_exclusoes(t: str) -> tuple[str, list[str]]:
    """(a) Tira as exclusões do texto: (texto sem elas, exclusões)."""
    excl = [m.group(0) for m in _RE_EXCLUSAO.finditer(t)]
    return _RE_EXCLUSAO.sub(" ", t), excl


def _tamanhos_incluem_55(pre: str, nums: str, pos: str) -> bool:
    """(c) "50, 55 e 65", "55 a 85", "50" a 65"", "a partir de 50", "50 ou mais", "até 65" incluem a 55"."""
    limpo = _RE_TEM_POLEGADA.sub(" ", nums)
    ns = [int(n) for n in re.findall(r"\d{2}", limpo)]
    if 55 in ns:
        return True
    for faixa in re.finditer(r"(\d{2})\s*(?:\ba\b|\bate\b|-|–)\s*(\d{2})", limpo):
        if int(faixa.group(1)) <= 55 <= int(faixa.group(2)):
            return True
    qual = f"{pre} {pos}"
    if (re.search(r"\b(?:acima|partir|maior\w*|mais|superior\w*|cima)\b", qual) or "+" in pos) and min(ns) <= 55:
        return True
    return bool(re.search(r"\b(?:ate|abaixo|menor\w*|menos|inferior\w*)\b", qual)) and max(ns) >= 55


def _lista_explicita(pre: str, nums: str, depois: str) -> bool:
    """(c) Lista de tamanhos sem polegada: dois ou mais números de tela (20 a 99), sem cara de data ou hora ("Smart
    TVs 32 e 43", "de 50 a 65"; não "até 30/09", "nos dias 19 e 20 de setembro", "em 10 ou 12 vezes")."""
    ns = re.findall(r"\d{2}", _RE_TEM_POLEGADA.sub(" ", nums))
    if len(ns) < 2 or any(n.startswith("0") or int(n) < 20 for n in ns):
        return False
    return not re.search(r"\b(?:dias?|as|das|hora\w*|horario\w*)\s*$", pre) and not _RE_DATA_HORA_DEPOIS.match(depois)


def _tamanhos_de_tv(t: str) -> list[re.Match]:
    """(c) As listas de tamanho ligadas a uma TV ("Smart TV", "TV", "televisor"): com a polegada, com a especificação
    de TV logo depois ("50 4K", "65 QLED", "65 C7K") ou numa lista explícita. Número solto sem nada disso (data, hora,
    limite, quantidade) não é tamanho."""
    out = []
    for m in _RE_SMART_TV_TAMANHOS.finditer(t):
        nums, depois = m.group("nums"), t[m.end("nums"):]
        if _RE_TEM_POLEGADA.search(nums) or _RE_ESPEC_DE_TV.match(depois) \
                or _lista_explicita(m.group("pre"), nums, depois):
            out.append(m)
    return out


def _outro_tamanho(campos: tuple[str, ...]) -> Optional[str]:
    """(c) 'smart tv tcl 50' quando o cupom é só de uma TV de outro tamanho (ou de outro modelo TCL com o tamanho no
    nome: '65C6K', '50P7K'). None quando a lista/faixa inclui o 55 ou quando o texto também fala de TVs em geral
    ("R$ 300 OFF em TVs, inclusive a Smart TV TCL 50"). Cada campo (título, regra) é lido separado: a busca não
    atravessa a junção dos dois."""
    tamanhos: list[re.Match] = []
    modelos: list[re.Match] = []
    restos = []
    for t in campos:
        tams, mods = _tamanhos_de_tv(t), list(_RE_MODELO_TCL.finditer(t))
        tamanhos += tams
        modelos += mods
        fora: set[int] = set()
        for m in tams + mods:
            fora.update(range(m.start(), m.end()))
        restos.append(_RE_NAO_E_TV.sub(" ", "".join(" " if i in fora else ch for i, ch in enumerate(t))))
    if any(_tamanhos_incluem_55(m.group("pre"), m.group("nums"), m.group("pos")) for m in tamanhos) \
            or any(m.group(1) == "55" for m in modelos):
        return None
    outros = [m.group(0).strip() for m in tamanhos] + [m.group(0) for m in modelos]
    if not outros:
        return None
    return None if any(_RE_TV.search(r) for r in restos) else outros[0]


def _tv_excluida(exclusoes: list[str]) -> str:
    """(a) A exclusão tira a 55C6K ("exceto TVs", "não vale para eletrônicos", "exceto TCL", "exceto a linha C6K",
    "exceto TVs 55 polegadas")? Devolve o trecho. Exclusão com qualificador que não cobre a 55C6K (outra marca, outro
    tamanho, outro modelo, mesmo da TCL: "exceto a TCL 32S5400A", "exceto modelos TCL de 32 e 43 polegadas";
    vendedor; preço) não tira a TV."""
    for ex in exclusoes:
        m = _RE_TV_EXCLUIDA.search(_RE_NAO_E_TV.sub(" ", _RE_ACESSORIO_DE_TV.sub(" acessorios ", ex)))
        if not m:
            continue
        if not re.search(r"\btcl\b|c6k", ex) and _RE_OUTRA_MARCA_DE_TV.search(ex):
            continue  # "exceto TVs Samsung": a TCL continua valendo
        if re.search(r"r\$|\bvendid|\bterceiros\b|\bmarketplace\b|\bparceir|\binternaciona|\bimportad", ex):
            continue  # "exceto eletrônicos vendidos por terceiros", "exceto TVs acima de R$ 5.000"
        tams = [t for t in _RE_TAMANHO_SOLTO.finditer(ex) if _RE_TEM_POLEGADA.search(t.group("nums"))]
        tams += _tamanhos_de_tv(ex)
        # numa exclusão, o número de tela logo depois da TV já é o tamanho ("exceto TVs 32", "exceto TVs de 32 e 43")
        tams += [t for t in _RE_SMART_TV_TAMANHOS.finditer(ex)
                 if all(20 <= int(n) and not n.startswith("0") for n in re.findall(r"\d{2}", t.group("nums")))
                 and not _RE_DATA_HORA_DEPOIS.match(ex[t.end("nums"):])]
        modelos = [(s.group("tam"), s.group("serie")) for s in _RE_SERIE_TCL.finditer(ex)]
        if tams or modelos:
            cobre = any(_tamanhos_incluem_55(t.group("pre"), t.group("nums"), t.group("pos")) for t in tams) \
                or any(serie == "c6k" and tam in (None, "55") for tam, serie in modelos)
            if not cobre:
                continue  # "exceto TVs de 32 polegadas", "exceto a TCL 32S5400A", "exceto a TCL 65C6K"
        return m.group(0)
    return ""


def _loja_de_marca(campos: tuple[str, ...]) -> str:
    """(e) O nome da marca/loja quando o cupom é de uma loja oficial, de uma marca ou de outra loja que não é a TCL
    ('' quando não é, ou quando o texto fala da TCL)."""
    if any(re.search(r"\btcl\b", t) for t in campos):
        return ""
    for t in campos:
        for m in _RE_LOJA_OFICIAL.finditer(t):
            if m.group("nome") and m.group("nome") not in _NAO_E_NOME_DE_LOJA:
                return m.group("nome")
        m = _RE_LOJA_DE_MARCA.search(t)
        if m:
            return m.group("nome")
    # "Loja Oficial" sem nome (ou com o nome de um varejista, que _RE_LOJA_NO_TEXTO já apagou) NÃO recusa: no ML a
    # própria 55C6K é vendida pela "Loja oficial Magalu"; quem decide é o teste no carrinho.
    return ""


class _Alvo:
    """Um alvo do anúncio: o que vem depois de "em", "na/no", "para" ou "categoria"."""

    __slots__ = ("frase", "intro", "governado", "forte", "e_titulo", "off_em", "agente")

    def __init__(self, frase: str, intro: str, governado: bool, forte: bool, e_titulo: bool, off_em: bool,
                 agente: str = ""):
        self.frase, self.intro, self.governado = frase, intro, governado
        self.forte, self.e_titulo, self.off_em = forte, e_titulo, off_em
        # "... vendidos pela loja parceira X": quem vende, quando não é a própria loja (o nome dela já saiu do texto)
        self.agente = agente


def _alvos(texto: str, e_titulo: bool) -> list[_Alvo]:
    """(b) Todos os alvos de um campo (título ou regra), já sem exclusões e sem o nome da loja.

    governado: ligado ao desconto/validade ("20% OFF em", "R$ 79 em", "válido para", "na categoria") ou no começo
    do campo ("Em Itens Selecionados"). forte: "em X" governado, "categoria X" e "válido/somente para X" (os que
    declaram o escopo; "na/no X" e "para X" são fracos). off_em: "OFF em X" no título."""
    t = re.sub(r"(\d)[.,](\d)", r"\1\2", texto)  # "R$ 1.999", "10,00%": número não é fim de frase
    t = re.sub(r"\bcategorias?\s*:", "categoria ", t)
    out: list[_Alvo] = []
    pos = 0
    for clausula in _RE_DELIMITADOR.split(t):
        inicio_do_campo = not t[:pos].strip()
        pos += len(clausula) + 1
        for m in _RE_INTRODUTOR.finditer(clausula):
            intro = m.group(0)
            antes = clausula[:m.start()]
            resto = clausula[m.end():]
            fim = _RE_FIM_DO_ALVO.search(resto)
            frase = (resto[:fim.start()] if fim else resto).strip(" ,-'\"")
            agente = ""
            if fim and re.fullmatch(r"pel[oa]s?|por", fim.group(0)):
                depois = resto[fim.end():]
                fim2 = _RE_FIM_DO_ALVO.search(depois)
                agente = (depois[:fim2.start()] if fim2 else depois).strip(" ,-'\"")
            if intro.startswith("categoria"):
                governado = forte = True
            elif intro in ("para", "pra"):
                forte = bool(_RE_PARA_FORTE.search(antes))
                governado = forte or bool(_RE_GOVERNO.search(antes))
                if _RE_PARA_QUEM.match(frase):
                    governado = forte = False  # "para você renovar a casa", "para usar no app": não é o escopo
            else:
                governado = bool(_RE_GOVERNO.search(antes)) or (inicio_do_campo and not antes.strip())
                forte = governado and intro == "em"
            off_em = e_titulo and intro == "em" and bool(re.search(r"\boff\s*$", antes))
            out.append(_Alvo(frase, intro, governado, forte, e_titulo, off_em, agente))
    return out


def _palavras(f: str) -> list[str]:
    sem_valor = re.sub(r"r\$\s?[\d.,]+\+?|\b\d+\s*(?:x|%)(?!\w)", " ", f)
    return [w for w in re.findall(r"[a-z0-9_]+", sem_valor) if w not in _NEUTRAS]


def _abertas(palavras: list[str]) -> list[str]:
    """Palavras de um alvo sem lista de categorias: sem seleção, números soltos e qualificadores."""
    return [w for w in palavras if w not in _PALAVRAS_DE_SELECAO and not w.isdigit() and w not in _QUALIFICADORES]


def _classe_do_alvo(a: _Alvo) -> tuple[str, str]:
    """('tv'|'site'|'valor'|'neutro'|'selecao'|'categoria', rótulo)."""
    f = a.frase.strip()
    if not f:
        return "neutro", ""
    if re.match(r"(?:r\$|\d|ate\s+\d)", f):
        return "valor", f  # "em R$ 79", "em até 10x": valor mínimo/parcelas, não categoria
    if _RE_TV.search(_RE_NAO_E_TV.sub(" ", f)):
        return "tv", f
    palavras = _palavras(f)
    if "tcl" in palavras and set(palavras) <= {"tcl", "semp", "oficial"}:
        return "tv", f  # (e) "OFF em TCL", "na Loja Oficial TCL": a marca da TV
    if _RE_SITE_TODO.search(f) or f == "tudo":
        return "site", f
    if not a.governado:
        return "neutro", f  # "receba em casa", "pagamento em Pix", "MERCADO EM ALTA": não é o escopo do cupom
    nome = _NOMES_DE_CATEGORIA.search(f)
    explicita = a.intro.startswith("categoria")
    if _RE_SELECAO.search(f) or any(w in _PALAVRAS_DE_SELECAO for w in palavras):
        resto = _abertas(palavras)
        # "Selecionados Cacife", "itens selecionados limpeza e higiene", "produtos TCL participantes": seleção com
        # nome é uma parte da loja; "em Selecionados" / "itens selecionados" sem nome é seleção vaga
        if a.forte and resto and (nome or a.e_titulo or explicita):
            return "categoria", " ".join(resto)
        return "selecao", f
    if nome:
        return "categoria", " ".join(palavras) or nome.group(0)
    if explicita or a.off_em:
        # nome aberto é um nome só: a lista depois da vírgula ("qualquer compra, inclusive...") não entra. Quem vende
        # entra quando não é a própria loja: "OFF em produtos vendidos pela loja parceira Lojas Colombo" é só dela
        abertas = _abertas(_palavras(f.split(",")[0]))
        if a.agente and set(_palavras(f)) & _QUALIFICADORES:
            abertas += _abertas(_palavras(a.agente.split(",")[0]))
        if abertas:
            return "categoria", " ".join(abertas)
    return "neutro", f


class _Escopo:
    """O que o anúncio diz sobre onde o cupom vale, já sem exclusões e sem o nome da loja."""

    def __init__(self, titulo: str, regra: str):
        self.titulo_n = _norm(titulo)
        self.regra_n = _norm(regra)
        tit, ex_t = _sem_exclusoes(self.titulo_n)
        reg, ex_r = _sem_exclusoes(self.regra_n)
        self.exclusoes = ex_t + ex_r
        # sem as exclusões: para marca, tamanho, cliente novo, frete e as regras de valor ("exceto TVs acima de
        # R$ 5.000" não é compra mínima). Título e regra são frases separadas ("|"): nada atravessa a junção
        self.escopo = f"{tit} | {reg}"
        self.campos = (tit, reg)  # título e regra sem exclusões, separados (o teto e o tamanho são lidos em cada um)
        # sem a loja; "Acessórios para TV" / "Suporte de TV" viram "acessorios" (é acessório, não TV)
        self.tit_cat = _RE_ACESSORIO_DE_TV.sub(" acessorios ", _RE_LOJA_NO_TEXTO.sub(" ", tit))
        self.reg_cat = _RE_ACESSORIO_DE_TV.sub(" acessorios ", _RE_LOJA_NO_TEXTO.sub(" ", reg))
        self.cat = f"{self.tit_cat} {self.reg_cat}"  # para as categorias
        self.tv_excluida = _tv_excluida(self.exclusoes)
        self.loja_de_marca = _loja_de_marca((self.tit_cat, self.reg_cat))
        alvos = _alvos(self.tit_cat, True) + _alvos(self.reg_cat, False)
        self.classes = [(*_classe_do_alvo(a), a.forte) for a in alvos]
        self.tem_tv = any(k == "tv" for k, _r, _f in self.classes)
        self.site_todo = any(k == "site" for k, _r, _f in self.classes) or bool(_RE_SITE_TODO.search(self.cat))
        self.categorias = [r for k, r, _f in self.classes if k == "categoria"]
        self.categorias_explicitas = [r for k, r, forte in self.classes if k == "categoria" and forte]
        self.selecao = next((r for k, r, _f in self.classes if k == "selecao"), "")
        # anúncio cortado: "15% de Desconto em" e nada mais (a categoria sumiu)
        self.cortado = bool(re.search(r"\bem\s*[!.:\s]*$", self.tit_cat))

    def categoria_declarada(self, so_explicita: bool = False) -> str:
        """(b) A categoria que não é TV que o anúncio declara ser o escopo ('' se não declara nenhuma, ou se algum alvo
        é TV ou o site todo). so_explicita: só "em X", "na categoria X", "válido para X" (para restricao_do_codigo)."""
        if self.tem_tv or self.site_todo:
            return ""
        cats = self.categorias_explicitas if so_explicita else self.categorias
        return cats[0][:30] if cats else ""


@lru_cache(maxsize=8192)
def _escopo(titulo: str, regra: str) -> _Escopo:
    return _Escopo(titulo or "", regra or "")


def _so_frete(e: _Escopo) -> bool:
    """(d) Cupom que só tira o frete: fala de frete e não sobra desconto em R$ ou % no preço."""
    if not _RE_FRETE.search(e.escopo):
        return False
    resto = _RE_CONDICAO_DE_VALOR.sub(" ", _RE_DESCONTO_NO_FRETE.sub(" ", e.escopo))
    return not _RE_TEM_DESCONTO.search(resto)


def cupom_compativel(c: Cupom, preco_loja: Optional[float]) -> tuple[bool, str]:
    """Verifica se a regra do cupom cabe na TV. Devolve (ok, motivo)."""
    if c.especifico:
        return True, "cupom do produto"
    e = _escopo(c.titulo, c.regra)
    if e.tv_excluida:
        return False, f"exclui: {e.tv_excluida}"
    marca = _motivo_marca(e.escopo, sem_acentos(c.codigo).lower())
    if marca:
        return False, marca
    if e.loja_de_marca:
        return False, f"loja/marca: {e.loja_de_marca}"
    outro = _outro_tamanho(e.campos)
    # anúncio de um kit ("Kit Streamer HyperX ... com 10% de Desconto"): o kit é o produto do título, sem TV em lugar
    # nenhum, sem o site todo e sem "compras"/"pedidos" (aí "kit" é só uma palavra do texto)
    if not outro and _RE_KIT.search(e.tit_cat) and not _RE_TV_EXCLUIDA.search(_RE_NAO_E_TV.sub(" ", e.cat)) \
            and not e.site_todo and not re.search(r"\b(?:compras?|pedidos?|site|loja)\b", e.tit_cat):
        outro = "kit"
    if outro:
        return False, f"outro produto: {outro}"
    for m in _RE_SO_NOVOS.finditer(e.escopo):
        if not _RE_NOVOS_TAMBEM.search(e.escopo[:m.start()]) and not _RE_NOVOS_E_ANTIGOS.match(e.escopo[m.end():]):
            return False, f"só para novos clientes: {m.group(0)}"
    if _so_frete(e):
        return False, "só frete"
    # categoria declarada num alvo ("em Casa", "na categoria Casa") sem nenhum alvo de TV/site todo
    cat = e.categoria_declarada()
    if cat:
        return False, f"categoria: {cat}"
    if e.cortado and not (e.tem_tv or e.site_todo):
        return False, "restrito: anúncio cortado (sem a categoria)"
    # palavras de categoria soltas no texto (sem "em"): a regra do código anterior, que valem quando nada no texto diz
    # TV, site todo, "em compras", "suas compras", "qualquer"...
    dentro = e.tem_tv or e.site_todo or any(d in e.cat for d in _CATEGORIAS_DENTRO) or bool(_RE_EM_TUDO.search(e.cat))
    if not dentro:
        for w in _CATEGORIAS_FORA_TEXTO:
            if w in e.cat:
                return False, f"categoria: {w.strip()}"
    # "APLICÁVEL A ITENS SELECIONADOS", "válido para produtos do link": só se o texto também diz TV ou o site todo
    m = _RE_SELECAO.search(e.cat)
    selecao = m.group(0) if m else e.selecao
    if selecao and not (e.tem_tv or e.site_todo or _RE_TV.search(_RE_NAO_E_TV.sub(" ", e.cat))):
        return False, f"restrito: {selecao}"
    p = preco_loja or config.ALVO_PARCELADO
    # cupom progressivo (em faixas: "R$ 100 OFF acima de R$ 1.000, R$ 300 OFF acima de R$ 3.000 e R$ 500 OFF acima de
    # R$ 5.000") serve se o preço da TV alcança QUALQUER faixa: vale o menor mínimo, e o mínimo de uma faixa de cima
    # nunca recusa. Pelo mesmo motivo, o teto de uma faixa de baixo ("Compras de R$ 800 até R$ 1.999") não recusa
    # quando o texto tem uma faixa que começa nele ou acima e que o preço da TV alcança. Um teto solto ("Válido para
    # compras até R$ 1.000") não é faixa: continua recusando
    minimos = _minimos_da_compra(e.escopo)
    for campo in e.campos:
        for lim, faixa in _tetos_da_compra(campo):
            # "compras até R$ 300", "itens até R$ 99", "TVs até R$ 2.000": a TV custa mais que o teto
            if lim < p and not (faixa and any(lim <= v <= p for v in minimos)):
                return False, f"só até R$ {lim:.0f}"
    if minimos and minimos[0] > p:
        return False, f"só acima de R$ {minimos[0]:.0f}"
    return True, ""


# ---- cupom já alertado ----
# Lojas que vendem a TV mesmo quando a rodada não trouxe preço delas (cupom dessas lojas pode virar alerta)
_LOJAS_COM_TV = {"Amazon", "Magazine Luiza", "Mercado Livre", "KaBuM!", "Casas Bahia", "Fast Shop"}

# Regra de compatibilidade do código anterior a 18/09/2026. Serve SÓ para ler estados antigos, que não registravam
# quais cupons viraram alerta: o código da época alertava justamente os cupons novos que esta regra aceitava, e ela
# recusava muitos que servem para a TV ("Economize até R$ 300", "OFF em compras acima de R$ 3.000", o "mercado" do
# nome da loja). A lista de marcas é a atual: um cupom de marca que ela recusa não vira alerta de qualquer jeito.
_RE_ATE_ANTIGO = re.compile(r"(?:compras?\s+)?(?:at[ée]|m[áa]ximo(?: de)?)\s*R\$\s?([\d.]+)", re.I)
_DENTRO_ANTIGO = [d for d in _CATEGORIAS_DENTRO if d != "todo site"]


def _compativel_regra_antiga(c: Cupom, preco_loja: Optional[float]) -> bool:
    if c.especifico:
        return True
    texto = sem_acentos(f"{c.titulo} {c.regra}").lower()
    titulo = sem_acentos(c.titulo).lower().strip()
    if _motivo_marca(texto, sem_acentos(c.codigo).lower()):
        return False
    dentro = any(d in texto for d in _DENTRO_ANTIGO) or bool(_RE_EM_TUDO.search(texto))
    m = _RE_EM_X.search(titulo)
    if m and not any(d in m.group(1) for d in _DENTRO_ANTIGO):
        return False
    if not dentro and any(cat in texto for cat in _CATEGORIAS_FORA):
        return False
    p = preco_loja or config.ALVO_PARCELADO
    m = _RE_ATE_ANTIGO.search(texto)
    if m and (lim := _num(m.group(1))) and lim < p * 0.5:
        return False
    m = _RE_ACIMA.search(texto)
    if m and (lim := _num(m.group(1))) and lim > p:
        return False
    return True


def _cupom_do_registro(reg: dict) -> Cupom:
    return Cupom(fonte=reg.get("fonte") or "", loja=loja_canonica(reg.get("loja") or ""), codigo=reg.get("codigo") or "",
                 titulo=reg.get("titulo") or "", url="", id=str(reg.get("id") or ""), regra=reg.get("regra") or "",
                 especifico=bool(reg.get("especifico")))


def _alertado_no_codigo_antigo(reg: dict, preco_por_loja: dict[str, float]) -> bool:
    """Registro de cupom de um estado antigo: o código da época alertou (ou anunciou na partida) este cupom?"""
    c = _cupom_do_registro(reg)
    lc = c.loja
    if lc not in _LOJAS_COM_TV and lc not in preco_por_loja and not c.especifico:
        return False
    return _compativel_regra_antiga(c, preco_por_loja.get(lc))


def restricao_do_codigo(cupons: list[Cupom], registros=()) -> set[str]:
    """'loja|CÓDIGO' que algum anúncio (desta rodada, ou dos `registros` vistos nos últimos 30 dias, nos dois modos)
    declara ser de uma categoria que não é TV/eletrônicos/tecnologia nem o site todo ("20% OFF em Casa e Decor", "na
    categoria Casa"), de uma loja oficial/marca que não é a TCL ("na Loja Oficial LG"), ou que exclui a TV ("exceto
    TVs"; uma exclusão de outras TVs, "exceto TVs 32 e 43 polegadas", não barra).

    O mesmo código aparece em anúncios diferentes, e o Promobit alterna títulos genéricos ("20% OFF no Mercado
    Livre", "Economize 20% em seus pedidos") com o que diz a categoria: o cupom é o mesmo, então o anúncio genérico
    também não serve. Só conta a categoria declarada num alvo explícito ("em X", "na categoria X", "válido para X"),
    depois de tirar as exclusões (a): a seleção vaga ("em Selecionados", que o Pelando põe em quase todo cupom do ML,
    REG-1), alvos neutros (Pix, app, promoção, ofertas, frete), exclusões de outras categorias ("Não válido para a
    categoria Celulares") e as listas de palavras (que pegam slogans como "MERCADO EM ALTA") não barram o código.
    Se outro anúncio do mesmo código diz TV ("em TVs e Celulares"), a categoria de um anúncio não barra o código."""
    categoria: set[str] = set()
    exclui_tv: set[str] = set()
    diz_tv: set[str] = set()
    for c in list(cupons) + [_cupom_do_registro(r) for r in registros]:
        if c.especifico or not (c.codigo or "").strip():
            continue
        e = _escopo(c.titulo, c.regra)
        marca = marca_cupom(c.loja, c.codigo)
        if e.tv_excluida:
            exclui_tv.add(marca)
        elif e.loja_de_marca:
            categoria.add(marca)  # (e) o código é da loja oficial/marca ("na Loja Oficial LG"), como uma categoria
        elif e.tem_tv:
            diz_tv.add(marca)
        elif e.categoria_declarada(so_explicita=True):
            categoria.add(marca)
    return exclui_tv | (categoria - diz_tv)


_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_RE_DESC_PCT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_RE_DESC_REAIS = re.compile(
    r"r\$\s?" + _NUM + r"\s*(?:off|de desconto|de volta)\b"
    r"|(?:economiz\w*|ganhe|desconto de|oferece|concede)\s+(?:ate\s+)?r\$\s?" + _NUM)
_RE_DESC_TETO = re.compile(
    r"(?:limitad[oa]|limite)\s+(?:a\s+|de\s+)?r\$\s?" + _NUM + r"|maximo(?:\s+de)?\s+r\$\s?" + _NUM
    + r"|%\s*(?:off\s+)?ate\s+r\$\s?" + _NUM)


def _valor(s: str) -> float:
    s = s.replace(".", "").replace(",", ".") if "," in s or re.search(r"\.\d{3}\b", s) else s
    return float(s)


def _desconto(titulo: str, regra: str) -> tuple[Optional[tuple[str, float]], Optional[float]]:
    """(desconto principal, teto): (('%', 10.0), 500.0) para '10% OFF limitado a R$ 500'; ('R$', 250.0) para
    'R$ 250,00 OFF'. Procura no título e, se ele não diz o desconto, na regra. Nada legível -> (None, None)."""
    principal = None
    for txt in (sem_acentos(titulo or "").lower(), sem_acentos(regra or "").lower()):
        m = _RE_DESC_PCT.search(txt)
        if m:
            principal = ("%", _valor(m.group(1)))
            break
        m = _RE_DESC_REAIS.search(txt)
        if m:
            principal = ("R$", _valor(m.group(1) or m.group(2)))
            break
    m = _RE_DESC_TETO.search(sem_acentos(f"{titulo or ''} {regra or ''}").lower())
    teto = _valor(next(g for g in m.groups() if g)) if m else None
    return principal, teto


def _norm_titulo(s: str) -> str:
    return re.sub(r"[^a-z0-9%$]+", " ", sem_acentos(s or "").lower()).strip()


def _mesmo_cupom(c: Cupom, alerta: dict) -> bool:
    """O cupom repete o que já foi alertado? Compara o desconto (e o teto, quando os dois dizem); quando um dos dois
    não traz desconto legível, compara o título. Fontes escrevem o mesmo cupom de jeitos diferentes, o desconto não."""
    p1, t1 = _desconto(c.titulo, c.regra)
    p2, t2 = _desconto(alerta.get("titulo") or "", alerta.get("regra") or "")
    if p1 is None or p2 is None:
        return _norm_titulo(c.titulo) == _norm_titulo(alerta.get("titulo") or "")
    return p1 == p2 and (t1 is None or t2 is None or t1 == t2)


def _ja_alertado(estado: Estado, marca: str, c: Cupom) -> bool:
    """Só é repetição o cupom (loja + código) que já foi ALERTADO (ou anunciado na partida) com o mesmo
    desconto/título. Ter sido só visto, ou visto e recusado, não conta. Cupom da página do produto (especifico) só
    repete outro cupom da página do produto: "vale para esta TV" é novidade mesmo que o código já tenha sido
    alertado como cupom do site."""
    for alerta in estado.alertas_de_cupom(marca):
        if c.especifico and not alerta.get("especifico"):
            continue
        if _mesmo_cupom(c, alerta):
            return True
    return False


_CAB_CUPONS = "🎟️ <b>Nov"


def e_mensagem_de_cupons(m: str) -> bool:
    """A mensagem de cupons de gerar_alertas (se ela não for enviada, os cupons dela não contam como alertados)."""
    return m.startswith(_CAB_CUPONS)


def _esc(s: Optional[str]) -> str:
    return html.escape(s or "", quote=False)


def _linha_preco(o: Oferta) -> str:
    partes = []
    if o.preco:
        partes.append(f"<b>{fmt_preco(o.preco)}</b>")
    if o.preco_pix and (not o.preco or abs(o.preco_pix - o.preco) > 0.5):
        partes.append(f"Pix {fmt_preco(o.preco_pix)}")
    if o.parcelado:
        partes.append(_esc(o.parcelado))
    if o.cupom:
        partes.append(f"cupom <code>{_esc(o.cupom)}</code>")
    return " · ".join(partes) if partes else "preço não informado"


def _msg_oferta(etiquetas: list[str], o: Oferta, anterior: Optional[float] = None) -> str:
    cab = " ".join(etiquetas)
    quem = o.loja + (f" (vendido por {o.vendedor})" if o.vendedor and o.vendedor != o.loja else "")
    linhas = [f"{cab} — <b>{_esc(quem)}</b>", _esc(o.titulo[:140]), _linha_preco(o)]
    if anterior:
        linhas.append(f"antes: {fmt_preco(anterior)}")
    if o.tipo == "post":
        linhas.append(f"via {_esc(o.fonte)}" + (f" · {_esc(o.publicado[:16].replace('T', ' '))}" if o.publicado else ""))
    linhas.append(o.url)
    return "\n".join(linhas)


def gerar_alertas(estado: Estado, ofertas: list[Oferta], cupons: list[Cupom]) -> tuple[list[str], dict[str, float]]:
    """Devolve (mensagens, {chave_oferta: preco_alertado}).

    Os cupons alertados ficam registrados no estado (em memória; o run.py salva no fim da rodada): quando o mesmo
    código volta com outro id, só deixa de ser novidade se já foi alertado com o mesmo desconto.
    """
    msgs: list[str] = []
    alertados: dict[str, float] = {}
    # agregador (Zoom) de loja que tem fonte direta nesta rodada, no state ou no outro modo não é preço
    diretas = estado.lojas_diretas_conhecidas(ofertas)
    # o "menor já visto" é o dos dois modos (o painel mostra o menor entre cloud e pc)
    minimo_antes = estado.minimo_geral(diretas)
    preco_minimo_antes = float(minimo_antes["preco"]) if minimo_antes else None

    lojas = [o for o in ofertas if o.tipo == "loja"]
    posts = [o for o in ofertas if o.tipo == "post"]

    # ---- preços de loja ----
    for o in lojas:
        p = o.melhor_preco
        # inativa, sem preço, ou agregador (Zoom) de loja com fonte direta conhecida: não gera alerta de preço
        if not p or not conta_como_preco(o, diretas):
            continue
        prev = estado.oferta_anterior(o.chave)
        etiquetas: list[str] = []
        anterior = None
        novo_minimo = preco_minimo_antes is not None and p < preco_minimo_antes
        if novo_minimo:
            etiquetas.append("🏆 MENOR PREÇO já visto")
        if prev is None:
            if not estado.bootstrap and (p <= config.ALVO_PARCELADO or (preco_minimo_antes and p <= preco_minimo_antes * 1.03)):
                etiquetas.append("🆕 Nova oferta")
        else:
            anterior = prev.get("ultimo_preco")
            if anterior and p < float(anterior) * (1 - config.QUEDA_MINIMA_PCT / 100):
                etiquetas.append("🔻 Queda de preço")
                anterior = float(anterior)
            else:
                anterior = None
        abaixo_alvo = (o.preco_pix and o.preco_pix <= config.ALVO_PIX) or p <= config.ALVO_PIX or \
            (o.preco and o.preco <= config.ALVO_PARCELADO and o.parcelado)
        if abaixo_alvo and not estado.bootstrap:
            ja = prev.get("preco_alertado") if prev else None
            if ja is None or p < float(ja) - 0.5:
                etiquetas.append("🎯 Abaixo do alvo")
        if etiquetas:
            msgs.append(_msg_oferta(etiquetas, o, anterior))
            alertados[o.chave] = p
        if novo_minimo:
            preco_minimo_antes = p

    # ---- postagens em sites de promoção e canais ----
    for o in posts:
        if estado.oferta_anterior(o.chave) is not None:
            continue
        if not o.ativo:
            continue
        d = dias_desde(o.publicado)
        if d is not None and d > 3:
            continue
        if estado.bootstrap:
            continue
        et = ["📣 Promoção postada"]
        if o.melhor_preco and o.melhor_preco <= config.ALVO_PIX:
            et.append("🎯")
        msgs.append(_msg_oferta(et, o))

    # ---- cupons ----
    preco_por_loja, lojas_com_tv = _precos_da_tv(ofertas, diretas, _substitutas(estado, ofertas, diretas))
    # estado antigo não registrava os alertas de cupom: reconstrói (uma vez) o que o código da época alertou, com o
    # preço que ele usava (qualquer oferta de loja ativa, agregador inclusive)
    preco_antigo = _precos_da_tv(ofertas, None)[0]
    estado.migra_alertas_de_cupom(lambda reg: _alertado_no_codigo_antigo(reg, preco_antigo))
    # códigos que outro anúncio declara serem de outra categoria (ex.: DESCONTOEMCASA "em Casa e Decor")
    restritos = restricao_do_codigo(cupons, estado.cupons_vistos())
    novos: list[tuple[Cupom, str]] = []
    codigos_vistos: set[str] = set()
    # cupom da página do produto primeiro (se o mesmo código vier também como cupom do site, fica a linha do produto),
    # depois os que falam de TV: a mensagem mostra só 12 linhas e estes não podem ficar no "… e mais N"
    for c in sorted(cupons, key=lambda c: (not c.especifico, not _escopo(c.titulo, c.regra).tem_tv)):
        if estado.cupom_anterior(c.chave) is not None:
            continue
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        ok, _motivo = cupom_compativel(c, preco_por_loja.get(lc))
        if not ok:
            continue
        marca = marca_cupom(lc, c.codigo)
        if marca in restritos and not c.especifico:
            continue
        if marca in codigos_vistos:
            continue  # o mesmo cupom no Promobit e no Pelando nesta rodada
        # o mesmo código volta com outro id (a Magalu põe a data no id; Pelando e Promobit têm ids próprios):
        # só é repetição se já foi ALERTADO com o mesmo desconto
        if _ja_alertado(estado, marca, c):
            continue
        codigos_vistos.add(marca)
        if estado.bootstrap:
            # partida: a mensagem de início anuncia os cupons aplicáveis e avisa que só chegam novidades depois
            estado.registra_alerta_cupom(c, origem="partida")
            continue
        pl = preco_por_loja.get(lc)
        linha = f"• <b>{_esc(lc)}</b> <code>{_esc(c.codigo)}</code> — {_esc(c.titulo[:90])}"
        if c.validade:
            linha += f" (até {_esc(c.validade[:10])})"
        if pl:
            linha += f" · TV lá: {fmt_preco(pl)}"
        if c.especifico:
            linha = "⭐ " + linha + " — cupom do produto"
        linha += f"\n  {c.url}"
        novos.append((c, linha))
    if novos:
        cab = "🎟️ <b>Novos cupons aplicáveis à TV</b>" if len(novos) > 1 else "🎟️ <b>Novo cupom aplicável à TV</b>"
        corpo = "\n".join(linha for _c, linha in novos[:12])
        if len(novos) > 12:
            corpo += f"\n… e mais {len(novos) - 12} (veja o painel)"
        msgs.append(cab + "\n" + corpo)
        # registra o que foi alertado de fato (as linhas que foram na mensagem), para não repetir depois
        for c, _linha in novos[:12]:
            estado.registra_alerta_cupom(c)

    return msgs, alertados


_RE_PARCELA_TXT = re.compile(r"(\d{1,2})x\s*(?:de\s*)?R\$\s?([\d.]+(?:,\d{2})?)", re.I)


def sanear(ofertas: list[Oferta]) -> tuple[list[Oferta], list[str]]:
    """Tira preços que claramente não são desta TV antes de virarem alerta.

    Nasceu de um caso real: a página esgotada da Casas Bahia fez o coletor pegar o preço de uma
    Hisense do carrossel de recomendados (R$ 2.189) como se fosse a 55C6K.
    Duas checagens: parcelamento que não fecha com o preço, e preço fora da faixa das outras lojas.
    """
    from statistics import median

    avisos: list[str] = []
    # 1) parcelado incoerente com o preço -> o parcelado veio de outro produto
    for o in ofertas:
        if not o.parcelado or not o.melhor_preco:
            continue
        m = _RE_PARCELA_TXT.search(o.parcelado)
        if not m:
            continue
        total = int(m.group(1)) * (parse_preco(m.group(2)) or 0)
        # o parcelamento é do preço do cartão; comparar com o Pix derrubaria parcelado bom quando o desconto do Pix
        # passa de 20% (a Amazon já mostra 10% no Pix)
        ref = o.preco or o.melhor_preco
        if total and abs(total - ref) > max(80.0, ref * 0.2):
            avisos.append(f"{o.loja}: parcelado '{o.parcelado}' não fecha com {fmt_preco(ref)}")
            o.extra["parcelado_descartado"] = o.parcelado
            o.parcelado = None

    # 2) preço muito fora da faixa das demais lojas
    precos = [o.melhor_preco for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco]
    if len(precos) >= 4:
        meio = median(precos)
        piso, teto = meio * 0.55, meio * 2.2
        for o in ofertas:
            p = o.melhor_preco
            if o.tipo != "loja" or not o.ativo or not p or piso <= p <= teto:
                continue
            avisos.append(f"{o.loja}: {fmt_preco(p)} fora da faixa (mediana {fmt_preco(meio)}) — descartado")
            o.ativo = False
            o.extra["descartado"] = f"fora da faixa (mediana {meio:.2f})"
    return ofertas, avisos


def cupons_aplicaveis(ofertas: list[Oferta], cupons: list[Cupom], estado: Optional[Estado] = None) -> list[Cupom]:
    """Só cupons de lojas que vendem a TV e cuja regra cabe no preço dela (para o painel e o resumo).
    Com o estado, um código que outro anúncio já visto diz ser de outra categoria também fica fora."""
    if estado is not None:
        diretas = estado.lojas_diretas_conhecidas(ofertas)
        preco_por_loja, lojas_com_tv = _precos_da_tv(ofertas, diretas, _substitutas(estado, ofertas, diretas))
    else:
        preco_por_loja, lojas_com_tv = _precos_da_tv(ofertas, lojas_diretas(ofertas))
    restritos = restricao_do_codigo(cupons, estado.cupons_vistos() if estado else [])
    out: list[Cupom] = []
    vistos: set[str] = set()
    for c in cupons:
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        if not cupom_compativel(c, preco_por_loja.get(lc))[0]:
            continue
        marca = marca_cupom(lc, c.codigo)
        if marca in restritos and not c.especifico:
            continue
        if marca in vistos:
            continue
        vistos.add(marca)
        out.append(c)
    return out


def _precos_da_tv(ofertas: list[Oferta], diretas: Optional[set[str]],
                  substitutas: list[dict] = ()) -> tuple[dict[str, float], set[str]]:
    """({loja: preço da TV}, lojas que vendem a TV) para os cupons ("TV lá" e o valor mínimo/teto da compra).

    O preço é o menor que conta (conta_como_preco; diretas=None: qualquer oferta de loja ativa, a regra antiga). A
    loja que nesta rodada só aparece por agregador que não conta usa a oferta direta do outro modo (`substitutas`)."""
    preco: dict[str, float] = {}
    com_tv: set[str] = set(_LOJAS_COM_TV)
    for o in ofertas:
        if o.tipo != "loja" or not o.melhor_preco or not o.ativo:
            continue
        lc = loja_canonica(o.loja)
        com_tv.add(lc)
        if diretas is None or conta_como_preco(o, diretas):
            preco[lc] = min(preco.get(lc, 1e9), o.melhor_preco)
    for d in substitutas:
        lc = loja_canonica(d.get("loja") or "")
        com_tv.add(lc)
        preco.setdefault(lc, float(d["melhor_preco"]))
    return preco, com_tv


def _substitutas(estado: Estado, ofertas: list[Oferta], diretas: set[str]) -> list[dict]:
    """Lojas que nesta rodada só aparecem por agregador (Zoom) que não conta porque o outro modo tem fonte direta
    delas: a oferta direta mais barata do outro modo, com '_modo' e '_visto'. Ex.: no cloud, a Amazon do Zoom (R$ 3.279
    parado desde 14/09) dá lugar à Amazon que o pc viu (R$ 3.749)."""
    contam = {loja_canonica(o.loja) for o in ofertas if conta_como_preco(o, diretas)}
    suprimidas = {loja_canonica(o.loja) for o in ofertas
                  if o.tipo == "loja" and o.ativo and o.melhor_preco and e_agregador(o)} - contam
    if not suprimidas:
        return []
    melhor: dict[str, dict] = {}
    for d in estado.ofertas_diretas_de_outros_modos():
        lc = loja_canonica(d.get("loja") or "")
        if lc in suprimidas and (lc not in melhor or float(d["melhor_preco"]) < float(melhor[lc]["melhor_preco"])):
            melhor[lc] = d
    return list(melhor.values())


_NOME_DO_MODO = {"pc": "PC", "cloud": "nuvem"}


def _quando_curto(iso: str) -> str:
    """'2026-09-18T17:43:57-03:00' -> '18/09 17:43'."""
    m = re.match(r"\d{4}-(\d\d)-(\d\d)[T ](\d\d:\d\d)", iso or "")
    return f"{m.group(2)}/{m.group(1)} {m.group(3)}" if m else (iso or "?")[:16]


def resumo_diario(estado: Estado, ofertas: list[Oferta], cupons: list[Cupom]) -> str:
    diretas = estado.lojas_diretas_conhecidas(ofertas)
    # (preço, linha): ofertas desta rodada que contam como preço e, no lugar da linha do agregador que não conta, a
    # oferta direta que o outro modo viu (com quando e qual modo)
    itens: list[tuple[float, str]] = []
    for o in ofertas:
        if o.tipo == "loja" and conta_como_preco(o, diretas):
            quem = o.loja + (f"/{o.vendedor}" if o.vendedor and o.vendedor != o.loja else "")
            extra = f" · {o.parcelado}" if o.parcelado else ""
            itens.append((o.melhor_preco or 0, f"• {_esc(quem)}: <b>{fmt_preco(o.melhor_preco)}</b>{_esc(extra)}"))
    for d in _substitutas(estado, ofertas, diretas):
        vend = d.get("vendedor")
        quem = (d.get("loja") or "") + (f"/{vend}" if vend and vend != d.get("loja") else "")
        extra = f" · {d['parcelado']}" if d.get("parcelado") else ""
        modo = _NOME_DO_MODO.get(d.get("_modo") or "", d.get("_modo") or "")
        visto = f" · visto {_quando_curto(d.get('_visto') or '')} ({modo})"
        p = float(d["melhor_preco"])
        itens.append((p, f"• {_esc(quem)}: <b>{fmt_preco(p)}</b>{_esc(extra)}{_esc(visto)}"))
    itens.sort(key=lambda x: x[0])
    linhas = ["☀️ <b>Resumo diário — TCL 55C6K</b>"]
    if itens:
        linhas += [linha for _p, linha in itens[:10]]
    else:
        linhas.append("• nenhum preço de loja coletado")
    m = estado.minimo_geral(diretas)
    if m:
        linhas.append(f"Menor já visto: {fmt_preco(float(m['preco']))} ({_esc(m['loja'])}, {m['quando'][:10]})")
    linhas.append(f"Alvo: Pix {fmt_preco(config.ALVO_PIX)} · parcelado {fmt_preco(config.ALVO_PARCELADO)}")
    if cupons:
        cods = ", ".join(sorted({f"{loja_canonica(c.loja)} {c.codigo}" for c in cupons}))[:400]
        linhas.append(f"Cupons ativos: {_esc(cods)}")
    return "\n".join(linhas)


def mensagem_bootstrap(ofertas: list[Oferta], cupons: list[Cupom], modo: str,
                       diretas: Optional[set[str]] = None) -> str:
    """`diretas`: lojas com fonte direta conhecidas (Estado.lojas_diretas_conhecidas); None: só as desta rodada."""
    if diretas is None:
        diretas = lojas_diretas(ofertas)
    lojas = sorted([o for o in ofertas if o.tipo == "loja" and conta_como_preco(o, diretas)],
                   key=lambda o: o.melhor_preco or 0)
    posts = [o for o in ofertas if o.tipo == "post"]
    linhas = [f"✅ <b>Monitor da TCL 55C6K iniciado</b> (modo {modo})"]
    for o in lojas[:8]:
        linhas.append(f"• {_esc(o.loja)}: <b>{fmt_preco(o.melhor_preco)}</b>" + (f" · {_esc(o.parcelado)}" if o.parcelado else ""))
    linhas.append(f"{len(posts)} postagens antigas registradas, {len(cupons)} cupons ativos. A partir de agora só chegam novidades.")
    return "\n".join(linhas)


def mensagem_fonte_quebrada(nome: str, falhas: int, erro: str) -> str:
    return f"⚠️ Fonte <b>{_esc(nome)}</b> falhou {falhas} vezes seguidas.\n<code>{_esc(erro[:200])}</code>"
