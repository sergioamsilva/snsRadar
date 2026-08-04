"""Descarrega datasets completos do portal Transparência SNS.

Usa o endpoint /exports/csv e não /records: este último recusa
`offset + limit > 10000`, o que truncaria silenciosamente 20 dos datasets que
nos interessam (o maior tem 420 372 registos).

Uso:
    python ingest/fetch.py                # datasets necessários à v1
    python ingest/fetch.py --todos        # os 144
    python ingest/fetch.py dataset-a ...  # datasets específicos
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from common import API, DIR_BRUTO, TEMPO_LIMITE, TENTATIVAS, garantir_dirs
from catalog import FICHEIRO_CATALOGO

# Datasets ao nível da instituição que alimentam a ficha (ver reference/indicadores.yaml)
# e que definem o universo de nomes usado para construir o crosswalk.
NUCLEO = [
    # Acesso
    "inscritos-em-lic-dentro-do-tmrg-180-dias",
    "inscritos-lic-dentro-tmrg",
    "consultas-em-tempo-real",
    "demora-media-antes-da-cirurgia",
    "atendimentos-em-urgencia-triagem-manchester",
    "atendimentos-por-tipo-de-urgencia-hospitalar-link",
    "01_sica_evolucao-mensal-das-consultas-medicas-hospitalares",
    # Qualidade
    "fraturas-da-anca-cirurgias-nas-primeiras-48h",
    "taxa-de-mortalidade-por-avc-isquemico-e-hemorragico",
    "partos-e-cesarianas",
    "cirurgias-em-ambulatorio",
    "morbilidade-e-mortalidade-hospitalar",
    # Capacidade e recursos
    "ocupacao-do-internamento",
    "lotacao-praticada-por-tipo-de-cama",
    "atividade-de-internamento-hospitalar",
    "trabalhadores-por-grupo-profissional",
    "intervencoes-cirurgicas",
    "consultas-em-telemedicina",
    "evolucao-mensal-das-consultas-de-psicologia",
    "evolucao-mensal-das-consultas-de-nutricao",
    # Dinheiro
    "divida-total-vencida-e-pagamentos",
    "tempo-medio-de-pagamento-das-instituicoes-do-sns-a-fornecedores",
    "percentagem-de-gastos-com-te-e-suplementos-no-total-gastos-com-pessoal",
    "portal-base",
    # Contexto nacional (não é ao nível da instituição, mas é a manchete cívica)
    "utentes-inscritos-em-cuidados-de-saude-primarios",
]


def caminho_bruto(dataset_id: str) -> "object":
    return DIR_BRUTO / f"{dataset_id}.csv.gz"


def descarregar(dataset_id: str) -> tuple[str, int, str]:
    """Descarrega um dataset em CSV e guarda-o comprimido. Devolve (id, bytes, estado)."""
    destino = caminho_bruto(dataset_id)
    url = f"{API}/catalog/datasets/{dataset_id}/exports/csv"
    ultimo = None
    for tentativa in range(TENTATIVAS):
        try:
            with requests.get(
                url,
                params={"delimiter": ";", "list_separator": "|", "with_bom": "false"},
                timeout=TEMPO_LIMITE,
                stream=True,
            ) as r:
                r.raise_for_status()
                tmp = destino.with_suffix(".part")
                with gzip.open(tmp, "wb") as saida:
                    for pedaco in r.iter_content(chunk_size=1 << 16):
                        if pedaco:
                            saida.write(pedaco)
                tmp.replace(destino)
            return dataset_id, destino.stat().st_size, "ok"
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(2**tentativa)
    return dataset_id, 0, f"FALHOU: {ultimo}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("datasets", nargs="*", help="ids específicos a descarregar")
    p.add_argument("--todos", action="store_true", help="descarregar os 144 do catálogo")
    args = p.parse_args()

    garantir_dirs()

    if args.datasets:
        alvos = args.datasets
    elif args.todos:
        if not FICHEIRO_CATALOGO.exists():
            print("catálogo em falta — corra primeiro: python ingest/catalog.py")
            return 1
        alvos = sorted(json.loads(FICHEIRO_CATALOGO.read_text(encoding="utf-8")))
    else:
        alvos = NUCLEO

    print(f"a descarregar {len(alvos)} datasets via /exports/csv")
    falhas = []
    total = 0
    # 4 em paralelo: o /exports é pesado do lado do servidor e não queremos
    # que um portal público do Estado nos trate como abuso.
    with ThreadPoolExecutor(4) as ex:
        futuros = {ex.submit(descarregar, d): d for d in alvos}
        for i, fut in enumerate(as_completed(futuros), 1):
            dataset_id, tamanho, estado = fut.result()
            if estado != "ok":
                falhas.append((dataset_id, estado))
                print(f"  [{i}/{len(alvos)}] {dataset_id}: {estado}")
            else:
                total += tamanho
                print(f"  [{i}/{len(alvos)}] {dataset_id}: {tamanho/1024:,.0f} KB")

    print(f"\ntotal: {total/1024/1024:,.1f} MB | falhas: {len(falhas)}")
    for d, e in falhas:
        print(f"  ! {d}: {e}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
