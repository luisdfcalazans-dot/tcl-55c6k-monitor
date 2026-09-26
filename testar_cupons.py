"""Testa cupons no carrinho das lojas com a sua conta logada e avisa o melhor preço da TV.

  python testar_cupons.py --loja magalu --login          # abre o Chrome para VOCÊ fazer login (uma vez por loja)
  python testar_cupons.py --loja mercadolivre --login
  python testar_cupons.py                                 # testa os cupons novos em todas as lojas logadas
  python testar_cupons.py --loja magalu --codigos ABC,XYZ # testa códigos específicos
  python testar_cupons.py --forcar                        # testa de novo todos os cupons conhecidos
  opções: --no-notify  --visivel (mostra a janela)  --check (só confere a sessão)

Cada teste fica gravado com um status: "aceito", "recusado" (a loja disse não) ou "erro" (falha do
robô: campo não achado, exceção, total ilegível). "erro" é testado de novo na rodada seguinte;
"recusado" depois de 24 h, ou a cada hora nova para cupons de horário (…14H, …18H).

Anúncios (pedido do usuário em 19/09: "priorize o mais barato"): o robô pega TODOS os anúncios ativos da
TV na loja (latest_cloud.json + latest_pc.json, um por anúncio+vendedor) e vai do mais barato ao mais caro.
Antes de mexer no carrinho calcula a fila de cada anúncio; anúncio sem cupom pendente é pulado sem tocar no
carrinho. Cupom já aceito num anúncio mais barato (e ainda válido) não é testado nos mais caros; cupom
recusado (ou com erro) no mais barato passa para o próximo. Limites por rodada: MAX_APLICACOES_POR_RODADA
testes por loja (divididos entre os modelos com cupom pendente) e loja.max_anuncios anúncios visitados por modelo
(Magalu 4, ML 3, Amazon 3 só leitura). No fim da rodada o
carrinho fica com o melhor cupom conhecido, se ele deixar a TV mais barata; senão, com o anúncio mais barato da loja
sem cupom, entre TODOS (aberto ou não nesta rodada; se ele não entrar, o próximo), nunca com um anúncio mais caro só
porque foi o último testado. Falha do robô no meio da rodada não pula esse passo. Cupom que não deixa a TV mais
barata que o anúncio mais barato sem cupom não vira "melhor preço" na mensagem. Anúncio do ML cujo vendedor a
coleta não conferiu (extra.vendedor_conferido=False) não entra.

Incidente de 22/09 10:12 (coleta do ML bloqueada pelo antirrobô) e correções:
  F1  loja sem anúncio conhecido nesta rodada: o carrinho dela NÃO é tocado (nem troca, nem cupom, nem passo
      final). Antes o robô caía num "anúncio padrão" (o catálogo, vendedor '?', R$ 0,00) e tentava trocar a TV
      da pessoa. Se o testador leu anúncios da loja nas últimas 24 h (reg["precos"]), eles servem no lugar
      (por modelo: sem anúncio da 65C6K na coleta, valem os da 65C6K que o testador leu).
  G1  (monitor.carrinho) o ML troca de anúncio TIRANDO primeiro e PONDO depois, com PRÉ-CHECAGEM do anúncio novo
      (a página é a TV do modelo, selecionou o item, tem o botão) antes de tirar qualquer coisa: nunca duas TVs do
      mesmo modelo. (A F2 de 22/09, que punha antes de tirar, deixava 2 TVs quando o "Excluir" falhava.)
  G2  o botão de tirar a linha é achado pelo texto OU pelo aria-label/title ("Excluir", "Remover produto",
      "Remover"): em 22/09 era só um ícone com aria-label "Remover produto".
  G3  cada linha tirada é conferida (a linha sumiu do carrinho); e o passo final, ao reaplicar um cupom de até 48 h
      (F4), compara o preço de AGORA com o anúncio mais barato sem cupom: se não compensa mais, volta a ele.
  F3  o aviso "a sacola pode ter ficado VAZIA" só sai quando o robô tirou algo do carrinho nesta rodada e a TV
      não voltou a ser conferida; sem remoção, o log diz "carrinho intacto".
  F4  o passo final também reaplica o melhor cupom ACEITO naquele anúncio nas últimas 48 h (a aplicação confere
      de novo; recusado agora fica gravado e o carrinho fica sem cupom, como já era).
  F5  opções do catálogo do ML que a página LOGADA mostra (o coletor anônimo vê 1 de 2) ficam no estado
      (reg["opcoes_catalogo"]) e viram anúncios nas próximas 24 h, com as travas da coleta; G4: só quando a página
      mostra um título legível da TV do modelo, com o tamanho.
  Os anúncios da F1 e da F5 passam pela MESMA checagem de confiança das ofertas da coleta (revisão de 26/09): vendedor
  reprovado (lista curada ou automático), ou desconhecido muito abaixo da loja confiável mais barata do mesmo modelo,
  fica de fora; anúncio que a coleta desta rodada barrou não volta pelo estado.

Dois modelos (pedido do usuário em 26/09: "coloque as duas, uma de cada modelo"): 55C6K e 65C6K. Os anúncios vêm
separados pelo campo 'modelo' da coleta (registro sem o campo = 55C6K). Os cupons são testados em cada modelo, do
anúncio mais barato ao mais caro. O cupom vale para o pedido inteiro, então para medir um cupom num modelo o anúncio
fica SOZINHO no carrinho (a TV do outro modelo sai só se o testador conhece um anúncio dela para devolver). No fim
da rodada o carrinho fica com UMA TV DE CADA MODELO (o anúncio mais barato de cada um, ou o do melhor cupom quando
ele compensa, 1 unidade cada) e o melhor cupom do pedido. A mensagem traz o melhor Pix e o melhor parcelado de cada
modelo, com o alvo de cada um (55C6K: Pix R$ 2.900 / parcelado R$ 3.000; 65C6K: Pix R$ 3.300 / parcelado R$ 3.500).
Regras: no máximo 1 unidade de cada modelo, nunca duas linhas do mesmo modelo, nunca outro produto; Amazon só
leitura; anúncio suspeito ou reprovado (monitor.confianca.pode_ir_ao_carrinho) nunca vai ao carrinho.

O robô nunca avança para pagamento nem digita dados de conta. Só aplica cupom, lê o total e remove.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from run import carrega_env  # noqa: E402

carrega_env()

from monitor import config, notificar  # noqa: E402
from monitor.carrinho import (  # noqa: E402
    LOJAS, MODELO_PADRAO, MODELOS, CarrinhoOcupado, LojaCarrinho, LojaIndisponivel, PrecisaLogin, ResultadoCupom,
    abrir_chrome_normal, abrir_navegador, eh_do_modelo, falha_da_ferramenta, modelo_da_oferta, norm_vendedor,
)
from monitor.filtro import eh_55c6k  # noqa: E402
from monitor.trava import PerfilOcupado, trava_perfil  # noqa: E402
from monitor.util import TZ_BR, agora, agora_iso, fmt_preco, hoje, loja_canonica  # noqa: E402

ARQ_ESTADO = config.DIR_DADOS / "cupons_carrinho.json"
CODIGOS_IGNORAR = {"DIRETO NO LINK", "SEM CUPOM", "LINK"}
MAX_POR_RODADA = 25
TTL_RECUSADO = timedelta(hours=24)       # recusa da loja vale por um dia; depois o cupom é testado de novo
RE_CUPOM_DE_HORARIO = re.compile(r"\d{1,2}H$")  # DIADOCLIENTE14H: só funciona na janela daquela hora
MAX_ERROS_SEGUIDOS = 3                   # falhas seguidas do robô num anúncio: para e tenta na próxima rodada
PAUSA_LOJA_INDISPONIVEL = timedelta(hours=3)  # carrinho não carregou: deixa a loja em paz um tempo
MAX_APLICACOES_POR_RODADA = 15           # somando todos os anúncios da loja: rajada grande dispara o antirrobô
PAUSA_ENTRE_ANUNCIOS_MS = 5000           # a loja não gosta de rajada
PRAZO_RODADA_S = 12 * 60                 # o cão de guarda mata o processo em 17 min: não começa nada novo depois disto
# o passo final (arrumar_carrinho) abre até 3 janelas novas do Chrome; os 3 min entre PRAZO_RODADA_S e este
# prazo são a reserva dele. Depois daqui ele não abre mais nada: o cão de guarda mata em 17 min e o
# run_pc.ps1 dá 1080 s para o testador inteiro — morrer no meio deixaria a sacola como estivesse.
PRAZO_PASSO_FINAL_S = 15 * 60
JANELA_ANUNCIO_DO_ESTADO = timedelta(hours=24)       # F1: anúncio lido pelo testador que ainda vale sem coleta
JANELA_OPCAO_DO_CATALOGO = timedelta(hours=24)       # F5: opção do catálogo vista logado que ainda vale
JANELA_ACEITE_NO_PASSO_FINAL = timedelta(hours=48)   # F4: aceite que o passo final ainda tenta reaplicar
# revisão de 26/09: TV de um modelo que o robô tirou do carrinho e não voltou (reg["tvs_fora"]) é devolvida nas rodadas
# seguintes, mesmo sem cupom pendente; desiste depois de tantas tentativas ou desse tempo (o aviso já foi dado)
JANELA_DEVOLVER_TV = timedelta(hours=24)
MAX_TENTATIVAS_DEVOLVER = 3
_RE_55 = re.compile(r"(?<!\d)55(?!\d)")

_INICIO: Optional[float] = None          # time.monotonic() do começo da rodada (executar)
AVISOS_CARRINHO: list[str] = []          # avisos da rodada que vão na mensagem mesmo sem cupom aceito


def _tempo_esgotado(prazo: float = PRAZO_RODADA_S) -> bool:
    """Passou do prazo da rodada? (o mesmo relógio para percorrer() e para o passo final)"""
    return _INICIO is not None and time.monotonic() - _INICIO > prazo


def status_do_registro(reg: dict) -> str:
    """Status gravado; registros antigos (só com 'aceito') são reclassificados pela mensagem."""
    st = reg.get("status")
    if st in ("aceito", "recusado", "erro"):
        return st
    if reg.get("aceito"):
        return "aceito"
    return "erro" if falha_da_ferramenta(reg.get("mensagem") or "") else "recusado"


def _quando(iso: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(iso or "")
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ_BR)


def _momento_do_registro(reg: Optional[dict]) -> datetime:
    return _quando((reg or {}).get("testado_em")) or datetime.min.replace(tzinfo=TZ_BR)


def precisa_testar(codigo: str, reg: dict | None, momento: datetime | None = None) -> bool:
    """Decide se o cupom volta para a fila deste anúncio.

    - nunca testado ou 'erro' (o robô falhou, a loja não respondeu): testa de novo;
    - 'aceito': de novo no dia seguinte (o desconto pode mudar);
    - 'recusado': de novo depois de 24 h; cupom de horário (…14H), a cada hora nova.
    """
    if not reg:
        return True
    momento = momento or agora()
    st = status_do_registro(reg)
    if st == "erro":
        return True
    quando = _quando(reg.get("testado_em"))
    if quando is None:
        return True
    quando = quando.astimezone(momento.tzinfo or TZ_BR)
    if st == "aceito":
        return quando.date() < momento.date()
    if RE_CUPOM_DE_HORARIO.search(codigo.upper()):
        return (quando.date(), quando.hour) != (momento.date(), momento.hour)
    return momento - quando >= TTL_RECUSADO


def aceito_valido(codigo: str, reg: dict | None, momento: datetime | None = None, mesma_hora: bool = True) -> bool:
    """O cupom foi aceito neste anúncio e o aceite ainda vale: mesmo dia; cupom de horário, mesma hora
    (`mesma_hora=False`: basta o anúncio não precisar de novo teste, como em precisa_testar)."""
    if not reg or status_do_registro(reg) != "aceito":
        return False
    momento = momento or agora()
    if precisa_testar(codigo, reg, momento):
        return False
    if mesma_hora and RE_CUPOM_DE_HORARIO.search(codigo.upper()):
        q = _momento_do_registro(reg).astimezone(momento.tzinfo or TZ_BR)
        return (q.date(), q.hour) == (momento.date(), momento.hour)
    return True


def _recente(iso: Optional[str], momento: datetime, janela: timedelta) -> bool:
    """O horário gravado está dentro da janela (e não no futuro, além de uma folga de relógio)?"""
    q = _quando(iso)
    return q is not None and timedelta(minutes=-5) <= momento - q <= janela


def aceito_recente(codigo: str, reg: dict | None, momento: datetime | None = None,
                   janela: timedelta = JANELA_ACEITE_NO_PASSO_FINAL) -> bool:
    """F4 (22/09): o cupom foi aceito neste anúncio nas últimas `janela` (48 h) e pode voltar no passo final.

    Em 22/09 10:12 o INFLU300 (aceito em 21/09 19:42, R$ 300 de desconto, ainda valendo) não voltou para o
    carrinho porque o passo final só olhava aceites de hoje. A reaplicação no passo final é o próprio teste:
    se a loja recusar agora, a recusa é gravada e o carrinho fica sem cupom. Cupom de horário (…14H) continua
    valendo só na mesma hora do aceite, como antes."""
    if not reg or status_do_registro(reg) != "aceito":
        return False
    momento = momento or agora()
    if RE_CUPOM_DE_HORARIO.search(codigo.upper()):
        return aceito_valido(codigo, reg, momento)
    return _recente(reg.get("testado_em"), momento, janela)


# ------------------------------------------------------------------------------------------------
# anúncios da loja
# ------------------------------------------------------------------------------------------------

@dataclass
class Anuncio:
    """Um anúncio (anúncio + vendedor) da TV numa loja, como a coleta gravou no latest_<modo>.json."""

    chave: str                          # identidade estável (Magalu '<id /p/>-<vendedor>', ML 'MLB…', Amazon '<ASIN>-<vendedor>')
    url: str
    vendedor: str
    preco: float                        # menor preço lido (Pix ou cartão): define a ordem de teste
    preco_cartao: Optional[float] = None
    vendedor_id: Optional[str] = None
    item_id: Optional[str] = None       # ML: o item MLB… deste vendedor
    produto: Optional[str] = None       # anúncio sem o vendedor (Magalu: id do /p/)
    catalogo: str = ""                  # ML: catálogo MLB… da URL
    # de onde veio: "coleta" (latest_<modo>.json), "estado" (lido pelo testador numa rodada anterior, F1) ou
    # "catalogo_logado" (opção do catálogo do ML vista pela página logada, F5)
    origem: str = "coleta"
    modelo: str = MODELO_PADRAO         # 55C6K ou 65C6K (campo 'modelo' da coleta; sem ele, 55C6K)
    # cupom da página do próprio anúncio (campo 'cupom' da oferta, ex. LU300 no Magalu 1P): testado primeiro nele
    cupom: Optional[str] = None
    # reconhece as chaves antigas do estado (fim da URL) que são deste anúncio
    antiga: Optional[Callable[[str, dict], bool]] = field(default=None, repr=False, compare=False)

    @property
    def rotulo(self) -> str:
        return f"{self.vendedor or '?'} [{self.chave}]"

    def alvo(self, ids_tv: Iterable[str] = (), contexto: Optional[dict] = None) -> dict:
        """O que o adaptador do carrinho precisa para achar ESTE anúncio (ver monitor.carrinho). `contexto`: o que a
        loja sabe dos dois modelos (ids_modelo: id do anúncio -> modelo; restauraveis: modelos com anúncio conhecido,
        cuja TV o testador consegue devolver ao carrinho depois de tirá-la para medir um cupom)."""
        ctx = contexto or {}
        return {"chave": self.chave, "url": self.url, "vendedor": self.vendedor or None,
                "vendedor_id": self.vendedor_id, "item_id": self.item_id, "produto": self.produto,
                "catalogo": self.catalogo, "preco": self.preco, "preco_cartao": self.preco_cartao,
                "ids_tv": sorted(set(ids_tv)), "modelo": self.modelo,
                "ids_modelo": dict(ctx.get("ids_modelo") or {}), "restauraveis": sorted(ctx.get("restauraveis") or ())}


def _eh_a_tv(titulo: str, modelo: str = MODELO_PADRAO) -> bool:
    """Só a TV do modelo, com o tamanho no título (55C6K de 55", 65C6K de 65"; nada de outro tamanho, kit, peça,
    controle ou modelo vizinho)."""
    if modelo == MODELO_PADRAO:
        return eh_55c6k(titulo) and bool(_RE_55.search(titulo))
    return eh_do_modelo(titulo, modelo)


def contexto_do_carrinho(anuncios: Iterable[Anuncio]) -> dict:
    """ids_modelo (id do /p/ do Magalu ou item MLB… do ML -> modelo) e restauraveis (modelos com anúncio conhecido na
    loja) para os adaptadores do carrinho."""
    ids: dict = {}
    modelos: set = set()
    for a in anuncios:
        modelos.add(a.modelo)
        for k in (a.produto, a.item_id):
            if k:
                ids[str(k)] = a.modelo
    return {"ids_modelo": ids, "restauraveis": sorted(modelos)}


def por_modelo(anuncios: Iterable[Anuncio]) -> dict[str, list[Anuncio]]:
    """{modelo: anúncios dele, do mais barato ao mais caro}, na ordem de MODELOS, só os modelos com anúncio."""
    lista = list(anuncios)
    return {m: [a for a in lista if a.modelo == m] for m in MODELOS if any(a.modelo == m for a in lista)}


def anuncio_da_oferta(loja: LojaCarrinho, o: dict) -> Optional[Anuncio]:
    """Oferta do latest (contrato: tipo 'loja', um id por anúncio+vendedor, campo 'modelo') -> Anuncio, ou None se não
    serve. O título, quando há, tem de ser a TV do MESMO modelo: título que diz outro tamanho (como o anúncio de 25/09
    que dizia 55" na opção de 65") não vai ao carrinho."""
    url = o.get("url") or ""
    if o.get("tipo", "loja") != "loja" or not o.get("ativo", True) or loja.dominio_url not in url:
        return None
    if (o.get("extra") or {}).get("vendedor_conferido") is False:
        # ML: anúncio fora do catálogo cujo vendedor a coleta não conferiu (vendas, página do anúncio).
        # Não vai para o carrinho da pessoa nem para a mensagem "é só entrar e finalizar".
        return None
    modelo = modelo_da_oferta(o)
    if modelo not in MODELOS:
        return None
    titulo = o.get("titulo") or ""
    if titulo and not _eh_a_tv(titulo, modelo):
        return None
    precos = [float(v) for v in (o.get("melhor_preco"), o.get("preco"), o.get("preco_pix"))
              if isinstance(v, (int, float)) and v > 0]
    if not precos:
        return None
    ident = loja.identidade(o)
    if not ident.get("chave"):
        return None
    cartao = o.get("preco")
    a = Anuncio(chave=ident["chave"], url=url, vendedor=(o.get("vendedor") or "").strip(), preco=min(precos),
                preco_cartao=float(cartao) if isinstance(cartao, (int, float)) and cartao > 0 else None,
                vendedor_id=ident.get("vendedor_id"), item_id=ident.get("item_id"), produto=ident.get("produto"),
                catalogo=ident.get("catalogo") or "", modelo=modelo,
                cupom=str(o["cupom"]).strip().upper() if o.get("cupom") else None)
    alvo = a.alvo()
    a.antiga = lambda sufixo, reg: loja.eh_chave_antiga(sufixo, reg, alvo)
    return a


def _oferta_do_registro(loja: LojaCarrinho, chave: str, v: dict) -> Optional[dict]:
    """O registro que o testador gravou no estado (reg["precos"] ou reg["opcoes_catalogo"]) no formato de uma oferta do
    latest (o que anuncio_da_oferta e a checagem de confiança leem). Registro sem 'modelo' (gravado antes de 26/09) é da
    55C6K."""
    if not isinstance(v, dict) or not v.get("url"):
        return None
    if "preco" in v or "preco_pix" in v:           # opção do catálogo (F5): preço de cartão e Pix da página
        cartao, pix = v.get("preco"), v.get("preco_pix")
    elif "sem_cupom_pix" in v or "sem_cupom_cartao" in v:   # leitura do carrinho sem cupom (F1)
        cartao, pix = v.get("sem_cupom_cartao"), v.get("sem_cupom_pix")
    else:                                          # leitura antiga (pode ser com cupom: só serve para a ordem)
        cartao, pix = v.get("tv_cartao"), v.get("tv_pix")
    o = {"tipo": "loja", "ativo": True, "loja": loja.loja_canonica, "url": v["url"], "id": chave,
         "titulo": v.get("titulo") or "", "vendedor": v.get("vendedor") or "", "preco": cartao, "preco_pix": pix,
         "modelo": modelo_da_oferta(v)}
    extra: dict = {}
    if v.get("item_id"):
        extra.update(item_id=v["item_id"], anuncio=v["item_id"], catalogo=v.get("catalogo"))
    if v.get("vendedor_id"):
        extra["vendedor_id"] = v["vendedor_id"]
    if extra:
        o["extra"] = extra
    return o


def _anuncio_do_registro(loja: LojaCarrinho, chave: str, v: dict, origem: str,
                         barrar: Optional[Callable[[dict, Anuncio], Optional[str]]] = None) -> Optional[Anuncio]:
    """Anúncio a partir do que o testador gravou no estado, com as mesmas travas de anuncio_da_oferta (domínio da loja,
    título da TV do modelo quando há título, preço > 0) e, com `barrar`, a mesma checagem de confiança das ofertas da
    coleta (revisão de 26/09): `barrar(oferta, anúncio)` devolve o motivo quando ele não pode ir ao carrinho."""
    o = _oferta_do_registro(loja, chave, v)
    a = anuncio_da_oferta(loja, o) if o is not None else None
    if a is None:
        return None
    motivo = barrar(o, a) if barrar is not None else None
    if motivo:
        qual = "a opção do catálogo vista logado" if origem == "catalogo_logado" else "o anúncio lido numa rodada anterior"
        print(f"[{loja.nome}] ignoro {qual} {a.rotulo}: {motivo[:200]}")
        return None
    a.origem = origem
    return a


def anuncios_do_estado(loja: LojaCarrinho, reg: Optional[dict], coletados: list[Anuncio],
                       momento: Optional[datetime] = None,
                       barrar: Optional[Callable[[dict, Anuncio], Optional[str]]] = None) -> list[Anuncio]:
    """Anúncios que o próprio testador conhece, além dos da coleta.

    F1: quando a coleta desta rodada não trouxe NENHUM anúncio da loja de um modelo (falhou ou foi bloqueada), valem
        os anúncios DESSE modelo que o testador leu no carrinho nas últimas 24 h (reg["precos"], com URL e lido_em).
    F5: opções do catálogo do ML vistas pela página logada nas últimas 24 h (reg["opcoes_catalogo"]), sempre
        que a coleta não tiver o mesmo item (a coleta anônima só enxerga 1 das 2 opções). Preço impossível para
        esta TV (_preco_plausivel da coleta: piso de peça e 2,5x acima dos outros anúncios do mesmo modelo) fica
        de fora.
    `barrar` (codigos_conhecidos): a checagem de confiança das ofertas da coleta, aplicada também a estes anúncios
    (revisão de 26/09: vendedor reprovado, ou desconhecido muito abaixo da loja confiável do mesmo modelo, nunca vai ao
    carrinho, venha da coleta, da leitura de uma rodada anterior ou da página logada)."""
    if not reg:
        return []
    from monitor.sources.playwright_sources import _preco_plausivel

    momento = momento or agora()
    ja = {a.chave for a in coletados}
    com_coleta = {a.modelo for a in coletados}
    out: list[Anuncio] = []
    for chave, v in (reg.get("precos") or {}).items():
        if not isinstance(v, dict) or modelo_da_oferta(v) in com_coleta or \
                not _recente(v.get("lido_em"), momento, JANELA_ANUNCIO_DO_ESTADO):
            continue
        a = _anuncio_do_registro(loja, chave, v, "estado", barrar)
        if a is not None and a.chave not in ja:
            out.append(a)
            ja.add(a.chave)
    opcoes = [(k, v) for k, v in (reg.get("opcoes_catalogo") or {}).items()
              if isinstance(v, dict) and _recente(v.get("visto_em"), momento, JANELA_OPCAO_DO_CATALOGO)]
    candidatas = [a for a in (_anuncio_do_registro(loja, k, v, "catalogo_logado", barrar) for k, v in opcoes) if a]
    conhecidos = coletados + out
    for a in candidatas:
        if a.chave in ja:
            continue   # a coleta (ou a leitura do carrinho) do mesmo item vale mais
        refs = [b.preco for b in conhecidos if b.preco and b.modelo == a.modelo]
        outras = refs or [b.preco for b in candidatas if b is not a and b.preco and b.modelo == a.modelo]
        if not _preco_plausivel(a.preco, outras):
            print(f"[{loja.nome}] opção do catálogo {a.rotulo} a {fmt_preco(a.preco)}: preço impossível para esta TV; "
                  "não uso")
            continue
        out.append(a)
        ja.add(a.chave)
    return out


def carrega_estado() -> dict:
    if ARQ_ESTADO.exists():
        try:
            return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def salva_estado(d: dict) -> None:
    config.DIR_DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def codigos_conhecidos(loja: LojaCarrinho, reg: Optional[dict] = None,
                       momento: Optional[datetime] = None) -> tuple[list[str], list[Anuncio]]:
    """Cupons da loja (Promobit, Pelando, etiquetas, postagens, CUPONS_EXTRA) e TODOS os anúncios ativos dela.

    Anúncios: um por anúncio+vendedor (a mesma chave nas duas coletas vira um só, com a leitura mais
    barata), do mais barato ao mais caro, cada um com o seu modelo (campo 'modelo'; sem ele, 55C6K). Sem teto
    fixo: o limite é por rodada (loja.max_anuncios, por modelo).
    Com o estado da loja (`reg`), entram também os anúncios que o testador conhece (anuncios_do_estado: F1 e
    F5). Sem anúncio nenhum, a lista volta VAZIA: não existe mais "anúncio padrão" (F1, 22/09).
    Os cupons são da loja (valem para os dois modelos). A checagem de confiança compara cada anúncio com as ofertas
    do MESMO modelo (a 65" custa mais: um golpe na 65" não pode passar por estar perto do preço da 55"), e vale também
    para os anúncios do estado (F1/F5): um anúncio que a coleta desta rodada barrou não volta por eles."""
    import os

    from monitor.confianca import cupom_barrado, pode_ir_ao_carrinho, reprovados_auto_dos_arquivos

    cods: dict[str, str] = {}
    anuncios: dict[str, Anuncio] = {}
    barrados: set[str] = set()     # chaves dos anúncios que a checagem de confiança barrou nesta rodada
    latests = [_json(config.DIR_DADOS / arq) for arq in ("latest_cloud.json", "latest_pc.json")]
    # referência de preço para o registro sem veredito (gravado antes da checagem de confiança existir)
    todas = [o for d in latests for o in d.get("ofertas_loja") or [] if isinstance(o, dict)]
    do_modelo = {m: [o for o in todas if modelo_da_oferta(o) == m] for m in {modelo_da_oferta(o) for o in todas}}
    auto = reprovados_auto_dos_arquivos()
    for d in latests:
        for c in d.get("cupons") or []:
            if loja_canonica(c.get("loja", "")) == loja.loja_canonica and c.get("codigo"):
                motivo = cupom_barrado(c, todas, auto)
                if motivo:  # cupom da página de anúncio reprovado/suspeito (latest gravado antes do filtro)
                    print(f"[{loja.nome}] ignoro o cupom {c['codigo']}: {motivo[:160]}")
                    continue
                cods.setdefault(c["codigo"].strip().upper(), c.get("fonte", ""))
        for p in d.get("posts") or []:
            if loja_canonica(p.get("loja", "")) == loja.loja_canonica and p.get("cupom"):
                cods.setdefault(str(p["cupom"]).strip().upper(), p.get("fonte", ""))
        for o in d.get("ofertas_loja") or []:
            if loja_canonica(o.get("loja", "")) != loja.loja_canonica:
                continue
            # só anúncio confiável ou sem risco aparente vai ao carrinho da pessoa; suspeito/reprovado nunca (nem o
            # cupom da página dele entra na fila)
            ok, motivo = pode_ir_ao_carrinho(o, do_modelo.get(modelo_da_oferta(o), []), auto)
            if not ok:
                print(f"[{loja.nome}] ignoro {o.get('vendedor')} ({o.get('id')}): {motivo[:200]}")
                barrados.update(_chaves_da_oferta(loja, o))
                continue
            if o.get("cupom"):
                cods.setdefault(str(o["cupom"]).strip().upper(), "produto")
            a = anuncio_da_oferta(loja, o)
            if a is None:
                continue
            atual = anuncios.get(a.chave)
            if atual is None or a.preco < atual.preco:
                anuncios[a.chave] = a
    for c in os.environ.get("CUPONS_EXTRA", "").split(","):
        if c.strip():
            cods.setdefault(c.strip().upper(), "manual")
    lista = [c for c in cods if 3 <= len(c) <= 30 and c not in CODIGOS_IGNORAR and " " not in c]
    coletados = sorted(anuncios.values(), key=lambda a: a.preco)

    def barrar(o: dict, a: Anuncio) -> Optional[str]:
        """A mesma checagem das ofertas da coleta, para o anúncio do estado (F1/F5)."""
        if a.chave in barrados or str(o.get("id") or "") in barrados:
            return "a checagem de confiança da coleta desta rodada barrou este anúncio"
        ok, motivo = pode_ir_ao_carrinho(o, do_modelo.get(modelo_da_oferta(o), []), auto)
        return None if ok else (motivo or "anúncio barrado pela checagem de confiança")

    ordenados = sorted(coletados + anuncios_do_estado(loja, reg, coletados, momento, barrar), key=lambda a: a.preco)
    return lista, ordenados


def _chaves_da_oferta(loja: LojaCarrinho, o: dict) -> set[str]:
    """Chaves com que um anúncio da coleta pode aparecer no estado do testador: o id da oferta e a chave do anúncio
    (loja.identidade), quando a oferta é desta loja."""
    out = {str(o.get("id"))} if o.get("id") else set()
    if loja.dominio_url and loja.dominio_url in (o.get("url") or ""):
        try:
            chave = loja.identidade(o).get("chave")
        except Exception:  # noqa: BLE001 - oferta fora do formato: fica só o id
            chave = None
        if chave:
            out.add(str(chave))
    return out


# ------------------------------------------------------------------------------------------------
# estado por anúncio e fila
# ------------------------------------------------------------------------------------------------

def registro_do_cupom(testados: dict, codigo: str, anuncio) -> Optional[dict]:
    """Registro do cupom neste anúncio: chave '<CÓDIGO>@<chave do anúncio>' ou, se ainda não houver, o mais
    recente das chaves antigas (fim da URL, antes de 19/09) que são deste MESMO anúncio. Assim a troca de
    chave não faz o robô retestar de uma vez tudo o que já foi recusado."""
    chave = anuncio.chave if isinstance(anuncio, Anuncio) else str(anuncio)
    reg = testados.get(f"{codigo}@{chave}")
    if reg is not None or not isinstance(anuncio, Anuncio) or anuncio.antiga is None:
        return reg
    prefixo = f"{codigo}@"
    antigos = [v for k, v in testados.items()
               if k.startswith(prefixo) and isinstance(v, dict) and anuncio.antiga(k[len(prefixo):], v)]
    return max(antigos, key=_momento_do_registro) if antigos else None


def ordenar_fila(fila: list[str], testados: dict, chave_anuncio: str, anuncio: Optional[Anuncio] = None) -> list[str]:
    """Ordem de teste quando não dá para testar tudo numa rodada.

    1) cupom de horário (…14H): a janela dele é agora ou nunca;  2) nunca testado, e entre eles primeiro o cupom da
    página do próprio anúncio (26/09: o LU300 do Magalu 1P da 65C6K ficava atrás de 20 códigos genéricos num anúncio
    novo, com 29 pendentes e ~9 testes por rodada);  3) 'erro' do robô;  4) recusa antiga que venceu o prazo.
    """
    proprio = getattr(anuncio, "cupom", None)

    def peso(c: str) -> float:
        reg = registro_do_cupom(testados, c, anuncio if anuncio is not None else chave_anuncio)
        if RE_CUPOM_DE_HORARIO.search(c.upper()):
            return 0
        if not reg:
            return 0.5 if proprio and c.upper() == proprio else 1
        return 2 if status_do_registro(reg) == "erro" else 3

    return sorted(fila, key=peso)


def aceito_em_mais_barato(codigo: str, mais_baratos: list[Anuncio], testados: dict, momento: datetime,
                          desde: Optional[datetime] = None) -> Optional[Anuncio]:
    """Anúncio mais barato em que o cupom foi aceito e o aceite ainda vale (com `desde`, só aceites a partir
    dele: com --forcar vale só o que foi testado nesta rodada).

    Cupom de horário aceito mais cedo hoje também tira o cupom dos mais caros: ou ainda vale (e o mais barato
    ganha) ou a janela passou (e ele seria recusado)."""
    for b in mais_baratos:
        reg = registro_do_cupom(testados, codigo, b)
        if aceito_valido(codigo, reg, momento, mesma_hora=False) and \
                (desde is None or _momento_do_registro(reg) >= desde):
            return b
    return None


def pendentes(anuncios: list[Anuncio], i: int, fila_base: list[str], testados: dict, momento: datetime,
              forcar: bool = False, explicitos: bool = False,
              desde: Optional[datetime] = None) -> tuple[list[str], dict[str, Anuncio]]:
    """Fila do anúncio i, calculada ANTES de mexer no carrinho.

    Entra o cupom que precisa de teste neste anúncio (precisa_testar; com --forcar/--codigos, todos),
    menos os já aceitos (e válidos) num anúncio mais barato. Recusa ou erro no mais barato não tira o
    cupom daqui: "troque de anúncio se não funcionar nos mais baratos". Devolve (fila, {código: anúncio
    mais barato onde já foi aceito})."""
    a = anuncios[i]
    fila: list[str] = []
    pulados: dict[str, Anuncio] = {}
    for c in fila_base:
        if not (forcar or explicitos) and not precisa_testar(c, registro_do_cupom(testados, c, a), momento):
            continue
        b = aceito_em_mais_barato(c, anuncios[:i], testados, momento, desde if forcar else None)
        if b is not None:
            pulados[c] = b
            continue
        fila.append(c)
    return fila, pulados


def _sem_repetir(codigos: Iterable[str]) -> list[str]:
    vistos: list[str] = []
    for c in codigos:
        c = (c or "").strip().upper()
        if c and c not in vistos:
            vistos.append(c)
    return vistos


# ------------------------------------------------------------------------------------------------
# mensagem
# ------------------------------------------------------------------------------------------------

def _onde(nome: str, r: ResultadoCupom) -> str:
    vend = str(r.extra.get("vendedor") or "").strip()
    return f"{nome} (vendido por {vend})" if vend and norm_vendedor(vend) not in norm_vendedor(nome) else nome


def _quando_foi_aceito(r: ResultadoCupom) -> str:
    """' (aceito mais cedo, hoje)' ou, para um aceite de outro dia que o passo final reaplicou (F4),
    ' (aceito em 21/09 19:42)'."""
    if not r.extra.get("anterior"):
        return ""
    q = _quando(r.extra.get("aceito_em"))
    if q is None or q.astimezone(TZ_BR).date() == agora().astimezone(TZ_BR).date():
        return " (aceito mais cedo, hoje)"
    return f" (aceito em {q.astimezone(TZ_BR):%d/%m %H:%M})"


def alvos_do_modelo(modelo: str) -> tuple[float, float]:
    """(alvo Pix, alvo parcelado) do modelo, os mesmos da coleta e do painel: 55C6K config.ALVO_PIX / ALVO_PARCELADO
    (R$ 2.900 / R$ 3.000); 65C6K config.ALVO_PIX_65 / ALVO_PARCELADO_65 (R$ 3.300 / R$ 3.500, decisão de 26/09)."""
    return float(config.alvo_pix(modelo)), float(config.alvo_parcelado(modelo))


def _modelo_do_resultado(r: ResultadoCupom) -> str:
    return str((r.extra or {}).get("modelo") or MODELO_PADRAO).upper()


def msg_melhor(resultados: list[tuple[str, ResultadoCupom]]) -> str:
    """Uma mensagem só, com o melhor preço à vista e o melhor parcelado entre todas as lojas e anúncios, de CADA
    modelo (55C6K e 65C6K), com o alvo de cada um.

    Cupom marcado por marcar_se_compensa (não deixa a TV mais barata que o anúncio mais barato da loja sem cupom)
    não disputa o melhor à vista (pior_a_vista) nem o melhor parcelado (pior_parcelado); se nenhum cupom
    compensa, não há mensagem. Só a 55C6K: o formato de sempre (sem o cabeçalho do modelo)."""
    presentes = {_modelo_do_resultado(r) for _, r in resultados}
    blocos = []
    for m in [*MODELOS, *sorted(presentes - set(MODELOS))]:
        linhas, meta = _bloco_do_modelo(m, [(n, r) for n, r in resultados if _modelo_do_resultado(r) == m])
        if linhas:
            blocos.append((m, linhas, meta))
    if not blocos:
        return ""
    topo = ["🎯 <b>META ATINGIDA</b>" if any(b[2] for b in blocos) else "✅ <b>Cupom funcionou</b>", ""]
    if len(blocos) == 1 and blocos[0][0] == MODELO_PADRAO:
        return "\n".join(topo + blocos[0][1])
    out = topo
    for k, (m, linhas, meta) in enumerate(blocos):
        if k:
            out.append("")
        out.append(("🎯 " if meta else "📺 ") + f"<b>{NOME_MODELO.get(m, m)}</b>")
        out += linhas
    return "\n".join(out)


def _bloco_do_modelo(modelo: str, resultados: list[tuple[str, ResultadoCupom]]) -> tuple[list[str], bool]:
    """Linhas da mensagem de UM modelo (melhor à vista, melhor parcelado, outros, alvo, carrinho) e se o alvo foi
    atingido. Sem cupom que compense, ([], False)."""
    alvo_pix, alvo_parc = alvos_do_modelo(modelo)
    validos = [(n, r) for n, r in resultados if r.aceito and (r.tv_pix or r.tv_cartao)]
    vista = [(n, r) for n, r in validos if not r.extra.get("pior_a_vista")]
    com_parcela = [(n, r) for n, r in validos if r.parcelado and r.tv_cartao and not r.extra.get("pior_parcelado")]
    if not vista and not com_parcela:
        return [], False
    melhor_vista = min(vista, key=lambda x: x[1].tv_pix or x[1].tv_cartao or 9e9) if vista else None
    melhor_parc = min(com_parcela, key=lambda x: x[1].tv_cartao or 9e9) if com_parcela else None
    principal = melhor_vista or melhor_parc

    r = principal[1]
    alvo = bool((melhor_vista is not None and r.tv_pix is not None and r.tv_pix <= alvo_pix) or
                (melhor_parc and (melhor_parc[1].tv_cartao or 9e9) <= alvo_parc))
    linhas: list[str] = []
    if melhor_vista:
        linhas.append(f"<b>Melhor à vista</b>: {fmt_preco(r.tv_pix or r.tv_cartao)} na {_onde(*melhor_vista)} "
                      f"com <code>{r.codigo}</code>" + _quando_foi_aceito(r))
        if r.extra.get("antes_pix") and r.frete is not None:
            antes = round((r.extra["antes_pix"] - r.frete) / max(1, r.quantidade), 2)  # de UMA TV, como tv_pix
            if antes > (r.tv_pix or 0):
                linhas.append(f"   antes {fmt_preco(antes)}, economia de {fmt_preco(antes - (r.tv_pix or 0))}")
    if melhor_parc:
        p = melhor_parc[1]
        linhas.append(f"<b>Melhor parcelado</b>: {fmt_preco(p.tv_cartao)} em {p.parcelado_real} na {_onde(*melhor_parc)} "
                      f"com <code>{p.codigo}</code>")
    outros = [f"{_onde(n, x)}: {fmt_preco(x.tv_pix or x.tv_cartao)} ({x.codigo})" for n, x in
              sorted((v for v in validos if v[1] is not r),
                     key=lambda x: x[1].tv_pix or x[1].tv_cartao or 9e9)[:4]]
    if outros:
        linhas.append("")
        linhas.append("Outros que funcionaram: " + " · ".join(outros))
    linhas.append("")
    linhas.append(f"Alvo: Pix {fmt_preco(alvo_pix)} · parcelado {fmt_preco(alvo_parc)}")
    # só afirma que o cupom ficou no carrinho quando o passo final foi conferido (ver testar_loja)
    if r.extra.get("no_carrinho") is True and r.extra.get("pedido"):
        linhas.append(f"O cupom <code>{r.codigo}</code> ficou aplicado no carrinho da {principal[0]}, com uma TV de "
                      "cada modelo (o cupom vale para o pedido); confira o total antes de finalizar.")
    elif r.extra.get("no_carrinho") is True:
        linhas.append(f"O cupom <code>{r.codigo}</code> ficou aplicado no carrinho da {principal[0]}, "
                      "só com a TV; é só entrar e finalizar.")
    elif r.extra.get("no_carrinho") is False and r.extra.get("motivo_carrinho") == MOTIVO_OUTRO_CUPOM:
        linhas.append(f"O carrinho da {principal[0]} tem uma TV de cada modelo e ficou com o cupom "
                      f"<code>{r.extra.get('cupom_do_pedido')}</code> (vale um cupom por pedido); para esta TV sozinha, "
                      f"o cupom é <code>{r.codigo}</code>.")
    elif r.extra.get("no_carrinho") is False and r.extra.get("motivo_carrinho") == MOTIVO_NAO_COMPENSA:
        linhas.append(f"Com o preço de agora, <code>{r.codigo}</code> não deixa a TV mais barata que o anúncio mais "
                      f"barato sem cupom da {principal[0]}; o carrinho ficou com ele, sem cupom.")
    elif r.extra.get("no_carrinho") is False:
        motivo = r.extra.get("motivo_carrinho") or "não deu para conferir"
        linhas.append(f"⚠️ Não consegui deixar o cupom aplicado no carrinho da {principal[0]} ({motivo}); "
                      f"aplique <code>{r.codigo}</code> à mão e confira o total antes de finalizar.")
    elif r.extra.get("so_leitura"):
        linhas.append(f"Na {principal[0]} o robô não monta o carrinho: marque o cupom na página do produto "
                      "e confira o total antes de finalizar.")
    return linhas, alvo


# ------------------------------------------------------------------------------------------------
# rodada de uma loja
# ------------------------------------------------------------------------------------------------

@dataclass
class Percurso:
    """O que aconteceu numa loja nesta rodada (sobrevive a exceção no meio do caminho)."""

    inicio: datetime
    orcamento: int = MAX_APLICACOES_POR_RODADA
    aceitos: list = field(default_factory=list)       # ResultadoCupom aceitos nesta rodada
    lidos: dict = field(default_factory=dict)         # chave do anúncio -> melhor leitura (sem cupom ou com)
    visitados: list = field(default_factory=list)     # chaves dos anúncios em que o robô abriu/mexeu no carrinho
    gravados: set = field(default_factory=set)        # chaves de estado escritas nesta rodada
    sem_cupom: dict = field(default_factory=dict)     # chave do anúncio -> leitura do carrinho sem cupom
    no_carrinho: Optional[str] = None                 # anúncio que está no carrinho agora (None: não se sabe)
    falhou: set = field(default_factory=set)          # anúncios que não entraram no carrinho nesta rodada
    # F3: loja.remocoes na última vez em que a TV foi conferida no carrinho (0 = o carrinho como a pessoa deixou)
    remocoes_conferidas: int = 0
    parou_por: Optional[str] = None                   # a rodada parou de mexer no carrinho (MOTIVO_PAROU_*)
    contexto: dict = field(default_factory=dict)      # contexto_do_carrinho: ids_modelo e restauraveis da loja
    # 26/09: modelos cuja TV o robô TIROU do carrinho (para isolar o outro modelo e medir um cupom) e que ainda não
    # foram conferidos de volta; o passo final devolve uma de cada e, se alguma não voltar, a pessoa é avisada
    modelos_fora: set = field(default_factory=set)
    removidos_vistos: int = 0                         # quantos de loja.removidos já passaram por modelos_fora
    conferidos: dict = field(default_factory=dict)    # modelo -> anúncio conferido no carrinho na última conferência
    # revisão de 26/09: modelos cuja TV saiu do carrinho numa rodada ANTERIOR e não voltou (reg["tvs_fora"]); saem daqui
    # quando a TV do modelo é conferida no carrinho nesta rodada (devolver_tvs_fora ou o passo final de sempre)
    fora_de_antes: set = field(default_factory=set)


MOTIVO_PAROU_OCUPADO = "o carrinho tem outro produto"          # não está vazio: sem aviso de sacola vazia
MOTIVO_PAROU_INDISPONIVEL = "a loja parou de responder"
MOTIVO_PAROU_LOGIN = "a sessão da loja expirou"


def _remocoes(loja) -> int:
    return int(getattr(loja, "remocoes", 0) or 0)


def _atualiza_fora(loja, p: Percurso, conferidos: Iterable[str] = ()) -> None:
    """Passa para p.modelos_fora os modelos das linhas que o adaptador tirou desde a última vez e tira de lá (e de
    p.fora_de_antes) os modelos cuja TV acabou de ser conferida no carrinho."""
    tirados = list(getattr(loja, "removidos", None) or [])
    p.modelos_fora |= {m for m in tirados[p.removidos_vistos:] if m in MODELOS}
    p.removidos_vistos = len(tirados)
    p.modelos_fora -= set(conferidos)
    p.fora_de_antes -= set(conferidos)


def _tv_conferida(loja, p: Percurso, chave: str, modelo: Optional[str] = None) -> None:
    """garantir_item conferiu a TV (anúncio `chave`) no carrinho, sozinha: o que foi tirado antes disto já não pesa
    para o aviso de sacola vazia (a TV do outro modelo que saiu continua em p.modelos_fora)."""
    p.no_carrinho = chave
    p.remocoes_conferidas = _remocoes(loja)
    p.conferidos = {modelo: chave} if modelo else {}
    _atualiza_fora(loja, p, [modelo] if modelo else [])


def _removeu_sem_conferir(loja, p: Percurso) -> bool:
    """F3: o robô tirou algo do carrinho depois da última vez em que a TV foi conferida lá (ou, sem nenhuma
    conferência, desde o começo da rodada)? Só aí a sacola pode ter ficado vazia."""
    return _remocoes(loja) > p.remocoes_conferidas


@contextmanager
def _sessao(loja: LojaCarrinho, visivel: bool):
    """Chrome do perfil da loja; devolve a página. Os testes trocam isto por uma página falsa."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel)
        try:
            yield ctx.pages[0] if ctx.pages else ctx.new_page()
        finally:
            ctx.close()


