"""Espelha o catálogo de datasets do portal Transparência SNS.

Guarda metadados e esquema de campos de todos os datasets, para que o resto do
pipeline nunca dependa de chamadas de rede ad-hoc e para que uma alteração na
fonte (campo renomeado, dataset removido) fique visível no diff do repositório.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from common import API, DIR_BRUTO, TEMPO_LIMITE, TENTATIVAS, garantir_dirs

FICHEIRO_CATALOGO = DIR_BRUTO / "_catalogo.json"


def _obter(url: str, params: dict | None = None) -> dict:
    ultimo = None
    for tentativa in range(TENTATIVAS):
        try:
            r = requests.get(url, params=params, timeout=TEMPO_LIMITE)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - queremos repetir em qualquer falha de rede
            ultimo = e
            time.sleep(2**tentativa)
    raise RuntimeError(f"falhou {url}: {ultimo}")


def listar_datasets() -> list[dict]:
    """Pagina o catálogo completo (100 de cada vez)."""
    resultados: list[dict] = []
    offset = 0
    while True:
        pagina = _obter(
            f"{API}/catalog/datasets", {"limit": 100, "offset": offset}
        )
        lote = pagina.get("results", [])
        resultados.extend(lote)
        total = pagina.get("total_count", 0)
        offset += 100
        if offset >= total or not lote:
            break
    return resultados


def obter_esquema(dataset_id: str) -> dict:
    d = _obter(f"{API}/catalog/datasets/{dataset_id}")
    meta = d.get("metas", {}).get("default", {})

    # O `records_count` do catálogo está desatualizado em alguns datasets: anuncia
    # 339 300 contratos no portal-base quando o dataset tem 44 015, e 6 403 em
    # inscritos-lic-dentro-tmrg quando tem 1 890. O `total_count` de /records
    # concorda com ambos os /exports, pelo que é esse o número autoritativo.
    # Guardamos os dois para que a divergência fique registada, não escondida.
    contagem_real = _obter(
        f"{API}/catalog/datasets/{dataset_id}/records", {"limit": 1}
    ).get("total_count")

    return {
        "dataset_id": dataset_id,
        "titulo": meta.get("title"),
        "descricao": meta.get("description"),
        "publisher": meta.get("publisher"),
        "tema": meta.get("theme"),
        "palavras_chave": meta.get("keyword"),
        "licenca": meta.get("license"),
        "n_registos": contagem_real,
        "n_registos_anunciado": meta.get("records_count"),
        "modificado": meta.get("modified"),
        "campos": [
            {"nome": f["name"], "tipo": f["type"], "rotulo": f.get("label")}
            for f in d.get("fields", [])
        ],
    }


def main() -> int:
    garantir_dirs()
    datasets = listar_datasets()
    print(f"catálogo: {len(datasets)} datasets")

    ids = [d["dataset_id"] for d in datasets]
    esquemas: dict[str, dict] = {}
    with ThreadPoolExecutor(8) as ex:
        for esquema in ex.map(obter_esquema, ids):
            esquemas[esquema["dataset_id"]] = esquema

    FICHEIRO_CATALOGO.write_text(
        json.dumps(esquemas, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    sem_licenca = sum(1 for e in esquemas.values() if not e["licenca"])
    total_registos = sum(e["n_registos"] or 0 for e in esquemas.values())
    discrepantes = [
        e["dataset_id"]
        for e in esquemas.values()
        if e["n_registos_anunciado"] is not None
        and e["n_registos"] is not None
        and e["n_registos_anunciado"] != e["n_registos"]
    ]
    print(f"escrito {FICHEIRO_CATALOGO.relative_to(FICHEIRO_CATALOGO.parents[2])}")
    print(f"  {total_registos:,} registos | {sem_licenca} datasets sem licença declarada")
    print(f"  {len(discrepantes)} datasets com contagem anunciada errada no catálogo:")
    for d in sorted(discrepantes):
        e = esquemas[d]
        print(f"    {d}: anuncia {e['n_registos_anunciado']:,}, tem {e['n_registos']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
