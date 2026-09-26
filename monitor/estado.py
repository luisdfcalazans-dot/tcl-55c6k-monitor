"""Estado persistente (JSON), histórico (CSV) e arquivo do painel (latest JSON).

Cada modo (cloud / pc) tem os seus próprios arquivos para que os dois executores
não briguem no git: docs/data/state_<modo>.json, historico_<modo>.csv, latest_<modo>.json.

Dois modelos (26/09/2026): 55C6K e 65C6K. Registro de oferta e linha do histórico levam 'modelo' (dado antigo sem o
campo é da 55C6K; nada é reescrito à mão). O "menor já visto" é por modelo: 'minimo' (55C6K, a chave de sempre) e
'minimo_65C6K' no state e no latest (chave_minimo). A primeira rodada em que um modelo aparece num modo é a partida
("bootstrap") desse modelo: registra tudo, sem alerta dele.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from . import config
from .confianca import (
    REPROVADO, e_do_reprovado_auto, fora_de_preco, identidade_em_duvida, motivo_bloqueio, reprovados_auto_do_estado,
    reprovados_para_painel, veredito_de,
)
from .models import MODELO_PADRAO, MODELOS, Cupom, Oferta, modelo_de
from .util import agora_iso, dias_desde, loja_canonica, sem_acentos

# 'modelo' no fim (26/09): o CSV antigo ganha a coluna só no cabeçalho, e as linhas antigas (sem ela) são da 55C6K
CAMPOS_HISTORICO = [
    "quando", "fonte", "tipo", "loja", "vendedor", "titulo", "preco", "preco_pix", "parcelado", "cupom", "url", "modelo",
]
MODOS = ("cloud", "pc")
# um cupom já alertado só volta a ser alerta depois deste prazo sem aparecer (ou se o desconto mudar)
JANELA_CUPOM_DIAS = 30


def chave_minimo(modelo: str = MODELO_PADRAO) -> str:
    """Chave do "menor já visto" do modelo no state e no latest: 'minimo' (55C6K, a de sempre) ou 'minimo_65C6K'."""
    m = modelo_de({"modelo": modelo})
    return "minimo" if m == MODELO_PADRAO else f"minimo_{m}"


def _linha_csv_valida(cab: list[str], row: list[str]) -> bool:
    """A linha tem o número de colunas do cabeçalho, ou uma a menos quando a que falta é a 'modelo' do fim (linha
    gravada antes de 26/09 num arquivo cujo cabeçalho já ganhou a coluna)."""
    return len(row) == len(cab) or (len(row) == len(cab) - 1 and bool(cab) and cab[-1] == "modelo")


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


def _identidade_de_oferta(o: Any) -> tuple[str, str, str, str] | None:
    """(loja canônica, vendedor, caminho da URL, modelo) de uma oferta de loja: o que identifica anúncio+vendedor
    independentemente do formato da chave 'fonte:id'. None quando falta alguma das três primeiras."""
    if str(_campo(o, "tipo") or "") != "loja":
        return None
    loja = loja_canonica(str(_campo(o, "loja") or ""))
    vend = _norm_vendedor(_campo(o, "vendedor"))
    url = _caminho_url(_campo(o, "url"))
    return (loja, vend, url, modelo_de(o)) if loja and loja != "?" and vend and url else None


def _e_direta(r: Any) -> bool:
    return isinstance(r, dict) and r.get("tipo") == "loja" and not e_agregador(r)


def lojas_diretas(ofertas: list[Oferta]) -> set[str]:
    """Lojas que têm oferta de fonte direta (não agregador) nesta rodada, ativa ou não."""
    return {loja_canonica(o.loja) for o in ofertas if o.tipo == "loja" and not e_agregador(o)}


def conta_como_preco(o: Oferta, diretas: set[str] | None = None) -> bool:
    """Se a oferta pode virar "menor já visto", alerta de preço de loja, linha do resumo e da mensagem de partida.

    Nunca: oferta inativa (esgotada ou descartada pelo sanear), sem preço, ou de anúncio suspeito/reprovado
    (monitor/confianca.py).
    Agregador: só quando a loja não tem fonte direta conhecida (`diretas`: Estado.lojas_diretas_conhecidas, que junta
    esta rodada, o state deste modo e o state/latest do outro modo; diretas=None = não sabemos -> não conta).
    """
    if o.tipo != "loja" or not o.ativo or not o.melhor_preco or fora_de_preco(o):
        return False
    if e_agregador(o):
        return diretas is not None and loja_canonica(o.loja) not in diretas
    return True


def _preco_do_minimo(m: Any) -> float | None:
    try:
        return float(m["preco"]) if m and m.get("preco") else None
    except (TypeError, ValueError, AttributeError):
        return None


def _nunca(_r: Any) -> bool:
    return False


def _minimo_conta(m: Any, diretas: set[str], bloqueado: Callable[[Any], bool] = _nunca) -> bool:
    """O mínimo gravado vale? Não quando veio de agregador de uma loja que tem fonte direta (preço parado no Zoom), nem
    de vendedor/anúncio reprovado (caso de 25/09/2026: o anúncio suspeito de R$ 2.609,01 virou o 'menor já visto')."""
    return bool(_preco_do_minimo(m)) and not (e_agregador(m) and loja_canonica(m.get("loja") or "") in diretas) \
        and not bloqueado(m)


def _minimo_dos_registros(registros: Any, diretas: set[str], bloqueado: Callable[[Any], bool] = _nunca,
                         modelo: str = MODELO_PADRAO) -> dict | None:
    """O menor preço já gravado nos registros de oferta do `modelo` que contam (substitui um mínimo de agregador ou de
    vendedor reprovado que não vale)."""
    melhor = None
    for r in (registros.values() if isinstance(registros, dict) else registros or []):
        if not isinstance(r, dict) or r.get("tipo") != "loja" or modelo_de(r) != modelo or bloqueado(r):
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
            "url": r.get("url"), "titulo": r.get("titulo"), "modelo": modelo}


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
            "minimo": None,       # 55C6K: {"preco", "loja", "quando", "url"}; a 65C6K em "minimo_65C6K" (chave_minimo)
            "saude": {},          # fonte -> {"falhas", "ultimo_ok", "ultimo_erro"}
            "ultimo_resumo": None,
            "criado_em": None,
            # 'loja|CÓDIGO' -> alertas de cupom enviados (chave, fonte, título, regra, especifico, quando)
            "cupons_alertados": {},
            # confiança nos vendedores (monitor/confianca.py): vereditos, catálogos lidos, reprovados automáticos e
            # avisos de suspeito já enviados (para não repetir a cada rodada)
            "confianca": {"vendedores": {}, "catalogos": {}, "reprovados_auto": {}, "fichas": {}, "avisos": {}},
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
        # modelos que este modo já registrou (oferta no state ou partida feita): um modelo novo tem a própria partida. A
        # 55C6K é monitorada desde o começo: todo state que existe já passou pela partida dela
        iniciados = self.dados.get("modelos_iniciados")
        self._modelos_conhecidos = {MODELO_PADRAO} | \
            {modelo_de(r) for r in self.dados["ofertas"].values() if isinstance(r, dict)} | \
            {m for m in (iniciados if isinstance(iniciados, list) else []) if m in MODELOS}
        self._historico_purgado = False
        self._purga_reprovados()

    def bootstrap_modelo(self, modelo: str) -> bool:
        """Primeira rodada deste modo com o `modelo` (a partida geral, ou a 65C6K entrando num state que já existia):
        registra ofertas e postagens sem alertar (senão as postagens antigas da 65" viram uma enxurrada de 📣) e manda
        a mensagem de início do modelo."""
        return self.bootstrap or modelo_de({"modelo": modelo}) not in self._modelos_conhecidos

    def marca_modelos_iniciados(self, modelos: set[str]) -> None:
        """Os modelos que tiveram oferta registrada nesta rodada deixam de estar na partida (vale na próxima rodada)."""
        atuais = self.dados.get("modelos_iniciados")
        atuais = [m for m in atuais if m in MODELOS] if isinstance(atuais, list) else []
        self.dados["modelos_iniciados"] = sorted(set(atuais) | {m for m in modelos if m in MODELOS})

    # ---- confiança: vendedor/anúncio reprovado some do estado, do mínimo e do histórico ----
    def reprovados_auto(self) -> list[dict]:
        """Reprovados automáticos deste modo (inclusive os da rodada) e do outro (state, só leitura)."""
        return reprovados_auto_do_estado(self)

    def _bloqueado(self, r: Any) -> bool:
        """Registro de oferta/mínimo/linha do histórico que não pode contar: vendedor ou anúncio reprovado (lista curada
        ou automático) ou oferta marcada suspeita na rodada em que apareceu."""
        return fora_de_preco(r) or bool(motivo_bloqueio(r, self.reprovados_auto()))

    def _purga_reprovados(self) -> None:
        """Feito por código ao carregar (os dois executores commitam docs/data; nada de editar à mão): tira do state os
        registros de vendedor/anúncio reprovado ou de anúncio que a rodada anterior julgou suspeito e refaz o 'minimo'
        quando ele veio de um reprovado. O histórico (CSV) perde só as linhas da lista curada, na próxima gravação
        (anexa_historico)."""
        regs = self.dados["ofertas"]
        auto = self.reprovados_auto()
        reprovados, suspeitos = [], []
        for k, r in regs.items():
            if not isinstance(r, dict):
                continue
            if veredito_de(r) == REPROVADO or motivo_bloqueio(r, auto):
                reprovados.append(k)
            elif fora_de_preco(r):
                suspeitos.append(k)
        for k in reprovados + suspeitos:
            del regs[k]
        if reprovados or suspeitos:
            # o log diz o que saiu de fato (revisão 3 de 26/09: o suspeito da rodada anterior aparecia como reprovado)
            partes = ([f"{len(reprovados)} de vendedor/anúncio reprovado"] if reprovados else []) + \
                ([f"{len(suspeitos)} de anúncio suspeito na rodada anterior"] if suspeitos else [])
            print(f"[confiança] state_{self.modo}: registro(s) removido(s): {' e '.join(partes)}")
        for modelo in MODELOS:
            chave = chave_minimo(modelo)
            m = self.dados.get(chave)
            if _preco_do_minimo(m) and self._bloqueado(m):
                diretas = self.lojas_diretas_conhecidas()
                novo = self._minimo_do_historico(diretas, modelo=modelo) or \
                    _minimo_dos_registros(regs, diretas, self._bloqueado, modelo)
                self.dados[chave] = novo
                print(f"[confiança] state_{self.modo}: mínimo da {modelo} de vendedor/anúncio reprovado "
                      f"({_preco_do_minimo(m)}) refeito: {_preco_do_minimo(novo)}")

    def _minimo_do_historico(self, diretas: set[str], bloqueado: Callable[[Any], bool] | None = None,
                             modelo: str = MODELO_PADRAO) -> dict | None:
        """O menor preço do `modelo` no histórico deste modo que conta (sem reprovado e sem agregador de loja com fonte
        direta), com o horário da linha. None sem histórico legível. `bloqueado`: o que não conta (padrão:
        _bloqueado). Linha antiga (sem a coluna 'modelo') é da 55C6K."""
        bloqueado = bloqueado or self._bloqueado
        try:
            with self.arq_hist.open(encoding="utf-8", newline="") as f:
                linhas = list(csv.DictReader(f))
        except (OSError, csv.Error):
            return None
        melhor: tuple[float, dict] | None = None
        for r in linhas:
            if r.get("tipo") != "loja" or modelo_de(r) != modelo:
                continue
            if e_agregador(r) and loja_canonica(r.get("loja") or "") in diretas:
                continue
            precos = []
            for c in ("preco", "preco_pix"):
                try:
                    v = float(r.get(c) or 0)
                except ValueError:
                    v = 0.0
                if v > 0:
                    precos.append(v)
            if not precos or (melhor is not None and min(precos) >= melhor[0]) or bloqueado(r):
                continue
            melhor = (min(precos), r)
        if melhor is None:
            return None
        p, r = melhor
        return {"preco": p, "loja": r.get("loja"), "quando": r.get("quando") or "", "url": r.get("url"),
                "titulo": r.get("titulo"), "vendedor": r.get("vendedor") or None, "modelo": modelo}

    def _purga_historico(self) -> int:
        """Tira do CSV deste modo as linhas de vendedor/anúncio da lista CURADA de reprovados (uma vez por execução, só
        se houver). As outras linhas ficam byte a byte como estão.

        O reprovado automático não apaga linha nenhuma (revisão 3 de 26/09): é heurística e pode ser falso positivo.
        As linhas dele ficam fora do mínimo (_bloqueado) e do painel (latest.confianca.reprovados) e voltam a valer
        quando o vendedor é posto em confiáveis (restaura_minimo_de_liberados)."""
        if self._historico_purgado or not self.arq_hist.exists():
            return 0
        self._historico_purgado = True
        from .confianca import listas

        lojas = set(listas()["reprovados"])
        try:
            with self.arq_hist.open(encoding="utf-8", newline="") as f:  # sem traduzir \r\n: o resto fica igual
                texto = f.read()
        except OSError:
            return 0
        linhas = texto.splitlines(keepends=True)
        if len(linhas) < 2:
            return 0
        cab = next(csv.reader([linhas[0]]))
        manter, tirou = [linhas[0]], 0
        for ln in linhas[1:]:
            try:
                row = next(csv.reader([ln]))
            except (csv.Error, StopIteration):
                row = []
            if _linha_csv_valida(cab, row):
                r = dict(zip(cab, row))
                if r.get("tipo") == "loja" and loja_canonica(r.get("loja") or "") in lojas \
                        and motivo_bloqueio(r, ()):
                    tirou += 1
                    continue
            manter.append(ln)
        if tirou:
            tmp = self.arq_hist.with_suffix(".csv.tmp")
            with tmp.open("w", encoding="utf-8", newline="") as f:
                f.write("".join(manter))
            os.replace(tmp, self.arq_hist)
            print(f"[confiança] historico_{self.modo}.csv: {tirou} linha(s) de vendedor/anúncio reprovado removida(s)")
        return tirou

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
        return s | {loja_canonica(r.get("loja") or "") for r in regs if _e_direta(r) and not self._bloqueado(r)}

    def ofertas_diretas_de_outros_modos(self) -> list[dict]:
        """Ofertas de fonte direta, ativas e com preço, na última rodada do outro modo (latest_<outro>.json; sem ele,
        os registros ativos do state_<outro>.json). Cada uma leva '_modo' e '_visto' (quando o outro modo a viu)."""
        out: list[dict] = []
        for m in self._outros_modos():
            lt = self._arquivo_do_modo(f"latest_{m}.json")
            if lt and isinstance(lt.get("ofertas_loja"), list):
                for o in lt["ofertas_loja"]:
                    if _e_direta(o) and o.get("ativo", True) and _preco_do_minimo({"preco": o.get("melhor_preco")}) \
                            and not self._bloqueado(o):
                        out.append({**o, "_modo": m, "_visto": lt.get("atualizado") or ""})
                continue
            st = (self._arquivo_do_modo(f"state_{m}.json") or {}).get("ofertas")
            for r in (st.values() if isinstance(st, dict) else []):
                if _e_direta(r) and r.get("ativo") and _preco_do_minimo({"preco": r.get("ultimo_preco")}) \
                        and not self._bloqueado(r):
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

    # ---- mínimo histórico (só lojas confiáveis), por modelo ----
    def minimo(self, modelo: str = MODELO_PADRAO) -> dict | None:
        return self.dados.get(chave_minimo(modelo))

    def _minimo_do_modo(self, modo: str, diretas: set[str], modelo: str = MODELO_PADRAO) -> dict | None:
        """Mínimo do `modelo` gravado pelo outro modo (só leitura). Arquivo ausente ou quebrado -> None. Mínimo que veio
        de agregador de loja com fonte direta não vale: fica o menor dos registros que contam (como o painel)."""
        chave = chave_minimo(modelo)
        for nome in (f"state_{modo}.json", f"latest_{modo}.json"):
            d = self._arquivo_do_modo(nome)
            m = d.get(chave) if d else None
            if not _preco_do_minimo(m):
                continue
            if _minimo_conta(m, diretas, self._bloqueado):
                return m
            if nome.startswith("state_"):
                return _minimo_dos_registros(d.get("ofertas"), diretas, self._bloqueado, modelo)
        return None

    def _minimo_proprio(self, diretas: set[str], modelo: str = MODELO_PADRAO) -> dict | None:
        m = self.dados.get(chave_minimo(modelo))
        if not _preco_do_minimo(m):
            return None
        return m if _minimo_conta(m, diretas, self._bloqueado) else \
            _minimo_dos_registros(self.dados["ofertas"], diretas, self._bloqueado, modelo)

    def minimo_geral(self, diretas: set[str] | None = None, modelo: str = MODELO_PADRAO) -> dict | None:
        """Menor preço já visto do `modelo` considerando os dois modos (cloud e pc), como o painel mostra. `diretas`:
        ver lojas_diretas_conhecidas (None: calcula sem as ofertas da rodada)."""
        if diretas is None:
            diretas = self.lojas_diretas_conhecidas()
        candidatos = [self._minimo_proprio(diretas, modelo)] + \
            [self._minimo_do_modo(m, diretas, modelo) for m in self._outros_modos()]
        validos = [m for m in candidatos if _preco_do_minimo(m)]
        return min(validos, key=_preco_do_minimo) if validos else None

    def atualiza_minimo(self, o: Oferta, diretas: set[str] | None = None) -> bool:
        """`diretas`: lojas com fonte direta conhecidas (lojas_diretas_conhecidas). Ver conta_como_preco. O mínimo é o
        do modelo da oferta."""
        if fora_de_preco(o):
            if identidade_em_duvida(o):
                self._tira_do_minimo(o, diretas)
            return False
        p = o.melhor_preco
        if not p or not conta_como_preco(o, diretas):
            return False
        modelo = modelo_de(o)
        chave = chave_minimo(modelo)
        m = self.dados.get(chave)
        if diretas is not None and _preco_do_minimo(m) and not _minimo_conta(m, diretas, self._bloqueado):
            # mínimo gravado de agregador de loja que tem fonte direta (preço parado no Zoom): não vale
            m = self.dados[chave] = _minimo_dos_registros(self.dados["ofertas"], diretas, self._bloqueado, modelo)
        if m is None or p < float(m["preco"]):
            # vendedor e chave vão junto: se ele for reprovado depois, o mínimo sai (Estado._purga_reprovados)
            self.dados[chave] = {"preco": p, "loja": o.loja, "quando": agora_iso(), "url": o.url, "titulo": o.titulo,
                                 "vendedor": o.vendedor, "vendedor_id": o.extra.get("vendedor_id"),
                                 "chave": o.chave, "modelo": modelo}
            return m is not None  # na primeira vez não é "novo mínimo", é o primeiro
        return False

    def _tira_do_minimo(self, o: Oferta, diretas: set[str] | None) -> None:
        """A oferta que é o 'minimo' do modelo dela ficou suspeita nesta rodada por sinal de identidade (o anúncio passou
        a ter a homologação de outro produto, a loja não vende TV...): o mínimo é refeito sem ela, pelo histórico e pelos
        registros (revisão de 26/09: o expurgo ao carregar só tira mínimo de reprovado, e suspeito não é reprovado).
        Suspeita só pelo preço de agora não apaga o preço que o anúncio mostrou quando passou nas checagens."""
        modelo = modelo_de(o)
        chave = chave_minimo(modelo)
        m = self.dados.get(chave)
        if not _preco_do_minimo(m) or not isinstance(m, dict):
            return
        ident = _identidade_de_oferta(o)
        if m.get("chave") != o.chave and (ident is None or
                                          _identidade_de_oferta({"modelo": modelo, **m, "tipo": "loja"}) != ident):
            return

        def fora(r: Any) -> bool:
            return self._bloqueado(r) or (isinstance(r, dict) and r.get("chave") == o.chave) \
                or (ident is not None and _identidade_de_oferta(r) == ident)

        if diretas is None:
            diretas = self.lojas_diretas_conhecidas()
        novo = self._minimo_do_historico(diretas, fora, modelo) or \
            _minimo_dos_registros(self.dados["ofertas"], diretas, fora, modelo)
        self.dados[chave] = novo
        print(f"[confiança] state_{self.modo}: mínimo da {modelo} de oferta que ficou suspeita ({_preco_do_minimo(m)}) "
              f"refeito: {_preco_do_minimo(novo)}")

    def restaura_minimo_de_liberados(self, liberados: list[dict]) -> None:
        """Reprovado automático cujo vendedor foi posto em confiáveis (confianca.avaliar): as linhas dele no histórico,
        que o expurgo não apaga, voltam a contar. Se a mais barata delas é menor que o mínimo gravado do modelo (que foi
        refeito sem ele), ela volta a ser o mínimo. Só as linhas desse vendedor: o resto do mínimo não muda."""
        if not liberados:
            return

        def fora(r: Any) -> bool:
            return self._bloqueado(r) or not any(e_do_reprovado_auto(e, r) for e in liberados)

        diretas = self.lojas_diretas_conhecidas()
        for modelo in MODELOS:
            chave = chave_minimo(modelo)
            m = self._minimo_do_historico(diretas, fora, modelo)
            atual = _preco_do_minimo(self.dados.get(chave))
            if m and (atual is None or m["preco"] < atual):
                self.dados[chave] = m
                print(f"[confiança] state_{self.modo}: vendedor liberado pela lista de confiáveis; mínimo da {modelo} "
                      f"volta a {m['preco']} ({m.get('vendedor') or m.get('loja')}, {m.get('quando')})")

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

    def _cabecalho_com_modelo(self) -> None:
        """CSV gravado antes de 26/09 (sem a coluna 'modelo'): o cabeçalho ganha a coluna no fim, por código, e as linhas
        antigas ficam byte a byte como estão (quem lê trata a coluna que falta como 55C6K)."""
        try:
            with self.arq_hist.open(encoding="utf-8", newline="") as f:
                texto = f.read()
        except OSError:
            return
        fim = texto.find("\n")
        primeira = texto if fim < 0 else texto[:fim + 1]
        corpo = "" if fim < 0 else texto[fim + 1:]
        quebra = "\r\n" if primeira.endswith("\r\n") else "\n" if primeira.endswith("\n") else ""
        try:
            cab = next(csv.reader([primeira]))
        except (csv.Error, StopIteration):
            return
        if not cab or "modelo" in cab:
            return
        tmp = self.arq_hist.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            f.write(primeira[:len(primeira) - len(quebra)] + ",modelo" + (quebra or "\r\n") + corpo)
        os.replace(tmp, self.arq_hist)
        print(f"[estado] historico_{self.modo}.csv: coluna 'modelo' acrescentada ao cabeçalho (linhas antigas = "
              f"{MODELO_PADRAO})")

    def anexa_historico(self, ofertas: list[Oferta]) -> None:
        self._purga_historico()
        linhas = [o for o in ofertas if o.ativo and o.melhor_preco and not self._bloqueado(o)]
        novo = not self.arq_hist.exists()
        if linhas and not novo:
            self._cabecalho_com_modelo()
        with self.arq_hist.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_HISTORICO)
            if novo:
                w.writeheader()
            # esgotada, descartada pelo sanear ou suspeita ficam de fora: o preço não é da TV e distorce o gráfico
            for o in linhas:
                w.writerow({
                    "quando": agora_iso(), "fonte": o.fonte, "tipo": o.tipo, "loja": o.loja,
                    "vendedor": o.vendedor or "", "titulo": o.titulo[:160], "preco": o.preco or "",
                    "preco_pix": o.preco_pix or "", "parcelado": o.parcelado or "", "cupom": o.cupom or "",
                    "url": o.url, "modelo": modelo_de(o),
                })

    def escreve_latest(self, ofertas: list[Oferta], cupons: list[Cupom]) -> None:
        lojas = [o.to_dict() for o in ofertas if o.tipo == "loja"]
        lojas.sort(key=lambda d: (d["melhor_preco"] is None, d["melhor_preco"] or 0))
        # posts: os desta execução + os recentes já conhecidos (as duas TVs dividem a lista)
        posts_conhecidos = [r for r in self.dados["ofertas"].values() if r.get("tipo") == "post"]
        posts_conhecidos.sort(key=lambda r: r.get("publicado") or r.get("primeira_vez") or "", reverse=True)
        cupons_ativos = [c.to_dict() for c in cupons]
        posts_conhecidos = [r for r in posts_conhecidos if not self._bloqueado(r)]
        latest = {
            "modo": self.modo,
            "atualizado": agora_iso(),
            # alvo_pix/alvo_parcelado/minimo: os da 55C6K (nomes de sempre); os de cada modelo em alvos/minimo_<modelo>
            "alvo_pix": config.ALVO_PIX,
            "alvo_parcelado": config.ALVO_PARCELADO,
            "alvos": config.alvos(),
            **{chave_minimo(m): self.dados.get(chave_minimo(m)) for m in MODELOS},
            "ofertas_loja": lojas,
            "posts": posts_conhecidos[:80],
            "cupons": cupons_ativos,
            "saude": self.dados["saude"],
            # o painel esconde linhas antigas (latest/histórico) de vendedor/anúncio reprovado com esta lista
            "confianca": {"reprovados": reprovados_para_painel(self.reprovados_auto())},
        }
        self.arq_latest.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