def _registra_leitura(p: Percurso, a: Anuncio, r: ResultadoCupom) -> None:
    atual = p.lidos.get(a.chave)
    if atual is None or (r.tv_pix or r.tv_cartao or 9e9) < (atual.tv_pix or atual.tv_cartao or 9e9):
        p.lidos[a.chave] = r


def _foto(page, loja_id: str) -> None:
    try:
        (RAIZ / "logs").mkdir(exist_ok=True)
        page.screenshot(path=str(RAIZ / "logs" / f"carrinho_{loja_id}.png"))
    except Exception:  # noqa: BLE001
        pass


def _ler_anuncio_so_leitura(loja: LojaCarrinho, page, a: Anuncio, p: Percurso, ids_tv) -> None:
    """Amazon: abre a página do anúncio/vendedor, lê o preço e marca o cupom de clicar, se houver."""
    if not loja.garantir_item(page, a.url, a.alvo(ids_tv, p.contexto)):
        print(f"[{loja.nome}] {a.rotulo}: não consegui ler este anúncio")
        return
    base = loja.ler_totais(page)
    base.codigo = "(sem cupom)"
    base.extra.update(anuncio=a.chave, vendedor=a.vendedor or base.extra.get("vendedor"), so_leitura=True,
                      modelo=a.modelo)
    p.sem_cupom[a.chave] = base
    _registra_leitura(p, a, base)
    print(f"[{loja.nome}] {a.rotulo}: Pix {fmt_preco(base.total_pix)} cartão {fmt_preco(base.total_cartao)}"
          + (f" · {base.parcelado}" if base.parcelado else ""))
    rot = loja.cupom_da_pagina(page) if hasattr(loja, "cupom_da_pagina") else None
    if not rot:
        print("  ℹ  sem cupom de clicar nesta página")
        return
    depois = loja.ler_totais(page)
    depois.codigo = "cupom da página"
    depois.aceito = bool(
        (depois.total_cartao and base.total_cartao and depois.total_cartao < base.total_cartao - 1)
        or (depois.total_pix and base.total_pix and depois.total_pix < base.total_pix - 1))
    depois.mensagem = rot
    depois.extra.update(so_leitura=True, anuncio=a.chave, vendedor=base.extra.get("vendedor"),  # nada vai ao carrinho
                        modelo=a.modelo)
    print(f"  {'✅' if depois.aceito else 'ℹ '} cupom da página: {rot[:80]}")
    if depois.aceito:
        p.aceitos.append(depois)
        _registra_leitura(p, a, depois)


