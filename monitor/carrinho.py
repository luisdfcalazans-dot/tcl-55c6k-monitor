"""Teste de cupons no carrinho das lojas, com a conta do usuário logada num perfil próprio do Chrome.

Regras de segurança, sem exceção:
  - o robô NUNCA clica em "continuar", "finalizar", "pagar" nem mexe em endereço ou pagamento;
  - o robô NUNCA digita e-mail, CPF ou senha: o login é feito pela pessoa, na janela aberta por --login;
  - se a loja pedir login, o teste para e avisa.

Cada loja é um adaptador com: garantir que a TV está no carrinho, abrir o campo de cupom, aplicar um
código e ler os totais, remover o cupom.

Desde 19/09 o testador percorre TODOS os anúncios da TV numa loja (do mais barato ao mais caro). Cada
anúncio chega aqui como um dicionário `alvo` (ver `LojaCarrinho.identidade`): chave estável do anúncio,
vendedor, id do vendedor, item do ML. `garantir_item(page, url, alvo)` deixa no carrinho exatamente
AQUELE anúncio e AQUELE vendedor, com 1 unidade, e só troca o que já estava lá quando o carrinho tem só a
TV. Com qualquer outro produto no carrinho, levanta CarrinhoOcupado e a loja fica para a próxima rodada.

Dois modelos (26/09): a 55C6K e a 65C6K. O carrinho da pessoa termina a rodada com UMA TV de cada modelo
(1 unidade cada) e nunca com outro produto. Para medir um cupom de um modelo, `garantir_item` isola aquele
anúncio no carrinho (o cupom vale para o pedido inteiro): a linha do outro modelo só sai se o testador
conhece um anúncio dele para devolver depois (`alvo["restauraveis"]`); senão, CarrinhoOcupado. No fim,
`garantir_itens(page, alvos)` deixa exatamente um anúncio de cada modelo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .filtro import eh_55c6k, eh_65c6k
from .models import MODELO_55, MODELO_65, MODELOS, MODELO_PADRAO  # noqa: F401 (MODELOS/MODELO_PADRAO: testar_cupons)
from .util import fmt_preco, next_data, parse_preco, sem_acentos

PERFIS = config.RAIZ / ".pw-profile-carrinho"

# ----------------------------------------------------------------------------------------------
# modelos (26/09): 55C6K e 65C6K. Nomes em monitor/models.py; registro sem o campo 'modelo' (gravado antes de
# 26/09) é da 55C6K (MODELO_PADRAO).
# ----------------------------------------------------------------------------------------------

# catálogo do Mercado Livre de cada modelo (o mesmo da coleta: config.ML_CATALOGOS)
CATALOGOS_ML = dict(config.ML_CATALOGOS)
_RE_TAMANHO = {MODELO_55: re.compile(r"(?<!\d)55(?!\d)"), MODELO_65: re.compile(r"(?<!\d)65(?!\d)")}
# os dois códigos no mesmo texto ("55C6K/65C6K", "55C6K ou 65C6K"): a coleta dá o par à 55C6K (o preço da postagem é
# o "a partir de"), mas no carrinho um texto que serve para os dois tamanhos não é nenhum deles
_RE_CODIGO = {MODELO_55: re.compile(r"(?<!\d)55\s*c6k(?![a-z0-9])", re.I),
              MODELO_65: re.compile(r"(?<!\d)65\s*c6k(?![a-z0-9])", re.I)}


def modelo_da_oferta(o) -> str:
    """Modelo de uma oferta/registro (campo 'modelo'); sem o campo, 55C6K (contrato de 26/09)."""
    m = o.get("modelo") if isinstance(o, dict) else getattr(o, "modelo", None)
    return str(m or MODELO_PADRAO).strip().upper()


def eh_do_modelo(texto: str, modelo: str) -> bool:
    """O título é a TV C6K deste modelo, com o tamanho escrito (55 ou 65). Filtros da coleta (monitor/filtro.py):
    acessório, combo, estado, vizinhos (65C7K, 65P7L, 65QM8K, C6KS...) e vários tamanhos ficam de fora."""
    t = texto or ""
    if modelo == MODELO_55:
        ok = eh_55c6k(t)
    elif modelo == MODELO_65:
        ok = eh_65c6k(t)
    else:
        return False
    return ok and bool(_RE_TAMANHO[modelo].search(t))


def modelo_do_titulo(texto: str) -> Optional[str]:
    """55C6K, 65C6K ou None (outro produto, ou texto que serve para os dois tamanhos: na dúvida, nenhum)."""
    t = texto or ""
    if all(r.search(t) for r in _RE_CODIGO.values()):
        return None
    achados = [m for m in MODELOS if eh_do_modelo(t, m)]
    return achados[0] if len(achados) == 1 else None

# mensagens que são do robô (campo não achado, exceção, total ilegível), não resposta da loja
_RE_FALHA = re.compile(r"^erro\b|campo de cupom n[ãa]o encontrado|n[ãa]o consegui|n[ãa]o conferid", re.I)


def falha_da_ferramenta(mensagem: str) -> bool:
    """True quando o teste não chegou a uma resposta da loja: não pode virar recusa do cupom."""
    return bool(_RE_FALHA.search(mensagem or ""))


# serviço vendido junto com a TV ("Garantia Estendida 12 meses - Smart TV 55" TCL ... 55C6K", "Seguro Roubo e
# Furto Smart TV TCL 55C6K", "Instalação de TV - ..."): o nome traz o título da TV e eh_55c6k aceita, mas NÃO é a
# TV. Conta só quando a palavra do serviço vem ANTES do nome da TV: a linha da própria TV pode oferecer o serviço
# depois do título ("Smart TV ... 55C6K\nAdicionar garantia estendida").
_RE_SERVICO = re.compile(r"\b(?:garantia|seguro|prote[çc][ãa]o|instala[çc][ãa]o|servi[çc]os?|assist[êe]ncia)\b", re.I)
_RE_NOME_TV = re.compile(r"smart\s*tv|\btv\b|televis|[56]5\s*c6k|\btcl\b", re.I)


def eh_servico(texto: str) -> bool:
    t = texto or ""
    m = _RE_NOME_TV.search(t)
    return bool(_RE_SERVICO.search(t[: m.start()] if m else t))


def modelo_da_linha(texto: str) -> Optional[str]:
    """Modelo da linha/item do carrinho que é a própria TV (55C6K ou 65C6K); None para serviço com o nome dela,
    outro produto ou texto que não dá para dizer."""
    return None if eh_servico(texto) else modelo_do_titulo(texto)


def eh_linha_da_tv(texto: str, modelo: Optional[str] = None) -> bool:
    """Linha/item do carrinho que é a própria TV (de `modelo`, ou de qualquer um dos dois), não um serviço."""
    m = modelo_da_linha(texto)
    return m is not None and (modelo is None or m == modelo)


@dataclass
class ResultadoCupom:
    codigo: str
    aceito: bool
    mensagem: str = ""
    produtos: Optional[float] = None      # soma dos produtos (sem frete)
    frete: Optional[float] = None
    desconto: Optional[float] = None
    total_pix: Optional[float] = None
    total_cartao: Optional[float] = None
    # total_pix é mesmo um preço de Pix? Carrinho que não mostra o Pix (ML sempre; Amazon quando a página
    # não traz o preço à vista) copia o total do CARTÃO para total_pix: ali tv_pix é preço de cartão e não
    # pode ser comparado com um preço de Pix (ver referencia_sem_cupom em testar_cupons.py).
    pix_real: bool = True
    parcelado: Optional[str] = None
    quantidade: int = 1
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        """'aceito' (o preço da TV caiu), 'so_frete' (a loja aceitou, mas só o frete mudou: não é desconto na TV),
        'recusado' (a loja disse não) ou 'erro' (falha do robô ou preço ilegível, que não vale como recusa)."""
        if self.aceito:
            return "aceito"
        if self.extra.get("so_frete"):
            return "so_frete"
        if self.extra.get("falha") or falha_da_ferramenta(self.mensagem):
            return "erro"
        return "recusado"

    @property
    def tv_pix(self) -> Optional[float]:
        """Preço de UMA TV no Pix já com cupom, sem frete."""
        if self.total_pix is None:
            return None
        return round((self.total_pix - (self.frete or 0)) / max(1, self.quantidade), 2)

    @property
    def tv_cartao(self) -> Optional[float]:
        if self.total_cartao is None:
            return None
        return round((self.total_cartao - (self.frete or 0)) / max(1, self.quantidade), 2)

    @property
    def parcelado_real(self) -> Optional[str]:
        """O parcelado que a loja mostra costuma ser o de antes do cupom; aqui refazemos a conta.

        Se '10x R$ 417,89' não bate com o total no cartão, devolvemos '10x de R$ 391,90'.
        """
        if not self.parcelado:
            return None
        m = re.search(r"(\d{1,2})x\s*(?:de\s*)?R\$\s?([\d.]+(?:,\d{2})?)", self.parcelado, re.I)
        alvo = self.tv_cartao
        if not m or alvo is None:
            return self.parcelado
        n = int(m.group(1))
        valor = parse_preco(m.group(2)) or 0
        if abs(n * valor - alvo) <= max(1.0, alvo * 0.02):
            return self.parcelado
        certo = alvo / n
        return f"{n}x de R$ {certo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " sem juros"


# ----------------------------------------------------------------------------------------------
# o que o cupom fez (L2, 26/09): no ML, "MELIPROMOBIT" saiu "aceito" com o total ILEGÍVEL ("TV —") e outros dois com a
# TV no mesmo preço, porque qualquer linha "Desconto" do resumo (o do Pix, o "de produtos") contava como cupom.
# Agora só o preço da TV medido antes e depois decide.
# ----------------------------------------------------------------------------------------------

TOLERANCIA_PRECO = 1.0   # R$: diferença menor que isto é arredondamento da loja, não desconto


def _tv_do_total(total: Optional[float], frete: Optional[float], quantidade: int) -> Optional[float]:
    return None if total is None else round((total - (frete or 0)) / max(1, quantidade), 2)


def medir_cupom(antes: ResultadoCupom, depois: ResultadoCupom, mensagem: str = "") -> ResultadoCupom:
    """Decide, em `depois`, o que o cupom fez, comparando o carrinho ANTES e DEPOIS dele:

    - a loja respondeu com uma recusa (`mensagem`): recusado;
    - o preço da TV não dá para ler antes E depois na mesma base (cartão com cartão, Pix com Pix): 'erro' (o teste
      não mediu nada e volta na próxima rodada), nunca 'aceito', nem com uma linha de desconto no resumo;
    - o preço da TV (total menos frete, por unidade) caiu: aceito;
    - só o frete caiu e a TV custa o mesmo: 'so_frete' (extra['so_frete']), que NUNCA é desconto na TV;
    - o resumo mostra um cupom mas o preço da TV não caiu: 'erro' (leitura no meio da atualização; testa de novo);
    - nada mudou: recusado ('sem mudança no preço da TV').
    O frete que não deu para ler de um lado vale o do outro (aí a queda do total fica com a TV)."""
    depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao, "antes_frete": antes.frete}
    depois.aceito = False
    if mensagem:
        depois.mensagem = mensagem
        return depois

    def falha(motivo: str) -> ResultadoCupom:
        depois.mensagem = motivo
        depois.extra["falha"] = True
        return depois

    if max(1, antes.quantidade) != max(1, depois.quantidade):
        return falha(f"não consegui medir: a quantidade no carrinho mudou ({antes.quantidade} -> {depois.quantidade})")
    fa, fd = antes.frete, depois.frete
    fa = fd if fa is None else fa
    fd = fa if fd is None else fd
    q = max(1, depois.quantidade)
    pares = []
    if antes.total_cartao is not None and depois.total_cartao is not None:
        pares.append((_tv_do_total(antes.total_cartao, fa, q), _tv_do_total(depois.total_cartao, fd, q)))
    if antes.pix_real and depois.pix_real and antes.total_pix is not None and depois.total_pix is not None:
        pares.append((_tv_do_total(antes.total_pix, fa, q), _tv_do_total(depois.total_pix, fd, q)))
    if not pares:
        return falha("não consegui ler o preço da TV no carrinho antes e depois do cupom")
    queda_tv = max(a - d for a, d in pares)
    tv_igual = all(abs(a - d) <= TOLERANCIA_PRECO for a, d in pares)
    queda_frete = (antes.frete - depois.frete) if antes.frete is not None and depois.frete is not None else 0.0
    if queda_tv > TOLERANCIA_PRECO:
        depois.aceito = True
        depois.mensagem = ""
    elif tv_igual and queda_frete > 0.5:
        depois.extra["so_frete"] = True
        tv = pares[-1][1]    # o Pix quando a loja mostra (a mesma base da mensagem), senão o cartão
        depois.mensagem = f"só frete: frete {fmt_preco(antes.frete)} → {fmt_preco(depois.frete)}; a TV continua {fmt_preco(tv)}"
    elif depois.desconto:
        return falha(f"não consegui ver o preço da TV cair (o resumo mostra cupom de {fmt_preco(depois.desconto)})")
    else:
        depois.mensagem = "sem mudança no preço da TV"
    return depois


class PrecisaLogin(Exception):
    """A loja pediu login: a sessão salva expirou ou nunca foi feita."""


class LojaIndisponivel(Exception):
    """A loja não carregou o carrinho (instabilidade ou bloqueio antirrobô): parar e esperar."""


class CarrinhoOcupado(Exception):
    """O carrinho tem produto que não é a TV (ou não dá para conferir que é): não mexemos em nada e a loja
    inteira fica para a próxima rodada (trocar de anúncio daria no mesmo carrinho)."""


# ----------------------------------------------------------------------------------------------
# vendedor: comparação tolerante (id x nome, acento, pontuação: "Magalu." na Amazon)
# ----------------------------------------------------------------------------------------------

# o próprio Magalu aparece como id "magazineluiza" e nome "Magalu" / "Magazine Luiza"
_MAGALU_1P = {"magalu", "magazineluiza"}


def norm_vendedor(s) -> str:
    """Nome/id do vendedor comparável, sem o ruído que a Amazon cola no nome ("Amazon.com.br Política de devolução",
    "Vendido por Amazon.com.br", "Enviado de e vendido por Amazon.com.br"): o 1P da Amazon (A1ZZFT5FULY4LN, 26/09) tem
    esse nome na coleta e "Amazon.com.br" na página do anúncio."""
    t = sem_acentos(str(s or "")).lower()
    t = re.sub(r"politica de devolucao|^\s*(?:enviado (?:de )?e )?vendido por\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


# a própria Amazon (1P): o merchantID A1ZZFT5FULY4LN ou o nome "Amazon.com.br" (L3, 26/09: a página do anúncio 1P não
# tem link de perfil do vendedor, só o merchantID escondido; a coleta grava o id e o nome)
_AMAZON_1P = {norm_vendedor(config.AMAZON_1P_ID), "amazoncombr"}


def mesmo_vendedor(a_id, a_nome, b_id, b_nome) -> Optional[bool]:
    """True/False comparando id e nome dos dois lados; None quando um dos lados não diz nada. O próprio Magalu
    ('magazineluiza' / 'Magalu') e a própria Amazon (A1ZZFT5FULY4LN / 'Amazon.com.br') valem pelo id OU pelo nome."""
    lado_a = {norm_vendedor(x) for x in (a_id, a_nome)} - {""}
    lado_b = {norm_vendedor(x) for x in (b_id, b_nome)} - {""}
    if not lado_a or not lado_b:
        return None
    for lado in (lado_a, lado_b):
        for primeira_parte in (_MAGALU_1P, _AMAZON_1P):
            if lado & primeira_parte:
                lado |= primeira_parte
    return bool(lado_a & lado_b)


class LojaCarrinho:
    nome = "base"
    loja_canonica = "?"
    url_login = ""
    url_carrinho = ""
    url_produto = ""          # anúncio usado quando não há um mais barato conhecido
    dominio_url = ""          # trecho que identifica um anúncio desta loja nas coletas
    so_leitura = False        # True quando a loja não aceita código digitado (só lê preço/cupom da página)
    max_anuncios = 1          # quantos anúncios diferentes visitar por rodada (antirrobô)
    item_alvo: Optional[str] = None  # id do anúncio que garantir_item conferiu no carrinho (quando a URL não diz)
    # 22/09 (F3): quantas linhas/itens que JÁ estavam no carrinho o robô tirou desde comecar_rodada(). O aviso de
    # "a sacola pode ter ficado vazia" só vale quando isto passou de zero e a TV não voltou a ser conferida.
    remocoes = 0
    # 26/09: o modelo de cada linha tirada (na ordem), para o testador saber qual TV saiu do carrinho e tem de voltar
    # ("?" quando não deu para dizer). Nunca alterado no lugar: comecar_rodada cria uma lista nova.
    removidos: list = []
    # o carrinho pode ter ficado com mais de uma TV do mesmo modelo (ou mais de 1 unidade): a pessoa precisa saber
    tvs_a_mais = False
    # 22/09 (F5): opções de compra do catálogo que a página LOGADA mostrou nesta rodada, por item (só ML).
    # Nunca alterado no lugar: cada rodada/leitura cria um dicionário novo.
    opcoes_vistas: dict = {}

    def comecar_rodada(self) -> None:
        """Zera o que o adaptador anota durante uma rodada da loja (chamado pelo testador antes de começar)."""
        self.remocoes = 0
        self.removidos = []
        self.tvs_a_mais = False
        self.opcoes_vistas = {}

    def _tirou(self, modelo: Optional[str]) -> None:
        """Conta uma linha/item que JÁ estava no carrinho e o robô tirou (F3) e guarda o modelo dela."""
        self.remocoes += 1
        self.removidos = [*self.removidos, modelo or "?"]

    def perfil(self) -> Path:
        return PERFIS / self.nome

    # --- identidade do anúncio (contrato com a coleta: uma Oferta tipo "loja" por anúncio+vendedor) ---
    def identidade(self, o: dict) -> dict:
        """Chave estável do anúncio e o que o carrinho precisa para achá-lo.

        `o` é a oferta como está no latest_<modo>.json. A chave é a identidade do anúncio+vendedor (nunca o
        fim da URL, que muda quando a coleta muda o formato do link)."""
        extra = o.get("extra") or {}
        return {"chave": str(o.get("id") or o.get("url") or ""), "vendedor_id": extra.get("vendedor_id"),
                "item_id": extra.get("item_id"), "produto": extra.get("anuncio")}

    def eh_chave_antiga(self, sufixo: str, reg: dict, alvo: dict) -> bool:
        """Registros de cupom gravados antes de 19/09 usavam o fim da URL (url[-40:]) como chave do anúncio.
        True quando `sufixo` é uma dessas chaves e é o MESMO anúncio de `alvo` (para não retestar tudo)."""
        return bool(sufixo) and sufixo == (alvo.get("url") or "")[-40:]

    def tem_cupom_aplicado(self, page, base: "ResultadoCupom") -> bool:
        """O carrinho já está com um cupom (de uma rodada anterior)? Aí o total não é o preço cheio."""
        return False

    # --- a implementar por loja ---
    def logado(self, page) -> bool:  # pragma: no cover
        raise NotImplementedError

    def garantir_item(self, page, url_produto: str, alvo: Optional[dict] = None) -> bool:  # pragma: no cover
        raise NotImplementedError

    def garantir_itens(self, page, alvos: list[dict]) -> set:  # pragma: no cover
        """Passo final com os dois modelos: deixa no carrinho exatamente estes anúncios (um por modelo), 1 unidade
        cada, sem tocar em linha de modelo que não está em `alvos`. Devolve as chaves conferidas no carrinho."""
        raise NotImplementedError

    def ler_totais(self, page) -> ResultadoCupom:  # pragma: no cover
        raise NotImplementedError

    def aplicar(self, page, codigo: str) -> ResultadoCupom:  # pragma: no cover
        raise NotImplementedError

    def remover(self, page) -> None:  # pragma: no cover
        raise NotImplementedError


# ----------------------------------------------------------------------------------------------
# Magazine Luiza
# ----------------------------------------------------------------------------------------------

_RE_PIX = re.compile(r"R\$\s?([\d.]+,\d{2})\s*no\s*PIX", re.I)
_RE_CARTAO = re.compile(r"ou\s*R\$\s?([\d.]+,\d{2})\s*no\s*cart", re.I)
_RE_PRODUTOS = re.compile(r"Produtos\s*\(\d+\):?\s*\n?\s*R\$\s?([\d.]+,\d{2})", re.I)
_RE_FRETE = re.compile(r"Frete:?\s*\n?\s*(R\$\s?[\d.]+,\d{2}|Gr[áa]tis)", re.I)
_RE_DESCONTO = re.compile(r"(?:Cupom|Desconto)[^\n]*\n?\s*-\s?R\$\s?([\d.]+,\d{2})", re.I)
_RE_PARCELA = re.compile(r"em\s+(\d{1,2})x\s+de\s+R\$\s?([\d.]+,\d{2})\s*sem juros", re.I)
_RE_REJEITADO = re.compile(
    r"inv[áa]lido|expirad|n[ãa]o (?:é |e )?v[áa]lido|n[ãa]o encontrad|n[ãa]o se aplica|indispon[íi]vel|"
    r"n[ãa]o pode ser (?:usado|aplicado)|esgotad|n[ãa]o eleg[íi]vel|n[ãa]o est[áa] dispon|n[ãa]o foi aplicado|"
    r"erro de digita", re.I)
_RE_ACEITO = re.compile(r"cupom (?:aplicado|adicionado|ativo)|desconto aplicado", re.I)


_RE_CARTAO_LOJA = re.compile(r"Pague com (?:o )?Cart[ãa]o Magalu", re.I)
_RE_LINHA_CARTAO_LOJA = re.compile(r"^(?:em|ou)\s+(?:at[ée]\s+)?\d{1,2}x\b|cart[ãa]o magalu", re.I)


def _sem_cartao_da_loja(texto: str) -> str:
    """Tira o quadro 'Pague com Cartão Magalu' (em 10x … / ou 21x … no Cartão Magalu).

    Essas parcelas valem só para o cartão da loja; o parcelado que interessa é o dos cartões comuns.
    """
    linhas = (texto or "").splitlines()
    fora: list[str] = []
    k = 0
    while k < len(linhas):
        if _RE_CARTAO_LOJA.search(linhas[k]):
            k += 1
            while k < len(linhas) and (not linhas[k].strip() or _RE_LINHA_CARTAO_LOJA.search(linhas[k].strip())):
                k += 1
            continue
        fora.append(linhas[k])
        k += 1
    return "\n".join(fora)


def _sem_total(r: ResultadoCupom) -> bool:
    """Não deu para ler total nenhum: o teste não mediu nada (é falha do robô, não recusa)."""
    return r.total_cartao is None and r.total_pix is None


def _texto(page) -> str:
    return page.evaluate("() => document.body ? document.body.innerText : ''")


class Magalu(LojaCarrinho):
    cupom_aplicado: Optional[str] = None   # preenchido por itens_da_sacola (appliedPromoCode)
    nome = "magalu"
    loja_canonica = "Magazine Luiza"
    url_login = "https://www.magazineluiza.com.br/cliente/login/"
    url_carrinho = "https://sacola.magazineluiza.com.br/"
    url_produto = config.URL_MAGALU_PRODUTO.replace(
        "https://www.magazinevoce.com.br/magazinecanaltechbr", "https://www.magazineluiza.com.br")
    dominio_url = "magazineluiza.com.br"
    max_anuncios = 4          # o cupom costuma valer para um vendedor e não para outro

    def logado(self, page) -> bool:
        t = _texto(page)[:1500]
        return "Entre ou Cadastre-se" not in t and "Quero criar uma conta" not in t

    def _pagina_de_login(self, page) -> bool:
        if "identificacao" in page.url or "/login" in page.url:
            return True
        t = _texto(page)[:2500]
        return "Quero criar uma conta" in t or page.locator("#input-login:visible, #input-password:visible").count() > 0

    @staticmethod
    def _id_anuncio(url: str) -> str:
        m = re.search(r"/p/([^/?#]+)", url or "")
        return m.group(1) if m else (url or "")[-24:]

    @staticmethod
    def _seller_da_url(url: str) -> Optional[str]:
        """O Magalu escolhe o vendedor pelo parâmetro ?seller_id= da página do produto (conferido em 19/09:
        vendedor que não vende aquele produto -> o site redireciona para o vendedor do buy box)."""
        m = re.search(r"[?&]seller_id=([^&#]+)", url or "")
        return m.group(1) if m else None

    def identidade(self, o: dict) -> dict:
        """Chave '<id do /p/ da URL>-<id do vendedor>'.

        Usamos o id do /p/ da URL (e não o 'id' do JSON da busca) porque é ele que a sacola devolve: em 19/09
        o anúncio 1P da 55C6K tinha id 240162800 no JSON e /p/240162700/ na URL (240162800 é o /p/ da 75")."""
        base = super().identidade(o)
        url = o.get("url") or ""
        oid = str(o.get("id") or "")
        pid = re.search(r"/p/([^/?#]+)", url)
        vend = base["vendedor_id"] or self._seller_da_url(url) or (oid.split("-", 1)[1] if "-" in oid else None)
        base["vendedor_id"] = vend
        base["produto"] = pid.group(1) if pid else base["produto"]
        if pid and vend:
            base["chave"] = f"{pid.group(1)}-{vend}"
        return base

    def eh_chave_antiga(self, sufixo: str, reg: dict, alvo: dict) -> bool:
        """Chave antiga 'fim da URL' ('...usb/p/240162700/et/elit/'): é deste anúncio se o /p/ bate e o
        vendedor gravado no registro (quando há) é o mesmo."""
        if super().eh_chave_antiga(sufixo, reg, alvo):
            return True
        pid = alvo.get("produto") or self._id_anuncio(alvo.get("url") or "")
        if not pid or f"/p/{pid}/" not in f"{sufixo}/":
            return False
        return mesmo_vendedor(None, (reg or {}).get("vendedor"), alvo.get("vendedor_id"), alvo.get("vendedor")) is not False

    def tem_cupom_aplicado(self, page, base: "ResultadoCupom") -> bool:
        return bool(self.cupom_aplicado)

    @staticmethod
    def info_da_pagina(html: str, texto: str = "", url: str = "") -> dict:
        """Vendedor e título que a página do produto está mostrando.

        Sinais: seller_id da URL final (o site redireciona quando o vendedor pedido não vende o produto),
        seller_id da query do __NEXT_DATA__, a oferta quando é uma só (ou item.seller) e o texto "Vendido
        por X". `sinais` traz todos os que a página deu; `vendedor_id`/`vendedor` são o melhor palpite."""
        nd = next_data(html or "") or {}
        dados = ((nd.get("props") or {}).get("pageProps") or {}).get("data") or {}
        item = dados.get("item") or dados.get("product") or {}
        ofertas = [o for o in (item.get("offers") or []) if isinstance(o, dict)]
        sinais: list[tuple] = []
        for sid in (Magalu._seller_da_url(url), (nd.get("query") or {}).get("seller_id")):
            if sid:
                nome = next(((o.get("seller") or {}).get("description") or (o.get("seller") or {}).get("name")
                             for o in ofertas if mesmo_vendedor((o.get("seller") or {}).get("id"), None, sid, None)),
                            None)
                sinais.append((sid, nome))
        if len(ofertas) == 1 or (not ofertas and item.get("seller")):
            s = (ofertas[0].get("seller") if ofertas else item.get("seller")) or {}
            if s.get("id") or s.get("description") or s.get("name"):
                sinais.append((s.get("id"), s.get("description") or s.get("name")))
        m = re.search(r"Vendido\s+(?:e\s+entregue\s+)?por\s+([^\n]+?)(?:\s+e\s+entregue\s+por\b[^\n]*)?\s*(?:\n|$)",
                      texto or "", re.I)
        if m:
            sinais.append((None, m.group(1).strip()))
        vid = next((i for i, _ in sinais if i), None)
        vnome = next((n for _, n in sinais if n), None)
        titulo = item.get("title")
        if not titulo:
            mt = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S | re.I)
            titulo = re.sub(r"<[^>]+>|\s+", " ", mt.group(1)).strip() if mt else None
        return {"vendedor_id": vid, "vendedor": vnome, "titulo": titulo, "sinais": sinais}

    def _abrir_pagina_do_anuncio(self, page, url_produto: str, vend_id, vend_nome, modelo: str = MODELO_PADRAO) -> bool:
        """Abre a página do anúncio e confere que ela é a TV do modelo pedido e está com o vendedor pedido.

        Chamado ANTES de mexer na sacola: se a página não oferece esse vendedor, nada muda no carrinho."""
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        info = self.info_da_pagina(page.content(), _texto(page), getattr(page, "url", "") or "")
        rotulo = self._id_anuncio(url_produto)
        if info["titulo"] and not (eh_55c6k(info["titulo"]) if modelo == MODELO_PADRAO
                                   else eh_do_modelo(info["titulo"], modelo)):
            print(f"[magalu] a página do anúncio {rotulo} não é a TV {modelo} ({info['titulo'][:60]}); não adiciono")
            return False
        if not (vend_id or vend_nome):
            return True
        # todos os sinais que a página deu têm de bater com o vendedor pedido (e pelo menos um tem de existir)
        comparacoes = [mesmo_vendedor(sid, snome, vend_id, vend_nome) for sid, snome in info["sinais"]]
        comparacoes = [c for c in comparacoes if c is not None]
        if not comparacoes:
            print(f"[magalu] não consegui ler o vendedor na página do anúncio {rotulo}; sem teste neste anúncio")
            return False
        if not all(comparacoes):
            print(f"[magalu] a página do anúncio {rotulo} abriu com o vendedor {info['vendedor'] or info['vendedor_id']}, "
                  f"não {vend_nome or vend_id}: não consegui escolher esse vendedor; sem teste neste anúncio")
            return False
        return True

    def itens_da_sacola(self, page) -> Optional[list[dict]]:
        """Abre a sacola e devolve os itens como a própria loja os descreve.

        A página da sacola consulta `GetPreBasketQuery` (GraphQL) e recebe, para cada item, o id do
        anúncio (o mesmo do /p/<id>/ da URL), a quantidade e o vendedor, além de `appliedPromoCode`.
        Ler isso é bem mais confiável que o texto da tela, que não traz o id do anúncio.
        Devolve None quando a consulta não aparece (aí não dá para afirmar o que está na sacola).
        """
        capt: dict = {}

        def pega(resp):
            if "GetPreBasketQuery" in resp.url:
                try:
                    capt["j"] = resp.json()
                except Exception:
                    pass

        page.on("response", pega)
        try:
            page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            _espera(page)
            for _ in range(12):
                if "j" in capt:
                    break
                page.wait_for_timeout(500)
        finally:
            try:
                page.remove_listener("response", pega)
            except Exception:
                pass
        if "j" not in capt:
            texto = _texto(page)
            if "Não conseguimos carregar sua sacola" in texto:
                # 18/09: depois de dezenas de operações seguidas, o Magalu passou a responder isso e a nem
                # chamar a consulta da sacola. Insistir só piora; quem chama deve pausar a loja.
                raise LojaIndisponivel("o Magalu não carregou a sacola (instabilidade ou bloqueio antirrobô)")
            return [] if "sacola está vazia" in texto else None
        lista = ((capt["j"].get("data") or {}).get("itemList") or {})
        self.cupom_aplicado = lista.get("appliedPromoCode")
        itens = []
        for it in lista.get("items") or []:
            ofertas = ((it.get("item") or {}).get("offers") or [{}])
            vend = (ofertas[0].get("seller") or {}) if ofertas else {}
            extras = it.get("extras") or {}
            itens.append({
                "id": it.get("id") or (it.get("item") or {}).get("id"),
                "quantidade": int(it.get("quantity") or 1),
                "vendedor": vend.get("name") or vend.get("description") or extras.get("sellerId"),
                "vendedor_id": vend.get("id") or extras.get("sellerId"),
                "titulo": it.get("name") or (it.get("item") or {}).get("title") or "",
            })
        return itens

    def _anuncio_na_sacola(self, page) -> str:
        """Id do único anúncio na sacola; '' se vazia; '?' se há mais de um ou não deu para ler."""
        itens = self.itens_da_sacola(page)
        if itens is None:
            return "?"
        if not itens:
            return ""
        return itens[0]["id"] if len(itens) == 1 else "?"

    @staticmethod
    def modelo_do_item(item: dict, ids_modelo: Optional[dict] = None) -> Optional[str]:
        """Modelo de um item da sacola: pelo id do /p/ de um anúncio conhecido (o tamanho vem da variação que a coleta
        leu, não do título) ou, sem isso, pelo título. Serviço com o nome da TV (garantia, seguro) não é a TV."""
        titulo = item.get("titulo") or ""
        if eh_servico(titulo):
            return None
        return (ids_modelo or {}).get(str(item.get("id") or "")) or modelo_da_linha(titulo)

    @classmethod
    def _so_tvs(cls, itens: Optional[list[dict]], ids_modelo: Optional[dict] = None) -> bool:
        """True só quando a sacola foi lida e TODO item dela é uma das TVs (55C6K ou 65C6K); garantia/seguro da TV
        não é a TV."""
        return itens is not None and all(cls.modelo_do_item(i, ids_modelo) for i in itens)

    @classmethod
    def _modelos_na_sacola(cls, itens: Optional[list[dict]], ids_modelo: Optional[dict] = None) -> set:
        return {cls.modelo_do_item(i, ids_modelo) for i in (itens or [])} - {None}

    # confirmação do "Excluir". Ancorada: solta, "sim" casa com "Produtos similares" e "excluir" com
    # qualquer frase que cite a palavra — e a sacola tem um carrossel de recomendados embaixo do resumo.
    _RE_CONFIRMA_EXCLUIR = re.compile(r"^(excluir|confirmar|sim)\b", re.I)

    def esvaziar(self, page, ids_modelo: Optional[dict] = None) -> None:
        """Remove itens da sacola SOMENTE se todos forem uma das TVs (55C6K ou 65C6K).

        A sacola é a do usuário: se houver qualquer outro produto (ou se não der para ler o que há),
        não mexemos em nada. Quem chama trata isso como "não deu para trocar o anúncio".
        Cada clique em "Excluir" conta em `remocoes` (F3) e guarda o modelo em `removidos`: o aviso de sacola
        vazia (ou de TV que saiu e não voltou) depende disso.

        Por que o Magalu esvazia a sacola em vez de tirar um item só: na sacola, os itens só têm identidade na
        resposta GetPreBasketQuery (id do /p/ + vendedor); o HTML não tem link /p/<id> nem nada que ligue um
        botão "Excluir" ao item (bug de 17/09). Com dois itens na sacola, não dá para garantir qual "Excluir" é de
        qual item (e o mesmo /p/ de outro vendedor pode até somar unidades). Por isso aqui continua: conferir
        página e vendedor ANTES, esvaziar só sacola que tem apenas as TVs, e pôr o(s) anúncio(s); se não
        entrarem, o testador tenta devolver o mais barato de cada modelo e, como houve remoção, avisa.
        """
        itens = self.itens_da_sacola(page)
        if not self._so_tvs(itens, ids_modelo):
            return
        modelos = [self.modelo_do_item(i, ids_modelo) for i in itens or []]
        for _ in range(6):
            if "sacola está vazia" in _texto(page):
                return
            bt = page.get_by_role("button", name=re.compile(r"^excluir$", re.I)).first
            if not bt.count():
                bt = page.get_by_text(re.compile(r"^Excluir$", re.I)).first
            if not bt.count():
                return
            try:
                bt.click(timeout=8000)
            except Exception:
                return
            # o "Excluir" clicado é sempre o primeiro da sacola: o modelo é o do item na mesma posição
            self._tirou(modelos.pop(0) if modelos else None)
            page.wait_for_timeout(2500)
            # a confirmação é do diálogo que o "Excluir" abriu; fora dele sobra a página inteira
            conf = (self._dialogo(page) or page).get_by_role(
                "button", name=self._RE_CONFIRMA_EXCLUIR).first
            if conf.count() and conf.is_visible():
                try:
                    conf.click(timeout=5000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

    @staticmethod
    def _so_o_alvo(itens: Optional[list[dict]], alvo: str, vendedor_id: Optional[str] = None,
                   vendedor: Optional[str] = None, sem_vendedor_ok: bool = True) -> bool:
        """True só quando a sacola tem o anúncio pedido e mais nada, com 1 unidade, e do vendedor pedido.

        Vendedor: quando a sacola diz o vendedor do item, ele tem de ser o pedido; quando não diz, vale
        `sem_vendedor_ok` (quem chama sabe se já conferiu o vendedor na página do produto)."""
        if itens is None or [(i["id"], i.get("quantidade") or 1) for i in itens] != [(alvo, 1)]:
            return False
        if not (vendedor_id or vendedor):
            return True
        igual = mesmo_vendedor(itens[0].get("vendedor_id"), itens[0].get("vendedor"), vendedor_id, vendedor)
        return sem_vendedor_ok if igual is None else igual

    def garantir_item(self, page, url_produto: str, alvo: Optional[dict] = None) -> bool:
        """Deixa na sacola exatamente o anúncio pedido, do vendedor pedido, com 1 unidade (o anúncio fica sozinho
        para o cupom ser medido só nele: o cupom vale para o pedido inteiro).

        - sacola com outro produto (não uma das TVs): CarrinhoOcupado, não mexe em nada;
        - sacola com a TV do OUTRO modelo que o testador não sabe devolver depois (`alvo["restauraveis"]` não tem o
          modelo dela): CarrinhoOcupado, não mexe em nada;
        - antes de esvaziar, abre a página do anúncio e confere modelo e vendedor (o Magalu troca de vendedor sem
          avisar quando o pedido não vende o produto): se não for o pedido, pula o anúncio sem mexer;
        - só esvazia a sacola quando ela tem só as TVs; depois adiciona e confere id + vendedor.
        O Magalu engasga quando recebe muitas operações de sacola seguidas, então tentamos
        mais de uma vez, com pausa, antes de desistir do anúncio.
        """
        info = alvo or {}
        modelo = info.get("modelo") or MODELO_PADRAO
        ids_modelo = dict(info.get("ids_modelo") or {})
        restauraveis = set(info.get("restauraveis") or ()) | {modelo}
        alvo_id = self._id_anuncio(url_produto)
        ids_modelo.setdefault(alvo_id, modelo)
        vend_id = info.get("vendedor_id") or self._seller_da_url(url_produto)
        vend_nome = info.get("vendedor")
        confere = bool(vend_id or vend_nome)
        for tentativa in range(3):
            itens = self.itens_da_sacola(page)
            if itens is None:
                return False  # não deu para ler a sacola: não mexe em nada
            if self._so_o_alvo(itens, alvo_id, vend_id, vend_nome, sem_vendedor_ok=False):
                return True
            if itens and not self._so_tvs(itens, ids_modelo):
                raise CarrinhoOcupado("a sacola do Magalu tem produtos que não são a TV; não mexo nela")
            sem_volta = self._modelos_na_sacola(itens, ids_modelo) - restauraveis
            if sem_volta:
                raise CarrinhoOcupado(f"a sacola do Magalu tem a {', '.join(sorted(sem_volta))} e não conheço anúncio "
                                      "dela para devolver depois do teste; não mexo nela")
            if confere and self._so_o_alvo(itens, alvo_id) and \
                    mesmo_vendedor(itens[0].get("vendedor_id"), itens[0].get("vendedor"), vend_id, vend_nome) is None:
                # a sacola não disse o vendedor: confere pela página (sem mexer na sacola) e volta para a
                # sacola, que é onde os testes leem o total
                if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome, modelo):
                    return False
                return self._so_o_alvo(self.itens_da_sacola(page), alvo_id)
            if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome, modelo):
                return False
            if itens:
                self.esvaziar(page, ids_modelo)
                page.wait_for_timeout(2000)
                if self.itens_da_sacola(page) != []:
                    # não esvaziou (ou não deu para ler): pôr outra TV só somaria unidades
                    page.wait_for_timeout(4000 * (tentativa + 1))
                    continue
                if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome, modelo):
                    return False
            botao = page.get_by_role("button", name=re.compile(r"adicionar à sacola|adicionar a sacola", re.I)).first
            if botao.count():
                try:
                    botao.click(timeout=12000)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass
            depois = self.itens_da_sacola(page)
            if self._so_o_alvo(depois, alvo_id, vend_id, vend_nome, sem_vendedor_ok=True):
                return True
            if confere and self._so_o_alvo(depois, alvo_id):
                d = depois[0]
                print(f"[magalu] a sacola recebeu o anúncio {alvo_id} de outro vendedor ({d.get('vendedor') or d.get('vendedor_id')}), "
                      f"não {vend_nome or vend_id}; sem teste neste anúncio")
                return False
            page.wait_for_timeout(4000 * (tentativa + 1))  # deixa a loja respirar
        return False

    # --- passo final com os dois modelos (26/09): uma TV de cada modelo, 1 unidade cada ---

    def _pedido(self, alvo: dict) -> dict:
        url = alvo.get("url") or ""
        return {"chave": alvo.get("chave") or url, "id": self._id_anuncio(url), "url": url,
                "vend_id": alvo.get("vendedor_id") or self._seller_da_url(url), "vend_nome": alvo.get("vendedor"),
                "modelo": alvo.get("modelo") or MODELO_PADRAO}

    @staticmethod
    def _casa(item: dict, ped: dict, sem_vendedor_ok: bool) -> bool:
        """O item da sacola é o anúncio pedido, do vendedor pedido, com 1 unidade?"""
        if str(item.get("id")) != ped["id"] or (item.get("quantidade") or 1) != 1:
            return False
        if not (ped["vend_id"] or ped["vend_nome"]):
            return True
        igual = mesmo_vendedor(item.get("vendedor_id"), item.get("vendedor"), ped["vend_id"], ped["vend_nome"])
        return sem_vendedor_ok if igual is None else igual

    def _casados(self, itens: list[dict], pedidos: list[dict], sem_vendedor_ok: bool) -> tuple[dict, list[int]]:
        """({chave do pedido: posição do item na sacola}, posições dos itens que não são pedido nenhum)."""
        casados: dict = {}
        for ped in pedidos:
            k = next((k for k, it in enumerate(itens) if k not in casados.values()
                      and self._casa(it, ped, sem_vendedor_ok)), None)
            if k is not None:
                casados[ped["chave"]] = k
        return casados, [k for k in range(len(itens)) if k not in casados.values()]

    def _situacao_final(self, itens: list[dict], pedidos: list[dict], ids_modelo: dict) -> set:
        """Chaves dos pedidos que estão na sacola como devem (1 unidade, e a única linha do modelo); marca
        `tvs_a_mais` quando algum modelo ficou com mais de uma linha ou mais de 1 unidade."""
        casados, _ = self._casados(itens, pedidos, sem_vendedor_ok=True)
        linhas: dict = {}
        for it in itens:
            m = self.modelo_do_item(it, ids_modelo)
            linhas[m] = linhas.get(m, 0) + int(it.get("quantidade") or 1)
        if any(n > 1 for m, n in linhas.items() if m):
            self.tvs_a_mais = True
            print("[magalu] ⚠ a sacola ficou com mais de uma unidade de um dos modelos")
        return {ped["chave"] for ped in pedidos if ped["chave"] in casados and linhas.get(ped["modelo"]) == 1}

    def garantir_itens(self, page, alvos: list[dict]) -> set:
        """Deixa na sacola exatamente estes anúncios (um de cada modelo), 1 unidade cada.

        - sacola com produto que não é uma das TVs: CarrinhoOcupado;
        - item de um modelo que não está em `alvos` fica como está (nunca é tirado); se para trocar o anúncio de um
          modelo fosse preciso esvaziar a sacola (o Magalu não liga o "Excluir" ao item) e ela tem esse item, não mexe;
        - só falta pôr: abre a página de cada anúncio que falta (confere modelo e vendedor) e adiciona, sem tirar nada;
        - há item errado de um dos modelos: confere ANTES a página de TODOS os anúncios pedidos (uma que não confira
          e a sacola fica como está), esvazia (só TVs) e põe todos de novo.
        Devolve as chaves dos anúncios conferidos na sacola (cada um a única linha do seu modelo, 1 unidade)."""
        pedidos = [self._pedido(a) for a in alvos]
        ids_modelo: dict = {}
        for a in alvos:
            ids_modelo.update(a.get("ids_modelo") or {})
        for ped in pedidos:
            ids_modelo[ped["id"]] = ped["modelo"]
        modelos = {ped["modelo"] for ped in pedidos}
        if not pedidos or len(modelos) != len(pedidos):
            print("[magalu] o passo final pediu dois anúncios do mesmo modelo; não mexo na sacola")
            return set()
        for tentativa in range(3):
            itens = self.itens_da_sacola(page)
            if itens is None:
                return set()  # não deu para ler a sacola: não mexe em nada
            if itens and not self._so_tvs(itens, ids_modelo):
                raise CarrinhoOcupado("a sacola do Magalu tem produtos que não são a TV; não mexo nela")
            casados, sobras = self._casados(itens, pedidos, sem_vendedor_ok=False)
            for ped in pedidos:   # a sacola não disse o vendedor do item: confere pela página, sem mexer na sacola
                k = next((k for k in sobras if ped["chave"] not in casados and self._casa(itens[k], ped, True)), None)
                if k is not None and self._abrir_pagina_do_anuncio(page, ped["url"], ped["vend_id"], ped["vend_nome"],
                                                                   ped["modelo"]):
                    casados[ped["chave"]] = k
                    sobras.remove(k)
            manter = [k for k in sobras if self.modelo_do_item(itens[k], ids_modelo) not in modelos]
            trocar = [k for k in sobras if k not in manter]
            faltam = [ped for ped in pedidos if ped["chave"] not in casados]
            if not trocar and not faltam:
                return self._situacao_final(itens, pedidos, ids_modelo)
            if trocar:
                if manter:
                    print("[magalu] para trocar o anúncio eu teria de esvaziar a sacola, que tem também uma TV de outro "
                          "modelo que não é deste passo; não mexo")
                    return self._situacao_final(itens, pedidos, ids_modelo)
                if not all(self._abrir_pagina_do_anuncio(page, p["url"], p["vend_id"], p["vend_nome"], p["modelo"])
                           for p in pedidos):
                    return self._situacao_final(self.itens_da_sacola(page) or [], pedidos, ids_modelo)
                self.esvaziar(page, ids_modelo)
                page.wait_for_timeout(2000)
                if self.itens_da_sacola(page) != []:
                    page.wait_for_timeout(4000 * (tentativa + 1))   # não esvaziou: pôr mais TVs só somaria unidades
                    continue
                faltam = list(pedidos)
            for ped in faltam:
                if not self._abrir_pagina_do_anuncio(page, ped["url"], ped["vend_id"], ped["vend_nome"], ped["modelo"]):
                    continue
                botao = page.get_by_role("button", name=re.compile(r"adicionar à sacola|adicionar a sacola", re.I)).first
                if botao.count():
                    try:
                        botao.click(timeout=12000)
                        page.wait_for_timeout(4000)
                    except Exception:
                        pass
            depois = self.itens_da_sacola(page)
            if depois is None:
                return set()
            casados, sobras = self._casados(depois, pedidos, sem_vendedor_ok=True)
            if len(casados) == len(pedidos) and all(self.modelo_do_item(depois[k], ids_modelo) not in modelos
                                                    for k in sobras):
                return self._situacao_final(depois, pedidos, ids_modelo)
            page.wait_for_timeout(4000 * (tentativa + 1))  # deixa a loja respirar
        return self._situacao_final(self.itens_da_sacola(page) or [], pedidos, ids_modelo)

    def ler_totais(self, page) -> ResultadoCupom:
        """Lê o resumo da sacola por linhas, ancorado em 'Total:'.

        O Magalu muda a ordem dos rótulos de tempos em tempos (já vi "Produtos (1): / Frete:" e
        "Frete total / Produto (1 item)"), então casamos rótulo → próximo valor em R$.
        """
        t = _sem_cartao_da_loja(_texto(page))
        linhas = [l.strip() for l in t.splitlines()]
        r = ResultadoCupom(codigo="", aceito=False)

        i_total = next((k for k, l in enumerate(linhas) if re.fullmatch(r"Total:?", l)), None)
        if i_total is not None:
            def valor_apos(k: int) -> Optional[float]:
                for l in linhas[k + 1: k + 4]:
                    if not l:
                        continue
                    if re.search(r"gr[áa]tis", l, re.I):
                        return 0.0
                    v = parse_preco((re.search(r"-?\s*R\$\s?([\d.]+,\d{2})", l) or [None, None])[1])
                    if v is not None:
                        return v
                    return None
                return None

            for k in range(max(0, i_total - 16), i_total):
                rot = linhas[k]
                if re.fullmatch(r"Frete(\s+total)?:?", rot, re.I) and r.frete is None:
                    r.frete = valor_apos(k)
                elif re.match(r"Produtos?\b", rot, re.I) and r.produtos is None:
                    r.produtos = valor_apos(k)
                    mq = re.search(r"\((\d+)", rot)  # 'Produtos (2):' / 'Produto (1 item)'
                    if mq:
                        r.quantidade = max(1, int(mq.group(1)))
                elif re.search(r"(cupom|desconto)", rot, re.I) and r.desconto is None:
                    v = valor_apos(k)
                    if v:
                        r.desconto = v
            bloco = "\n".join(linhas[i_total: i_total + 8])
        else:
            bloco = t

        m = _RE_PIX.search(bloco) or _RE_PIX.search(t)
        r.total_pix = parse_preco(m.group(1)) if m else None
        m = _RE_CARTAO.search(bloco) or _RE_CARTAO.search(t)
        r.total_cartao = parse_preco(m.group(1)) if m else None
        m = _RE_PARCELA.search(bloco) or _RE_PARCELA.search(t)
        r.parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
        # fallbacks dos formatos antigos
        if r.produtos is None:
            m = _RE_PRODUTOS.search(t)
            r.produtos = parse_preco(m.group(1)) if m else None
        if r.frete is None:
            m = _RE_FRETE.search(t)
            r.frete = (0.0 if m and "gr" in m.group(1).lower() else parse_preco(m.group(1))) if m else None
        # coerência: total no cartão = produtos + frete - desconto
        if r.frete is None and r.produtos and r.total_cartao:
            dif = round(r.total_cartao - r.produtos, 2)
            r.frete = dif if 0 <= dif < r.produtos * 0.5 else None
        return r

    _SEL_CAMPO = "[data-testid=cupom-input]:visible, [role=dialog] input:visible, input[placeholder*=cupom i]:visible"

    def _abrir_campo(self, page):
        """Devolve o input do cupom, abrindo o diálogo se preciso.

        O botão troca de rótulo ('Inserir' quando não há cupom, 'Ver cupons' quando há um aplicado),
        e logo depois de remover um cupom a sacola recarrega. Por isso tentamos algumas vezes.
        """
        for tentativa in range(3):
            campo = page.locator(self._SEL_CAMPO).first
            if campo.count():
                return campo
            if self._pagina_de_login(page):
                raise PrecisaLogin("o Magalu pediu login ao abrir o campo de cupom")
            botao = page.locator("[data-testid=coupon-button]").first
            if not botao.count():
                botao = page.get_by_role("button", name=re.compile(r"^inserir$|ver cupons|cupom", re.I)).first
            if botao.count():
                try:
                    botao.click(timeout=8000)
                    page.wait_for_timeout(2500)
                    continue
                except Exception:
                    pass
            if tentativa < 2:  # recarrega a sacola e tenta de novo
                page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
                _espera(page)
        campo = page.locator(self._SEL_CAMPO).first
        return campo if campo.count() else None

    def _dialogo(self, page):
        # há vários [role=dialog] ocultos na página; só interessa o visível
        d = page.locator("[data-testid=dialog-container]:visible, [role=dialog]:visible").first
        return d if d.count() else None

    # botões que confirmam o cupom. "adicionar" SÓ vale dentro do diálogo do cupom: na sacola, o
    # "Adicionar à sacola" dos produtos recomendados também casa com ele, e clicar nele poria na sacola
    # da pessoa um produto que não é a TV.
    _RE_BOTAO_CUPOM = re.compile(r"^aplicar|^inserir|^adicionar|^ok$|^confirmar", re.I)
    _RE_BOTAO_CUPOM_FORA_DO_DIALOGO = re.compile(r"^aplicar|^inserir|^ok$|^confirmar", re.I)
    # bloco em volta do campo de cupom: o form/[data-testid] mais próximo dele
    _XPATH_AREA_DO_CUPOM = "xpath=ancestor::*[self::form or self::dialog or @data-testid][1]"

    def _area_do_cupom(self, page, campo):
        """(escopo, padrão) para achar o botão que confirma o cupom.

        O escopo é o diálogo visível ou, sem ele, o bloco em volta do campo — NUNCA a página inteira, que
        tem os produtos recomendados da sacola com "Adicionar à sacola". Sem recorte, devolve (None, …): aí
        o cupom vai por Enter, sem clicar em botão nenhum."""
        d = self._dialogo(page)
        if d is not None:
            return d, self._RE_BOTAO_CUPOM
        try:
            volta = campo.locator(self._XPATH_AREA_DO_CUPOM).first
            if volta.count():
                return volta, self._RE_BOTAO_CUPOM_FORA_DO_DIALOGO
        except Exception:  # noqa: BLE001 - recorte é só uma otimização; sem ele, Enter
            pass
        return None, self._RE_BOTAO_CUPOM_FORA_DO_DIALOGO

    def _fechar_dialogo(self, page) -> None:
        d = self._dialogo(page)
        if d is None:
            return
        x = page.locator("[data-testid=close-dialog]:visible, [role=dialog] [aria-label=Fechar]:visible").first
        try:
            if x.count():
                x.click(timeout=5000)
            else:
                page.keyboard.press("Escape")
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(700)

    def aplicar(self, page, codigo: str) -> ResultadoCupom:
        antes = self.ler_totais(page)
        campo = self._abrir_campo(page)
        if campo is None:
            return ResultadoCupom(codigo=codigo, aceito=False, mensagem="campo de cupom não encontrado",
                                  extra={"antes": antes.__dict__, "falha": True})
        campo.fill("")
        campo.fill(codigo)
        page.wait_for_timeout(500)
        escopo, padrao = self._area_do_cupom(page, campo)
        botao = escopo.get_by_role("button", name=padrao).first if escopo is not None else None
        try:
            if botao is not None and botao.count():
                botao.click(timeout=8000)
            else:
                campo.press("Enter")
        except Exception:
            campo.press("Enter")
        # espera a resposta: mensagem de recusa (no diálogo ou na página) ou diálogo fechado
        mensagem = ""
        for _ in range(12):
            page.wait_for_timeout(500)
            if self._pagina_de_login(page):
                raise PrecisaLogin("o Magalu pediu login ao aplicar o cupom")
            d = self._dialogo(page)
            alvo = d.inner_text() if d is not None else _texto(page)
            linha = next((l for l in alvo.splitlines() if _RE_REJEITADO.search(l)), None)
            if linha:
                mensagem = re.sub(r"\s+", " ", linha).strip()[:200]
                break
            if d is None:
                break
        page.wait_for_timeout(1500)
        depois = self.ler_totais(page)
        depois.codigo = codigo
        if not mensagem and (_sem_total(antes) or _sem_total(depois)):
            depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao, "falha": True}
            depois.aceito, depois.mensagem = False, "não consegui ler o total da sacola"
        else:
            # L2 (26/09): só o preço da TV medido antes e depois decide (linha de desconto sozinha não é aceite)
            medir_cupom(antes, depois, mensagem)
            if depois.status == "recusado" and not mensagem:
                t = _texto(page)
                i_res = t.find("Produtos (")
                depois.mensagem = ("sem mudança no total: " + re.sub(r"\s+", " ", t[i_res:i_res + 160]).strip()
                                   if i_res >= 0 else "sem mudança no total")
        self._fechar_dialogo(page)
        return depois

    def remover(self, page) -> None:
        """Tira o cupom aplicado para o próximo teste começar do preço cheio."""
        for _ in range(2):
            if "Cupom aplicado" not in _texto(page) and self._dialogo(page) is None:
                page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
                _espera(page)
                if "Cupom aplicado" not in _texto(page):
                    return
            self._abrir_campo(page)  # abre o diálogo ('Ver cupons')
            rem = page.locator("[data-testid=modalSheet-icon-remove]:visible, [aria-label='Remover cupom']:visible").first
            if rem.count():
                try:
                    rem.click(timeout=8000)
                    page.wait_for_timeout(2500)
                except Exception:
                    pass
            self._fechar_dialogo(page)
            page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            _espera(page)
            if "Cupom aplicado" not in _texto(page):
                return


