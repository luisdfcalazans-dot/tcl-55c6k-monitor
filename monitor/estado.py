"""Estado persistente (JSON), histórico (CSV) e arquivo do painel (latest JSON).

Cada modo (cloud / pc) tem os seus próprios arquivos para que os dois executores
não briguem no git: docs/data/state_<modo>.json, historico_<modo>.csv, latest_<modo>.json.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from . import config
from .models import Cupom, Oferta
from .util import agora_iso, dias_desde, loja_canonica

CAMPOS_HISTORICO = [
    "quando", "fonte", "tipo", "loja", "vendedor", "titulo", "preco", "preco_pix", "parcelado", "cupom", "url",
]
MODOS = ("cloud", "pc")
# um cupom já alertado só volta a ser alerta depois deste prazo sem aparecer (ou se o desconto mudar)
JANELA_CUPOM_DIAS = 30


def marca_cupom(loja: str, codigo: str) -> str:
    """Identidade do cupom entre fontes e ids: 'Loja canônica|CÓDIGO'."""
    return f"{loja_canonica(loja or '')}|{str(codigo or '').upper()}"


def e_agregador(o: Oferta) -> bool:
    """Zoom/Buscapé é agregador de preços, não loja: o preço que ele mostra pode estar atrasado."""
    return bool((o.extra or {}).get("agregador"))


def lojas_diretas(ofertas: list[Oferta]) -> set[str]:
    """Lojas que têm oferta de fonte direta (não agregador) nesta rodada, ativa ou não."""
    return {loja_canonica(o.loja) for o in ofertas if o.tipo == "loja" and not e_agregador(o)}


def conta_como_preco(o: Oferta, diretas: set[str] | None = None) -> bool:
    """Se a oferta pode virar "menor já visto" e alerta de preço de loja.

    Nunca: oferta inativa (esgotada ou descartada pelo sanear) ou sem preço.
    Agregador: só quando a loja não tem fonte direta nesta rodada (diretas=None = não sabemos -> não conta).
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
        self.bootstrap = not self.dados["ofertas"] and self.dados.get("criado_em") is None
        if self.dados.get("criado_em") is None:
            self.dados["criado_em"] = agora_iso()

    # ---- ofertas ----
    def oferta_anterior(self, chave: str) -> dict | None:
        return self.dados["ofertas"].get(chave)

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

    def _minimo_do_modo(self, modo: str) -> dict | None:
        """Mínimo gravado pelo outro modo (só leitura). Arquivo ausente ou quebrado -> None."""
        for nome in (f"state_{modo}.json", f"latest_{modo}.json"):
            try:
                m = json.loads((self.arq_estado.parent / nome).read_text(encoding="utf-8")).get("minimo")
            except (OSError, ValueError, AttributeError):
                continue
            if _preco_do_minimo(m):
                return m
        return None

    def minimo_geral(self) -> dict | None:
        """Menor preço já visto considerando os dois modos (cloud e pc), como o painel mostra."""
        candidatos = [self.dados.get("minimo")] + [self._minimo_do_modo(m) for m in MODOS if m != self.modo]
        validos = [m for m in candidatos if _preco_do_minimo(m)]
        return min(validos, key=_preco_do_minimo) if validos else None

    def atualiza_minimo(self, o: Oferta, diretas: set[str] | None = None) -> bool:
        """`diretas`: lojas com fonte direta nesta rodada (lojas_diretas). Ver conta_como_preco."""
        p = o.melhor_preco
        if not p or not conta_como_preco(o, diretas):
            return False
        m = self.dados.get("minimo")
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