def _grava_teste(loja: LojaCarrinho, testados: dict, a: Anuncio, cod: str, r: ResultadoCupom) -> str:
    """Grava o resultado de uma aplicação do cupom `cod` no anúncio `a` (chave '<CÓDIGO>@<chave do anúncio>')."""
    chave = f"{cod}@{a.chave}"
    testados[chave] = {
        "testado_em": agora_iso(), "status": r.status, "aceito": r.aceito, "mensagem": r.mensagem[:200],
        "vendedor": a.vendedor or loja.loja_canonica, "anuncio": a.chave, "url": a.url, "modelo": a.modelo,
        "tv_pix": r.tv_pix, "tv_cartao": r.tv_cartao, "pix_real": r.pix_real,
        "total_pix": r.total_pix, "total_cartao": r.total_cartao, "frete": r.frete,
        "desconto": r.desconto, "parcelado": r.parcelado, "quantidade": r.quantidade,
    }
    if getattr(loja, "item_alvo", None):
        testados[chave]["item"] = loja.item_alvo
    return chave


def _testar_fila(loja: LojaCarrinho, page, a: Anuncio, fila: list[str], testados: dict, p: Percurso) -> None:
    fila = ordenar_fila(fila, testados, a.chave, a)
    vez = fila[: min(MAX_POR_RODADA, p.orcamento)]
    if len(vez) < len(fila):
        print(f"[{loja.nome}] {a.rotulo}: {len(fila) - len(vez)} cupons ficam para a próxima rodada")
    print(f"[{loja.nome}] {a.rotulo}: testando {len(vez)} cupons")
    erros_seguidos = 0
    for i, cod in enumerate(vez):
        if _tempo_esgotado():
            print(f"[{loja.nome}] a rodada passou de {PRAZO_RODADA_S // 60} min; o resto fica para a próxima")
            break
        p.orcamento -= 1
        try:
            r = loja.aplicar(page, cod)
        except (PrecisaLogin, LojaIndisponivel, CarrinhoOcupado):
            raise
        except Exception as e:  # noqa: BLE001
            r = ResultadoCupom(codigo=cod, aceito=False, extra={"falha": True},
                               mensagem=f"erro: {type(e).__name__}: {str(e)[:120]}")
        st = r.status  # 'erro' não é recusa: volta na próxima rodada
        p.gravados.add(_grava_teste(loja, testados, a, cod, r))
        print(f"  {'✅' if r.aceito else ('⚠ ' if st == 'erro' else '✗ ')} {cod:<18} "
              f"{('TV ' + fmt_preco(r.tv_pix or r.tv_cartao)) if r.aceito else r.mensagem[:80]}")
        erros_seguidos = erros_seguidos + 1 if st == "erro" else 0
        if erros_seguidos >= MAX_ERROS_SEGUIDOS:
            print(f"[{loja.nome}] {a.rotulo}: {erros_seguidos} falhas seguidas do robô; "
                  "paro este anúncio e os cupons voltam na próxima rodada")
            break
        if r.aceito:
            r.extra.update(vendedor=a.vendedor or loja.loja_canonica, anuncio=a.chave, modelo=a.modelo)
            p.aceitos.append(r)
            _registra_leitura(p, a, r)
            loja.remover(page)
            page.wait_for_timeout(1000)
        if i % 5 == 4:
            page.wait_for_timeout(3000)  # respiro para não parecer ataque