# ----------------------------------------------------------------------------------------------
# Mercado Livre
# ----------------------------------------------------------------------------------------------

_RE_ML_ERRO = re.compile(
    r"confira se o cupom|n[ãa]o est[áa] mais dispon|cupom inv[áa]lido|n[ãa]o encontramos|"
    r"n[ãa]o p[oô]de ser aplicado|expirou|j[áa] foi usado|n[ãa]o se aplica", re.I)
_RE_ML_QTD = re.compile(r"Produtos?\s*\((\d+)\)", re.I)
_RE_ML_ID = re.compile(r"MLB-?(\d{6,})", re.I)
# opções de compra do catálogo no JSON da página: {"selected":true,"type":"BEST_PRICE","item_id":"MLB…",…}
_RE_ML_OFERTA = re.compile(r'"selected":(true|false),"type":"(BEST_[A-Z_]+)","item_id":"(MLB\d+)"')
_RE_ML_ALTERNATIVA = re.compile(r'"buying_option_id":"(BEST_[A-Z_]+)","item_id":"(MLB\d+)","price":([\d.]+)')
_RE_ML_GTM = re.compile(r'"itemId":"(MLB\d+)"[^{}]*?"localItemPrice":([\d.]+)')
_SEL_ML_MENOS = "[data-andes-input-stepper-control-type=decrement]"
_RE_ML_ITEM_URL = re.compile(r"(?:item_id(?:%3A|:)|[?&]wid=)(MLB\d{6,})", re.I)
_RE_ML_PRODUTO_URL = re.compile(r"produto\.mercadolivre\.com\.br/MLB-?(\d{6,})", re.I)
_RE_ML_CATALOGO_URL = re.compile(r"/p/(MLB\d+)", re.I)
# controle que tira a linha do carrinho, pelo texto OU pelo aria-label/title (G2, 22/09: no carrinho real o botão
# era só um ícone com aria-label "Remover produto", sem o texto "Excluir", e o robô desistia antes de clicar)
_RE_REMOVER = re.compile(r"^\s*(?:excluir|remover(?:\s+produto)?)\s*$", re.I)
_RE_EXCLUIR = _RE_REMOVER   # nome antigo, usado por scripts de leitura
# cada linha do carrinho (uma por seletor de quantidade): sobe do seletor até o bloco da linha, que é o
# primeiro que tem UM controle de tirar ("Excluir", "Remover produto", "Remover", por texto, aria-label ou title)
# ou, sem ele, o primeiro que tem link. Nunca sobe para um bloco que tenha outra linha, o "Resumo da compra" ou
# texto demais (recomendações com a própria TV poderiam fazer um produto qualquer parecer a TV). Marca o bloco com
# data-tv55-linha=<k> e o controle de tirar com data-tv55-excluir=<k>: o clique é nesse controle, DAQUELA linha.
# qtd: o número do campo do seletor de quantidade (None quando não dá para ler).
_ML_MAX_TEXTO_LINHA = 2000
_JS_ML_LINHAS = """() => {
  const sel = '[data-andes-input-stepper-control-type=decrement]';
  const rx = /^\\s*(?:excluir|remover(?:\\s+produto)?)\\s*$/i;
  const ehRemover = b => [b.innerText, b.getAttribute('aria-label'), b.getAttribute('title')]
                           .some(x => rx.test((x || '').trim()));
  const grande = el => el.querySelectorAll(sel).length > 1 || (el.innerText || '').length > %d
                       || /Resumo da compra/i.test(el.innerText || '');
  document.querySelectorAll('[data-tv55-linha]').forEach(e => e.removeAttribute('data-tv55-linha'));
  document.querySelectorAll('[data-tv55-excluir]').forEach(e => e.removeAttribute('data-tv55-excluir'));
  const campoQtd = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden])';
  return [...document.querySelectorAll(sel)].map((s, k) => {
    let caixa = s.parentElement, campo = null;
    for (let i = 0; i < 3 && caixa && !campo; i++, caixa = caixa.parentElement) {
      if (caixa.querySelectorAll(sel).length > 1) break;
      campo = caixa.querySelector(campoQtd);
    }
    const q = String((campo && (campo.value || campo.getAttribute('value'))) || '').match(/^\\s*(\\d+)\\s*$/);
    const qtd = q ? parseInt(q[1], 10) : null;
    let el = s.parentElement, linha = null, comLink = null, botao = null;
    for (let i = 0; i < 12 && el && el !== document.body; i++, el = el.parentElement) {
      if (grande(el)) break;
      if (!comLink && el.querySelector('a[href]')) comLink = el;
      const bs = [...el.querySelectorAll('button, a, [role=button]')].filter(ehRemover);
      if (bs.length === 1) { linha = el; botao = bs[0]; break; }
    }
    const bloco = linha || comLink;
    if (!bloco) return {links: [], texto: '', excluir: false, qtd: qtd};
    bloco.setAttribute('data-tv55-linha', String(k));
    if (botao) botao.setAttribute('data-tv55-excluir', String(k));
    return {links: [...bloco.querySelectorAll('a[href]')].map(a => a.href),
            texto: (bloco.innerText || '').slice(0, %d), excluir: !!botao, qtd: qtd};
  });
}""" % (_ML_MAX_TEXTO_LINHA, _ML_MAX_TEXTO_LINHA + 1)


