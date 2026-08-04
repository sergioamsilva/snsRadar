"""Regista o estado de cada ingestão, para que os números citados hoje
continuem verificáveis amanhã.

A fonte revê dados em silêncio: um valor publicado em julho pode mudar em
agosto sem qualquer aviso. Guardar o SHA-256 de cada ficheiro bruto permite
detetar essas revisões e provar o que a fonte dizia numa data concreta.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone

import duckdb

from common import DIR_BRUTO, DIR_SNAPSHOTS, garantir_dirs
from catalog import FICHEIRO_CATALOGO

MANIFESTO_ATUAL = DIR_SNAPSHOTS / "manifesto-atual.json"


def _hash_conteudo(caminho) -> str:
    """Hash do conteúdo *descomprimido*.

    O gzip embebe timestamps, pelo que o hash do ficheiro .gz mudaria a cada
    execução mesmo com dados idênticos. Só o conteúdo interessa.
    """
    h = hashlib.sha256()
    with gzip.open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _contar_registos(con, caminho) -> int:
    """Conta registos com um parser de CSV a sério.

    Contar `\\n` daria valores errados: campos de texto livre como
    `objeto_do_contrato` no portal-base contêm quebras de linha dentro de aspas.
    """
    return con.execute(
        "select count(*) from read_csv(?, delim=';', header=true, "
        "quote='\"', escape='\"', sample_size=-1)",
        [str(caminho)],
    ).fetchone()[0]


def construir_manifesto() -> dict:
    con = duckdb.connect()
    entradas = {}
    for caminho in sorted(DIR_BRUTO.glob("*.csv.gz")):
        dataset_id = caminho.name[: -len(".csv.gz")]
        entradas[dataset_id] = {
            "sha256": _hash_conteudo(caminho),
            "bytes_comprimidos": caminho.stat().st_size,
            "registos": _contar_registos(con, caminho),
        }
    return {
        "capturado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "datasets": entradas,
    }


def validar_contra_catalogo(atual: dict) -> list[str]:
    """Confirma que descarregámos tudo o que a fonte diz ter.

    Compara com o `total_count` de /records, que é o número autoritativo — o
    `records_count` do catálogo está errado em 7 datasets (ver catalog.py).
    """
    if not FICHEIRO_CATALOGO.exists():
        return []
    catalogo = json.loads(FICHEIRO_CATALOGO.read_text(encoding="utf-8"))
    problemas = []
    for dataset_id, v in sorted(atual["datasets"].items()):
        esperado = catalogo.get(dataset_id, {}).get("n_registos")
        if esperado is not None and v["registos"] != esperado:
            problemas.append(
                f"{dataset_id}: fonte tem {esperado:,}, temos {v['registos']:,} "
                f"({v['registos'] - esperado:+,})"
            )
    return problemas


def comparar(anterior: dict, atual: dict) -> dict:
    a, b = anterior.get("datasets", {}), atual.get("datasets", {})
    alterados = [k for k in a.keys() & b.keys() if a[k]["sha256"] != b[k]["sha256"]]
    return {
        "novos": sorted(b.keys() - a.keys()),
        "removidos": sorted(a.keys() - b.keys()),
        "alterados": sorted(alterados),
        "inalterados": sorted(k for k in a.keys() & b.keys() if a[k]["sha256"] == b[k]["sha256"]),
    }


def main() -> int:
    garantir_dirs()
    atual = construir_manifesto()
    if not atual["datasets"]:
        print("nada em data/raw — corra primeiro: python ingest/fetch.py")
        return 1

    anterior = (
        json.loads(MANIFESTO_ATUAL.read_text(encoding="utf-8"))
        if MANIFESTO_ATUAL.exists()
        else {"datasets": {}}
    )
    d = comparar(anterior, atual)

    carimbo = atual["capturado_em"].replace(":", "").replace("-", "")[:15]
    arquivo = DIR_SNAPSHOTS / f"manifesto-{carimbo}.json"
    texto = json.dumps(atual, ensure_ascii=False, indent=2, sort_keys=True)
    arquivo.write_text(texto, encoding="utf-8")
    MANIFESTO_ATUAL.write_text(texto, encoding="utf-8")

    n = len(atual["datasets"])
    registos = sum(v["registos"] for v in atual["datasets"].values())
    print(f"snapshot {atual['capturado_em']} — {n} datasets, {registos:,} registos")
    print(
        f"  novos={len(d['novos'])} alterados={len(d['alterados'])} "
        f"removidos={len(d['removidos'])} inalterados={len(d['inalterados'])}"
    )
    for k in d["alterados"]:
        print(f"  ~ {k}: a fonte reviu este dataset")
    for k in d["removidos"]:
        print(f"  - {k}: DESAPARECEU da fonte")
    print(f"  arquivado em {arquivo.name}")

    problemas = validar_contra_catalogo(atual)
    if problemas:
        print(f"\n  {len(problemas)} datasets incompletos face à fonte:")
        for p in problemas:
            print(f"    ! {p}")
        return 1
    print("  todos os datasets completos face à fonte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
