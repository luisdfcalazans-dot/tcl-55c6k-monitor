"""Estado persistente (JSON), histórico (CSV) e arquivo do painel (latest JSON).

Cada modo (cloud / pc) tem os seus próprios arquivos para que os dois executores
não briguem no git: docs/data/state_<modo>.json, historico_<modo>.csv, latest_<modo>.json.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from . import config
from .models import Cupom, Oferta
from .util import agora_iso

CAMPOS_HISTORICO = [
    "quando", "fonte", "tipo", "loja", "vendedor", "titulo", "preco", "preco_pix", "parcelado", "cupom", "url",
]


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
        }
        if self.arq_estado.exists():
            try:
                self.dados.update(json.loads(self.arq_estado.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
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
        reg["ultimo_preco"] = o.melhor_preco
        mp = reg.get("menor_preco")
        if o.melhor_preco and (mp is None or o.melhor_preco < mp):
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

    def registra_cupom(self, c: Cupom) -> None:
        reg = self.dados["cupons"].get(c.chave) or {"primeira_vez": agora_iso()}
        reg.update(c.to_dict())
        reg["ultima_vez"] = agora_iso()
        self.dados["cupons"][c.chave] = reg

    # ---- mínimo histórico (só lojas confiáveis) ----
    def minimo(self) -> dict | None:
        return self.dados.get("minimo")

    def atualiza_minimo(self, o: Oferta) -> bool:
        p = o.melhor_preco
        if not p or o.tipo != "loja":
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