# ----------------------------------------------------------------------------------------------
# resumo do carrinho do ML (L1, 26/09). O innerText põe o rótulo numa linha e o valor em pedaços nas seguintes
# ('-' / 'R$' / '235' / ',' / '01'). Com as duas TVs o resumo real ficou assim:
#   Resumo da compra | Produtos (2) | R$ 8.298 | Desconto de produtos | - R$ 235,01 | Frete | R$ 632 (riscado) |
#   R$ 203,99 | Inserir código do cupom | Desconto no Pix | - R$ 420,45 | Total | R$ 8.930 (riscado) | R$ 7.846,53 |
#   no Pix | Economize R$ 1.083,47 | Continuar (2)
# O valor riscado (preço antigo) vem ANTES do atual no mesmo rótulo: vale o ÚLTIMO. O total "no Pix" é o do Pix; o do
# cartão é produtos - descontos (menos o do Pix) + frete (e bate com Pix + desconto do Pix). Abaixo do resumo vêm as
# RECOMENDAÇÕES (racks, suportes, com preços): nunca são linha do carrinho nem preço.
# ----------------------------------------------------------------------------------------------

_RE_ML_FIM_DO_RESUMO = re.compile(
    r"^(?:continuar\b|recomenda[çc][õo]es|produtos que te interessaram|voc[êe] tamb[ée]m pode gostar|quem viu|"
    r"mais informa[çc][õo]es|inspirado)", re.I)
