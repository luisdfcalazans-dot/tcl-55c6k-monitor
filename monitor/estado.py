"""Estado persistente (JSON), histórico (CSV) e arquivo do painel (latest JSON).

Cada modo (cloud / pc) tem os seus próprios arquivos para que os dois executores
não briguem no git: docs/data/state_<modo>.json, historico_<modo>.csv, latest_<modo>.json.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Callable

from . import config
from .models import Cupom, Oferta
from .util import agora_iso, dias_desde, loja_canonica, sem_acentos

CAMPOS_HISTORICO = [
    "quando", "fonte", "tipo", "loja", "vendedor", "titulo", "preco", "preco_pix", "parcelado", "cupom", "url",
]
MODOS = ("cloud", "pc")
# um cupom já alertado só volta a ser alerta depois deste prazo sem aparecer (ou se o desconto mudar)
JANELA_CUPOM_DIAS = 30


def marca_cupom(loja: str, codigo: str) -> str:
    """Identidade do cupom entre fontes e ids: 'Loja canônica|CÓDIGO'."""
    return f"{loja_canonica(loja or '')}|{str(codigo or '').upper()}"


AGREGADORES = ("zoom", "buscape")
_RE_URL_AGREGADOR = re.compile(r"^https?://(?:www\.)?(?:zoom|buscape)\.com\.br/", re.I)


def _campo(o: Any, nome: str) -> Any:
    return o.get(nome) if isinstance(o, dict) else getattr(o, nome, None)


def e_agregador(o: Oferta | dict) -> bool:
    """Zoom/Buscapé é agregador de preços, não loja: o preço que ele mostra pode estar atrasado (a Amazon ficou a
    R$ 3.279 no Zoom de 14 a 18/09 com a loja a R$ 3.749).

    Mesmo critério do painel (docs/index.html, ehAgregador): extra.agregador, fonte zoom/buscape ou URL deles. Aceita
    Oferta ou registro (dict) de state/latest, inclusive o "minimo", que só traz a URL."""
    extra = _campo(o, "extra")
    if isinstance(extra, dict) and extra.get("agregador"):
        return True
    if str(_campo(o, "fonte") or "").strip().lower() in AGREGADORES:
        return True
    return bool(_RE_URL_AGREGADOR.match(str(_campo(o, "url") or "")))


# o histórico por oferta que passa da chave antiga para a nova (ver Estado.migra_chaves_de_oferta)
CAMPOS_MIGRADOS = ("primeira_vez", "menor_preco", "ultimo_preco", "preco_alertado", "ultima_vez")


def _norm_vendedor(nome: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acentos(str(nome or "")).lower())


def _caminho_url(url: Any) -> str:
    """URL sem query nem fragmento: o caminho do anúncio não muda quando a chave ganha o vendedor
    (a Amazon passa a pôr ?smid=..., o Magalu ?seller_id=...)."""
    return str(url or "").strip().lower().split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _identidade_de_oferta(o: Any) -> tuple[str, str, str] | None:
    """(loja canônica, vendedor, caminho da URL) de uma oferta de loja: o que identifica anúncio+vendedor
    independentemente do formato da chave 'fonte:id'. None quando falta alguma das três."""
    if str(_campo(o, "tipo") or "") != "loja":
        return None
    loja = loja_canonica(str(_campo(o, "loja") or ""))
    vend = _norm_vendedor(_campo(o, "vendedor"))
    url = _caminho_url(_campo(o, "url"))
    return (loja, vend, url) if loja and loja != "?" and vend and url else None


def _e_direta(r: Any) -> bool:
    return isinstance(r, dict) and r.get("tipo") == "loja" and not e_agregador(r)


def lojas_diretas(ofertas: list[Oferta]) -> set[str]:
    """Lojas que têm oferta de fonte direta (não agregador) nesta rodada, ativa ou não."""
    return {loja_canonica(o.loja) for o in ofertas if o.tipo == "loja" and not e_agregador(o)}


def conta_como_preco(o: Oferta, diretas: set[str] | None = None) -> bool:
    """Se a oferta pode virar "menor já visto", alerta de preço de loja, linha do resumo e da mensagem de partida.

    Nunca: oferta inativa (esgotada ou descartada pelo sanear) ou sem preço.
    Agregador: só quando a loja não tem fonte direta conhecida (`diretas`: Estado.lojas_diretas_conhecidas, que junta
    esta rodada, o state deste modo e o state/latest do outro modo; diretas=None = não sabemos -> não conta).
    """
    if o.tipo != "loja" or not o.ativo or not o.melhor_preco:
        return False
    if e_agregador(o):
        return diretas is not None and loja_canonica(o.loja) not in diretas
    return True


def _preco_do_minimo(m: Any) -> float | None:
    try:
        return float(m["preco"]) if m and m.get("preco") else None
    except (TypeError, ValueError, AttributeError):
        return None


def _minimo_conta(m: Any, diretas: set[str]) -> bool:
    """O mínimo gravado vale? Não quando veio de agregador de uma loja que tem fonte direta (preço parado no Zoom)."""
    return bool(_preco_do_minimo(m)) and not (e_agregador(m) and loja_canonica(m.get("loja") or "") in diretas)


def _minimo_dos_registros(registros: Any, diretas: set[str]) -> dict | None:
    """O menor preço já gravado nos registros de oferta que contam (substitui um mínimo de agregador que não vale)."""
    melhor = None
    for r in (registros.values() if isinstance(registros, dict) else registros or []):
        if not isinstance(r, dict) or r.get("tipo") != "loja":
            continue
        try:
            p = float(r.get("menor_preco") or 0)
        except (TypeError, ValueError):
            continue
        if p <= 0 or (e_agregador(r) and loja_canonica(r.get("loja") or "") in diretas):
            continue
        if melhor is None or p < melhor[0]:
            melhor = (p, r)
    if melhor is None:
        return None
    p, r = melhor
    return {"preco": p, "loja": r.get("loja"), "quando": r.get("ultima_vez") or r.get("primeira_vez") or "",
            "url": r.get("url"), "titulo": r.get("titulo")}


class Estado:
    def __init__(self, modo: str):
        self.modo = modo
        config.DIR_DADOS.mkdir(parents=True, exist_ok=True)
        self.arq_estado = config.DIR_DADOS / f"state_{modo}.json"
        self.arq_hist = config.DIR_DADOS / f"historico_{modo}.csv"
        self.arq_latest = config.DIR_DADOS / f"latest_{modo}.json"
        self.dados: dict[str, Any] = {
            "ofertas": {},        # chave -> registro
            "cupons": {},         # chave -> registro
            "minimo": None,       # {"preco", "loja", "quando", "url"}
            "saude": {},          # fonte -> {"falhas", "ultimo_ok", "ultimo_erro"}
            "ultimo_resumo": None,
            "criado_em": None,
            # 'loja|CÓDIGO' -> alertas de cupom enviados (chave, fonte, título, regra, especifico, quando)
            "cupons_alertados": {},
        }
        carregado: dict[str, Any] = {}
        if self.arq_estado.exists():
            try:
                carregado = json.loads(self.arq_estado.read_text(encoding="utf-8"))
                self.dados.update(carregado)
            except json.JSONDecodeError:
                pass
        # estado gravado antes de os alertas de cupom serem registrados: ver migra_alertas_de_cupom
        self._cupons_legado = bool(self.dados["cupons"]) and "cupons_alertados" not in carregado
        self._alertas_cupom_rodada: list[tuple[str, dict]] = []  # para desfazer se a mensagem não sair
        self._cache_outros: dict[str, Any] = {}  # state/latest do outro modo (só leitura, lidos uma vez por rodada)
        self.bootstrap = not self.dados["ofertas"] and self.dados.get("criado_em") is None
        if self.dados.get("criado_em") is None:
            self.dados["criado_em"] = agora_iso()

    # ---- ofertas ----
    def oferta_anterior(self, chave: str) -> dict | None:
        return self.dados["ofertas"].get(chave)

    def migra_chaves_de_oferta(self, ofertas: list[Oferta]) -> dict[str, str]:
        """Leva o histórico por oferta da chave antiga para a nova quando só o FORMATO da chave mudou.

        Quando a coleta passa a identificar o vendedor na chave (Amazon 'B0F7JZMVKF' -> 'B0F7JZMVKF-<vendedor>',
        Casas Bahia '55069456' -> '55069456-<lojista>', ML catálogo -> item do vendedor), a chave nova nasce sem
        passado: a rodada não manda 🔻 (não há 'ultimo_preco' para comparar) e pode repetir 🎯 (não há
        'preco_alertado'). Aqui a chave antiga é reconhecida pelo que não mudou — loja, vendedor e o caminho da
        URL do anúncio — e leva junto CAMPOS_MIGRADOS. Devolve {chave antiga: chave nova}.

        Conservador de propósito: só entra chave nova que ainda não tem registro, só sai registro que ninguém
        mais usa nesta rodada, e identidade disputada por mais de uma oferta não migra (inventaria um 🔻).
        Roda uma vez por registro: 'migrado_para' marca o que já passou.
        """
        regs = self.dados["ofertas"]
        usadas = {o.chave for o in ofertas}
        novas: dict[tuple, list[str]] = {}
        for o in ofertas:
            ident = _identidade_de_oferta(o) if o.chave not in regs else None
            if ident:
                novas.setdefault(ident, []).append(o.chave)
        velhas: dict[tuple, list[str]] = {}
        for chave, r in regs.items():
            if chave in usadas or not isinstance(r, dict) or r.get("migrado_para"):
                continue
            ident = _identidade_de_oferta(r)
            if ident:
                velhas.setdefault(ident, []).append(chave)
        mapa: dict[str, str] = {}
        for ident, candidatas in novas.items():
            iguais = velhas.get(ident) or []
            if len(candidatas) != 1 or len(iguais) != 1:
                continue   # ninguém ou ambíguo: melhor sem passado do que com o passado de outro anúncio
            nova, velha = candidatas[0], iguais[0]
            passado = {k: regs[velha][k] for k in CAMPOS_MIGRADOS if regs[velha].get(k) is not None}
            if not passado:
                continue
            regs[nova] = passado
            regs[velha]["migrado_para"] = nova
            regs[velha]["ativo"] = False
            mapa[velha] = nova
        return mapa

    def registra_oferta(self, o: Oferta, alertado_preco: float | None = None) -> None:
        reg = self.dados["ofertas"].get(o.chave) or {"primeira_vez": agora_iso(), "preco_alertado": None}
        reg.update(o.to_dict())
        reg["ultima_vez"] = agora_iso()
        # preço de oferta esgotada ou descartada pelo sanear não é preço da TV: não vira último nem menor preço
        if o.ativo and o.melhor_preco:
            reg["ultimo_preco"] = o.melhor_preco
            mp = reg.get("menor_preco")
            if mp is None or o.melhor_preco < mp:
                reg["menor_preco"] = o.melhor_preco
        if alertado_preco is not None:
            reg["preco_alertado"] = alertado_preco
        self.dados["ofertas"][o.chave] = reg

    def marca_inativas(self, chaves_vistas: set[str], fontes_executadas: set[str]) -> None:
        """Ofertas de loja que não apareceram desta vez (na fonte que rodou) ficam inativas."""
        for chave, reg in self.dados["ofertas"].items():
            if reg.get("tipo") != "loja":
                continue
            if reg.get("fonte") in fontes_executadas and chave not in chaves_vistas:
                reg["ativo"] = False

    # ---- cupons ----
    def cupom_anterior(self, chave: str) -> dict | None:
        return self.dados["cupons"].get(chave)

    def cupons_vistos(self, dias: float = JANELA_CUPOM_DIAS, todos_os_modos: bool = True) -> list[dict]:
        """Anúncios de cupom vistos nos últimos `dias` dias (para saber o que outro anúncio do mesmo código diz).

        todos_os_modos: inclui os do outro modo (state_<outro>.json, só leitura; arquivo ausente ou quebrado é
        ignorado). O cloud lê o Promobit e o pc lê o Pelando: o que um sabe de um código (ex.: DESCONTOJA é só
        "em Casa") vale para o outro."""
        regs = list(self.dados["cupons"].values())
        if todos_os_modos:
            for m in MODOS:
                if m != self.modo:
                    regs += self._cupons_do_modo(m)
        out = []
        for reg in regs:
            d = dias_desde(reg.get("ultima_vez") or reg.get("primeira_vez"))
            if d is None or d <= dias:
                out.append(reg)
        return out

    def _arquivo_do_modo(self, nome: str) -> dict | None:
        """state_<outro>.json ou latest_<outro>.json (só leitura). Ausente ou quebrado -> None."""
        if nome not in self._cache_outros:
            try:
                d = json.loads((self.arq_estado.parent / nome).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = None
            self._cache_outros[nome] = d if isinstance(d, dict) else None
        return self._cache_outros[nome]

    def _outros_modos(self) -> list[str]:
        return [m for m in MODOS if m != self.modo]

    def _cupons_do_modo(self, modo: str) -> list[dict]:
        cupons = (self._arquivo_do_modo(f"state_{modo}.json") or {}).get("cupons")
        return [r for r in cupons.values() if isinstance(r, dict)] if isinstance(cupons, dict) else []

    # ---- fontes diretas x agregador (Zoom) ----
    def lojas_diretas_conhecidas(self, ofertas: list[Oferta] = ()) -> set[str]:
        """Lojas com fonte direta (não agregador) nesta rodada, no state deste modo ou no state/latest do outro modo,
        de qualquer idade: o mesmo critério do painel, que esconde a linha do agregador quando alguma fonte direta
        (de qualquer modo, mesmo antiga) cobre a loja. O cloud não tem fonte direta da Amazon, o pc tem."""
        s = lojas_diretas(list(ofertas))
        regs: list[Any] = list(self.dados["ofertas"].values())
        for m in self._outros_modos():
            st = (self._arquivo_do_modo(f"state_{m}.json") or {}).get("ofertas")
            regs += list(st.values()) if isinstance(st, dict) else []
            lt = (self._arquivo_do_modo(f"latest_{m}.json") or {}).get("ofertas_loja")
            regs += lt if isinstance(lt, list) else []
        return s | {loja_canonica(r.get("loja") or "") for r in regs if _e_direta(r)}

    def ofertas_diretas_de_outros_modos(self) -> list[dict]:
        """Ofertas de fonte direta, ativas e com preço, na última rodada do outro modo (latest_<outro>.json; sem ele,
        os registros ativos do state_<outro>.json). Cada uma leva '_modo' e '_visto' (quando o outro modo a viu)."""
        out: list[dict] = []
        for m in self._outros_modos():
            lt = self._arquivo_do_modo(f"latest_{m}.json")
            if lt and isinstance(lt.get("ofertas_loja"), list):
                for o in lt["ofertas_loja"]:
                    if _e_direta(o) and o.get("ativo", True) and _preco_do_minimo({"preco": o.get("melhor_preco")}):
                        out.append({**o, "_modo": m, "_visto": lt.get("atualizado") or ""})
                continue
            st = (self._arquivo_do_modo(f"state_{m}.json") or {}).get("ofertas")
            for r in (st.values() if isinstance(st, dict) else []):
                if _e_direta(r) and r.get("ativo") and _preco_do_minimo({"preco": r.get("ultimo_preco")}):
                    out.append({**r, "melhor_preco": r["ultimo_preco"], "_modo": m, "_visto": r.get("ultima_vez") or ""})
        return out

    def alertas_de_cupom(self, marca: str, dias: float = JANELA_CUPOM_DIAS) -> list[dict]:
        """Alertas já ENVIADOS para 'loja|CÓDIGO' que ainda valem: alertados há até `dias` dias, ou cujo anúncio
        alertado continua aparecendo. Cupom só visto (ou visto e incompatível) não entra aqui."""
        out = []
        for a in self.dados.get("cupons_alertados", {}).get(marca, []):
            reg = self.dados["cupons"].get(a.get("chave")) or {}
            ds = [d for d in (dias_desde(a.get("quando")), dias_desde(reg.get("ultima_vez"))) if d is not None]
            if ds and min(ds) <= dias:
                out.append(a)
        return out

    def registra_alerta_cupom(self, c: Cupom | dict, quando: str | None = None, origem: str = "alerta") -> None:
        """Guarda o que foi alertado (título e regra da época), para decidir se o mesmo código é novidade depois.

        origem: "alerta" (mensagem de cupom), "partida" (anunciado na mensagem de início do monitor, que avisa que
        "a partir de agora só chegam novidades") ou "legado" (reconstruído de um estado antigo).
        """
        d = c.to_dict() if isinstance(c, Cupom) else c
        marca = marca_cupom(d.get("loja") or "", d.get("codigo") or "")
        alerta = {
            "chave": d.get("chave") or f"{d.get('fonte')}:{d.get('id')}", "fonte": d.get("fonte"),
            "titulo": (d.get("titulo") or "")[:200], "regra": (d.get("regra") or "")[:400],
            "especifico": bool(d.get("especifico")), "quando": quando or agora_iso(), "origem": origem,
        }
        self.dados.setdefault("cupons_alertados", {}).setdefault(marca, []).append(alerta)
        if origem == "alerta":
            self._alertas_cupom_rodada.append((marca, alerta))

    def esquece_alertas_de_cupom_da_rodada(self) -> int:
        """A mensagem de cupons desta rodada não saiu (cortada pelo limite ou falha no envio): os cupons dela não
        foram alertados e continuam podendo virar alerta."""
        todos = self.dados.get("cupons_alertados", {})
        n = 0
        for marca, alerta in self._alertas_cupom_rodada:
            lista = todos.get(marca, [])
            resto = [a for a in lista if a is not alerta]
            n += len(lista) - len(resto)
            if resto:
                todos[marca] = resto
            else:
                todos.pop(marca, None)
        self._alertas_cupom_rodada = []
        return n

    def migra_alertas_de_cupom(self, alertou: Callable[[dict], bool]) -> int:
        """Estado antigo (sem 'cupons_alertados') não diz quais cupons viraram alerta. O código da época alertava
        (ou, na partida, anunciava) todo cupom de chave nova que a regra de então aceitava: `alertou(reg)` responde
        isso para cada registro. Roda uma vez; depois só vale o que registra_alerta_cupom gravou."""
        if not self._cupons_legado:
            return 0
        self._cupons_legado = False
        self.dados.setdefault("cupons_alertados", {})
        n = 0
        for reg in self.dados["cupons"].values():
            if reg.get("codigo") and alertou(reg):
                self.registra_alerta_cupom(reg, quando=reg.get("primeira_vez"), origem="legado")
                n += 1
        return n

    def registra_cupom(self, c: Cupom) -> None:
        reg = self.dados["cupons"].get(c.chave) or {"primeira_vez": agora_iso()}
        reg.update(c.to_dict())
        reg["ultima_vez"] = agora_iso()
        self.dados["cupons"][c.chave] = reg

    # ---- mínimo histórico (só lojas confiáveis) ----
    def minimo(self) -> dict | None:
        return self.dados.get("minimo")

    def _minimo_do_modo(self, modo: str, diretas: set[str]) -> dict | None:
        """Mínimo gravado pelo outro modo (só leitura). Arquivo ausente ou quebrado -> None. Mínimo que veio de
        agregador de loja com fonte direta não vale: fica o menor dos registros que contam (como o painel)."""
        for nome in (f"state_{modo}.json", f"latest_{modo}.json"):
            d = self._arquivo_do_modo(nome)
            m = d.get("minimo") if d else None
            if not _preco_do_minimo(m):
                continue
            if _minimo_conta(m, diretas):
                return m
            if nome.startswith("state_"):
                return _minimo_dos_registros(d.get("ofertas"), diretas)
        return None

    def _minimo_proprio(self, diretas: set[str]) -> dict | None:
        m = self.dados.get("minimo")
        if not _preco_do_minimo(m):
            return None
        return m if _minimo_conta(m, diretas) else _minimo_dos_registros(self.dados["ofertas"], diretas)

    def minimo_geral(self, diretas: set[str] | None = None) -> dict | None:
        """Menor preço já visto considerando os dois modos (cloud e pc), como o painel mostra. `diretas`: ver
        lojas_diretas_conhecidas (None: calcula sem as ofertas da rodada)."""
        if diretas is None:
            diretas = self.lojas_diretas_conhecidas()
        candidatos = [self._minimo_proprio(diretas)] + [self._minimo_do_modo(m, diretas) for m in self._outros_modos()]
        validos = [m for m in candidatos if _preco_do_minimo(m)]
        return min(validos, key=_preco_do_minimo) if validos else None

    def atualiza_minimo(self, o: Oferta, diretas: set[str] | None = None) -> bool:
        """`diretas`: lojas com fonte direta conhecidas (lojas_diretas_conhecidas). Ver conta_como_preco."""
        p = o.melhor_preco
        if not p or not conta_como_preco(o, diretas):
            return False
        m = self.dados.get("minimo")
        if diretas is not None and _preco_do_minimo(m) and not _minimo_conta(m, diretas):
            # mínimo gravado de agregador de loja que tem fonte direta (preço parado no Zoom): não vale
            m = self.dados["minimo"] = _minimo_dos_registros(self.dados["ofertas"], diretas)
        if m is None or p < float(m["preco"]):
            self.dados["minimo"] = {"preco": p, "loja": o.loja, "quando": agora_iso(), "url": o.url, "titulo": o.titulo}
            return m is not None  # na primeira vez não é "novo mínimo", é o primeiro
        return False

    # ---- saúde das fontes ----
    def fonte_ok(self, nome: str) -> None:
        s = self.dados["saude"].setdefault(nome, {"falhas": 0, "ultimo_ok": None, "ultimo_erro": None})
        s["falhas"] = 0
        s["ultimo_ok"] = agora_iso()
        s["ultimo_erro"] = None

    def fonte_falhou(self, nome: str, erro: str) -> int:
        s = self.dados["saude"].setdefault(nome, {"falhas": 0, "ultimo_ok": None, "ultimo_erro": None})
        s["falhas"] = int(s.get("falhas", 0)) + 1
        s["ultimo_erro"] = f"{agora_iso()} {erro[:300]}"
        return s["falhas"]

    # ---- persistência ----
    def salva(self) -> None:
        self.arq_estado.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1), encoding="utf-8")

    def anexa_historico(self, ofertas: list[Oferta]) -> None:
        novo = not self.arq_hist.exists()
        with self.arq_hist.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_HISTORICO)
            if novo:
                w.writeheader()
            for o in ofertas:
                if not o.ativo or not o.melhor_preco:
                    continue  # esgotada ou descartada pelo sanear: o preço não é da TV e distorce o gráfico
                w.writerow({
                    "quando": agora_iso(), "fonte": o.fonte, "tipo": o.tipo, "loja": o.loja,
                    "vendedor": o.vendedor or "", "titulo": o.titulo[:160], "preco": o.preco or "",
                    "preco_pix": o.preco_pix or "", "parcelado": o.parcelado or "", "cupom": o.cupom or "",
                    "url": o.url,
                })

    def escreve_latest(self, ofertas: list[Oferta], cupons: list[Cupom]) -> None:
        lojas = [o.to_dict() for o in ofertas if o.tipo == "loja"]
        lojas.sort(key=lambda d: (d["melhor_preco"] is None, d["melhor_preco"] or 0))
        # posts: os desta execução + os recentes já conhecidos
        posts_conhecidos = [r for r in self.dados["ofertas"].values() if r.get("tipo") == "post"]
        posts_conhecidos.sort(key=lambda r: r.get("publicado") or r.get("primeira_vez") or "", reverse=True)
        cupons_ativos = [c.to_dict() for c in cupons]
        latest = {
            "modo": self.modo,
            "atualizado": agora_iso(),
            "alvo_pix": config.ALVO_PIX,
            "alvo_parcelado": config.ALVO_PARCELADO,
            "minimo": self.dados.get("minimo"),
            "ofertas_loja": lojas,
            "posts": posts_conhecidos[:60],
            "cupons": cupons_ativos,
            "saude": self.dados["saude"],
        }
        self.arq_latest.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