def percorrer(loja: LojaCarrinho, page, anuncios: list[Anuncio], fila_base: list[str], reg: dict, p: Percurso,
              forcar: bool = False, explicitos: bool = False) -> None:
    """Vai do anúncio mais barato ao mais caro (de UM modelo) até acabar o orçamento de testes (p.orcamento) ou o
    limite de anúncios (loja.max_anuncios por modelo)."""
    testados = reg.setdefault("cupons", {})
    ids_tv = sorted({a.item_id for a in anuncios if a.item_id})
    so_leitura = getattr(loja, "so_leitura", False)
    visitas = 0
    for i, a in enumerate(anuncios):
        if visitas >= loja.max_anuncios:
            print(f"[{loja.nome}] limite de {loja.max_anuncios} anúncios por rodada; "
                  f"{len(anuncios) - i} ficam para a próxima")
            break
        if _tempo_esgotado():
            print(f"[{loja.nome}] a rodada passou de {PRAZO_RODADA_S // 60} min; o resto fica para a próxima")
            break
        if so_leitura:
            if p.visitados:
                page.wait_for_timeout(PAUSA_ENTRE_ANUNCIOS_MS)
            p.visitados.append(a.chave)
            visitas += 1
            _ler_anuncio_so_leitura(loja, page, a, p, ids_tv)
            continue
        fila, pulados = pendentes(anuncios, i, fila_base, testados, agora(), forcar, explicitos, p.inicio)
        if pulados:
            print(f"[{loja.nome}] {a.rotulo}: não testo {', '.join(pulados)} (já aceito(s) num anúncio mais barato)")
        if not fila:
            print(f"[{loja.nome}] {a.rotulo} ({fmt_preco(a.preco)}): nada pendente; não mexo no carrinho")
            continue
        if p.orcamento <= 0:
            print(f"[{loja.nome}] limite de {MAX_APLICACOES_POR_RODADA} testes da rodada atingido; "
                  f"{len(fila)} cupons de {a.rotulo} ficam para a próxima")
            break
        if p.visitados:
            page.wait_for_timeout(PAUSA_ENTRE_ANUNCIOS_MS)
        p.visitados.append(a.chave)
        visitas += 1
        print(f"[{loja.nome}] anúncio {visitas}/{loja.max_anuncios}: {a.rotulo} ({fmt_preco(a.preco)}), "
              f"{len(fila)} cupom(ns) pendente(s)")
        p.no_carrinho = None  # se a troca parar no meio (falha ou exceção), no fim da rodada o carrinho é conferido
        p.conferidos = {}
        try:
            entrou = loja.garantir_item(page, a.url, a.alvo(ids_tv, p.contexto))
        finally:
            _atualiza_fora(loja, p)
        if not entrou:
            p.falhou.add(a.chave)
            print(f"[{loja.nome}] não consegui deixar só {a.rotulo} no carrinho; passo para o próximo anúncio")
            continue
        _tv_conferida(loja, p, a.chave, a.modelo)
        base = loja.ler_totais(page)
        if loja.tem_cupom_aplicado(page, base):
            print(f"[{loja.nome}] o carrinho estava com um cupom de antes; tiro para medir o preço cheio")
            loja.remover(page)
            base = loja.ler_totais(page)
        base.codigo = "(sem cupom)"
        base.extra.update(anuncio=a.chave, vendedor=a.vendedor or loja.loja_canonica, modelo=a.modelo)
        p.sem_cupom[a.chave] = base
        _registra_leitura(p, a, base)
        print(f"[{loja.nome}] {a.rotulo}: produtos {fmt_preco(base.produtos)} frete {fmt_preco(base.frete)} "
              f"Pix {fmt_preco(base.total_pix)} cartão {fmt_preco(base.total_cartao)}"
              + (f" · {base.parcelado}" if base.parcelado else ""))
        _testar_fila(loja, page, a, fila, testados, p)


def _resultado_do_registro(codigo: str, reg: dict, a: Anuncio) -> ResultadoCupom:
    return ResultadoCupom(
        codigo=codigo, aceito=True, mensagem=reg.get("mensagem") or "", frete=reg.get("frete"),
        desconto=reg.get("desconto"), total_pix=reg.get("total_pix"), total_cartao=reg.get("total_cartao"),
        pix_real=bool(reg.get("pix_real", True)),  # registro antigo, sem o campo: trata como Pix de verdade
        parcelado=reg.get("parcelado"), quantidade=int(reg.get("quantidade") or 1),
        extra={"vendedor": a.vendedor or reg.get("vendedor"), "anuncio": a.chave, "anterior": True,
               "aceito_em": reg.get("testado_em"), "modelo": a.modelo})


def escolher_final(p: Percurso, anuncios: list[Anuncio], testados: dict,
                   momento: datetime | None = None,
                   so_codigo: Optional[str] = None) -> Optional[tuple[Anuncio, ResultadoCupom]]:
    """Melhor cupom conhecido para deixar no carrinho: aceitos nesta rodada e aceites de rodadas anteriores
    nas últimas 48 h naquele anúncio (aceito_recente, F4; senão, testar um anúncio mais caro — ou um cupom que
    ficou fora do orçamento da rodada — deixaria o carrinho pior que antes). O passo final reaplica o cupom e
    a própria aplicação confere se ele ainda vale. `so_codigo`: só esse cupom (o do pedido, com os dois modelos)."""
    momento = momento or agora()
    por_chave = {a.chave: a for a in anuncios if a.chave not in p.falhou}
    cands = [(por_chave[r.extra["anuncio"]], r) for r in p.aceitos if r.extra.get("anuncio") in por_chave
             and (so_codigo is None or r.codigo == so_codigo)]
    codigos = {k.split("@", 1)[0] for k in testados if "@" in k}
    if so_codigo is not None:
        codigos &= {so_codigo}
    for a in por_chave.values():
        for cod in sorted(codigos):
            if f"{cod}@{a.chave}" in p.gravados:
                continue  # testado nesta rodada: se foi aceito, já está em p.aceitos
            reg = registro_do_cupom(testados, cod, a)
            if aceito_recente(cod, reg, momento) and (reg.get("total_pix") or reg.get("total_cartao")):
                cands.append((a, _resultado_do_registro(cod, reg, a)))
    if not cands:
        return None
    return min(cands, key=lambda x: x[1].tv_pix or x[1].tv_cartao or 9e9)