_RE_ML_RECOMENDACOES = re.compile(
    r"^(?:recomenda[çc][õo]es|produtos que te interessaram|voc[êe] tamb[ée]m pode gostar|quem viu|inspirado)", re.I)
_RE_ML_NUMERO = re.compile(r"(-)?\s*(?:R\$\s?)?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?")
_RE_ML_ROTULO_COM_VALOR = re.compile(r"^(.*?\S)\s*:?\s+((?:-\s*)?R\$\s?[\d.]+(?:,\d{2})?|gr[áa]tis)$", re.I)
_ML_MAX_LINHAS_RESUMO = 120


def _pedaco_de_valor(l: str) -> bool:
    """Linha que é só um pedaço de valor em R$ ('-', 'R$', '8.930', ',', '53', 'Grátis', '-R$ 100')."""
    return l in ("-", "R$", ",") or bool(re.fullmatch(r"gr[áa]tis", l, re.I) or _RE_ML_NUMERO.fullmatch(l))


def _valores_ml(linhas: list[str], k: int) -> tuple[list[float], int]:
    """Valores em R$ a partir da linha k, até a primeira linha que não é pedaço de valor: (valores na ordem da
    página, com sinal; índice da linha seguinte). 'Grátis' vale 0,0."""
    vals: list[float] = []
    sinal = 1
    j = k
    while j < len(linhas):
        l = linhas[j]
        if not l or l == "R$":
            j += 1
            continue
        if l == "-":
            sinal, j = -1, j + 1
            continue
        if re.fullmatch(r"gr[áa]tis", l, re.I):
            vals.append(0.0)
            sinal, j = 1, j + 1
            continue
        m = _RE_ML_NUMERO.fullmatch(l)
        if not m:
            break
        j += 1
        centavos = m.group(3)
        if centavos is None and j + 1 < len(linhas) and linhas[j] == "," and re.fullmatch(r"\d{2}", linhas[j + 1]):
            centavos, j = linhas[j + 1], j + 2
        v = int(m.group(2).replace(".", "")) + (int(centavos) / 100 if centavos else 0)
        vals.append(round(-v if (m.group(1) or sinal < 0) else v, 2))
        sinal = 1
    return vals, j


