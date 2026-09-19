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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .filtro import eh_55c6k
from .util import fmt_preco, next_data, parse_preco, sem_acentos

PERFIS = config.RAIZ / ".pw-profile-carrinho"

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
_RE_NOME_TV = re.compile(r"smart\s*tv|\btv\b|televis|55\s*c6k|\btcl\b", re.I)


def eh_servico(texto: str) -> bool:
    t = texto or ""
    m = _RE_NOME_TV.search(t)
    return bool(_RE_SERVICO.search(t[: m.start()] if m else t))


def eh_linha_da_tv(texto: str) -> bool:
    """Linha/item do carrinho que é a própria TV 55C6K (não um serviço com o nome dela)."""
    return eh_55c6k(texto) and not eh_servico(texto)


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
        """'aceito', 'recusado' (a loja disse não) ou 'erro' (falha do robô, que não vale como recusa)."""
        if self.aceito:
            return "aceito"
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
    return re.sub(r"[^a-z0-9]", "", sem_acentos(str(s or "")).lower())


def mesmo_vendedor(a_id, a_nome, b_id, b_nome) -> Optional[bool]:
    """True/False comparando id e nome dos dois lados; None quando um dos lados não diz nada."""
    lado_a = {norm_vendedor(x) for x in (a_id, a_nome)} - {""}
    lado_b = {norm_vendedor(x) for x in (b_id, b_nome)} - {""}
    if not lado_a or not lado_b:
        return None
    for lado in (lado_a, lado_b):
        if lado & _MAGALU_1P:
            lado |= _MAGALU_1P
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

    def _abrir_pagina_do_anuncio(self, page, url_produto: str, vend_id, vend_nome) -> bool:
        """Abre a página do anúncio e confere que ela é a 55C6K e está com o vendedor pedido.

        Chamado ANTES de mexer na sacola: se a página não oferece esse vendedor, nada muda no carrinho."""
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        info = self.info_da_pagina(page.content(), _texto(page), getattr(page, "url", "") or "")
        rotulo = self._id_anuncio(url_produto)
        if info["titulo"] and not eh_55c6k(info["titulo"]):
            print(f"[magalu] a página do anúncio {rotulo} não é a TV 55C6K ({info['titulo'][:60]}); não adiciono")
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
    def _so_tvs(itens: Optional[list[dict]]) -> bool:
        """True só quando a sacola foi lida e TODO item dela é a 55C6K (garantia/seguro da TV não é a TV)."""
        return itens is not None and all(eh_linha_da_tv(i.get("titulo") or "") for i in itens)

    def esvaziar(self, page) -> None:
        """Remove itens da sacola SOMENTE se todos forem a 55C6K.

        A sacola é a do usuário: se houver qualquer outro produto (ou se não der para ler o que há),
        não mexemos em nada. Quem chama trata isso como "não deu para trocar o anúncio".
        """
        if not self._so_tvs(self.itens_da_sacola(page)):
            return
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
            page.wait_for_timeout(2500)
            conf = page.get_by_role("button", name=re.compile(r"excluir|confirmar|sim", re.I)).first
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
        """Deixa na sacola exatamente o anúncio pedido, do vendedor pedido, com 1 unidade.

        - sacola com outro produto (não a TV): CarrinhoOcupado, não mexe em nada;
        - antes de esvaziar, abre a página do anúncio e confere o vendedor (o Magalu troca de vendedor sem
          avisar quando o pedido não vende o produto): se não for o pedido, pula o anúncio sem mexer;
        - só esvazia a sacola quando ela tem só a 55C6K; depois adiciona e confere id + vendedor.
        O Magalu engasga quando recebe muitas operações de sacola seguidas, então tentamos
        mais de uma vez, com pausa, antes de desistir do anúncio.
        """
        info = alvo or {}
        alvo_id = self._id_anuncio(url_produto)
        vend_id = info.get("vendedor_id") or self._seller_da_url(url_produto)
        vend_nome = info.get("vendedor")
        confere = bool(vend_id or vend_nome)
        for tentativa in range(3):
            itens = self.itens_da_sacola(page)
            if itens is None:
                return False  # não deu para ler a sacola: não mexe em nada
            if self._so_o_alvo(itens, alvo_id, vend_id, vend_nome, sem_vendedor_ok=False):
                return True
            if itens and not self._so_tvs(itens):
                raise CarrinhoOcupado("a sacola do Magalu tem produtos que não são a TV; não mexo nela")
            if confere and self._so_o_alvo(itens, alvo_id) and \
                    mesmo_vendedor(itens[0].get("vendedor_id"), itens[0].get("vendedor"), vend_id, vend_nome) is None:
                # a sacola não disse o vendedor: confere pela página (sem mexer na sacola) e volta para a
                # sacola, que é onde os testes leem o total
                if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome):
                    return False
                return self._so_o_alvo(self.itens_da_sacola(page), alvo_id)
            if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome):
                return False
            if itens:
                self.esvaziar(page)
                page.wait_for_timeout(2000)
                if self.itens_da_sacola(page) != []:
                    # não esvaziou (ou não deu para ler): pôr outra TV só somaria unidades
                    page.wait_for_timeout(4000 * (tentativa + 1))
                    continue
                if not self._abrir_pagina_do_anuncio(page, url_produto, vend_id, vend_nome):
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
        escopo = self._dialogo(page) or page
        botao = escopo.get_by_role("button", name=re.compile(r"^aplicar|^inserir|^adicionar|^ok$|^confirmar", re.I)).first
        try:
            if botao.count():
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
        caiu = (antes.total_cartao and depois.total_cartao and depois.total_cartao < antes.total_cartao - 1) or \
               (antes.total_pix and depois.total_pix and depois.total_pix < antes.total_pix - 1)
        depois.aceito = (not mensagem) and (bool(depois.desconto) or bool(caiu))
        falha = False
        if not mensagem and not depois.aceito:
            if _sem_total(antes) or _sem_total(depois):
                mensagem, falha = "não consegui ler o total da sacola", True
            else:
                t = _texto(page)
                i_res = t.find("Produtos (")
                mensagem = "sem mudança no total: " + re.sub(r"\s+", " ", t[i_res:i_res + 160]).strip() if i_res >= 0 else "sem mudança no total"
        depois.mensagem = mensagem
        depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao}
        if falha:
            depois.extra["falha"] = True
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
_RE_EXCLUIR = re.compile(r"^\s*Excluir\s*$", re.I)
# cada linha do carrinho (uma por seletor de quantidade): sobe do seletor até o bloco da linha, que é o
# primeiro que tem UM botão "Excluir" (ou, sem ele, o primeiro que tem link). Nunca sobe para um bloco que
# tenha outra linha, o "Resumo da compra" ou texto demais (recomendações com a própria 55C6K poderiam fazer um
# produto qualquer parecer a TV). Marca o bloco com data-tv55-linha=<k> para o clique em "Excluir" ser
# dentro DAQUELA linha.
_ML_MAX_TEXTO_LINHA = 2000
_JS_ML_LINHAS = """() => {
  const sel = '[data-andes-input-stepper-control-type=decrement]';
  const ehExcluir = b => /^\\s*excluir\\s*$/i.test((b.innerText || b.getAttribute('aria-label') || '').trim());
  const grande = el => el.querySelectorAll(sel).length > 1 || (el.innerText || '').length > %d
                       || /Resumo da compra/i.test(el.innerText || '');
  document.querySelectorAll('[data-tv55-linha]').forEach(e => e.removeAttribute('data-tv55-linha'));
  return [...document.querySelectorAll(sel)].map((s, k) => {
    let el = s.parentElement, linha = null, comLink = null;
    for (let i = 0; i < 12 && el && el !== document.body; i++, el = el.parentElement) {
      if (grande(el)) break;
      if (!comLink && el.querySelector('a[href]')) comLink = el;
      if ([...el.querySelectorAll('button, a, [role=button]')].filter(ehExcluir).length === 1) { linha = el; break; }
    }
    const bloco = linha || comLink;
    if (!bloco) return {links: [], texto: '', excluir: false};
    bloco.setAttribute('data-tv55-linha', String(k));
    return {links: [...bloco.querySelectorAll('a[href]')].map(a => a.href),
            texto: (bloco.innerText || '').slice(0, %d), excluir: !!linha};
  });
}""" % (_ML_MAX_TEXTO_LINHA, _ML_MAX_TEXTO_LINHA + 1)


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
        """Linha do carrinho como veio do JS ({links, texto, excluir}) ou no formato antigo (só links)."""
        if isinstance(l, dict):
            return {"links": [str(x) for x in (l.get("links") or [])], "texto": str(l.get("texto") or ""),
                    "excluir": bool(l.get("excluir"))}
        return {"links": [str(x) for x in (l or [])], "texto": "", "excluir": False}

    @classmethod
    def classificar_linhas(cls, linhas: list, item_alvo: str, catalogo: str = "", ids_tv=()) -> list[dict]:
        """Para cada linha: ids de item nos links, se é a 55C6K e se é o anúncio alvo.

        É a TV quando o link é de um item conhecido da 55C6K (coleta ou opções do catálogo), quando o link é
        do catálogo da TV, ou quando o texto da linha é o título da 55C6K. Sem nada disso NÃO é a TV (na
        dúvida, o carrinho é tratado como "tem outro produto" e ninguém mexe nele). Bloco grande demais (vários
        preços, texto longo, vários itens) não é uma linha só: também NÃO é a TV. Serviço com o nome da TV
        (garantia estendida, seguro, instalação) NÃO é a TV, mesmo com o link do anúncio dela."""
        catalogos = {c for c in (catalogo, catalogo_ml_da_url(config.URL_ML_CATALOGO)) if c}
        conhecidos = set(ids_tv) | {item_alvo}
        out = []
        for l in map(cls._linha, linhas):
            juntos = " ".join(l["links"])
            ids = set(ids_ml(juntos)) - catalogos
            do_catalogo = any(f"/p/{c}".upper() in juntos.upper() for c in catalogos)
            poluido = len(l["texto"]) > _ML_MAX_TEXTO_LINHA or l["texto"].count("R$") > 8 or len(ids) > 3
            tv = not poluido and not eh_servico(l["texto"]) and \
                (bool(ids & conhecidos) or do_catalogo or eh_linha_da_tv(l["texto"]))
            out.append({**l, "ids": ids, "tv": tv, "alvo": item_alvo in ids})
        return out

    @classmethod
    def situacao_do_carrinho(cls, linhas: list, totais: ResultadoCupom, texto: str, alvo: dict,
                             ofertas: list[dict], catalogo: str = "", ids_tv=()) -> str:
        """Confere o carrinho contra o anúncio alvo.

        'ok'      só o anúncio alvo (a quantidade é ajustada depois);
        'vazio'   carrinho vazio;
        'trocar'  só anúncios da 55C6K, mas não só o alvo: pode trocar pelo alvo;
        'outro'   tem produto que não é a 55C6K (ou uma linha que não dá para conferir): não mexe em nada;
        '?'       não deu para conferir qual anúncio é.
        `linhas`: uma por seletor de quantidade. Quando a linha não traz o id do anúncio, conferimos pelo
        preço de uma unidade contra os preços das opções do catálogo: o 'Parcelamento sem juros'
        (R$ 3.749) não passa por 'Melhor preço' (R$ 3.599).
        """
        tem_tv = "55C6K" in (texto or "").upper().replace(" ", "")
        vazio = re.search(r"carrinho est[áa] vazio", texto or "", re.I)
        if not linhas and totais.produtos is None and totais.total_cartao is None and (vazio or not tem_tv):
            return "vazio"
        ids_tv = set(ids_tv) | {o["item_id"] for o in ofertas}
        cl = cls.classificar_linhas(linhas, alvo["item_id"], catalogo, ids_tv)
        if any(not c["tv"] for c in cl):
            return "outro"  # produto que não é a TV: não mexemos no carrinho da pessoa
        if len(cl) > 1:
            return "trocar"  # só TVs, mas mais de um anúncio
        outras = [o for o in ofertas if o["item_id"] != alvo["item_id"]]
        if cl:
            ids = cl[0]["ids"]
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
            # outro anúncio da TV; sem a linha lida não há onde clicar em "Excluir": não mexe
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

    def _adicionar(self, page, url_produto: str, alvo: dict, catalogo: str) -> bool:
        """Põe no carrinho o anúncio alvo (abre o catálogo já com ele selecionado)."""
        url = url_produto
        if catalogo:
            url = url_produto.split("#")[0].split("?")[0] + f"?pdp_filters=item_id%3A{alvo['item_id']}"
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        html = page.content()
        titulo = self._titulo_da_pagina(html)
        if titulo and not eh_55c6k(titulo):
            print(f"[mercadolivre] a página de {alvo['item_id']} não é a TV 55C6K ({titulo[:60]}); não adiciono")
            return False
        selecionada = next((o["item_id"] for o in self.ofertas_do_catalogo(html) if o["selecionada"]), None)
        if selecionada is None:
            gtm = _RE_ML_GTM.search(html or "")
            selecionada = gtm.group(1) if gtm else None
        if selecionada is not None and selecionada != alvo["item_id"]:
            print(f"[mercadolivre] a página selecionou {selecionada}, não o anúncio {alvo['item_id']}; não adiciono")
            return False
        botao = page.get_by_role("button", name=re.compile(r"adicionar ao carrinho", re.I)).first
        if not botao.count():
            botao = page.locator("a:has-text('Adicionar ao carrinho'), button:has-text('Adicionar ao carrinho')").first
        if not botao.count():
            return False
        botao.click(timeout=10000)
        page.wait_for_timeout(4000)
        return True

    def _excluir_linha(self, page, k: int) -> bool:
        """Clica em "Excluir" DENTRO da linha k (marcada por _JS_ML_LINHAS). Só é chamada para linhas da TV."""
        bt = page.locator(f"[data-tv55-linha='{k}']").locator("button, a, [role=button]").filter(has_text=_RE_EXCLUIR).first
        if not bt.count():
            return False
        try:
            bt.click(timeout=8000)
            page.wait_for_timeout(2000)
            conf = page.locator("[role=dialog] button, .andes-modal button").filter(has_text=_RE_EXCLUIR).first
            if conf.count() and conf.is_visible():
                conf.click(timeout=5000)
                page.wait_for_timeout(2000)
        except Exception:
            return False
        return True

    def _tirar_outras_tvs(self, page, alvo: dict, ofertas: list[dict], catalogo: str, ids_tv) -> bool:
        """Tira do carrinho, uma a uma, as linhas da 55C6K que não são o anúncio alvo.

        Antes de cada clique relê o carrinho e confere de novo que TODAS as linhas são a TV; se aparecer
        qualquer outra coisa, ou se a linha não sumir depois do clique, para sem mexer em mais nada."""
        for _ in range(6):
            linhas, totais, texto = self._ler_carrinho(page)
            sit = self.situacao_do_carrinho(linhas, totais, texto, alvo, ofertas, catalogo, ids_tv)
            if sit in ("vazio", "ok"):
                return True
            if sit != "trocar":
                return False
            cl = self.classificar_linhas(linhas, alvo["item_id"], catalogo, set(ids_tv) | {o["item_id"] for o in ofertas})
            if not cl or any(not c["tv"] for c in cl):
                return False
            k = next((i for i, c in enumerate(cl) if not c["alvo"]), None)
            if k is None or not cl[k]["excluir"]:
                return False
            if not self._excluir_linha(page, k):
                return False
            page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            _espera(page)
            if len(self._ler_carrinho(page)[0]) >= len(cl):
                return False  # a linha não saiu: não insiste
        return False

    def garantir_item(self, page, url_produto: str, alvo: Optional[dict] = None) -> bool:
        """Deixa no carrinho 1 unidade do anúncio pedido, e só ele.

        O anúncio é o item MLB… de `alvo["item_id"]` ou da URL (?pdp_filters=item_id%3AMLB… /
        produto.mercadolivre.com.br/MLB-…); sem item (formato antigo), vale o 'Melhor preço' do catálogo.
        - carrinho vazio: adiciona o anúncio;
        - só anúncios da 55C6K: tira os outros e adiciona o pedido (1 unidade);
        - qualquer outro produto (ou linha que não dá para conferir): CarrinhoOcupado, não mexe em nada.
        """
        self.item_alvo = None
        info = alvo or {}
        pedido = (info.get("item_id") or item_ml_da_url(url_produto) or "").upper() or None
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        html = page.content()
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
        catalogo = catalogo_ml_da_url(url_produto)
        ids_tv = set(info.get("ids_tv") or ())
        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login ao abrir o carrinho")
        situacao = self.situacao_do_carrinho(*self._ler_carrinho(page), oferta, ofertas, catalogo, ids_tv)
        if situacao == "outro":
            raise CarrinhoOcupado("o carrinho do Mercado Livre tem produto que não é a TV (ou um item que não "
                                  "consigo conferir); não mexo nele. Tire-o à mão para o teste voltar")
        if situacao == "trocar":
            if not self._tirar_outras_tvs(page, oferta, ofertas, catalogo, ids_tv):
                print(f"[mercadolivre] não consegui trocar a TV do carrinho pelo anúncio {oferta['item_id']}; "
                      "sem teste neste anúncio")
                return False
            situacao = self.situacao_do_carrinho(*self._ler_carrinho(page), oferta, ofertas, catalogo, ids_tv)
        if situacao == "vazio":
            if not self._adicionar(page, url_produto, oferta, catalogo):
                return False
            page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            _espera(page)
            situacao = self.situacao_do_carrinho(*self._ler_carrinho(page), oferta, ofertas, catalogo, ids_tv)
        if situacao != "ok":
            precos = " / ".join(fmt_preco(p) for p in oferta["precos"])
            print(f"[mercadolivre] o carrinho não ficou só com o anúncio {oferta['item_id']} ({precos}): "
                  "não consegui conferir o anúncio. Sem teste neste anúncio.")
            return False
        if not self.ajustar_quantidade(page, 1):
            print("[mercadolivre] não consegui deixar 1 unidade da TV no carrinho; sem teste neste anúncio")
            return False
        self.item_alvo = oferta["item_id"]
        return True

    def ler_totais(self, page) -> ResultadoCupom:
        """O resumo do ML põe rótulo e valor em linhas separadas ('Produtos (2)' / 'R$' / '8.338')."""
        linhas = [l.strip() for l in _texto(page).splitlines()]
        r = ResultadoCupom(codigo="", aceito=False)

        def valor_apos(k: int) -> Optional[float]:
            for j in range(k + 1, min(len(linhas), k + 5)):
                l = linhas[j]
                if not l:
                    continue
                if re.fullmatch(r"gr[áa]tis", l, re.I):
                    return 0.0
                if l == "R$" or l == "-":
                    continue
                m = re.fullmatch(r"-?\s*(?:R\$\s?)?([\d.]+)", l)
                if m:
                    inteiro = parse_preco(m.group(1))
                    centavos = 0.0
                    if j + 2 < len(linhas) and linhas[j + 1] == "," and re.fullmatch(r"\d{2}", linhas[j + 2]):
                        centavos = int(linhas[j + 2]) / 100
                    return round((inteiro or 0) + centavos, 2) or None
                return None
            return None

        i_resumo = next((k for k, l in enumerate(linhas) if l.startswith("Resumo da compra")), None)
        fatia = range(i_resumo, min(len(linhas), i_resumo + 24)) if i_resumo is not None else range(len(linhas))
        for k in fatia:
            rot = linhas[k]
            m = _RE_ML_QTD.match(rot)
            if m and r.produtos is None:
                r.quantidade = max(1, int(m.group(1)))
                r.produtos = valor_apos(k)
            elif re.fullmatch(r"Produto", rot, re.I) and r.produtos is None:
                r.quantidade = 1  # com 1 unidade o resumo diz só 'Produto', sem o número
                r.produtos = valor_apos(k)
            elif re.fullmatch(r"Frete", rot, re.I) and r.frete is None:
                r.frete = valor_apos(k)
            elif re.fullmatch(r"Total", rot, re.I) and r.total_cartao is None:
                r.total_cartao = valor_apos(k)
            elif re.search(r"(cupom|desconto)", rot, re.I) and "Inserir" not in rot and r.desconto is None:
                r.desconto = valor_apos(k)
        # o ML só mostra o desconto do Pix no pagamento: este "Pix" é o total do CARTÃO (pix_real=False)
        r.total_pix, r.pix_real = r.total_cartao, False
        m = _RE_PARCELA.search("\n".join(linhas))
        r.parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
        return r

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
        caiu = bool(antes.total_cartao and depois.total_cartao and depois.total_cartao < antes.total_cartao - 1)
        depois.aceito = (not mensagem) and (bool(depois.desconto) or caiu)
        falha = not mensagem and not depois.aceito and (_sem_total(antes) or _sem_total(depois))
        depois.mensagem = mensagem or ("" if depois.aceito else
                                       "não consegui ler o total do carrinho" if falha else "sem mudança no total")
        depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao}
        if falha:
            depois.extra["falha"] = True
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
    def vendedor_da_pagina(html: str, texto: str = "") -> tuple[Optional[str], Optional[str]]:
        """(id, nome) do vendedor da oferta em destaque: link #sellerProfileTriggerId (…seller=ACUNARZFR75ET…,
        texto "Magalu.") ou, sem ele (vendido pela própria Amazon), a frase "Vendido por X"."""
        m = re.search(r'<a\b([^>]*\bid="sellerProfileTriggerId"[^>]*)>\s*([^<]*?)\s*</a>', html or "")
        if m:
            ms = re.search(r"[?&;]seller=([A-Z0-9]+)", m.group(1))
            return (ms.group(1) if ms else None), (m.group(2).strip() or None)
        mt = re.search(r"Vendido por\s*\n?\s*([^\n]+)", texto or "", re.I)
        return None, (mt.group(1).strip()[:60] if mt else None)

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
        r.frete = 0.0
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