def _preco(r: ResultadoCupom) -> float:
    return r.tv_pix or r.tv_cartao or 9e9


def ordem_sem_cupom(p: Percurso, anuncios: list[Anuncio]) -> list[Anuncio]:
    """Anúncios que podem ficar no carrinho sem cupom no fim da rodada, do mais barato ao mais caro: TODOS os
    anúncios da loja (visitados ou não nesta rodada), na ordem do preço coletado (a mesma do percurso), menos os
    que não entraram no carrinho nesta rodada."""
    return [a for a in anuncios if a.chave not in p.falhou]


def preco_sem_cupom(p: Percurso, a: Anuncio) -> float:
    """Preço do anúncio sem cupom: a leitura do carrinho nesta rodada ou, sem ela, o preço coletado."""
    r = p.sem_cupom.get(a.chave)
    v = (r.tv_pix or r.tv_cartao) if r is not None else None
    return v or a.preco or 9e9


def destino_do_modelo(p: Percurso, anuncios: list[Anuncio], testados: dict, momento: datetime | None = None,
                      so_codigo: Optional[str] = None) -> Optional[tuple[Anuncio, Optional[ResultadoCupom]]]:
    """Onde a TV (de um modelo) deve terminar a rodada: (anúncio, melhor cupom) quando o cupom deixa a TV mais barata
    que o anúncio mais barato sem cupom; senão (anúncio mais barato sem cupom, None). None: nenhum anúncio."""
    final = escolher_final(p, anuncios, testados, momento, so_codigo)
    # nenhum anúncio entrou no carrinho nesta rodada: a sacola pode ter ficado VAZIA (o robô esvazia antes
    # de pôr o anúncio novo), então o destino volta a ser o mais barato de TODOS, nem que ele já tenha falhado
    ordem = ordem_sem_cupom(p, anuncios) or list(anuncios)
    base = ordem[0] if ordem else None
    if final and (base is None or _preco(final[1]) < preco_sem_cupom(p, base)):
        return final
    return (base, None) if base is not None else None


def destino_final(p: Percurso, anuncios: list[Anuncio], testados: dict,
                  momento: datetime | None = None) -> Optional[tuple[Anuncio, Optional[ResultadoCupom]]]:
    """Como o carrinho termina a rodada (só quando o robô mexeu nele), numa loja com anúncios de UM modelo.

    (anúncio, cupom): deixa o melhor cupom conhecido aplicado (escolher_final);
    (anúncio, None):  volta para o anúncio mais barato da loja, sem cupom;
    None:             o carrinho já está no lugar certo.
    "Priorize o mais barato": o anúncio mais barato é o de TODOS os anúncios (ordem_sem_cupom), não só dos que o
    robô abriu nesta rodada: o mais barato sem nada pendente é pulado sem tocar no carrinho, e testar um mais caro
    não pode deixar a TV mais cara no carrinho da pessoa. O cupom só fica se deixar a TV mais barata que esse
    anúncio sem cupom.
    """
    destino = destino_do_modelo(p, anuncios, testados, momento)
    if destino is None or (destino[1] is None and destino[0].chave == p.no_carrinho):
        return None
    return destino


def _pausar(loja: LojaCarrinho, reg: dict, e: Exception) -> None:
    ate = agora() + PAUSA_LOJA_INDISPONIVEL
    reg["pausa_ate"] = ate.isoformat(timespec="seconds")
    reg["pausa_motivo"] = str(e)
    print(f"[{loja.nome}] {e}; pausa até {ate.strftime('%d/%m %H:%M')}")


def voltar_ao_anuncio(loja: LojaCarrinho, a: Anuncio, anuncios: list[Anuncio], visivel: bool,
                      reg: dict, p: Optional[Percurso] = None) -> Optional[bool]:
    """Deixa no carrinho só o anúncio `a`, sem cupom (as mesmas regras de garantir_item: carrinho com outro
    produto não é mexido).

    True: o carrinho ficou só com `a`; False: não deu (quem chama pode tentar o próximo mais barato);
    None: parar de mexer (carrinho com outro produto, loja fora do ar ou sessão expirada; o motivo vai para
    p.parou_por, para o aviso de sacola vazia)."""
    print(f"[{loja.nome}] volto o carrinho para o anúncio mais barato, sem cupom: {a.rotulo} ({fmt_preco(a.preco)})")
    try:
        with _sessao(loja, visivel) as page:
            try:
                entrou = loja.garantir_item(page, a.url, a.alvo((x.item_id for x in anuncios if x.item_id),
                                                                p.contexto if p is not None else None))
            finally:
                if p is not None:
                    _atualiza_fora(loja, p)
            if entrou:
                return True
        print(f"[{loja.nome}] não consegui voltar o carrinho para {a.rotulo}")
    except LojaIndisponivel as e:
        _pausar(loja, reg, e)
        if p is not None:
            p.parou_por = MOTIVO_PAROU_INDISPONIVEL
        return None
    except (CarrinhoOcupado, PrecisaLogin) as e:
        print(f"[{loja.nome}] não voltei o carrinho para {a.rotulo}: {e}")
        if p is not None:
            p.parou_por = MOTIVO_PAROU_OCUPADO if isinstance(e, CarrinhoOcupado) else MOTIVO_PAROU_LOGIN
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[{loja.nome}] não voltei o carrinho para {a.rotulo}: {type(e).__name__}: {str(e)[:120]}")
    return False


MAX_VOLTAS = 2  # no fim da rodada: tenta o mais barato e, se ele não entrar, o próximo (a sacola não fica vazia)
MAX_VOLTAS_SACOLA_VAZIA = 3  # nenhum anúncio entrou na rodada: insiste mais, porque a sacola ficou vazia


def ordem_de_recuperacao(p: Percurso, anuncios: list[Anuncio], pular: Iterable[str] = ()) -> list[Anuncio]:
    """Anúncios que o passo final tenta pôr de volta no carrinho, do mais barato ao mais caro.

    Normalmente os que entraram nesta rodada (ordem_sem_cupom). Quando NENHUM entrou — justo o caso em que a
    sacola foi esvaziada e não recebeu nada — tenta de novo TODOS os conhecidos, inclusive os que falharam:
    melhor insistir (com um limite de tentativas) do que deixar a sacola da pessoa vazia.
    """
    pular = set(pular)
    ordem = [a for a in ordem_sem_cupom(p, anuncios) if a.chave not in pular]
    if ordem:
        return ordem[:MAX_VOLTAS]
    return [a for a in anuncios if a.chave not in pular][:MAX_VOLTAS_SACOLA_VAZIA]


def _carrinho_intacto(loja: LojaCarrinho, p: Percurso) -> None:
    """F3: a TV não foi (re)conferida no fim, mas o robô não tirou nada do carrinho desde a última conferência
    (ou desde o começo da rodada): o carrinho está como estava. Só log, sem aviso no Telegram."""
    onde = f"com {p.no_carrinho}" if p.no_carrinho else "como a pessoa deixou"
    print(f"[{loja.nome}] não tirei nada do carrinho nesta rodada depois da última conferência: carrinho intacto "
          f"({onde}); sem aviso")


def _avisar_sacola_vazia(loja: LojaCarrinho, tentados: list[Anuncio], motivo: Optional[str] = None) -> None:
    """O robô TIROU algo do carrinho nesta rodada (esvaziar do Magalu, linha antiga do ML) e a TV não voltou a
    ser conferida lá: a sacola da pessoa pode ter ficado VAZIA. Vai para o log e para o Telegram.
    Quem chama confere antes (_removeu_sem_conferir, F3): sem remoção, o carrinho está intacto e não há aviso."""
    quais = ", ".join(a.rotulo for a in tentados[:3]) or "nenhum anúncio conhecido"
    if motivo:
        print(f"[{loja.nome}] ⚠ tirei a TV do carrinho e {motivo} antes de ela voltar; a sacola pode ter ficado VAZIA")
        AVISOS_CARRINHO.append(
            f"⚠️ <b>{loja.loja_canonica}</b>: tirei a TV do carrinho para trocar de anúncio e {motivo} antes de "
            f"ela voltar; a sua sacola pode ter ficado <b>vazia</b>. Confira em {loja.url_carrinho}")
        return
    print(f"[{loja.nome}] ⚠ não consegui deixar a TV no carrinho ({quais}); a sacola pode ter ficado VAZIA")
    AVISOS_CARRINHO.append(
        f"⚠️ <b>{loja.loja_canonica}</b>: não consegui deixar a TV no carrinho nesta rodada "
        f"(tentei {len(tentados)} anúncio(s)); a sua sacola pode ter ficado <b>vazia</b>. "
        f"Confira em {loja.url_carrinho}")


def _avisar_sem_tempo(loja: LojaCarrinho, p: Percurso) -> None:
    """O relógio da rodada acabou antes de o passo final arrumar o carrinho. Só vira aviso no Telegram quando
    o robô tirou algo do carrinho depois da última vez em que a TV foi conferida lá (F3); sem isso o carrinho
    está intacto e, se faltar algo, é só o cupom, e disso a mensagem já fala."""
    print(f"[{loja.nome}] ⚠ a rodada passou de {PRAZO_PASSO_FINAL_S // 60} min antes de eu arrumar o carrinho; "
          "não abro outra janela")
    if not _removeu_sem_conferir(loja, p):
        _carrinho_intacto(loja, p)
        return
    AVISOS_CARRINHO.append(
        f"⚠️ <b>{loja.loja_canonica}</b>: o tempo da rodada acabou antes de eu conferir o carrinho; "
        f"ele pode ter ficado <b>vazio</b>. Confira em {loja.url_carrinho}")


def _avisar_tvs_a_mais(loja: LojaCarrinho) -> None:
    """O carrinho terminou com mais de uma linha (ou mais de 1 unidade) do mesmo modelo e o robô não conseguiu
    arrumar sem arriscar tirar a TV errada."""
    print(f"[{loja.nome}] ⚠ o carrinho pode ter ficado com mais de uma TV do mesmo modelo")
    AVISOS_CARRINHO.append(
        f"⚠️ <b>{loja.loja_canonica}</b>: o carrinho pode ter ficado com <b>mais de uma TV do mesmo modelo</b> (ou mais "
        f"de 1 unidade). Confira em {loja.url_carrinho} e deixe só uma de cada modelo.")


NOME_MODELO = {"55C6K": 'TV 55" (55C6K)', "65C6K": 'TV 65" (65C6K)'}


def _avisar_tv_fora(loja: LojaCarrinho, modelos: Iterable[str], motivo: Optional[str] = None) -> None:
    """26/09: o robô tirou do carrinho a TV de um modelo (para medir o cupom do outro, que vale para o pedido
    inteiro) e ela não voltou a ser conferida lá. Vai para o log e para o Telegram."""
    ms = [m for m in MODELOS if m in set(modelos)]
    if not ms:
        return
    quais = " e ".join(NOME_MODELO.get(m, m) for m in ms)
    porque = f" ({motivo})" if motivo else ""
    print(f"[{loja.nome}] ⚠ tirei do carrinho a {quais} e ela não voltou{porque}")
    vazia = " A sua sacola pode ter ficado <b>vazia</b>." if len(ms) == len(MODELOS) else ""
    AVISOS_CARRINHO.append(
        f"⚠️ <b>{loja.loja_canonica}</b>: tirei do carrinho a <b>{quais}</b> para medir um cupom e não consegui "
        f"devolver{porque}.{vazia} Confira em {loja.url_carrinho}")


def arrumar_carrinho(loja: LojaCarrinho, p: Percurso, anuncios: list[Anuncio], reg: dict,
                     visivel: bool) -> Optional[tuple[Anuncio, ResultadoCupom]]:
    """Passo final, só quando o robô mexeu no carrinho: o melhor cupom conhecido (desta rodada ou aceito naquele
    anúncio nas últimas 48 h, F4) quando ele deixa a TV mais barata; senão, o anúncio mais barato da loja sem cupom
    (destino_final). A reaplicação é um teste de verdade: aceito ou recusado agora, o registro do cupom é
    atualizado (_grava_reaplicacao).

    Se o cupom não ficar (a loja recusou agora, o anúncio não entrou, falha do robô), o carrinho também volta para
    o anúncio mais barato sem cupom: nunca termina num anúncio mais caro só porque o cupom dele era o melhor. Se o
    mais barato não entrar, tenta o próximo (até MAX_VOLTAS), para a sacola da pessoa não terminar vazia.
    Cada tentativa abre uma janela nova do Chrome, então tudo aqui corre no mesmo relógio de percorrer():
    passado PRAZO_PASSO_FINAL_S não abre mais nenhuma, e a mensagem avisa que o carrinho ficou sem conferir.
    Aviso de sacola vazia só quando o robô tirou algo do carrinho e a TV não voltou a ser conferida (F3).
    G3 (22/09): o cupom aceito há até 48 h foi escolhido pelo total gravado naquele dia; se, com o preço de AGORA, ele
    não deixa a TV mais barata que o anúncio mais barato sem cupom, o carrinho volta para esse anúncio.
    Devolve (anúncio, cupom) quando havia um cupom para deixar (a mensagem diz se ficou)."""
    destino = destino_final(p, anuncios, reg["cupons"])
    if destino is None:
        return None
    a, melhor = destino
    pular: set = set()
    sem_tempo = False
    if melhor is not None and _tempo_esgotado(PRAZO_PASSO_FINAL_S):
        # sem tempo para reaplicar o cupom; o que não pode faltar é a TV voltar para o carrinho
        _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_SEM_TEMPO)
        melhor = None
    if melhor is not None:
        if melhor.extra.get("anterior"):
            print(f"[{loja.nome}] volto o carrinho para o melhor conhecido: {a.rotulo} com {melhor.codigo}")
        resposta = None
        try:
            with _sessao(loja, visivel) as page:
                try:
                    situacao, erro, resposta = _deixar_cupom(
                        loja, page, a.url, melhor, a.alvo((x.item_id for x in anuncios if x.item_id), p.contexto))
                finally:
                    _atualiza_fora(loja, p)
        except Exception as e:  # noqa: BLE001 - o navegador não abriu
            situacao, erro = "erro", e
            _marca_sem_cupom_no_carrinho(loja, melhor, f"erro: {type(e).__name__}")
        if situacao in ("ok", "sem_cupom"):
            _tv_conferida(loja, p, a.chave, a.modelo)   # garantir_item conferiu a TV deste anúncio no carrinho
        _grava_reaplicacao(loja, reg["cupons"], a, melhor, situacao, resposta)
        ordem = ordem_sem_cupom(p, anuncios)
        if situacao == "ok" and ordem and ordem[0].chave != a.chave and \
                _preco(melhor) >= preco_sem_cupom(p, ordem[0]) - 0.005:
            # G3: o preço de agora (o cupom pode ser de ontem) não bate o anúncio mais barato sem cupom
            print(f"[{loja.nome}] com o preço de agora, {melhor.codigo} em {a.rotulo} dá {fmt_preco(_preco(melhor))}, "
                  f"não menos que {ordem[0].rotulo} sem cupom ({fmt_preco(preco_sem_cupom(p, ordem[0]))})")
            _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_NAO_COMPENSA)
            situacao = "nao_compensa"
        if situacao == "ok":
            return destino
        if situacao == "parar":
            if isinstance(erro, LojaIndisponivel):
                _pausar(loja, reg, erro)
            if not isinstance(erro, CarrinhoOcupado) and _removeu_sem_conferir(loja, p):
                _avisar_sacola_vazia(loja, [a], MOTIVO_PAROU_INDISPONIVEL if isinstance(erro, LojaIndisponivel)
                                     else MOTIVO_PAROU_LOGIN)
            return destino
        if situacao == "sem_cupom" and ordem and ordem[0].chave == a.chave:
            return destino  # a TV do anúncio mais barato ficou no carrinho, só sem o cupom
        if situacao == "sem_tv":
            pular.add(a.chave)
        print(f"[{loja.nome}] sem o cupom, o carrinho volta para o anúncio mais barato")
    tentados = ordem_de_recuperacao(p, anuncios, pular)
    entrou = parou = False
    tentados_de_fato: list[Anuncio] = []
    for x in tentados:
        if _tempo_esgotado(PRAZO_PASSO_FINAL_S):   # cada tentativa abre uma janela nova do Chrome
            sem_tempo = True
            break
        tentados_de_fato.append(x)
        r = voltar_ao_anuncio(loja, x, anuncios, visivel, reg, p)
        if r is None:          # carrinho com outro produto, loja fora do ar ou sessão expirada: não insiste
            parou = True
            break
        if r:
            entrou = True
            _tv_conferida(loja, p, x.chave, x.modelo)
            break
    if not entrou:
        if sem_tempo:
            _avisar_sem_tempo(loja, p)
        elif not _removeu_sem_conferir(loja, p):
            if tentados_de_fato:
                _carrinho_intacto(loja, p)
        elif parou:
            if p.parou_por and p.parou_por != MOTIVO_PAROU_OCUPADO:
                _avisar_sacola_vazia(loja, tentados_de_fato, p.parou_por)
        elif tentados_de_fato:
            _avisar_sacola_vazia(loja, tentados_de_fato)
    return destino if destino[1] is not None else None