def _linhas_do_resumo_ml(linhas: list[str]) -> list[tuple[str, list[float]]]:
    """[(rótulo, valores)] na ordem da página. Rótulo sem valor ('Inserir código do cupom', 'no Pix') vem com []."""
    out: list[tuple[str, list[float]]] = []
    k = 0
    while k < len(linhas):
        l = linhas[k]
        if not l:
            k += 1
            continue
        if _pedaco_de_valor(l):
            vals, k = _valores_ml(linhas, k)      # valor sem rótulo: continua o rótulo anterior
            if out:
                out[-1][1].extend(vals)
            continue
        m = _RE_ML_ROTULO_COM_VALOR.match(l)
        rotulo, na_linha = (m.group(1), _valores_ml([m.group(2).strip()], 0)[0]) if m else (l, [])
        vals, j = _valores_ml(linhas, k + 1)
        out.append((rotulo.strip(), na_linha + vals))
        k = max(j, k + 1)
    return out


def ler_resumo_ml(texto: str) -> ResultadoCupom:
    """Resumo do carrinho do ML a partir do innerText da página (layout de 26/09 e o antigo, com 1 ou 2 TVs).

    Só lê do 'Resumo da compra' até o 'Continuar' (ou o começo das recomendações). Sem o 'Resumo da compra', lê o
    texto até as recomendações. `desconto` é só o de CUPOM (linha com 'cupom', menos 'Inserir código do cupom'); os
    descontos 'de produtos' e 'no Pix' vão em extra. Layout antigo ('Total' sem 'no Pix'): o total é o do cartão e
    total_pix é cópia dele (pix_real=False)."""
    linhas = [l.strip() for l in (texto or "").splitlines()]
    i_rec = next((k for k, l in enumerate(linhas) if _RE_ML_RECOMENDACOES.match(l)), len(linhas))
    i_resumo = next((k for k, l in enumerate(linhas) if l.lower().startswith("resumo da compra")), None)
    if i_resumo is not None:
        # do "Resumo da compra" até o "Continuar" ou o começo de um bloco de recomendações (esteja onde estiver)
        fim = next((k for k in range(i_resumo + 1, min(len(linhas), i_resumo + _ML_MAX_LINHAS_RESUMO))
                    if _RE_ML_FIM_DO_RESUMO.match(linhas[k])), min(len(linhas), i_resumo + _ML_MAX_LINHAS_RESUMO))
        fatia = linhas[i_resumo + 1: fim]
    else:
        fatia = linhas[:i_rec]
    r = ResultadoCupom(codigo="", aceito=False)
    frete = total = None
    riscados: dict = {}
    desc = {"pix": 0.0, "frete": 0.0, "cupom": 0.0, "produtos": 0.0, "outros": 0.0}
    tem_desc_pix = no_pix = False
    rows = _linhas_do_resumo_ml(fatia)
    for k, (rot, vals) in enumerate(rows):
        baixo = sem_acentos(rot).lower()
        ultimo = vals[-1] if vals else None
        m = _RE_ML_QTD.match(rot)
        if (m or re.fullmatch(r"produto", rot, re.I)) and r.produtos is None:
            r.quantidade = max(1, int(m.group(1))) if m else 1   # com 1 unidade o resumo pode dizer só 'Produto'
            r.produtos = abs(ultimo) if ultimo is not None else None
        elif re.fullmatch(r"frete:?(?: gratis)?", baixo) and frete is None:
            frete = abs(ultimo) if ultimo is not None else (0.0 if "gratis" in baixo else None)
            if len(vals) > 1:
                riscados["frete"] = abs(vals[0])
        elif re.fullmatch(r"total:?(?: no pix)?", baixo) and total is None:
            total = abs(ultimo) if ultimo is not None else None
            if len(vals) > 1:
                riscados["total"] = abs(vals[0])
            seguinte = sem_acentos(rows[k + 1][0] if k + 1 < len(rows) else "").lower()
            no_pix = "pix" in baixo or bool(re.match(r"(?:a vista\s+)?no pix\b", seguinte))
        elif vals and "inserir" not in baixo and ("desconto" in baixo or "cupom" in baixo or ultimo < 0):
            v = abs(ultimo)
            qual = next((q for q, chave in (("pix", "pix"), ("frete", "frete"), ("cupom", "cupom"),
                                            ("produtos", "produto")) if chave in baixo), "outros")
            desc[qual] += v
            tem_desc_pix = tem_desc_pix or qual == "pix"
    frete_efetivo = None if frete is None else round(max(0.0, frete - desc["frete"]), 2)
    r.frete = frete_efetivo
    r.desconto = round(desc["cupom"], 2) or None
    r.extra = {"desconto_produtos": round(desc["produtos"], 2), "desconto_pix": round(desc["pix"], 2),
               **({"outros_descontos": round(desc["outros"], 2)} if desc["outros"] else {}),
               **({"riscados": riscados} if riscados else {})}
    if no_pix or tem_desc_pix:
        # layout de 26/09: o Total (o último valor, o que não está riscado) é o do Pix; o do cartão sai das linhas
        # (e confere com Pix + desconto do Pix)
        pelas_linhas = None
        if r.produtos is not None:
            pelas_linhas = round(r.produtos - desc["produtos"] - desc["cupom"] - desc["outros"]
                                 + (frete_efetivo or 0), 2)
        pix_mais_desconto = round(total + desc["pix"], 2) if total is not None and tem_desc_pix else None
        cartao = pelas_linhas if pelas_linhas is not None else pix_mais_desconto
        if pelas_linhas is not None and pix_mais_desconto is not None and \
                abs(pelas_linhas - pix_mais_desconto) > TOLERANCIA_PRECO:
            # alguma linha do resumo não foi entendida: vale o que a loja mostra no fim (Pix + desconto do Pix)
            r.extra["cartao_pelas_linhas"] = pelas_linhas
            cartao = pix_mais_desconto
        r.total_pix = total
        r.total_cartao = cartao
        r.pix_real = True
    else:
        # layout antigo: o ML só mostrava o desconto do Pix no pagamento; este "Pix" é o total do CARTÃO
        r.total_cartao = total
        r.total_pix, r.pix_real = total, False
    # parcelado: só no resumo e nas linhas das TVs (o "em 10x de R$ 211,20 sem juros" de um rack recomendado não é)
    m = _RE_PARCELA.search("\n".join(fatia)) or _RE_PARCELA.search("\n".join(linhas[:min(i_rec, i_resumo or i_rec)]))
    r.parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
    return r


def item_ml_da_url(url: str) -> Optional[str]:
    """Item (anúncio) do ML que a URL abre: ?pdp_filters=item_id%3AMLB…, wid=MLB… ou produto.mercadolivre.com.br/MLB-…"""
    m = _RE_ML_ITEM_URL.search(url or "")
    if m:
        return m.group(1).upper()
    m = _RE_ML_PRODUTO_URL.search(url or "")
    return "MLB" + m.group(1) if m else None


def catalogo_ml_da_url(url: str) -> str:
    m = _RE_ML_CATALOGO_URL.search(url or "")
    return m.group(1).upper() if m else ""


def _poe_preco(oferta: dict, v: Optional[str]) -> None:
    try:
        preco = float(v) if v else 0.0
    except ValueError:
        return
    if preco > 0 and preco not in oferta["precos"]:
        oferta["precos"].append(preco)


def ids_ml(texto: str) -> list[str]:
    """Ids de anúncio do ML num texto ou URL ('MLB-123…' e 'MLB123…' viram 'MLB123…'), sem repetir."""
    ids: list[str] = []
    for m in _RE_ML_ID.finditer(texto or ""):
        i = "MLB" + m.group(1)
        if i not in ids:
            ids.append(i)
    return ids


