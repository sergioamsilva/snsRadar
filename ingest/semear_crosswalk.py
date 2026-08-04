"""Semeia o crosswalk de instituições a partir dos dados descarregados.

Este script NÃO produz o crosswalk final. Produz um rascunho para revisão
humana. A reforma das Unidades Locais de Saúde (Decreto-Lei n.º 102/2023)
fundiu centros hospitalares e ACES em ULS, e muitas dessas fusões são de
vários-para-um: nenhuma correspondência automática as acerta. O ficheiro
final, reference/instituicoes.yaml, é curado à mão.

Saída: reference/_semente-instituicoes.yaml (rascunho, não usar em produção)
"""

from __future__ import annotations

import sys
from collections import defaultdict

import duckdb
import yaml

from common import DIR_BRUTO, DIR_REFERENCIA, garantir_dirs, normalizar

SEMENTE = DIR_REFERENCIA / "_semente-instituicoes.yaml"

# Coluna que identifica a entidade em cada dataset. `regiao` acompanha quase
# sempre e serve para desambiguar homónimos.
COLUNAS_ENTIDADE = {
    "entidade": "divida-total-vencida-e-pagamentos",
}


def _ler(con, dataset_id: str):
    caminho = DIR_BRUTO / f"{dataset_id}.csv.gz"
    return (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1, all_varchar=true)"
    )


def recolher(con) -> dict[str, dict]:
    """Recolhe (nome, região, datasets onde ocorre, primeira e última data)."""
    ocorrencias: dict[str, dict] = defaultdict(
        lambda: {"datasets": set(), "regioes": set(), "min": None, "max": None}
    )

    for caminho in sorted(DIR_BRUTO.glob("*.csv.gz")):
        dataset_id = caminho.name[: -len(".csv.gz")]
        cols = [
            r[0]
            for r in con.execute(f"describe select * from {_ler(con, dataset_id)}").fetchall()
        ]
        coluna = "instituicao" if "instituicao" in cols else COLUNAS_ENTIDADE.get("entidade")
        if "instituicao" not in cols and "entidade" not in cols:
            continue
        coluna = "instituicao" if "instituicao" in cols else "entidade"

        tempo = next(
            (c for c in ("tempo", "periodo", "data", "ano") if c in cols), None
        )
        regiao = "regiao" if "regiao" in cols else "NULL"
        sel_tempo = f"min({tempo}), max({tempo})" if tempo else "NULL, NULL"

        linhas = con.execute(
            f"select {coluna}, {regiao}, {sel_tempo} from {_ler(con, dataset_id)} "
            f"where {coluna} is not null group by 1, 2"
        ).fetchall()

        for nome, reg, mn, mx in linhas:
            e = ocorrencias[nome.strip()]
            e["datasets"].add(dataset_id)
            if reg:
                e["regioes"].add(reg.strip())
            for valor, chave, agg in ((mn, "min", min), (mx, "max", max)):
                if valor:
                    e[chave] = valor if e[chave] is None else agg(e[chave], valor)

    return ocorrencias


def agrupar(ocorrencias: dict) -> list[dict]:
    """Agrupa nomes pela sua forma normalizada.

    Só apanha variantes de grafia (espaçamento, acentos, sufixo EPE). NÃO liga
    um centro hospitalar à ULS que o substituiu — isso é decisão humana.
    """
    grupos: dict[str, list[str]] = defaultdict(list)
    for nome in ocorrencias:
        grupos[normalizar(nome)].append(nome)

    saida = []
    for chave, nomes in sorted(grupos.items()):
        datasets: set[str] = set()
        regioes: set[str] = set()
        mn = mx = None
        for n in nomes:
            e = ocorrencias[n]
            datasets |= e["datasets"]
            regioes |= e["regioes"]
            if e["min"]:
                mn = e["min"] if mn is None else min(mn, e["min"])
            if e["max"]:
                mx = e["max"] if mx is None else max(mx, e["max"])
        principal = max(nomes, key=len)
        saida.append(
            {
                "chave_normalizada": chave,
                "nome_provavel": principal,
                "aliases": sorted(nomes),
                "regioes": sorted(regioes),
                "n_datasets": len(datasets),
                "primeiro_periodo": str(mn)[:10] if mn else None,
                "ultimo_periodo": str(mx)[:10] if mx else None,
                "e_uls": "unidade local de saude" in chave,
            }
        )
    return saida


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    ocorrencias = recolher(con)
    grupos = agrupar(ocorrencias)

    # Uma entidade que deixou de aparecer antes de 2024 é candidata a ter sido
    # absorvida por uma ULS; uma que só aparece a partir de 2024 é candidata a
    # ser a sucessora. Sinalizar ambas orienta a revisão manual.
    extintas = [g for g in grupos if g["ultimo_periodo"] and g["ultimo_periodo"] < "2024-06-01"]
    novas = [g for g in grupos if g["primeiro_periodo"] and g["primeiro_periodo"] >= "2023-06-01"]

    SEMENTE.write_text(
        "# RASCUNHO gerado por ingest/semear_crosswalk.py — não usar em produção.\n"
        "# O crosswalk de produção é reference/instituicoes.yaml, curado à mão\n"
        "# contra o Decreto-Lei n.º 102/2023.\n"
        + yaml.safe_dump(grupos, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )

    print(f"{len(ocorrencias):,} nomes distintos -> {len(grupos):,} grupos por grafia")
    print(f"  presentes em >=10 datasets: {sum(1 for g in grupos if g['n_datasets'] >= 10)}")
    print(f"  ULS: {sum(1 for g in grupos if g['e_uls'])}")
    print(f"  extintas antes de 2024-06 (candidatas a absorvidas): {len(extintas)}")
    print(f"  surgidas a partir de 2023-06 (candidatas a sucessoras): {len(novas)}")
    print(f"escrito {SEMENTE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