def _grava_reaplicacao(loja: LojaCarrinho, testados: dict, a: Anuncio, melhor: ResultadoCupom, situacao: str,
                       resposta: Optional[ResultadoCupom]) -> None:
    """F4: a reaplicação do passo final é um teste no mesmo anúncio. Aceito agora: o registro fica com a data de
    agora (o cupom não é retestado hoje e segue valendo para o passo final); recusado pela loja agora: a recusa
    fica gravada (volta à fila em 24 h, como qualquer recusa). Falha do robô não muda o registro."""
    if resposta is None or resposta.codigo != melhor.codigo:
        return
    if (situacao == "ok" and resposta.aceito) or (situacao == "sem_cupom" and resposta.status == "recusado"):
        _grava_teste(loja, testados, a, melhor.codigo, resposta)
        if situacao != "ok":
            print(f"[{loja.nome}] {melhor.codigo} foi recusado agora em {a.rotulo}: gravado como recusado")


# ------------------------------------------------------------------------------------------------
# passo final com os dois modelos (26/09: "coloque as duas, uma de cada modelo")
# ------------------------------------------------------------------------------------------------

def _mais_barato(p: Percurso, anuncios: list[Anuncio]) -> Anuncio:
    return (ordem_sem_cupom(p, anuncios) or list(anuncios))[0]


def _preco_do_pedido(r: ResultadoCupom) -> Optional[float]:
    """Preço do pedido inteiro (as duas TVs) numa leitura do carrinho, sem frete; Pix quando há, senão cartão."""
    total = r.total_pix if r.total_pix is not None else r.total_cartao
    return None if total is None else round(total - (r.frete or 0), 2)


def cupom_do_pedido(p: Percurso, grupos: dict[str, list[Anuncio]],
                    destinos: dict) -> Optional[tuple[str, ResultadoCupom]]:
    """O cupom vale para o pedido inteiro, então só um fica no carrinho: dos cupons de destino de cada modelo, o de
    maior economia (preço sem cupom do anúncio mais barato do modelo menos o preço com o cupom). (modelo, cupom)."""
    cands = [(preco_sem_cupom(p, _mais_barato(p, grupos[m])) - _preco(r), m, r)
             for m, (_a, r) in destinos.items() if r is not None]
    if not cands:
        return None
    _economia, m, r = max(cands, key=lambda x: x[0])
    return m, r


def _conferencia_do_pedido(loja: LojaCarrinho, p: Percurso, alvos: dict[str, Anuncio], conferidos: set) -> list[str]:
    """Anota o que garantir_itens conferiu no carrinho; devolve os modelos cuja TV está lá como deve."""
    ok = [m for m, a in alvos.items() if a.chave in conferidos]
    p.conferidos = {m: alvos[m].chave for m in ok}
    p.no_carrinho = None
    _atualiza_fora(loja, p, ok)
    if ok and len(ok) == len(alvos):
        p.remocoes_conferidas = _remocoes(loja)
    return ok


def _alvos_do_pedido(p: Percurso, alvos: dict[str, Anuncio], grupos: dict[str, list[Anuncio]]) -> list[dict]:
    return [a.alvo((x.item_id for x in grupos[m] if x.item_id), p.contexto) for m, a in alvos.items()]


def _deixar_cupom_no_pedido(loja: LojaCarrinho, p: Percurso, alvos: dict[str, Anuncio],
                            grupos: dict[str, list[Anuncio]], melhor: ResultadoCupom,
                            visivel: bool) -> tuple[str, Optional[Exception]]:
    """Carrinho com uma TV de cada modelo (garantir_itens) e o cupom do pedido aplicado. 'ok' | 'sem_tv' | 'sem_cupom'
    | 'parar' | 'erro'. O preço lido é o do PEDIDO (as duas TVs): vai para extra['preco_pedido'] e não muda os
    preços de uma TV do resultado (a mensagem continua com o preço medido com a TV sozinha no carrinho)."""
    melhor.extra["no_carrinho"] = False
    try:
        with _sessao(loja, visivel) as page:
            try:
                conferidos = loja.garantir_itens(page, _alvos_do_pedido(p, alvos, grupos))
            finally:
                _atualiza_fora(loja, p)
            if len(_conferencia_do_pedido(loja, p, alvos, conferidos)) != len(alvos):
                _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_SEM_AS_DUAS)
                return "sem_tv", None
            r = loja.aplicar(page, melhor.codigo)
            if r.aceito and r.codigo == melhor.codigo:
                melhor.extra.update(no_carrinho=True, pedido=True, preco_pedido=_preco_do_pedido(r))
                return "ok", None
            _marca_sem_cupom_no_carrinho(loja, melhor, r.mensagem or "a loja não confirmou o cupom")
            return "sem_cupom", None
    except CarrinhoOcupado as e:
        _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_OCUPADO)
        p.parou_por = MOTIVO_PAROU_OCUPADO
        return "parar", e
    except (LojaIndisponivel, PrecisaLogin) as e:
        _marca_sem_cupom_no_carrinho(loja, melhor, f"erro: {type(e).__name__}")
        p.parou_por = MOTIVO_PAROU_INDISPONIVEL if isinstance(e, LojaIndisponivel) else MOTIVO_PAROU_LOGIN
        return "parar", e
    except Exception as e:  # noqa: BLE001 - falha do robô ou do navegador
        _marca_sem_cupom_no_carrinho(loja, melhor, f"erro: {type(e).__name__}")
        return "erro", e


def _pedido_sem_cupom(loja: LojaCarrinho, p: Percurso, grupos: dict[str, list[Anuncio]], reg: dict,
                      visivel: bool) -> tuple[Optional[str], bool]:
    """Uma TV de cada modelo, sem cupom: o anúncio mais barato de cada modelo; o modelo cuja TV não entra passa para o
    próximo mais barato (até MAX_VOLTAS, ou MAX_VOLTAS_SACOLA_VAZIA quando nenhum anúncio dele entrou na rodada).
    Cada tentativa abre uma janela nova do Chrome, no relógio do passo final. Devolve (motivo de parada, sem_tempo)."""
    cands = {m: ordem_de_recuperacao(p, grupos[m]) for m in grupos}
    idx = {m: 0 for m in cands if cands[m]}
    while idx:
        if _tempo_esgotado(PRAZO_PASSO_FINAL_S):
            print(f"[{loja.nome}] ⚠ a rodada passou de {PRAZO_PASSO_FINAL_S // 60} min antes de eu arrumar o carrinho; "
                  "não abro outra janela")
            return None, True
        alvos = {m: cands[m][i] for m, i in idx.items()}
        print(f"[{loja.nome}] passo final, sem cupom: "
              + " + ".join(f"{m} {a.rotulo} ({fmt_preco(a.preco)})" for m, a in alvos.items()))
        conferidos: set = set()
        try:
            with _sessao(loja, visivel) as page:
                try:
                    conferidos = loja.garantir_itens(page, _alvos_do_pedido(p, alvos, grupos))
                finally:
                    _atualiza_fora(loja, p)
        except LojaIndisponivel as e:
            _pausar(loja, reg, e)
            p.parou_por = MOTIVO_PAROU_INDISPONIVEL
            return p.parou_por, False
        except (CarrinhoOcupado, PrecisaLogin) as e:
            print(f"[{loja.nome}] não arrumei o carrinho: {e}")
            p.parou_por = MOTIVO_PAROU_OCUPADO if isinstance(e, CarrinhoOcupado) else MOTIVO_PAROU_LOGIN
            return p.parou_por, False
        except Exception as e:  # noqa: BLE001
            print(f"[{loja.nome}] não arrumei o carrinho: {type(e).__name__}: {str(e)[:120]}")
        ok = _conferencia_do_pedido(loja, p, alvos, conferidos)
        faltam = [m for m in idx if m not in ok]
        if not faltam:
            return None, False
        mudou = False
        for m in faltam:
            print(f"[{loja.nome}] a {m} não ficou no carrinho com {alvos[m].rotulo}")
            if idx[m] + 1 < len(cands[m]):
                idx[m] += 1
                mudou = True
            else:
                del idx[m]
        if not mudou:
            break
    return None, False


def _avisos_do_pedido(loja: LojaCarrinho, p: Percurso, grupos: dict[str, list[Anuncio]], parou: Optional[str],
                      sem_tempo: bool) -> None:
    """Depois do passo final com os dois modelos: avisa quando uma TV que o robô TIROU do carrinho não voltou (a do
    outro modelo, tirada para medir um cupom, ou as duas). Sem remoção, o carrinho está como a pessoa deixou."""
    motivo = MOTIVO_SEM_TEMPO if sem_tempo else parou
    if p.modelos_fora:
        _avisar_tv_fora(loja, p.modelos_fora, motivo)
        return
    # adaptador que não disse o modelo do que tirou: a regra da F3 (tirou algo e nada foi conferido depois)
    if not p.conferidos and _removeu_sem_conferir(loja, p) and parou != MOTIVO_PAROU_OCUPADO:
        _avisar_tv_fora(loja, grupos, motivo)
    elif not p.conferidos:
        _carrinho_intacto(loja, p)


def arrumar_carrinho_modelos(loja: LojaCarrinho, p: Percurso, grupos: dict[str, list[Anuncio]], reg: dict,
                             visivel: bool) -> dict:
    """Passo final numa loja com anúncios dos DOIS modelos (só quando o robô mexeu no carrinho): UMA TV DE CADA MODELO
    (1 unidade cada, nunca outro produto) e o melhor cupom do pedido.

    - destino de cada modelo (destino_do_modelo): o anúncio do melhor cupom quando ele compensa, senão o mais barato
      sem cupom;
    - o cupom vale para o pedido inteiro: fica o de maior economia (cupom_do_pedido); para o outro modelo, vale o
      anúncio em que ESSE cupom compensa, ou o mais barato sem cupom;
    - garantir_itens deixa as duas TVs no carrinho e o cupom é aplicado; se ele não ficar (recusado, erro) ou, com o
      preço de AGORA, o pedido não sair mais barato que as duas TVs mais baratas sem cupom (G3), o carrinho fica com
      a mais barata de cada modelo, sem cupom (_pedido_sem_cupom);
    - TV que o robô tirou e não voltou: aviso no Telegram (_avisos_do_pedido).
    Devolve {modelo: (anúncio, cupom) ou None}: o cupom que ficou (ou tentou ficar) no carrinho, no modelo dono dele."""
    testados = reg["cupons"]
    finais: dict = {m: None for m in grupos}
    destinos = {m: d for m in grupos for d in [destino_do_modelo(p, grupos[m], testados)] if d is not None}
    if not destinos:
        return finais
    proprios = dict(destinos)          # o melhor destino de cada modelo, com o cupom DELE
    pedido = cupom_do_pedido(p, grupos, destinos)
    if pedido is not None:
        dono, melhor = pedido
        for m in destinos:
            if m != dono and (destinos[m][1] is None or destinos[m][1].codigo != melhor.codigo):
                destinos[m] = destino_do_modelo(p, grupos[m], testados, so_codigo=melhor.codigo) or destinos[m]
        finais[dono] = destinos[dono]
        if _tempo_esgotado(PRAZO_PASSO_FINAL_S):
            _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_SEM_TEMPO)
            pedido = None
    parou: Optional[str] = None
    sem_tempo = feito = False
    if pedido is not None:
        dono, melhor = pedido
        alvos = {m: d[0] for m, d in destinos.items()}
        print(f"[{loja.nome}] passo final: uma TV de cada modelo ("
              + " + ".join(f"{m} {a.rotulo}" for m, a in alvos.items()) + f") com {melhor.codigo}"
              + (" (aceito antes)" if melhor.extra.get("anterior") else ""))
        situacao, erro = _deixar_cupom_no_pedido(loja, p, alvos, grupos, melhor, visivel)
        if situacao == "ok":
            baratos = {m: _mais_barato(p, grupos[m]) for m in alvos}
            ref = sum(preco_sem_cupom(p, b) for b in baratos.values())
            fresco = melhor.extra.get("preco_pedido")
            if fresco is not None and any(baratos[m].chave != alvos[m].chave for m in alvos) and fresco >= ref - 0.005:
                print(f"[{loja.nome}] com o preço de agora, o pedido com {melhor.codigo} sai {fmt_preco(fresco)}, não "
                      f"menos que as TVs mais baratas sem cupom ({fmt_preco(ref)})")
                _marca_sem_cupom_no_carrinho(loja, melhor, MOTIVO_NAO_COMPENSA)
            else:
                feito = True
                for m, (a_m, r_m) in proprios.items():
                    # o melhor cupom do outro modelo não coube: vale um cupom por pedido
                    if m != dono and r_m is not None and r_m.codigo != melhor.codigo:
                        r_m.extra.update(no_carrinho=False, motivo_carrinho=MOTIVO_OUTRO_CUPOM,
                                         cupom_do_pedido=melhor.codigo)
                        finais[m] = (a_m, r_m)
        elif situacao == "parar":
            parou = p.parou_por
            if isinstance(erro, LojaIndisponivel):
                _pausar(loja, reg, erro)
    if not feito and parou is None:
        parou, sem_tempo = _pedido_sem_cupom(loja, p, grupos, reg, visivel)
    _avisos_do_pedido(loja, p, grupos, parou, sem_tempo)
    return finais