class MercadoLivre(LojaCarrinho):
    """No ML o cupom é ativado na conta (página de cupons) e entra sozinho no carrinho.

    Por isso aqui "aplicar" significa: ativar o cupom disponível e reler o total do carrinho.
    O robô nunca avança para envio nem pagamento.
    """

    nome = "mercadolivre"
    loja_canonica = "Mercado Livre"
    url_login = "https://www.mercadolivre.com.br/login"
    url_carrinho = "https://www.mercadolivre.com.br/gz/cart"
    url_cupons = "https://www.mercadolivre.com.br/cupons"
    url_cupons_carrinho = "https://www.mercadolivre.com.br/cupons/cart?context=general&filters=detail"
    url_produto = config.URL_ML_CATALOGO
    dominio_url = "mercadolivre.com.br"
    max_anuncios = 3

    def logado(self, page) -> bool:
        t = _texto(page)[:2000]
        if "iniciar sessão" in t.lower() or "Crie sua conta" in t or "Digite seu e-mail" in t:
            return False
        return "/login" not in page.url

    # --- identidade do anúncio: o item MLB… (cada vendedor do catálogo é um item) ---
    def identidade(self, o: dict) -> dict:
        base = super().identidade(o)
        url = o.get("url") or ""
        catalogo = catalogo_ml_da_url(url)
        item = (base["item_id"] or item_ml_da_url(url) or "").upper() or None
        oid = str(o.get("id") or "").upper()
        if not item and re.fullmatch(r"MLB\d{6,}", oid) and oid != catalogo:
            item = oid  # contrato: o id da oferta do ML é o item, mesmo quando a URL é só a do catálogo
        base["item_id"] = item
        base["catalogo"] = catalogo
        if item:
            base["chave"] = item
        return base

    def eh_chave_antiga(self, sufixo: str, reg: dict, alvo: dict) -> bool:
        """Chave antiga '<fim da URL do catálogo>#<item conferido no carrinho>': é deste anúncio se o item
        bate. Anúncio sem item (catálogo, formato antigo da coleta): qualquer chave antiga do catálogo."""
        if super().eh_chave_antiga(sufixo, reg, alvo):
            return True
        item = alvo.get("item_id")
        if item:
            return sufixo.upper().endswith(f"#{item}")
        cat = alvo.get("catalogo")
        return bool(cat) and f"/p/{cat}".upper() in sufixo.upper()

    def tem_cupom_aplicado(self, page, base: "ResultadoCupom") -> bool:
        """Desconto no resumo E uma linha de cupom que não é o 'Inserir código do cupom'."""
        if not base.desconto:
            return False
        return any(re.search(r"cupom", l, re.I) and "inserir" not in l.lower() for l in _texto(page).splitlines())

    # --- qual anúncio do catálogo testar ---
    @staticmethod
    def ofertas_do_catalogo(html: str) -> list[dict]:
        """Opções de compra do catálogo ('Melhor preço', 'Parcelamento sem juros'…) lidas do JSON da página.

        Cada uma vira {"item_id", "tipo", "selecionada", "precos"}; em "precos" vão o preço mostrado e o
        original (em 18/09 o 'Melhor preço' era R$ 3.491,03, riscado R$ 3.599).
        """
        html = html or ""
        ofertas: dict[str, dict] = {}

        def oferta(item_id: str, tipo: str) -> dict:
            return ofertas.setdefault(item_id, {"item_id": item_id, "tipo": tipo, "selecionada": False, "precos": []})

        achados = list(_RE_ML_OFERTA.finditer(html))
        for k, m in enumerate(achados):
            o = oferta(m.group(3), m.group(2))
            o["selecionada"] = o["selecionada"] or m.group(1) == "true"
            fim = achados[k + 1].start() if k + 1 < len(achados) else m.end() + 4000
            mp = re.search(r'"price":\{"type":"price","value":([\d.]+)(?:,"original_value":([\d.]+))?',
                           html[m.end():fim])
            for v in (mp.groups() if mp else ()):
                _poe_preco(o, v)
        for m in _RE_ML_ALTERNATIVA.finditer(html):
            _poe_preco(oferta(m.group(2), m.group(1)), m.group(3))
        return list(ofertas.values())

    @classmethod
    def anuncio_melhor_preco(cls, html: str) -> Optional[dict]:
        """O anúncio 'Melhor preço' do catálogo, que é o preço de referência da coleta.

        Sem opções de compra na página (catálogo de um vendedor só), vale o anúncio da própria página.
        """
        html = html or ""
        ofertas = cls.ofertas_do_catalogo(html)
        alvo = next((o for o in ofertas if o["tipo"] == "BEST_PRICE"), None)
        if alvo is None:
            m = re.search(r'"multiple_offer_default_winner_item_id":"(MLB\d+)"', html)
            alvo = next((o for o in ofertas if (m and o["item_id"] == m.group(1)) or o["selecionada"]), None)
        gtm = _RE_ML_GTM.search(html)
        if alvo is None and not ofertas and gtm:
            alvo = {"item_id": gtm.group(1), "tipo": "UNICO", "selecionada": True, "precos": []}
        if alvo is not None and gtm and gtm.group(1) == alvo["item_id"]:
            _poe_preco(alvo, gtm.group(2))
        return alvo

    @staticmethod
    def _linha(l) -> dict:
        """Linha do carrinho como veio do JS ({links, texto, excluir, qtd}) ou no formato antigo (só links)."""
        if isinstance(l, dict):
            q = l.get("qtd")
            return {"links": [str(x) for x in (l.get("links") or [])], "texto": str(l.get("texto") or ""),
                    "excluir": bool(l.get("excluir")), "qtd": q if isinstance(q, int) and q > 0 else None}
        return {"links": [str(x) for x in (l or [])], "texto": "", "excluir": False, "qtd": None}

    @staticmethod
    def _modelo_do_catalogo(catalogo: str) -> Optional[str]:
        return next((m for m, c in CATALOGOS_ML.items() if c and c.upper() == (catalogo or "").upper()), None)

    @classmethod
    def classificar_linhas(cls, linhas: list, item_alvo: Optional[str], catalogo: str = "", ids_tv=(),
                           modelo: Optional[str] = None, ids_modelo: Optional[dict] = None) -> list[dict]:
        """Para cada linha: ids de item nos links, se é uma das TVs (e de qual modelo) e se é o anúncio alvo.

        O modelo da linha sai, nesta ordem, do item no link (anúncio conhecido: `ids_modelo`, ou `ids_tv`/o próprio
        alvo, que são do modelo do alvo), do link de um catálogo conhecido (55C6K ou 65C6K) ou do texto da linha
        (título da TV com o tamanho). Sem nada disso NÃO é a TV (na dúvida, o carrinho é tratado como "tem outro
        produto" e ninguém mexe nele). Bloco grande demais (vários preços, texto longo, vários itens) não é uma linha
        só: também NÃO é a TV. Serviço com o nome da TV (garantia estendida, seguro, instalação) NÃO é a TV, mesmo com
        o link do anúncio dela."""
        modelo_alvo = modelo or cls._modelo_do_catalogo(catalogo) or MODELO_PADRAO
        catalogos = {c.upper(): m for m, c in CATALOGOS_ML.items() if c}
        catalogos.setdefault(catalogo_ml_da_url(config.URL_ML_CATALOGO), MODELO_PADRAO)
        if catalogo:
            catalogos.setdefault(catalogo.upper(), modelo_alvo)
        conhecidos = {str(k).upper(): v for k, v in (ids_modelo or {}).items()}
        for i in [*ids_tv, item_alvo]:
            if i:
                conhecidos.setdefault(str(i).upper(), modelo_alvo)
        out = []
        for l in map(cls._linha, linhas):
            juntos = " ".join(l["links"])
            ids = set(ids_ml(juntos)) - set(catalogos)
            cats = {m for c, m in catalogos.items() if f"/P/{c}" in juntos.upper()}
            poluido = len(l["texto"]) > _ML_MAX_TEXTO_LINHA or l["texto"].count("R$") > 8 or len(ids) > 3
            mod = None
            if not poluido and not eh_servico(l["texto"]):
                por_id = {conhecidos[i] for i in ids if i in conhecidos}
                if por_id:
                    mod = por_id.pop() if len(por_id) == 1 else None
                elif cats:
                    mod = cats.pop() if len(cats) == 1 else None
                else:
                    mod = modelo_da_linha(l["texto"])
            out.append({**l, "ids": ids, "tv": mod is not None, "modelo": mod,
                        "alvo": bool(item_alvo) and item_alvo in ids})
        return out

    @classmethod
    def situacao_do_carrinho(cls, linhas: list, totais: ResultadoCupom, texto: str, alvo: dict,
                             ofertas: list[dict], catalogo: str = "", ids_tv=(), modelo: Optional[str] = None,
                             ids_modelo: Optional[dict] = None) -> str:
        """Confere o carrinho contra o anúncio alvo.

        'ok'      só o anúncio alvo (a quantidade é ajustada depois);
        'vazio'   carrinho vazio;
        'trocar'  só TVs (55C6K/65C6K), mas não só o alvo: pode trocar pelo alvo (a linha do OUTRO modelo só sai se
                  o testador souber devolvê-la: garantir_item confere);
        'outro'   tem produto que não é uma das TVs (ou uma linha que não dá para conferir): não mexe em nada;
        '?'       não deu para conferir qual anúncio é.
        `linhas`: uma por seletor de quantidade. Quando a linha não traz o id do anúncio, conferimos pelo
        preço de uma unidade contra os preços das opções do catálogo: o 'Parcelamento sem juros'
        (R$ 3.749) não passa por 'Melhor preço' (R$ 3.599).
        """
        tem_tv = bool(re.search(r"[56]5C6K", (texto or "").upper().replace(" ", "")))
        vazio = re.search(r"carrinho est[áa] vazio", texto or "", re.I)
        if not linhas and totais.produtos is None and totais.total_cartao is None and (vazio or not tem_tv):
            return "vazio"
        ids_tv = set(ids_tv) | {o["item_id"] for o in ofertas}
        cl = cls.classificar_linhas(linhas, alvo["item_id"], catalogo, ids_tv, modelo, ids_modelo)
        if any(not c["tv"] for c in cl):
            return "outro"  # produto que não é a TV: não mexemos no carrinho da pessoa
        if len(cl) > 1:
            return "trocar"  # só TVs, mas mais de um anúncio
        outras = [o for o in ofertas if o["item_id"] != alvo["item_id"]]
        if cl:
            ids = cl[0]["ids"]
            if cl[0]["modelo"] != (modelo or cl[0]["modelo"]):
                return "trocar"  # a TV do outro modelo
            if ids and alvo["item_id"] not in ids:
                return "trocar"
            if ids and not ids & {o["item_id"] for o in outras}:
                return "ok"
        if totais.produtos is None:
            return "?"
        unidade = totais.produtos / max(1, totais.quantidade)

        def bate(o: dict) -> bool:
            return any(abs(unidade - p) <= max(1.0, p * 0.005) for p in o["precos"])

        if any(bate(o) for o in outras):
            # outro anúncio da TV; sem a linha lida não há onde clicar para tirar: não mexe
            return "trocar" if cl else "outro"
        return "ok" if bate(alvo) else "?"

    def _ler_carrinho(self, page) -> tuple[list[dict], ResultadoCupom, str]:
        try:
            linhas = page.evaluate(_JS_ML_LINHAS) or []
        except Exception:
            linhas = []
        return [self._linha(l) for l in linhas], self.ler_totais(page), _texto(page)

    @staticmethod
    def _titulo_da_pagina(html: str) -> Optional[str]:
        m = re.search(r'<h1[^>]*class="[^"]*ui-pdp-title[^"]*"[^>]*>(.*?)</h1>', html or "", re.S | re.I) or \
            re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html or "", re.I)
        return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else None

    @staticmethod
    def _titulo_do_modelo(titulo: str, modelo: Optional[str]) -> bool:
        m = modelo or MODELO_PADRAO
        return eh_55c6k(titulo) if m == MODELO_PADRAO else eh_do_modelo(titulo, m)

    def _abrir_anuncio(self, page, url_produto: str, alvo: dict, catalogo: str) -> str:
        """Abre a página do anúncio alvo (o catálogo já com ele selecionado) e devolve o HTML."""
        url = url_produto
        if catalogo:
            url = url_produto.split("#")[0].split("?")[0] + f"?pdp_filters=item_id%3A{alvo['item_id']}"
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        return page.content()

    def _pagina_nao_confere(self, html: str, alvo: dict, modelo: Optional[str], estrito: bool) -> Optional[str]:
        """Motivo para NÃO pôr o anúncio a partir desta página, ou None. `estrito` (pré-checagem, G1): o título tem de
        ser legível e a página tem de dizer qual anúncio selecionou."""
        titulo = self._titulo_da_pagina(html)
        if not titulo and estrito:
            return "a página não mostrou um título legível"
        if titulo and not self._titulo_do_modelo(titulo, modelo):
            return f"a página de {alvo['item_id']} não é a TV {modelo or MODELO_PADRAO} ({titulo[:60]})"
        selecionada = next((o["item_id"] for o in self.ofertas_do_catalogo(html) if o["selecionada"]), None)
        if selecionada is None:
            gtm = _RE_ML_GTM.search(html or "")
            selecionada = gtm.group(1) if gtm else None
        if selecionada is None and estrito:
            return "não consegui ver qual anúncio a página selecionou"
        if selecionada is not None and selecionada != alvo["item_id"]:
            return f"a página selecionou {selecionada}, não o anúncio {alvo['item_id']}"
        return None

    @staticmethod
    def _botao_adicionar(page):
        botao = page.get_by_role("button", name=re.compile(r"adicionar ao carrinho", re.I)).first
        if not botao.count():
            botao = page.locator("a:has-text('Adicionar ao carrinho'), button:has-text('Adicionar ao carrinho')").first
        return botao if botao.count() else None

    def _pre_checagem(self, page, url_produto: str, alvo: dict, catalogo: str, modelo: Optional[str]) -> bool:
        """G1 (22/09): ANTES de tirar qualquer linha do carrinho, a página do anúncio novo tem de ser a TV do modelo,
        selecionar o item pedido e ter o botão de pôr no carrinho (sem clicar). Senão, nada sai do carrinho."""
        html = self._abrir_anuncio(page, url_produto, alvo, catalogo)
        motivo = self._pagina_nao_confere(html, alvo, modelo, estrito=True)
        if motivo is None and self._botao_adicionar(page) is None:
            motivo = "a página não tem o botão 'Adicionar ao carrinho'"
        if motivo:
            print(f"[mercadolivre] pré-checagem do anúncio {alvo['item_id']}: {motivo}; não tiro nada do carrinho")
            return False
        return True

    def _adicionar(self, page, url_produto: str, alvo: dict, catalogo: str, modelo: Optional[str] = None) -> bool:
        """Põe no carrinho o anúncio alvo (abre o catálogo já com ele selecionado)."""
        html = self._abrir_anuncio(page, url_produto, alvo, catalogo)
        motivo = self._pagina_nao_confere(html, alvo, modelo, estrito=False)
        if motivo:
            print(f"[mercadolivre] {motivo}; não adiciono")
            return False
        botao = self._botao_adicionar(page)
        if botao is None:
            return False
        botao.click(timeout=10000)
        page.wait_for_timeout(4000)
        return True

    def _excluir_linha(self, page, k: int) -> bool:
        """Clica no controle de tirar DA linha k (marcado por _JS_ML_LINHAS com data-tv55-excluir, achado pelo texto ou
        pelo aria-label/title) e confirma, se o ML perguntar. Só é chamada para linhas das TVs."""
        bt = page.locator(f"[data-tv55-excluir='{k}']").first
        if not bt.count():
            return False
        try:
            bt.click(timeout=8000)
            page.wait_for_timeout(2000)
            conf = page.locator("[role=dialog] button, .andes-modal button").filter(has_text=_RE_REMOVER).first
            if conf.count() and conf.is_visible():
                conf.click(timeout=5000)
                page.wait_for_timeout(2000)
        except Exception:
            return False
        return True

    def _classificar(self, page, ctx: dict) -> tuple[list[dict], ResultadoCupom]:
        """Relê o carrinho (página atual) e classifica as linhas contra o anúncio alvo de `ctx`."""
        linhas, totais, _ = self._ler_carrinho(page)
        conhecidos = set(ctx.get("ids_tv") or ()) | {o["item_id"] for o in ctx.get("ofertas") or ()}
        return self.classificar_linhas(linhas, (ctx.get("alvo") or {}).get("item_id"), ctx.get("catalogo") or "",
                                       conhecidos, ctx.get("modelo"), ctx.get("ids_modelo")), totais

    def _voltar_ao_carrinho(self, page) -> None:
        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)

    def _tirar_linha(self, page, ids: set, ctx: dict) -> bool:
        """Tira UMA linha das TVs (a que tem estes itens no link): relê o carrinho antes de clicar, clica no controle
        de tirar daquela linha e relê de novo para CONFERIR que ela sumiu (G3). Conta em `remocoes`/`removidos`."""
        cl, _ = self._classificar(page, ctx)
        ks = [k for k, c in enumerate(cl) if c["ids"] and c["ids"] == ids]
        if len(ks) != 1 or not cl[ks[0]]["tv"] or not cl[ks[0]]["excluir"]:
            return False
        c = cl[ks[0]]
        if not self._excluir_linha(page, ks[0]):
            return False
        self._voltar_ao_carrinho(page)
        depois, _ = self._classificar(page, ctx)
        if len(depois) != len(cl) - 1 or any(d["ids"] & ids for d in depois):
            print(f"[mercadolivre] a linha {', '.join(sorted(ids))} não saiu do carrinho depois do clique")
            return False
        self._tirou(c["modelo"])
        return True

    def _confere_duplicadas(self, page, ctx: dict) -> None:
        """Depois de uma troca que parou no meio: se o carrinho ficou (ou já estava) com duas linhas do mesmo modelo,
        a pessoa precisa saber (tvs_a_mais). O robô não põe nada nessa situação."""
        try:
            cl, _ = self._classificar(page, ctx)
        except Exception:  # noqa: BLE001 - só uma conferência para o aviso
            return
        modelos = [c["modelo"] for c in cl if c["tv"]]
        if any(modelos.count(m) > 1 for m in set(modelos)):
            self.tvs_a_mais = True
            print("[mercadolivre] ⚠ o carrinho tem duas linhas do mesmo modelo e não consegui tirar uma")

    def _trocar_pelo_alvo(self, page, url_produto: str, alvo: dict, ofertas: list[dict], catalogo: str,
                          ctx: dict) -> bool:
        """Troca a(s) TV(s) do carrinho pelo anúncio alvo: TIRA PRIMEIRO e PÕE DEPOIS (G1, 22/09), para nunca ficar
        com duas TVs do mesmo modelo.

        1) cada linha tem de ser identificável pelo anúncio (item MLB… no link) e ter o seu controle de tirar
           (texto "Excluir", ou aria-label/title "Remover produto"/"Remover"); senão não mexe em nada;
        2) PRÉ-CHECAGEM do anúncio novo antes de tirar qualquer coisa: a página é a TV do modelo, selecionou o item
           pedido e tem o botão de pôr no carrinho;
        3) tira as outras linhas uma a uma, relendo o carrinho e conferindo que cada uma sumiu; uma que não sai para a
           troca ali, SEM pôr o anúncio novo (o passo final devolve o que faltar e, como houve remoção, avisa);
        4) põe o anúncio novo (a página é conferida de novo antes do clique).
        A quantidade (1 unidade) é ajustada depois, em garantir_item."""
        cl, _ = self._classificar(page, ctx)
        tirar = [c for c in cl if not c["alvo"]]
        if not cl or any(not c["tv"] for c in cl) or any(not c["ids"] or not c["excluir"] for c in tirar):
            print("[mercadolivre] não consigo identificar cada linha do carrinho pelo anúncio (ou achar o botão de "
                  "tirar dela); não troco: o carrinho fica como está")
            return False
        ja_esta = any(c["alvo"] for c in cl)
        if not ja_esta:
            if not self._pre_checagem(page, url_produto, alvo, catalogo, ctx.get("modelo")):
                return False
            self._voltar_ao_carrinho(page)
        for c in tirar:
            if not self._tirar_linha(page, c["ids"], ctx):
                print(f"[mercadolivre] não consegui tirar a linha {', '.join(sorted(c['ids']))}; paro a troca sem pôr "
                      f"o anúncio {alvo['item_id']} (nunca duas TVs do mesmo modelo)")
                self._confere_duplicadas(page, ctx)
                return False
        if not ja_esta:
            if not self._adicionar(page, url_produto, alvo, catalogo, ctx.get("modelo")):
                print(f"[mercadolivre] o anúncio {alvo['item_id']} não entrou depois de eu tirar a TV antiga")
                return False
            self._voltar_ao_carrinho(page)
        return True

    def _anota_opcoes(self, html: str, url_produto: str, modelo: Optional[str] = None) -> None:
        """F5 (22/09): guarda as opções de compra do catálogo que a página LOGADA mostra.

        O coletor (perfil sem login) vê só 1 das 2 opções do catálogo ("2 opções; 1 visível sem login"). A
        página que o testador abre está logada e traz as duas: item, preço, vendedor e parcelado de cada uma
        vão para `opcoes_vistas` (com o modelo), e o testador as oferece como anúncios nas próximas rodadas. As mesmas
        travas da coleta: só o catálogo conhecido do modelo; a página tem de mostrar um título LEGÍVEL da TV do modelo,
        com o tamanho (G4: sem título, nada é anotado); opção com título de outro produto sai; preço impossível para
        esta TV sai (piso e teto de _preco_plausivel)."""
        from .sources.playwright_sources import (_ml_alternativas, _ml_opcoes_buybox, _ml_url_item_do_catalogo,
                                                  _ml_vendedor, _preco_plausivel, _titulo_de_outro_produto)

        catalogo = catalogo_ml_da_url(url_produto)
        modelo = modelo or self._modelo_do_catalogo(catalogo)
        if not modelo or not catalogo or (CATALOGOS_ML.get(modelo) or "").upper() != catalogo:
            return
        titulo = self._titulo_da_pagina(html)
        if not titulo or not eh_do_modelo(titulo, modelo):
            print(f"[mercadolivre] a página do catálogo não mostrou um título legível da TV {modelo} "
                  f"({(titulo or 'sem título')[:60]}); não anoto as opções")
            return

        def outro_produto(t: Optional[str]) -> bool:
            if modelo == MODELO_PADRAO:
                return _titulo_de_outro_produto(t)
            t = (t or "").strip()   # mesma regra da coleta, com o filtro da 65C6K
            return bool(t) and not eh_65c6k(t) and bool(
                len(t.split()) >= 4 or re.search(r"\b(tv|televis|polegada|monitor|smart)\b", t, re.I))

        opcoes = _ml_opcoes_buybox(html)
        ja = {o["item_id"] for o in opcoes}
        opcoes += [o for o in _ml_alternativas(html, [], catalogo) if o["item_id"] not in ja]
        refs = [o["preco"] for o in opcoes if o.get("preco")]
        vend = _ml_vendedor(html)
        novas: dict[str, dict] = {}
        for op in opcoes:
            item = str(op.get("item_id") or "").upper()
            if not re.fullmatch(r"MLB\d{6,}", item) or item == catalogo:
                continue
            if outro_produto(op.get("titulo")) or not _preco_plausivel(op.get("preco"), refs):
                print(f"[mercadolivre] opção {item} do catálogo ({fmt_preco(op.get('preco'))}) descartada: título de "
                      "outro produto ou preço impossível para esta TV")
                continue
            pix, cartao = None, op["preco"]
            if op.get("desconto") and op.get("preco_de") and op["preco_de"] > op["preco"] + 0.005:
                pix, cartao = op["preco"], op["preco_de"]   # "R$ 3.491,03 · 3% OFF · ou R$ 3.599": Pix e cartão
            vendedor = op.get("vendedor") or (vend.get("vendedor") if vend.get("item_id") == item else None)
            novas[item] = {"item_id": item, "preco": cartao, "preco_pix": pix, "vendedor": vendedor,
                           "parcelado": op.get("parcelado"), "tipo": op.get("tipo"), "titulo": titulo,
                           "url": _ml_url_item_do_catalogo(url_produto, item), "catalogo": catalogo, "modelo": modelo}
        if novas:
            self.opcoes_vistas = {**self.opcoes_vistas, **novas}

    def garantir_item(self, page, url_produto: str, alvo: Optional[dict] = None) -> bool:
        """Deixa no carrinho 1 unidade do anúncio pedido, e só ele (o cupom vale para o pedido inteiro).

        O anúncio é o item MLB… de `alvo["item_id"]` ou da URL (?pdp_filters=item_id%3AMLB… /
        produto.mercadolivre.com.br/MLB-…); sem item (formato antigo), vale o 'Melhor preço' do catálogo.
        - carrinho vazio: adiciona o anúncio;
        - só as TVs (55C6K/65C6K): pré-checa o anúncio novo, TIRA as outras linhas (conferindo cada uma) e só depois
          PÕE o pedido (_trocar_pelo_alvo, G1); a linha do OUTRO modelo só sai se o testador conhece um anúncio dele
          para devolver no fim (`alvo["restauraveis"]`), senão CarrinhoOcupado;
        - qualquer outro produto (ou linha que não dá para conferir): CarrinhoOcupado, não mexe em nada.
        Anota as opções de compra do catálogo que a página logada mostra (F5, _anota_opcoes).
        """
        self.item_alvo = None
        info = alvo or {}
        catalogo = catalogo_ml_da_url(url_produto)
        modelo = info.get("modelo") or self._modelo_do_catalogo(catalogo) or MODELO_PADRAO
        restauraveis = set(info.get("restauraveis") or ()) | {modelo}
        ids_modelo = dict(info.get("ids_modelo") or {})
        pedido = (info.get("item_id") or item_ml_da_url(url_produto) or "").upper() or None
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        html = page.content()
        try:
            self._anota_opcoes(html, url_produto, modelo)
        except Exception as e:  # noqa: BLE001 - anotar opções é extra: nunca atrapalha o carrinho
            print(f"[mercadolivre] não anotei as opções do catálogo: {type(e).__name__}: {str(e)[:100]}")
        ofertas = self.ofertas_do_catalogo(html)
        if pedido:
            achada = next((o for o in ofertas if o["item_id"] == pedido), None)
            oferta = {**achada, "precos": list(achada["precos"])} if achada else \
                {"item_id": pedido, "tipo": "ANUNCIO", "selecionada": False, "precos": []}
            gtm = _RE_ML_GTM.search(html or "")
            if gtm and gtm.group(1) == pedido:
                _poe_preco(oferta, gtm.group(2))
            if info.get("preco_cartao"):
                _poe_preco(oferta, str(info["preco_cartao"]))
        else:
            oferta = self.anuncio_melhor_preco(html)
            if oferta is None:
                print("[mercadolivre] não achei o anúncio 'Melhor preço' na página do catálogo; não testo")
                return False
        ids_modelo.setdefault(oferta["item_id"], modelo)
        ids_tv = set(info.get("ids_tv") or ())
        ctx = {"alvo": oferta, "ofertas": ofertas, "catalogo": catalogo, "ids_tv": ids_tv, "modelo": modelo,
               "ids_modelo": ids_modelo}

        def situacao() -> str:
            linhas, totais, texto = self._ler_carrinho(page)
            return self.situacao_do_carrinho(linhas, totais, texto, oferta, ofertas, catalogo, ids_tv, modelo,
                                             ids_modelo)

        self._voltar_ao_carrinho(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login ao abrir o carrinho")
        sit = situacao()
        if sit == "outro":
            raise CarrinhoOcupado("o carrinho do Mercado Livre tem produto que não é a TV (ou um item que não "
                                  "consigo conferir); não mexo nele. Tire-o à mão para o teste voltar")
        if sit == "trocar":
            cl, _ = self._classificar(page, ctx)
            sem_volta = {c["modelo"] for c in cl if c["tv"]} - restauraveis
            if sem_volta:
                raise CarrinhoOcupado(f"o carrinho do Mercado Livre tem a {', '.join(sorted(sem_volta))} e não conheço "
                                      "anúncio dela para devolver depois do teste; não mexo nele")
            if not self._trocar_pelo_alvo(page, url_produto, oferta, ofertas, catalogo, ctx):
                print(f"[mercadolivre] não consegui trocar a TV do carrinho pelo anúncio {oferta['item_id']}; "
                      "sem teste neste anúncio")
                return False
            sit = situacao()
        elif sit == "vazio":
            if not self._adicionar(page, url_produto, oferta, catalogo, modelo):
                return False
            self._voltar_ao_carrinho(page)
            sit = situacao()
        if sit != "ok":
            precos = " / ".join(fmt_preco(p) for p in oferta["precos"])
            print(f"[mercadolivre] o carrinho não ficou só com o anúncio {oferta['item_id']} ({precos}): "
                  "não consegui conferir o anúncio. Sem teste neste anúncio.")
            return False
        if not self.ajustar_quantidade(page, 1):
            print("[mercadolivre] não consegui deixar 1 unidade da TV no carrinho; sem teste neste anúncio")
            return False
        self.item_alvo = oferta["item_id"]
        return True

    # --- passo final com os dois modelos (26/09): uma TV de cada modelo, 1 unidade cada ---

    def _uma_unidade_por_linha(self, page, ctx: dict) -> bool:
        """Com mais de uma linha, o 'menos' certo é o de DENTRO da linha que tem unidade a mais (a quantidade lida
        no campo do seletor dela). Sem saber qual é, não clica em nada."""
        for _ in range(6):
            cl, totais = self._classificar(page, ctx)
            if totais.produtos is not None and totais.quantidade <= len(cl):
                return True
            k = next((k for k, c in enumerate(cl) if (c.get("qtd") or 0) > 1 and c["tv"]), None)
            if k is None:
                return False
            menos = page.locator(f"[data-tv55-linha='{k}'] {_SEL_ML_MENOS}")
            if menos.count() != 1:
                return False
            try:
                menos.first.click(timeout=8000)
            except Exception:
                return False
            page.wait_for_timeout(2500)
        return False

    def garantir_itens(self, page, alvos: list[dict]) -> set:
        """Deixa no carrinho exatamente estes anúncios (um de cada modelo), 1 unidade cada, pela mesma ordem da troca
        (G1): pré-checa cada anúncio que falta, TIRA as linhas erradas de cada modelo (conferindo que sumiram) e só
        então PÕE o que falta. Um modelo cuja pré-checagem falha, ou cuja linha errada não dá para tirar, fica como
        está (nunca duas linhas do mesmo modelo). Linha de modelo que não está em `alvos` não é tocada; produto que
        não é uma das TVs: CarrinhoOcupado. Devolve as chaves conferidas (única linha do modelo, 1 unidade)."""
        self.item_alvo = None
        ids_modelo: dict = {}
        for a in alvos:
            ids_modelo.update({str(k).upper(): v for k, v in (a.get("ids_modelo") or {}).items()})
        pedidos = []
        for a in alvos:
            url = a.get("url") or ""
            item = (a.get("item_id") or item_ml_da_url(url) or "").upper()
            cat = a.get("catalogo") or catalogo_ml_da_url(url)
            modelo = a.get("modelo") or self._modelo_do_catalogo(cat) or MODELO_PADRAO
            if not item:
                print(f"[mercadolivre] anúncio da {modelo} sem o item MLB…; não entra no passo final")
                continue
            pedidos.append({"chave": a.get("chave") or item, "item_id": item, "url": url, "catalogo": cat,
                            "modelo": modelo})
            ids_modelo[item] = modelo
        if not pedidos or len({p["modelo"] for p in pedidos}) != len(pedidos):
            return set()
        ctx = {"alvo": {"item_id": None}, "ofertas": [], "catalogo": "", "ids_tv": set(), "modelo": None,
               "ids_modelo": ids_modelo}
        self._voltar_ao_carrinho(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login ao abrir o carrinho")
        cl, _ = self._classificar(page, ctx)
        if any(not c["tv"] for c in cl):
            raise CarrinhoOcupado("o carrinho do Mercado Livre tem produto que não é a TV (ou um item que não "
                                  "consigo conferir); não mexo nele. Tire-o à mão para o teste voltar")
        plano = {}
        for p in pedidos:
            do_modelo = [c for c in cl if c["modelo"] == p["modelo"]]
            presente = any(p["item_id"] in c["ids"] for c in do_modelo)
            tirar = [c for c in do_modelo if p["item_id"] not in c["ids"]]
            if any(not c["ids"] or not c["excluir"] for c in tirar):
                print(f"[mercadolivre] não consigo identificar a linha da {p['modelo']} pelo anúncio (ou achar o botão "
                      "de tirar dela); essa TV fica como está")
                continue
            if not presente and not self._pre_checagem(page, p["url"], p, p["catalogo"], p["modelo"]):
                continue
            plano[p["modelo"]] = (p, presente, tirar)
        self._voltar_ao_carrinho(page)
        for m, (p, presente, tirar) in list(plano.items()):
            for c in tirar:
                if not self._tirar_linha(page, c["ids"], ctx):
                    print(f"[mercadolivre] não consegui tirar a linha {', '.join(sorted(c['ids']))} da {m}; não ponho "
                          f"o anúncio {p['item_id']} (nunca duas TVs do mesmo modelo)")
                    del plano[m]
                    break
        for m, (p, presente, tirar) in plano.items():
            if not presente:
                if not self._adicionar(page, p["url"], p, p["catalogo"], m):
                    print(f"[mercadolivre] o anúncio {p['item_id']} da {m} não entrou")
                self._voltar_ao_carrinho(page)
        self._uma_unidade_por_linha(page, ctx)
        cl, totais = self._classificar(page, ctx)
        por_modelo: dict = {}
        for c in cl:
            por_modelo.setdefault(c["modelo"], []).append(c)
        uma_cada = totais.produtos is not None and totais.quantidade == len(cl)
        if any(len(v) > 1 for v in por_modelo.values()) or (totais.produtos is not None and totais.quantidade > len(cl)):
            self.tvs_a_mais = True
            print("[mercadolivre] ⚠ o carrinho ficou com mais de uma TV (ou unidade) do mesmo modelo")
        conferidos = {p["chave"] for p in pedidos
                      if len(por_modelo.get(p["modelo"], [])) == 1 and p["item_id"] in por_modelo[p["modelo"]][0]["ids"]
                      and (uma_cada or por_modelo[p["modelo"]][0].get("qtd") == 1)}
        if len(conferidos) == 1 and len(cl) == 1:
            self.item_alvo = next(p["item_id"] for p in pedidos if p["chave"] in conferidos)
        return conferidos

    def ler_totais(self, page) -> ResultadoCupom:
        """O resumo do ML põe rótulo e valor em linhas separadas ('Produtos (2)' / 'R$' / '8.338'): ver ler_resumo_ml
        (26/09: a janela fixa de 24 linhas depois de 'Resumo da compra' deixava o 'Total' de fora quando o resumo
        ganhou 'Desconto de produtos', e o teste do cupom saía com o preço ilegível)."""
        return ler_resumo_ml(_texto(page))

    def ajustar_quantidade(self, page, alvo: int = 1) -> bool:
        """Deixa o carrinho com `alvo` unidades da TV, clicando no menos do seletor de quantidade.

        Só clica quando o carrinho tem UM seletor (uma linha só): com outros produtos, o 'menos'
        poderia ser o de um item da pessoa.
        """
        for _ in range(12):
            atual = self.ler_totais(page).quantidade
            if atual <= alvo:
                return atual == alvo
            menos = page.locator(_SEL_ML_MENOS)
            if menos.count() != 1:
                return False
            try:
                menos.first.click(timeout=8000)
            except Exception:
                return False
            page.wait_for_timeout(2500)
        return False

    def aplicar(self, page, codigo: str) -> ResultadoCupom:
        """Insere o código na página de cupons do carrinho e relê o total."""
        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login ao abrir o carrinho")
        antes = self.ler_totais(page)

        page.goto(self.url_cupons_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login na página de cupons")
        campo = page.locator("#inputcode-textfield-inline, input[placeholder*='código' i]").first
        if not campo.count():
            return ResultadoCupom(codigo=codigo, aceito=False, mensagem="campo de cupom não encontrado",
                                  extra={"falha": True})
        campo.fill("")
        campo.fill(codigo)
        page.wait_for_timeout(400)
        bt = page.get_by_role("button", name=re.compile(r"^inserir$|^aplicar$", re.I)).first
        try:
            if bt.count():
                bt.click(timeout=8000)
            else:
                campo.press("Enter")
        except Exception:
            campo.press("Enter")

        mensagem = ""
        for _ in range(8):
            page.wait_for_timeout(700)
            linha = next((l.strip() for l in _texto(page).splitlines() if _RE_ML_ERRO.search(l)), None)
            if linha:
                mensagem = re.sub(r"\s+", " ", linha)[:200]
                break

        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        depois = self.ler_totais(page)
        depois.codigo = codigo
        # L2 (26/09): só o preço da TV medido antes e depois decide. O resumo novo sempre tem "Desconto no Pix" (e, às
        # vezes, "Desconto de produtos"), que antes contavam como cupom: tudo saía "aceito", até com o total ilegível
        medir_cupom(antes, depois, mensagem)
        if not mensagem and antes.desconto:
            # o carrinho já estava com um cupom: o "antes" não é o preço cheio e a comparação não mede este código
            depois.aceito = False
            depois.extra.pop("so_frete", None)
            depois.extra["falha"] = True
            depois.mensagem = (f"não consegui medir: o carrinho já estava com um cupom de {fmt_preco(antes.desconto)} "
                               "antes do teste")
        return depois

    def remover(self, page) -> None:
        """Tira o cupom do carrinho para o próximo teste começar limpo."""
        page.goto(self.url_cupons_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        rem = page.get_by_role("button", name=re.compile(r"remover|excluir|tirar", re.I)).first
        if rem.count():
            try:
                rem.click(timeout=6000)
                page.wait_for_timeout(2500)
            except Exception:
                pass


# ----------------------------------------------------------------------------------------------
# Amazon
# ----------------------------------------------------------------------------------------------

_RE_AMZ_SUBTOTAL = re.compile(r"Subtotal\s*\((\d+)\s*it[ae]ns?\):?\s*\n?\s*R\$\s?([\d.]+,\d{2})", re.I)
_RE_AMZ_ERRO = re.compile(
    r"n[ãa]o (?:é|e) v[áa]lido|inv[áa]lido|expirou|n[ãa]o p[ôo]de ser aplicado|n[ãa]o reconhecemos|"
    r"n[ãa]o se aplica|j[áa] foi (?:usado|resgatado)|n[ãa]o dispon[íi]vel", re.I)


class Amazon(LojaCarrinho):
    """A Amazon é diferente das outras duas.

    Ela bloqueia o robô de pôr item no carrinho (o contador fica em zero) e o campo de código
    promocional só existe no passo de pagamento, onde o robô não entra. Então aqui trabalhamos na
    página do produto: marcamos o cupom de clicar ("Economize R$ X com cupom") e lemos o preço.
    """

    nome = "amazon"
    loja_canonica = "Amazon"
    url_login = config.URL_AMAZON_LOGIN
    url_carrinho = config.URL_AMAZON_PRODUTO   # o "carrinho" desta loja é a própria página do anúncio
    url_produto = config.URL_AMAZON_PRODUTO
    dominio_url = "amazon.com.br"
    so_leitura = True                          # não testa códigos digitados
    max_anuncios = 3                           # páginas de vendedor lidas por rodada (só leitura)

    def logado(self, page) -> bool:
        if "/ap/signin" in page.url:
            return False
        t = _texto(page)[:2500]
        return "Faça seu login" not in t

    @staticmethod
    def _smid(url: str) -> Optional[str]:
        m = re.search(r"[?&](?:smid|m)=([A-Z0-9]{8,})", url or "")
        return m.group(1) if m else None

    def identidade(self, o: dict) -> dict:
        base = super().identidade(o)
        base["vendedor_id"] = base["vendedor_id"] or self._smid(o.get("url") or "")
        return base

    @staticmethod
    def _merchant_id(html: str) -> Optional[str]:
        """O campo escondido merchantID do formulário de compra da oferta em destaque (o de id="merchantID"; sem ele, o
        primeiro name="merchantID")."""
        for padrao in (r'<input\b[^>]*\bid=["\']merchantID["\'][^>]*>', r'<input\b[^>]*\bname=["\']merchantID["\'][^>]*>'):
            m = re.search(padrao, html or "", re.I)
            if m:
                mv = re.search(r'\bvalue=["\']\s*([A-Z0-9]{8,20})\s*["\']', m.group(0))
                if mv:
                    return mv.group(1)
        return None

    @staticmethod
    def _nome_no_html(html: str) -> Optional[str]:
        """O nome de quem vende no bloco da oferta em destaque, sem o link de perfil (a própria Amazon): o texto de
        #merchantInfoFeature_feature_div (offer-display-feature-text-message) ou de #merchant-info."""
        h = html or ""
        m = re.search(r'id=["\']merchantInfoFeature_feature_div["\'].{0,4000}?offer-display-feature-text-message'
                      r'[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,80}?)\s*<', h, re.S)
        if not m:
            m = re.search(r'id=["\']merchant-info["\'][^>]*>(.{0,600}?)</div>', h, re.S)
            if m:
                txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
                mt = re.search(r"vendido por\s+(.{2,60})", txt, re.I)
                return mt.group(1).strip() if mt else None
        return m.group(1).strip() if m else None

    @classmethod
    def vendedor_da_pagina(cls, html: str, texto: str = "") -> tuple[Optional[str], Optional[str]]:
        """(id, nome) do vendedor da oferta em destaque:
        1) link #sellerProfileTriggerId (…seller=ACUNARZFR75ET…, texto "Magalu."): outro vendedor, pelo id dele;
        2) sem o link (vendido pela própria Amazon, L3 de 26/09: "a página mostrou o vendedor ?"), o campo escondido
           merchantID (A1ZZFT5FULY4LN é a própria Amazon, "Amazon.com.br");
        3) o nome no bloco da oferta ou a frase "Vendido por X" do texto; "Amazon.com.br" sem id é a própria Amazon."""
        m = re.search(r'<a\b([^>]*\bid="sellerProfileTriggerId"[^>]*)>\s*([^<]*?)\s*</a>', html or "")
        if m:
            ms = re.search(r"[?&;]seller=([A-Z0-9]+)", m.group(1))
            return (ms.group(1) if ms else None), (m.group(2).strip() or None)
        vid = cls._merchant_id(html)
        nome = cls._nome_no_html(html)
        if not nome:
            mt = re.search(r"Vendido por\s*\n?\s*([^\n]+)", texto or "", re.I)
            nome = mt.group(1).strip()[:60] if mt else None
        eh_1p = (vid == config.AMAZON_1P_ID) or (not vid and norm_vendedor(nome) == "amazoncombr")
        if eh_1p:
            return config.AMAZON_1P_ID, (nome or "Amazon.com.br")
        return vid, nome

    def garantir_item(self, page, url_produto: str, alvo: Optional[dict] = None) -> bool:
        """Abre a página do anúncio (com smid=<vendedor> quando a coleta sabe) e confere o vendedor.

        Nada vai para o carrinho. Se a página mostrar outro vendedor, o preço lido não é deste anúncio."""
        info = alvo or {}
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("a Amazon pediu login na página do produto")
        if page.locator("#productTitle").count() == 0:
            return False
        vend_id = info.get("vendedor_id") or self._smid(url_produto)
        vend_nome = info.get("vendedor")
        if not (vend_id or vend_nome):
            return True
        pid, pnome = self.vendedor_da_pagina(page.content(), _texto(page))
        igual = mesmo_vendedor(pid, pnome, vend_id, vend_nome)
        if igual is False or (igual is None and self._smid(url_produto)):
            print(f"[amazon] a página mostrou o vendedor {pnome or pid or '?'}, não {vend_nome or vend_id}; "
                  "não leio este anúncio")
            return False
        return True

    def ler_totais(self, page) -> ResultadoCupom:
        t = _texto(page)
        r = ResultadoCupom(codigo="", aceito=False)
        bloco = page.locator("#corePriceDisplay_desktop_feature_div, #corePrice_feature_div, #apex_desktop").first
        preco = None
        if bloco.count():
            m = re.search(r"R\$\s?([\d.]+,\d{2})", bloco.inner_text().replace("\xa0", " "))
            preco = parse_preco(m.group(1)) if m else None
        if preco is None:
            m = re.search(r'"displayPrice":"R\$\s?([\d.,]+)"', page.content())
            preco = parse_preco(m.group(1)) if m else None
        from .sources.amazon import separa_pix_cartao

        def _txt(sel: str) -> str:
            e = page.locator(sel).first
            return e.inner_text() if e.count() else ""

        cartao, pix, parcelado = separa_pix_cartao(
            preco, _txt("#oneTimePaymentPrice_feature_div"), _txt("#best-offer-string-cc"))
        r.total_pix = pix or cartao
        r.pix_real = pix is not None  # sem Pix na página, total_pix é o preço do CARTÃO
        r.total_cartao = cartao
        r.produtos = cartao or pix
        r.frete = None   # a página do produto não diz o frete até o endereço (L4: frete desconhecido, não "grátis")
        if parcelado is None and not pix:
            m = re.search(r"(\d{1,2})x de R\$\s?([\d.]+,\d{2})\s*sem juros", t.replace("\xa0", " "))
            parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
        r.parcelado = parcelado
        mv = page.locator("#sellerProfileTriggerId").first
        if mv.count():
            r.extra["vendedor"] = mv.inner_text().strip()[:40]
        md = re.search(r"Inclui desconto de\s*R\$\s?([\d.,]+)", t.replace("\xa0", " "))
        if md:
            r.desconto = parse_preco(md.group(1))
        return r

    def cupom_da_pagina(self, page) -> Optional[str]:
        """Marca o cupom de clicar da página, se houver, e devolve o texto dele."""
        cx = page.locator(
            "#couponFeature input[type=checkbox], input[id*=couponCheckbox], "
            "#promoPriceBlockMessage input[type=checkbox], #vpcButton input[type=checkbox]").first
        if not cx.count():
            return None
        rotulo = ""
        for sel in ("#couponFeature", "label[for*=coupon]", "#promoPriceBlockMessage"):
            e = page.locator(sel).first
            if e.count():
                rotulo = re.sub(r"\s+", " ", e.inner_text())[:120]
                break
        try:
            if not cx.is_checked():
                cx.check(timeout=6000)
                page.wait_for_timeout(2500)
        except Exception:
            pass
        return rotulo or "cupom da página"

    def aplicar(self, page, codigo: str) -> ResultadoCupom:
        base = self.ler_totais(page)
        base.codigo = codigo
        base.aceito = False
        base.mensagem = "a Amazon só aceita código no pagamento; não testo lá por segurança"
        return base

    def remover(self, page) -> None:
        return


def _espera(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


LOJAS: dict[str, LojaCarrinho] = {"magalu": Magalu(), "mercadolivre": MercadoLivre(), "amazon": Amazon()}


def caminho_chrome() -> Optional[str]:
    import shutil

    candidatos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidatos:
        if Path(c).exists():
            return c
    return shutil.which("chrome")


def abrir_chrome_normal(loja: LojaCarrinho, url: str):
    """Abre o Chrome comum (sem automação) no perfil da loja.

    Sites como o Mercado Livre não carregam o captcha num navegador aberto por automação;
    o login precisa acontecer numa janela normal. Depois, a sessão salva no perfil é reaproveitada.
    """
    import subprocess

    exe = caminho_chrome()
    if not exe:
        return None
    loja.perfil().mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        exe,
        f"--user-data-dir={loja.perfil()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-position=120,60",
        "--window-size=1280,900",
        url,
    ])


def abrir_navegador(pw, loja: LojaCarrinho, visivel: bool):
    loja.perfil().mkdir(parents=True, exist_ok=True)
    args = ["--disable-blink-features=AutomationControlled"]
    if visivel:
        # o perfil lembra a última posição (fora da tela); no modo visível forçamos o centro
        args += ["--window-position=120,60", "--window-size=1280,860"]
    else:
        args.append("--window-position=-32000,-32000")
    return pw.chromium.launch_persistent_context(
        str(loja.perfil()), channel="chrome", headless=False, locale="pt-BR", timezone_id="America/Sao_Paulo",
        viewport={"width": 1280, "height": 860}, args=args,
    )
