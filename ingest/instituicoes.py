"""Resolução de nomes de instituição para entidades canónicas.

Carrega reference/instituicoes.yaml e oferece a resolução usada por todo o
pipeline. Também valida o crosswalk: sem estas verificações, um nome novo na
fonte desapareceria silenciosamente das fichas, e uma chave a mais faria dois
nomes da mesma entidade somar-se no mesmo mês.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

from common import DIR_REFERENCIA, normalizar_agressivo

FICHEIRO = DIR_REFERENCIA / "instituicoes.yaml"


@dataclass
class Instituicao:
    id: str
    nome: str
    nome_curto: str
    regiao: str
    distrito: str
    tipo: str
    chaves: list[str]
    # Coordenadas curadas à mão. As da fonte não servem: coloca o Centro
    # Hospitalar Universitário do Algarve na Baixa de Lisboa, e dezenas de
    # instituições partilham o mesmo ponto genérico.
    geo: dict | None = None
    sucessao: list[dict] = field(default_factory=list)
    nota: str | None = None

    @property
    def data_descontinuidade(self) -> str | None:
        """Data a partir da qual o perímetro da entidade mudou, se aplicável."""
        if not self.sucessao:
            return None
        return max(str(s["data"]) for s in self.sucessao)

    @property
    def e_fusao(self) -> bool:
        """True se alguma sucessão juntou mais do que uma entidade numa só."""
        return any(len(s.get("de", [])) > 1 for s in self.sucessao)

    @property
    def data_ultima_fusao(self) -> str | None:
        """Data da última fusão de várias entidades numa só.

        Antes desta data, a entidade existia repartida por vários nomes na
        fonte e é correto somá-los — é assim que se reconstrói o perímetro
        atual para trás no tempo. A partir dela, dois nomes no mesmo mês
        significam grafias duplicadas, ou seja, dupla contagem.
        """
        datas = [str(s["data"]) for s in self.sucessao if len(s.get("de", [])) > 1]
        return max(datas) if datas else None


class Crosswalk:
    def __init__(self, caminho: pathlib.Path | None = None):
        dados = yaml.safe_load((caminho or FICHEIRO).read_text(encoding="utf-8"))
        self.instituicoes: list[Instituicao] = []
        self._por_chave: dict[str, Instituicao] = {}

        for d in dados:
            inst = Instituicao(
                id=d["id"],
                nome=d["nome"],
                nome_curto=d["nome_curto"],
                regiao=d["regiao"],
                distrito=d["distrito"],
                tipo=d["tipo"],
                chaves=d["chaves"],
                geo=d.get("geo"),
                sucessao=d.get("sucessao", []),
                nota=d.get("nota"),
            )
            self.instituicoes.append(inst)
            for chave in inst.chaves:
                if chave in self._por_chave:
                    raise ValueError(
                        f"chave '{chave}' declarada em {self._por_chave[chave].id} "
                        f"e em {inst.id}"
                    )
                self._por_chave[chave] = inst

    def __len__(self) -> int:
        return len(self.instituicoes)

    def resolver(self, nome: str) -> Instituicao | None:
        """Devolve a entidade canónica de um nome tal como a fonte o escreve."""
        if not nome:
            return None
        return self._por_chave.get(normalizar_agressivo(nome.strip()))

    def por_id(self, id_: str) -> Instituicao | None:
        return next((i for i in self.instituicoes if i.id == id_), None)


def carregar() -> Crosswalk:
    return Crosswalk()