# ------------------------------------------------------------------------------------------------
# TV que saiu do carrinho numa rodada anterior e não voltou (revisão de 26/09)
# ------------------------------------------------------------------------------------------------

def _tvs_fora_do_estado(loja: LojaCarrinho, reg: dict, momento: Optional[datetime] = None) -> dict[str, dict]:
    """reg["tvs_fora"] ({modelo: {"desde", "tentativas"}}): modelos cuja TV o robô tirou do carrinho numa rodada
    anterior (para medir o cupom do outro modelo) e que não voltaram. Os que passaram de JANELA_DEVOLVER_TV ou de
    MAX_TENTATIVAS_DEVOLVER saem (a pessoa já foi avisada na rodada em que a TV saiu); o estado fica só com o resto."""
    momento = momento or agora()
    bruto = reg.get("tvs_fora")
    vale: dict[str, dict] = {}
    for m, v in (bruto.items() if isinstance(bruto, dict) else ()):
        if m not in MODELOS or not isinstance(v, dict):
            continue
        tentativas = int(v.get("tentativas") or 0)
        if tentativas >= MAX_TENTATIVAS_DEVOLVER or not _recente(v.get("desde"), momento, JANELA_DEVOLVER_TV):
            print(f"[{loja.nome}] desisto de devolver ao carrinho a {NOME_MODELO.get(m, m)} (fora desde "
                  f"{v.get('desde')}, {tentativas} tentativa(s)); a pessoa foi avisada quando ela saiu")
            continue
        vale[m] = {"desde": v.get("desde"), "tentativas": tentativas}
    if vale:
        reg["tvs_fora"] = vale
    else:
        reg.pop("tvs_fora", None)
    return vale


def devolver_tvs_fora(loja: LojaCarrinho, p: Percurso, grupos: dict[str, list[Anuncio]], reg: dict,
                      visivel: bool) -> set[str]:
    """Rodada em que o passo final não correu (nada pendente, loja parada no meio): devolve ao carrinho a TV dos modelos
    que saíram numa rodada anterior e não voltaram (p.fora_de_antes), o anúncio mais barato de cada um, sem cupom, sem
    tocar na TV do outro modelo (garantir_itens só com os que faltam). Modelo sem anúncio conhecido nesta rodada fica
    para a próxima. Devolve os modelos tentados."""
    faltam = {m: grupos[m] for m in MODELOS if m in p.fora_de_antes and grupos.get(m)}
    sem_anuncio = sorted(p.fora_de_antes - set(faltam))
    if sem_anuncio:
        print(f"[{loja.nome}] a {' e a '.join(NOME_MODELO.get(m, m) for m in sem_anuncio)} saiu do carrinho numa rodada "
              "anterior, mas não conheço anúncio dela nesta rodada; tento na próxima")
    if not faltam:
        return set()
    if _tempo_esgotado(PRAZO_PASSO_FINAL_S):
        print(f"[{loja.nome}] sem tempo nesta rodada para devolver a TV que saiu do carrinho; tento na próxima")
        return set()
    print(f"[{loja.nome}] devolvo ao carrinho a {' e a '.join(NOME_MODELO.get(m, m) for m in faltam)}, que saiu numa "
          "rodada anterior e não voltou (sem cupom, sem mexer na TV do outro modelo)")
    _pedido_sem_cupom(loja, p, faltam, reg, visivel)
    return set(faltam)


def _grava_tvs_fora(loja: LojaCarrinho, reg: dict, p: Percurso, antes: dict[str, dict], tentou: Iterable[str]) -> None:
    """Fim da rodada: reg["tvs_fora"] fica com os modelos cuja TV está fora do carrinho por causa do robô (saiu nesta
    rodada e não voltou, ou saiu antes e ainda não voltou); a que voltou sai de lá e a pessoa sabe."""
    tentou = set(tentou)
    novo: dict[str, dict] = {}
    for m in MODELOS:
        if m in antes and m in p.fora_de_antes:             # saiu antes e ainda não voltou
            novo[m] = {**antes[m], "tentativas": int(antes[m].get("tentativas") or 0) + (1 if m in tentou else 0)}
        elif m in p.modelos_fora:                           # saiu nesta rodada e não voltou (o aviso já foi dado)
            novo[m] = {"desde": agora_iso(), "tentativas": 0}
    de_volta = [m for m in MODELOS if m in antes and m not in novo]
    if de_volta:
        quais = " e a ".join(NOME_MODELO.get(m, m) for m in de_volta)
        print(f"[{loja.nome}] a {quais}, que tinha saído do carrinho numa rodada anterior, está de volta (conferido)")
        AVISOS_CARRINHO.append(f"✅ <b>{loja.loja_canonica}</b>: a <b>{quais}</b>, que tinha saído do carrinho numa "
                               f"rodada anterior, está de volta lá (conferido agora).")
    if novo:
        reg["tvs_fora"] = novo
    else:
        reg.pop("tvs_fora", None)


def _precos_por_anuncio(antigos: Optional[dict], p: Percurso, anuncios: list[Anuncio]) -> dict:
    """reg["precos"]: última leitura de cada anúncio, pela chave do anúncio (os não visitados ficam como
    estavam; chaves que não são anúncio atual, como as antigas por nome do vendedor, saem). Guarda também a
    leitura SEM cupom (sem_cupom_pix / sem_cupom_cartao), que é o preço do anúncio quando ele volta do estado
    numa rodada sem coleta (F1), e o id do vendedor (a checagem de confiança do anúncio que volta do estado)."""
    por_chave = {a.chave: a for a in anuncios}
    novo = {k: v for k, v in (antigos or {}).items() if k in por_chave and isinstance(v, dict)}
    for chave, r in p.lidos.items():
        a = por_chave.get(chave)
        novo[chave] = {"vendedor": (a.vendedor if a else None) or r.extra.get("vendedor"), "url": a.url if a else None,
                       "modelo": a.modelo if a else (r.extra.get("modelo") or MODELO_PADRAO),
                       "tv_pix": r.tv_pix, "tv_cartao": r.tv_cartao, "parcelado": r.parcelado, "cupom": r.codigo,
                       "lido_em": agora_iso()}
        if a is not None and a.vendedor_id:
            novo[chave]["vendedor_id"] = a.vendedor_id
        s = p.sem_cupom.get(chave)
        if s is not None:
            novo[chave].update(sem_cupom_pix=s.tv_pix, sem_cupom_cartao=s.tv_cartao)
    return novo


def _anota_opcoes_do_catalogo(reg: dict, loja: LojaCarrinho, momento: Optional[datetime] = None) -> None:
    """F5: guarda em reg["opcoes_catalogo"] as opções do catálogo que a página logada mostrou nesta rodada
    (item, preço, vendedor, visto_em). As que passaram de 24 h sem serem vistas de novo saem."""
    vistas = getattr(loja, "opcoes_vistas", None) or {}
    if not vistas and "opcoes_catalogo" not in reg:
        return
    momento = momento or agora()
    atuais = {k: v for k, v in (reg.get("opcoes_catalogo") or {}).items()
              if isinstance(v, dict) and _recente(v.get("visto_em"), momento, JANELA_OPCAO_DO_CATALOGO)}
    visto_em = agora_iso()
    for item, v in vistas.items():
        atuais[item] = {**v, "visto_em": visto_em}
    reg["opcoes_catalogo"] = atuais
    if vistas:
        print(f"[{loja.nome}] opções do catálogo vistas logado: "
              + " · ".join(f"{v.get('vendedor') or '?'} [{k}] {fmt_preco(v.get('preco_pix') or v.get('preco'))}"
                           for k, v in vistas.items()))


def testar_loja(loja_id: str, codigos: list[str] | None, forcar: bool, visivel: bool,
                notify: bool, estado: dict) -> list[ResultadoCupom]:
    loja = LOJAS[loja_id]
    reg = estado.setdefault(loja_id, {"cupons": {}, "aviso_login": None, "ultima_execucao": None})
    reg.setdefault("cupons", {})
    if not loja.perfil().exists():
        print(f"[{loja_id}] sem login salvo. Rode: python testar_cupons.py --loja {loja_id} --login")
        return []
    pausa = _quando(reg.get("pausa_ate"))
    if pausa and agora() < pausa and not codigos:
        print(f"[{loja_id}] em pausa até {pausa.strftime('%d/%m %H:%M')}: {reg.get('pausa_motivo', '')}")
        return []
    # TV que o robô tirou do carrinho numa rodada anterior e não voltou: volta nesta, mesmo sem cupom pendente
    fora_antes = _tvs_fora_do_estado(loja, reg)
    conhecidos, anuncios = codigos_conhecidos(loja, reg)
    if not anuncios:
        # F1 (22/09 10:12): a coleta do ML foi bloqueada e o robô caiu no "anúncio padrão" (catálogo, vendedor
        # '?', R$ 0,00), tentou trocar a TV da pessoa e avisou "sacola VAZIA" à toa. Sem anúncio conhecido,
        # nada de troca, de teste de cupom nem de passo final.
        print(f"[{loja_id}] nenhum anúncio conhecido nesta rodada (a coleta não trouxe a TV desta loja — falhou ou "
              f"foi bloqueada — e o testador não leu anúncio dela nas últimas "
              f"{int(JANELA_ANUNCIO_DO_ESTADO.total_seconds() // 3600)} h): não mexo no carrinho")
        return []
    fila_base = _sem_repetir(codigos or conhecidos)
    grupos = por_modelo(anuncios)
    for m, lista in grupos.items():
        print(f"[{loja_id}] " + ("" if list(grupos) == [MODELO_PADRAO] else f"{m}: ")
              + f"{len(lista)} anúncio(s), do mais barato ao mais caro: "
              + " · ".join(f"{a.rotulo} {fmt_preco(a.preco)}" for a in lista[:8]))
    do_estado = [a for a in anuncios if a.origem == "estado"]
    if do_estado:
        de_quem = sorted({a.modelo for a in do_estado})
        qual = "desta loja" if list(grupos) == de_quem == [MODELO_PADRAO] else f"da {' e da '.join(de_quem)} desta loja"
        print(f"[{loja_id}] a coleta desta rodada não trouxe anúncio {qual}; uso {len(do_estado)} anúncio(s) "
              f"que o testador leu nas últimas {int(JANELA_ANUNCIO_DO_ESTADO.total_seconds() // 3600)} h")
    logados = [a for a in anuncios if a.origem == "catalogo_logado"]
    if logados:
        print(f"[{loja_id}] {len(logados)} opção(ões) do catálogo vista(s) pelo testador logado (a coleta sem login "
              "não mostra): " + " · ".join(a.rotulo for a in logados))
    if hasattr(loja, "comecar_rodada"):
        loja.comecar_rodada()
    so_leitura = getattr(loja, "so_leitura", False)
    p = Percurso(inicio=agora().replace(microsecond=0), orcamento=MAX_APLICACOES_POR_RODADA,
                 contexto=contexto_do_carrinho(anuncios), fora_de_antes=set(fora_antes))
    if fora_antes:
        print(f"[{loja_id}] a {' e a '.join(NOME_MODELO.get(m, m) for m in fora_antes)} saiu do carrinho numa rodada "
              "anterior e não voltou: vai de volta nesta rodada")
    interrompida: Optional[str] = None   # motivo (MOTIVO_PAROU_*) quando a loja parou no meio do percurso
    try:
        with _sessao(loja, visivel) as page:
            try:
                percorrer_modelos(loja, page, grupos, fila_base, reg, p, forcar, bool(codigos))
                _foto(page, loja_id)
            except LojaIndisponivel as e:
                interrompida = MOTIVO_PAROU_INDISPONIVEL
                _pausar(loja, reg, e)
            except CarrinhoOcupado as e:
                interrompida = MOTIVO_PAROU_OCUPADO
                print(f"[{loja_id}] {e}. Pulo a loja nesta rodada.")
            except PrecisaLogin as e:
                interrompida = MOTIVO_PAROU_LOGIN
                print(f"[{loja_id}] {e}")
                if notify and reg.get("aviso_login") != hoje():
                    notificar.enviar(f"🔐 <b>{loja.loja_canonica}</b>: a sessão expirou, não consigo testar cupons.\n"
                                     f"No PC, rode:\n<code>python testar_cupons.py --loja {loja_id} --login</code>")
                    reg["aviso_login"] = hoje()
            finally:
                reg["ultima_execucao"] = agora_iso()
                reg["precos"] = _precos_por_anuncio(reg.get("precos"), p, anuncios)
    except Exception as e:  # noqa: BLE001
        # falha do robô ou do navegador no meio da rodada (ex.: TimeoutError no page.goto de uma troca de anúncio):
        # a troca pode ter parado no meio, então o passo final ainda roda e os aceites da rodada não se perdem
        p.no_carrinho = None
        print(f"[{loja_id}] a rodada parou por uma falha do robô: {type(e).__name__}: {str(e)[:160]}")

    finais: dict = {}
    tentou: set = set()    # modelos de p.fora_de_antes que o robô tentou devolver ao carrinho nesta rodada
    try:
        if p.visitados and not so_leitura and not interrompida:
            tentou |= p.fora_de_antes & set(grupos)       # o passo final de sempre põe uma TV de cada modelo
            if len(grupos) == 1:
                (m, lista), = grupos.items()
                finais = {m: arrumar_carrinho(loja, p, lista, reg, visivel)}
            else:
                finais = arrumar_carrinho_modelos(loja, p, grupos, reg, visivel)
        else:
            if interrompida and not so_leitura and len(grupos) > 1 and p.modelos_fora:
                # a loja parou depois de o robô tirar a TV de um modelo (para medir o cupom do outro): sem passo final
                _avisar_tv_fora(loja, p.modelos_fora, interrompida)
            elif interrompida and interrompida != MOTIVO_PAROU_OCUPADO and not so_leitura and \
                    _removeu_sem_conferir(loja, p):
                # a loja parou (antirrobô, sessão) depois de o robô tirar a TV e antes de ela voltar: sem passo final
                _avisar_sacola_vazia(loja, [a for a in anuncios if a.chave in p.visitados], interrompida)
            if p.fora_de_antes and not so_leitura and interrompida in (None, MOTIVO_PAROU_OCUPADO):
                # nada pendente (o passo final não correu) ou a loja parou por uma TV que o robô não sabe devolver:
                # a TV que saiu numa rodada anterior volta mesmo assim (loja fora do ar ou sessão expirada: não)
                tentou |= devolver_tvs_fora(loja, p, grupos, reg, visivel)
    finally:
        if not so_leitura:
            _grava_tvs_fora(loja, reg, p, fora_antes, tentou)
    if getattr(loja, "tvs_a_mais", False):
        _avisar_tvs_a_mais(loja)
    _anota_opcoes_do_catalogo(reg, loja)
    print(f"[{loja_id}] {len(p.aceitos)} cupom(ns) aceito(s)")
    resultado = list(p.aceitos)
    for m, final in finais.items():
        if final and final[1] is not None and final[1].extra.get("anterior") and \
                any(_modelo_do_resultado(r) == m for r in p.aceitos):
            resultado.append(final[1])  # a mensagem compara com o melhor que já funcionou hoje
    for m, lista in grupos.items():
        marcar_se_compensa([r for r in resultado if _modelo_do_resultado(r) == m], *referencia_sem_cupom(p, lista))
    return resultado


