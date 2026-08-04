"""População servida por cada unidade de saúde, para converter contagens em taxas.

Sem denominador, «5 675 949 atendimentos em urgência» não se interpreta e um
hospital pequeno parece melhor só por ser pequeno. Com denominador, passa a
«urgências por mil habitantes» e as unidades tornam-se comparáveis.

Duas fontes, por esta ordem:

  1. **Utentes inscritos nos cuidados primários** (Portal da Transparência).
     É o denominador certo: a população pela qual cada ULS é legalmente
     responsável, não a que por acaso reside no distrito. Desde a reforma de
     2024 o dataset vem indexado por ULS — «CSP da ULS Coimbra» — o que o liga
     diretamente ao crosswalk.

  2. **População residente do INE** por município, sexo e grupo etário. Serve
     para a estrutura etária, que os utentes inscritos não dão, e como
     verificação independente do total.

O IPO de Lisboa, o IPO do Porto e o Hospital de Cascais não têm população
atribuída: são centros de referência ou de gestão privada, sem lista de
inscritos própria. Ficam sem taxas per capita, e é isso que se declara.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ingest"))

import duckdb  # noqa: E402
import requests  # noqa: E402

from common import (  # noqa: E402
    DIR_BRUTO,
    DIR_SAIDA,
    TEMPO_LIMITE,
    garantir_dirs,
    normalizar_agressivo,
)
from instituicoes import carregar  # noqa: E402

DATASET_CSP = "utentes-inscritos-em-cuidados-de-saude-primarios"

# Indicador do INE: população residente por local de residência, sexo e grupo
# etário. Anual, de 2011 a 2023, sem chave de acesso.
INE_POP = "0008273"
INE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp"


def _rel(dataset: str) -> str:
    caminho = DIR_BRUTO / f"{dataset}.csv.gz"
    return (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1)"
    )


def _chave(rotulo: str) -> str:
    """Converte «CSP da ULS Trás-os-Montes Alto Douro» na chave do crosswalk."""
    t = rotulo.strip()
    for prefixo in ("CSP da ", "CSP do ", "CSP de ", "CSP "):
        if t.startswith(prefixo):
            t = t[len(prefixo):]
            break
    # A fonte abrevia aqui o que escreve por extenso em todos os outros datasets.
    if t.upper().startswith("ULS"):
        t = "Unidade Local de Saúde " + t[3:].lstrip()
    return normalizar_agressivo(t)


def inscritos_por_instituicao(con, cw) -> dict:
    """Utentes inscritos nos cuidados primários, por entidade canónica."""
    ultimo = con.execute(
        f"select max(periodo) from {_rel(DATASET_CSP)}"
    ).fetchone()[0]
    linhas = con.execute(
        f"select aces, ars, utentes_inscritos_csp, total_utentes_sem_mdf_atribuido "
        f"from {_rel(DATASET_CSP)} where periodo = '{ultimo}'"
    ).fetchall()

    out, sem_correspondencia = {}, []
    for aces, ars, inscritos, sem_mdf in linhas:
        chave = _chave(aces)
        inst = next(
            (i for i in cw.instituicoes if chave in i.chaves), None
        )
        if inst is None:
            sem_correspondencia.append(aces)
            continue
        out[inst.id] = {
            "inscritos": int(inscritos or 0),
            "sem_medico_familia": int(sem_mdf or 0),
            "percentagem_sem_medico": round(
                100 * (sem_mdf or 0) / inscritos, 1
            ) if inscritos else None,
            "regiao": ars,
            "periodo": ultimo,
        }
    return out, sem_correspondencia, ultimo


def populacao_ine(ano: int = 2023) -> tuple[dict, dict]:
    """População residente por município e por grupo etário (INE).

    A resposta do INE mistura níveis geográficos no mesmo array — país, NUTS II,
    NUTS III e município — e somar tudo dá cinco vezes a população do país. Os
    municípios são os códigos de 7 dígitos; `dim_4 = 'T'` é o total de idades e
    `dim_3 = 'T'` o total de ambos os sexos.
    """
    r = requests.get(
        INE_URL,
        params={"op": "2", "varcd": INE_POP, "Dim1": f"S7A{ano}", "lang": "PT"},
        timeout=TEMPO_LIMITE,
    )
    r.raise_for_status()
    dados = r.json()[0]["Dados"][str(ano)]

    municipios: dict[str, dict] = {}
    idades: dict[str, float] = {}
    territorio: dict[str, float] = {}
    for linha in dados:
        if linha.get("dim_3") != "T" or linha.get("valor") is None:
            continue
        cod, nome, valor = linha["geocod"], linha["geodsg"], float(linha["valor"])

        if len(cod) == 1:  # Continente, Açores, Madeira
            if linha.get("dim_4") == "T":
                territorio[nome] = valor
        elif len(cod) == 7 and linha.get("dim_4") == "T":
            municipios[cod] = {"nome": nome, "total": valor}
        elif len(cod) == 1 and linha.get("dim_4") != "T":
            idades[linha.get("dim_4_t") or linha["dim_4"]] = (
                idades.get(linha.get("dim_4_t") or linha["dim_4"], 0) + valor
            )

    # Estrutura etária nacional, útil para padronizar taxas populacionais.
    for linha in dados:
        if (linha.get("dim_3") == "T" and linha.get("dim_4") != "T"
                and len(linha.get("geocod", "")) == 1 and linha.get("valor") is not None):
            rot = linha.get("dim_4_t") or linha["dim_4"]
            idades[rot] = idades.get(rot, 0) + float(linha["valor"])

    return municipios, {"por_territorio": territorio, "por_idade": idades}


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    cw = carregar()

    inscritos, sem_corr, periodo = inscritos_por_instituicao(con, cw)
    total = sum(v["inscritos"] for v in inscritos.values())
    sem_mdf = sum(v["sem_medico_familia"] for v in inscritos.values())

    print(f"utentes inscritos em {periodo}: {len(inscritos)} unidades, "
          f"{total:,} utentes")
    print(f"  sem médico de família: {sem_mdf:,} ({100 * sem_mdf / total:.1f} %)")
    if sem_corr:
        print(f"  {len(sem_corr)} rótulos sem correspondência: {sem_corr}")

    sem_populacao = [
        i.id for i in cw.instituicoes
        if i.id not in inscritos and i.tipo != "extinto"
    ]
    print(f"  {len(sem_populacao)} unidades sem população atribuída "
          f"(centros de referência e PPP): {', '.join(sem_populacao)}")

    print("\npopulação residente do INE (2023), para estrutura etária e verificação")
    agregados = {}
    try:
        mun, agregados = populacao_ine()
        continente = agregados["por_territorio"].get("Continente", 0)
        print(f"  {len(mun)} municípios; continente {continente:,.0f} residentes")
        # O SNS cobre apenas o continente: as regiões autónomas têm serviços
        # regionais próprios. Os inscritos excedem ligeiramente os residentes
        # porque as inscrições sobrevivem a mudanças de residência e à emigração.
        if continente:
            print(f"  utentes inscritos ÷ residentes no continente = "
                  f"{total / continente:.2f}")
    except Exception as e:  # noqa: BLE001
        print(f"  INE indisponível ({str(e)[:60]}); segue-se só com os inscritos")
        mun = {}

    saida = DIR_SAIDA / "populacao.json"
    saida.write_text(
        json.dumps(
            {
                "periodo": periodo,
                "por_instituicao": inscritos,
                "sem_populacao_atribuida": sem_populacao,
                "nacional": {"inscritos": total, "sem_medico_familia": sem_mdf},
                "ine_municipios": mun,
                "ine_agregados": agregados,
                "nota": (
                    "Denominador = utentes inscritos nos cuidados de saúde "
                    "primários da ULS, que é a população pela qual a unidade é "
                    "responsável. Centros de referência (IPO) e a PPP de Cascais "
                    "não têm lista própria e ficam sem taxas per capita."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nescrito em {saida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
