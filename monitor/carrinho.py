"""Teste de cupons no carrinho das lojas, com a conta do usuário logada num perfil próprio do Chrome.

Regras de segurança, sem exceção:
  - o robô NUNCA clica em "continuar", "finalizar", "pagar" nem mexe em endereço ou pagamento;
  - o robô NUNCA digita e-mail, CPF ou senha: o login é feito pela pessoa, na janela aberta por --login;
  - se a loja pedir login, o teste para e avisa.

Cada loja é um adaptador com: garantir que a TV está no carrinho, abrir o campo de cupom, aplicar um
código e ler os totais, remover o cupom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .util import parse_preco

PERFIS = config.RAIZ / ".pw-profile-carrinho"


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
    parcelado: Optional[str] = None
    quantidade: int = 1
    extra: dict = field(default_factory=dict)

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


class LojaCarrinho:
    nome = "base"
    loja_canonica = "?"
    url_login = ""
    url_carrinho = ""
    url_produto = ""          # anúncio usado quando não há um mais barato conhecido
    dominio_url = ""          # trecho que identifica um anúncio desta loja nas coletas
    so_leitura = False        # True quando a loja não aceita código digitado (só lê preço/cupom da página)
    max_anuncios = 1          # quantos anúncios diferentes testar por rodada

    def perfil(self) -> Path:
        return PERFIS / self.nome

    # --- a implementar por loja ---
    def logado(self, page) -> bool:  # pragma: no cover
        raise NotImplementedError

    def garantir_item(self, page, url_produto: str) -> bool:  # pragma: no cover
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
    max_anuncios = 3          # o cupom costuma valer para um vendedor e não para outro

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
        m = re.search(r"/p/([^/?]+)", url or "")
        return m.group(1) if m else (url or "")[-24:]

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
            return [] if "sacola está vazia" in _texto(page) else None
        lista = ((capt["j"].get("data") or {}).get("itemList") or {})
        self.cupom_aplicado = lista.get("appliedPromoCode")
        itens = []
        for it in lista.get("items") or []:
            ofertas = ((it.get("item") or {}).get("offers") or [{}])
            vend = (ofertas[0].get("seller") or {}) if ofertas else {}
            itens.append({
                "id": it.get("id") or (it.get("item") or {}).get("id"),
                "quantidade": int(it.get("quantity") or 1),
                "vendedor": vend.get("name") or (it.get("extras") or {}).get("sellerId"),
                "titulo": it.get("name") or "",
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
        """True só quando a sacola foi lida e TODO item dela é a 55C6K."""
        from .filtro import eh_55c6k

        return itens is not None and all(eh_55c6k(i.get("titulo") or "") for i in itens)

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

    def garantir_item(self, page, url_produto: str) -> bool:
        """Deixa na sacola exatamente o anúncio pedido (troca se for outro).

        O Magalu engasga quando recebe muitas operações de sacola seguidas, então tentamos
        mais de uma vez, com pausa, antes de desistir do anúncio.
        """
        alvo = self._id_anuncio(url_produto)
        for tentativa in range(3):
            itens = self.itens_da_sacola(page)
            if itens is None:
                return False  # não deu para ler a sacola: não mexe em nada
            ids = [i["id"] for i in itens]
            if ids == [alvo]:
                return True
            if ids:
                if not self._so_tvs(itens):
                    print("[magalu] a sacola tem produtos que não são a TV; não mexo nela")
                    return False
                self.esvaziar(page)
                page.wait_for_timeout(2000)
            page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
            _espera(page)
            botao = page.get_by_role("button", name=re.compile(r"adicionar à sacola|adicionar a sacola", re.I)).first
            if botao.count():
                try:
                    botao.click(timeout=12000)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass
            depois = self.itens_da_sacola(page)
            if depois is not None and [i["id"] for i in depois] == [alvo]:
                return True
            page.wait_for_timeout(4000 * (tentativa + 1))  # deixa a loja respirar
        return False

    def ler_totais(self, page) -> ResultadoCupom:
        """Lê o resumo da sacola por linhas, ancorado em 'Total:'.

        O Magalu muda a ordem dos rótulos de tempos em tempos (já vi "Produtos (1): / Frete:" e
        "Frete total / Produto (1 item)"), então casamos rótulo → próximo valor em R$.
        """
        t = _texto(page)
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
            return ResultadoCupom(codigo=codigo, aceito=False, mensagem="campo de cupom não encontrado", extra={"antes": antes.__dict__})
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
        if not mensagem and not depois.aceito:
            t = _texto(page)
            i_res = t.find("Produtos (")
            mensagem = "sem mudança no total: " + re.sub(r"\s+", " ", t[i_res:i_res + 160]).strip() if i_res >= 0 else "sem mudança no total"
        depois.mensagem = mensagem
        depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao}
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

    def logado(self, page) -> bool:
        t = _texto(page)[:2000]
        if "iniciar sessão" in t.lower() or "Crie sua conta" in t or "Digite seu e-mail" in t:
            return False
        return "/login" not in page.url

    def garantir_item(self, page, url_produto: str) -> bool:
        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("o Mercado Livre pediu login ao abrir o carrinho")
        if "55C6K" in _texto(page).upper().replace(" ", ""):
            return True
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        botao = page.get_by_role("button", name=re.compile(r"adicionar ao carrinho", re.I)).first
        if not botao.count():
            botao = page.locator("a:has-text('Adicionar ao carrinho'), button:has-text('Adicionar ao carrinho')").first
        if not botao.count():
            return False
        botao.click(timeout=10000)
        page.wait_for_timeout(4000)
        page.goto(self.url_carrinho, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        return "55C6K" in _texto(page).upper().replace(" ", "")

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
            elif re.fullmatch(r"Frete", rot, re.I) and r.frete is None:
                r.frete = valor_apos(k)
            elif re.fullmatch(r"Total", rot, re.I) and r.total_cartao is None:
                r.total_cartao = valor_apos(k)
            elif re.search(r"(cupom|desconto)", rot, re.I) and "Inserir" not in rot and r.desconto is None:
                r.desconto = valor_apos(k)
        r.total_pix = r.total_cartao  # o ML só mostra o desconto do Pix no pagamento
        m = _RE_PARCELA.search("\n".join(linhas))
        r.parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
        return r

    def ajustar_quantidade(self, page, alvo: int = 1) -> bool:
        """Deixa o carrinho com `alvo` unidades da TV, clicando no menos do seletor de quantidade."""
        for _ in range(12):
            atual = self.ler_totais(page).quantidade
            if atual <= alvo:
                return atual == alvo
            menos = page.locator("[data-andes-input-stepper-control-type=decrement]").first
            if not menos.count():
                return False
            try:
                menos.click(timeout=8000)
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
            return ResultadoCupom(codigo=codigo, aceito=False, mensagem="campo de cupom não encontrado")
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
        depois.mensagem = mensagem or ("" if depois.aceito else "sem mudança no total")
        depois.extra = {"antes_pix": antes.total_pix, "antes_cartao": antes.total_cartao}
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

    def logado(self, page) -> bool:
        if "/ap/signin" in page.url:
            return False
        t = _texto(page)[:2500]
        return "Faça seu login" not in t

    def garantir_item(self, page, url_produto: str) -> bool:
        page.goto(url_produto, wait_until="domcontentloaded", timeout=60000)
        _espera(page)
        if not self.logado(page):
            raise PrecisaLogin("a Amazon pediu login na página do produto")
        return page.locator("#productTitle").count() > 0

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
        r.produtos = r.total_cartao = r.total_pix = preco
        r.frete = 0.0
        m = re.search(r"(\d{1,2})x de R\$\s?([\d.]+,\d{2})\s*sem juros", t.replace("\xa0", " "))
        r.parcelado = f"{m.group(1)}x R$ {m.group(2)} sem juros" if m else None
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