def _tem_pendencia(anuncios: list[Anuncio], fila_base: list[str], testados: dict, p: Percurso, forcar: bool,
                   explicitos: bool) -> bool:
    """Algum anúncio deste modelo tem cupom para testar nesta rodada (mesma conta de percorrer, sem mexer em nada)?"""
    momento = agora()
    return any(pendentes(anuncios, i, fila_base, testados, momento, forcar, explicitos, p.inicio)[0]
               for i in range(len(anuncios)))


def percorrer_modelos(loja: LojaCarrinho, page, grupos: dict[str, list[Anuncio]], fila_base: list[str], reg: dict,
                      p: Percurso, forcar: bool = False, explicitos: bool = False) -> None:
    """percorrer() em cada modelo (55C6K primeiro). Os testes de cupom da rodada (p.orcamento, contra o antirrobô)
    são divididos entre os modelos que têm cupom pendente: cada um tem direito à sua parte, e o que um não usa passa
    para o seguinte. Loja só de leitura (Amazon) lê os anúncios dos dois modelos."""
    testados = reg.setdefault("cupons", {})
    so_leitura = getattr(loja, "so_leitura", False)
    modelos = list(grupos)
    pend = {m: so_leitura or _tem_pendencia(grupos[m], fila_base, testados, p, forcar, explicitos) for m in modelos}
    for k, m in enumerate(modelos):
        com_pendencia = [x for x in modelos[k:] if pend[x]]
        cota = p.orcamento
        if not so_leitura and pend[m] and len(com_pendencia) > 1:
            cota = -(-p.orcamento // len(com_pendencia))   # arredonda para cima
        if len(modelos) > 1:
            print(f"[{loja.nome}] {m}: " + (f"até {cota} teste(s) de cupom nesta rodada" if pend[m] and not so_leitura
                                           else ("leitura dos anúncios" if so_leitura else "nada pendente")))
        reserva = p.orcamento - cota
        p.orcamento = cota
        try:
            percorrer(loja, page, grupos[m], fila_base, reg, p, forcar, explicitos)
        finally:
            p.orcamento += reserva


def preco_a_vista(r: Optional[ResultadoCupom]) -> Optional[float]:
    """Preço à vista (Pix) de uma leitura do carrinho — só quando o Pix dela é mesmo Pix.

    Carrinho que não mostra o Pix (ML sempre; Amazon quando a página não traz o preço à vista) copia o total
    do CARTÃO para total_pix, e aí `tv_pix` é preço de cartão. Misturar esse número com o Pix coletado de
    outro anúncio marcava como "não compensa" um cupom que era o melhor preço NO CARTÃO (19/09, item B1)."""
    if r is None or not getattr(r, "pix_real", True):
        return None
    return r.tv_pix


def referencia_sem_cupom(p: Percurso, anuncios: list[Anuncio]) -> tuple[Optional[float], Optional[float]]:
    """(à vista, cartão) mais baratos da loja SEM cupom, entre todos os anúncios: a leitura do carrinho nesta
    rodada ou, sem ela, o preço coletado.

    Cada lista só junta preços da MESMA base: à vista com à vista (Pix de verdade), cartão com cartão."""
    vista: list[float] = []
    cartao: list[float] = []
    for a in anuncios:
        r = p.sem_cupom.get(a.chave)
        v = preco_a_vista(r) or a.preco            # Pix com Pix (a.preco é o menor preço coletado, à vista)
        c = (r.tv_cartao if r is not None else None) or a.preco_cartao
        if v:
            vista.append(v)
        if c:
            cartao.append(c)
    return (min(vista) if vista else None), (min(cartao) if cartao else None)


def marcar_se_compensa(resultados: list[ResultadoCupom], ref_vista: Optional[float],
                       ref_cartao: Optional[float]) -> None:
    """Cupom aceito que não deixa a TV mais barata que o anúncio mais barato sem cupom não é "melhor preço"
    (ex.: LU250 no Colombo a R$ 3.687,15 com o 1P a R$ 3.561,55 sem cupom). pior_a_vista / pior_parcelado
    tiram o resultado da disputa do melhor à vista / melhor parcelado na mensagem (msg_melhor).

    Cada comparação é entre preços da MESMA base. Quando o carrinho não mostra o Pix (ML, Amazon sem preço à
    vista na página), o número que a mensagem mostra como "à vista" é o do CARTÃO, então ele é comparado com a
    referência de cartão; sem referência na base certa, não marca (19/09, item B1)."""
    for r in resultados:
        vista = preco_a_vista(r)
        if vista is not None:
            r.extra["pior_a_vista"] = bool(ref_vista and vista >= ref_vista - 0.005)
        else:   # msg_melhor cai no tv_cartao: compara com o cartão, nunca com o Pix de outro anúncio
            r.extra["pior_a_vista"] = bool(ref_cartao and r.tv_cartao and r.tv_cartao >= ref_cartao - 0.005)
        r.extra["pior_parcelado"] = bool(ref_cartao and r.tv_cartao and r.tv_cartao >= ref_cartao - 0.005)


MOTIVO_SEM_TV = "o carrinho não ficou só com a TV"
MOTIVO_OCUPADO = "o carrinho tem outros produtos além da TV"
MOTIVO_SEM_TEMPO = "o tempo da rodada acabou antes do passo final"
MOTIVO_NAO_COMPENSA = "com o preço de agora o cupom não deixa a TV mais barata que o anúncio mais barato sem cupom"
MOTIVO_SEM_AS_DUAS = "o carrinho não ficou com uma TV de cada modelo"
MOTIVO_OUTRO_CUPOM = "o carrinho tem as duas TVs e vale um cupom por pedido"


def _marca_sem_cupom_no_carrinho(loja: LojaCarrinho, melhor: ResultadoCupom, motivo: str) -> None:
    melhor.extra["no_carrinho"] = False
    melhor.extra["motivo_carrinho"] = motivo[:120]
    print(f"[{loja.nome}] não deixei {melhor.codigo} aplicado no carrinho: {motivo[:120]}")


def _deixar_cupom(loja: LojaCarrinho, page, url: str, melhor: ResultadoCupom,
                  alvo: Optional[dict] = None) -> tuple[str, Optional[Exception], Optional[ResultadoCupom]]:
    """deixar_cupom_no_carrinho dizendo como o carrinho ficou:
    'ok' | 'sem_tv' (o anúncio não ficou sozinho no carrinho) | 'sem_cupom' (a TV ficou, o cupom não) |
    'parar' (carrinho com outro produto, loja fora do ar, sessão expirada: não mexer mais) | 'erro' (falha do robô).
    Devolve também a resposta da loja à aplicação (None quando não chegou a aplicar), para o registro (F4)."""
    melhor.extra["no_carrinho"] = False
    erro: Optional[Exception] = None
    final: Optional[ResultadoCupom] = None
    try:
        if not loja.garantir_item(page, url, alvo):
            situacao, motivo = "sem_tv", MOTIVO_SEM_TV
        else:
            final = loja.aplicar(page, melhor.codigo)
            if final.aceito and final.codigo == melhor.codigo:
                melhor.extra["no_carrinho"] = True
                if final.total_pix is not None or final.total_cartao is not None:
                    # o preço de agora (para um aceite de mais cedo, o total pode ter mudado)
                    for k in ("total_pix", "total_cartao", "frete", "desconto", "parcelado", "quantidade"):
                        setattr(melhor, k, getattr(final, k))
                return "ok", None, final
            situacao, motivo = "sem_cupom", final.mensagem or "a loja não confirmou o cupom"
    except CarrinhoOcupado as e:
        situacao, motivo, erro = "parar", MOTIVO_OCUPADO, e
    except (LojaIndisponivel, PrecisaLogin) as e:
        situacao, motivo, erro = "parar", f"erro: {type(e).__name__}", e
    except Exception as e:  # noqa: BLE001
        situacao, motivo, erro = "erro", f"erro: {type(e).__name__}", e
    _marca_sem_cupom_no_carrinho(loja, melhor, motivo)
    return situacao, erro, final


def deixar_cupom_no_carrinho(loja: LojaCarrinho, page, url: str, melhor: ResultadoCupom,
                             alvo: Optional[dict] = None) -> bool:
    """Passo final: carrinho só com a TV (1 unidade) e o melhor cupom aplicado de novo.

    Marca melhor.extra["no_carrinho"] = True só quando garantir_item conferiu o carrinho e a loja
    aceitou o MESMO código; senão grava o motivo, e o alerta manda aplicar à mão.
    """
    return _deixar_cupom(loja, page, url, melhor, alvo)[0] == "ok"


def executar(lojas: list[str], codigos: list[str] | None, forcar: bool, visivel: bool, notify: bool) -> int:
    global _INICIO
    _INICIO = time.monotonic()
    AVISOS_CARRINHO.clear()
    estado = carrega_estado()
    resultados: list[tuple[str, ResultadoCupom]] = []
    for loja_id in lojas:
        try:
            # o perfil fica travado durante toda a loja: nenhum outro processo abre o mesmo Chrome
            with trava_perfil(LOJAS[loja_id].perfil(), espera_s=60):
                for r in testar_loja(loja_id, codigos, forcar, visivel, notify, estado):
                    resultados.append((LOJAS[loja_id].loja_canonica, r))
        except PerfilOcupado as e:
            print(f"[{loja_id}] pulado: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[{loja_id}] falhou: {type(e).__name__}: {str(e)[:160]}")
        salva_estado(estado)
    msg = msg_melhor(resultados)
    if AVISOS_CARRINHO:  # sacola que pode ter ficado vazia: a pessoa precisa saber, com ou sem cupom aceito
        msg = (msg + "\n\n" if msg else "") + "\n".join(AVISOS_CARRINHO)
    if msg:
        if notify:
            notificar.enviar(msg)
        else:
            print("\n[alerta]\n" + msg + "\n")
    return 0


def checar_sessao(loja_id: str, visivel: bool = False) -> bool:
    """Abre o carrinho num contexto novo do perfil salvo e diz se a sessão está logada (com foto em logs/)."""
    loja = LOJAS[loja_id]
    from playwright.sync_api import sync_playwright

    (RAIZ / "logs").mkdir(exist_ok=True)
    try:
        with trava_perfil(loja.perfil(), espera_s=60):
            return _checar_sessao_travado(loja_id, loja, visivel)
    except PerfilOcupado as e:
        print(f"[{loja_id}] {e}")
        return False


def _checar_sessao_travado(loja_id: str, loja, visivel: bool) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel=visivel)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(loja.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            ok = loja.logado(page)
            texto = page.evaluate("() => document.body ? document.body.innerText : ''")
            foto = RAIZ / "logs" / f"sessao_{loja_id}.png"
            page.screenshot(path=str(foto))
            print(f"[{loja_id}] url: {page.url}")
            print(f"[{loja_id}] cabeçalho: {texto[:260].replace(chr(10), ' | ')}")
            print(f"[{loja_id}] foto: {foto}")
        except Exception as e:  # noqa: BLE001
            print(f"[{loja_id}] erro ao abrir o carrinho: {type(e).__name__}: {str(e)[:120]}")
            ok = False
        finally:
            ctx.close()
    print(f"[{loja_id}] sessão logada: {'SIM' if ok else 'NÃO'}")
    return ok


def login(loja_id: str) -> int:
    loja = LOJAS[loja_id]

    print(f"Vai abrir uma janela normal do Chrome na página de login do {loja.loja_canonica}.")
    print("É um Chrome comum, sem automação: o captcha carrega igual ao do seu navegador do dia a dia.")
    print("Faça o login (e-mail/CPF, senha, código se pedir). Eu não vejo nem guardo esses dados;")
    print("ficam só no perfil do Chrome desta pasta.")
    try:
        trava = trava_perfil(loja.perfil(), espera_s=90)
        trava.__enter__()
    except PerfilOcupado:
        print("O monitor está usando esse perfil agora. Espere a rodada terminar e tente de novo.")
        return 1
    try:
        proc = abrir_chrome_normal(loja, loja.url_login)
        if proc is None:
            print("Não encontrei o chrome.exe. Instale o Google Chrome ou me avise.")
            return 1
        print("\nQuando terminar o login, FECHE a janela do Chrome e volte aqui.")
        input(">>> Fechou a janela? Aperte Enter para eu conferir a sessão... ")
        if proc.poll() is None:
            print("A janela ainda está aberta; fechando para liberar o perfil...")
            try:
                proc.terminate()
            except Exception:
                pass
        import time

        time.sleep(3)
    finally:
        trava.__exit__(None, None, None)
    ok = checar_sessao(loja_id)
    if ok:
        print(f"Login salvo. Agora rode: python testar_cupons.py --loja {loja_id} --visivel --forcar")
        return 0
    print("Não detectei a sessão logada. Veja a foto em logs\\ e me mande o cabeçalho acima.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loja", default="todas", choices=sorted(LOJAS) + ["todas"])
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--check", action="store_true", help="só confere se a sessão salva está logada")
    ap.add_argument("--codigos", default="")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--visivel", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()
    (RAIZ / "logs").mkdir(exist_ok=True)
    lojas = sorted(LOJAS) if a.loja == "todas" else [a.loja]
    if a.login:
        if a.loja == "todas":
            return print("escolha a loja: --loja magalu --login") or 1
        return login(a.loja)
    if a.check:
        return 0 if all(checar_sessao(l, a.visivel) for l in lojas) else 1
    cods = [c.strip() for c in a.codigos.split(",") if c.strip()] or None
    return executar(lojas, cods, a.forcar, a.visivel, not a.no_notify)


if __name__ == "__main__":
    if "--login" in sys.argv:
        sys.exit(main())  # login é interativo: sem cão de guarda
    from monitor.saida import sair, vigiar

    vigiar(17 * 60, "cupons")
    sair(main())
