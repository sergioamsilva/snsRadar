"""Contexto europeu, a partir da API aberta do Eurostat.

## Porquê

Tudo o resto neste portal compara Portugal com Portugal. Quem lê «33 % de
cesarianas» só tem como referência os 10 a 15 % da OMS — um consenso de 1985 que
a própria OMS deixou de apresentar como alvo em 2015, e que hoje quase nenhum
país europeu respeita. É uma régua que informa pouco: diz que estamos longe,
não diz se estamos longe como os outros ou sozinhos.

## O que entra, e o que ficou de fora

Só entra o que sobrevive à mesma pergunta que se faz a tudo o resto: **isto é
comparável?**

- **Cesarianas** entram. Todos os países reportam os partos hospitalares e a
  distribuição observada (15,7 % nos Países Baixos a 41,1 % na Polónia) é
  coerente com o que a literatura descreve.
- **Cirurgia de catarata em ambulatório** foi testada e **rejeitada**. Os
  valores dão Portugal a 99,1 % e a Alemanha a 0,1 %. A Alemanha faz cirurgia
  de catarata em ambulatório como toda a gente — o que difere é onde ela é
  registada, porque lá acontece fora do hospital e não entra nesta estatística.
  Publicar isso seria apresentar uma diferença de contabilidade como diferença
  de prática.

## A ressalva que acompanha o número

O Eurostat conta **todos os hospitais**, públicos e privados. Os privados
portugueses operam muito mais, e por isso a taxa nacional (37,4 % em 2022) é
mais alta do que a dos hospitais do SNS que este portal mede. Não é comparação
direta com o valor de cada instituição: é contexto do país.

Fonte reutilizável ao abrigo da Decisão 2011/833/UE da Comissão Europeia.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from common import DIR_SAIDA, TEMPO_LIMITE

API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Países da UE mais alguns vizinhos com dados. Não é uma escolha editorial:
# entram todos os que respondem, e a lista serve só para pedir uma consulta de
# cada vez em vez de descarregar a tabela inteira.
PAISES = [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK", "IS", "NO",
]

# Anos a tentar, do mais recente para trás: nem todos os países reportam ao
# mesmo ritmo, e um ano sem Portugal não serve de nada.
ANOS = ["2024", "2023", "2022", "2021"]

MINIMO_PAISES = 8


def _pedir(dataset: str, **filtros) -> dict:
    partes = [f"format=JSON"]
    for chave, valor in filtros.items():
        for v in valor if isinstance(valor, list) else [valor]:
            partes.append(f"{chave}={v}")
    url = f"{API}/{dataset}?{'&'.join(partes)}"
    with urllib.request.urlopen(url, timeout=TEMPO_LIMITE) as r:
        return json.loads(r.read())


def _por_pais(resposta: dict, fatia: dict | None = None) -> dict[str, float]:
    """Converte a resposta JSON-stat num `{código do país: valor}`.

    O Eurostat devolve os valores numa lista achatada, indexada pelo produto
    das dimensões. `fatia` fixa a posição das dimensões que não são o país;
    sem ela, uma tabela com quatro modalidades de cuidado devolveria quatro
    valores por país e ficaríamos com o primeiro por acaso.
    """
    dims = resposta["id"]
    tamanhos = resposta["size"]
    geo = resposta["dimension"]["geo"]["category"]["index"]
    inverso = {i: cod for cod, i in geo.items()}
    i_geo = dims.index("geo")

    # Passo de cada dimensão no índice achatado (ordem C: a última varia mais).
    passos = [1] * len(dims)
    for i in range(len(dims) - 2, -1, -1):
        passos[i] = passos[i + 1] * tamanhos[i + 1]

    fixo = 0
    for i, dim in enumerate(dims):
        if i == i_geo:
            continue
        alvo = (fatia or {}).get(dim)
        if alvo is None:
            continue
        idx = resposta["dimension"][dim]["category"]["index"][alvo]
        fixo += idx * passos[i]

    saida = {}
    for chave, valor in resposta["value"].items():
        n = int(chave)
        if (n - fixo) % passos[i_geo] or not 0 <= (n - fixo) // passos[i_geo] < tamanhos[i_geo]:
            continue
        # Confirma que este índice pertence mesmo à fatia pedida.
        if any(
            i != i_geo
            and (fatia or {}).get(dim) is not None
            and (n // passos[i]) % tamanhos[i]
            != resposta["dimension"][dim]["category"]["index"][fatia[dim]]
            for i, dim in enumerate(dims)
        ):
            continue
        pais = inverso.get((n // passos[i_geo]) % tamanhos[i_geo])
        if pais:
            saida[pais] = valor
    return saida


def cesarianas(ano: str) -> dict | None:
    """Cesarianas em percentagem dos nascidos vivos, por país."""
    try:
        cirurgias = _pedir(
            "hlth_co_proc3", icd9cm="CM74_CAE", unit="NR", time=ano, geo=PAISES
        )
        nascimentos = _pedir("demo_gind", indic_de="LBIRTH", time=ano, geo=PAISES)
    except (urllib.error.URLError, TimeoutError, KeyError):
        return None

    ces = _por_pais(cirurgias, {"icha_hc": "TOT_PAT"})
    nas = _por_pais(nascimentos)
    nomes = cirurgias["dimension"]["geo"]["category"]["label"]

    valores = {
        p: 100 * ces[p] / nas[p]
        for p in ces
        if nas.get(p) and ces[p] is not None
    }
    if "PT" not in valores or len(valores) < MINIMO_PAISES:
        return None

    ordenado = sorted(valores.items(), key=lambda kv: -kv[1])
    return {
        "indicador": "cesarianas",
        "ano": ano,
        "unidade": "percentagem",
        "titulo": "Cesarianas em percentagem dos nascimentos",
        "fonte": "Eurostat · hlth_co_proc3 e demo_gind",
        "url": "https://ec.europa.eu/eurostat/databrowser/view/hlth_co_proc3",
        "nota": (
            "O Eurostat conta todos os hospitais, públicos e privados. Os "
            "privados portugueses operam mais, pelo que a taxa do país é mais "
            "alta do que a dos hospitais do SNS medida neste portal."
        ),
        "paises": [
            {"codigo": p, "nome": nomes.get(p, p), "valor": round(v, 1)}
            for p, v in ordenado
        ],
    }


def _indicador_simples(dataset: str, fatia: dict, meta: dict, ano: str) -> dict | None:
    """Um indicador de tabela única: pede, fatia e devolve na forma comum."""
    try:
        resposta = _pedir(dataset, time=ano, geo=PAISES,
                          **{k: v for k, v in fatia.items()})
    except (urllib.error.URLError, TimeoutError, KeyError):
        return None
    valores = {p: v for p, v in _por_pais(resposta, fatia).items() if v is not None}
    if "PT" not in valores or len(valores) < MINIMO_PAISES:
        return None
    nomes = resposta["dimension"]["geo"]["category"]["label"]
    ordenado = sorted(valores.items(), key=lambda kv: -kv[1])
    return {
        **meta,
        "ano": ano,
        "paises": [
            {"codigo": p, "nome": nomes.get(p, p), "valor": round(v, 1)}
            for p, v in ordenado
        ],
    }


def mortalidade_evitavel(ano: str) -> dict | None:
    """Mortes evitáveis — tratáveis e preveníveis — padronizadas, por 100 mil.

    É o indicador-resumo com que a OCDE e a Comissão comparam sistemas de
    saúde: mortes antes dos 75 anos que cuidados atempados (tratáveis) ou
    políticas de prevenção (preveníveis) teriam evitado. Padronizado por
    idade — a única forma de comparar países que envelhecem a ritmos
    diferentes.
    """
    return _indicador_simples(
        "hlth_cd_apr",
        {"mortalit": "TOTAL", "sex": "T", "icd10": "TOTAL", "unit": "RT"},
        {
            "indicador": "mortalidade-evitavel",
            "unidade": "por_100000",
            "titulo": "Mortalidade evitável, padronizada, por 100 mil habitantes",
            "fonte": "Eurostat · hlth_cd_apr",
            "url": "https://ec.europa.eu/eurostat/databrowser/view/hlth_cd_apr",
            "nota": (
                "Mortes antes dos 75 anos que cuidados atempados ou prevenção "
                "teriam evitado, padronizadas por idade. É um retrato do país "
                "inteiro — sistema de saúde, mas também tabaco, álcool, "
                "estradas —, não dos hospitais do SNS isoladamente."
            ),
        },
        ano,
    )


def camas(ano: str) -> dict | None:
    """Camas de hospital por 100 mil habitantes."""
    return _indicador_simples(
        "hlth_rs_bds1",
        {"facility": "HBEDT", "hlthcare": "TOTAL", "unit": "P_HTHAB"},
        {
            "indicador": "camas",
            "unidade": "por_100000",
            "titulo": "Camas de hospital por 100 mil habitantes",
            "fonte": "Eurostat · hlth_rs_bds1",
            "url": "https://ec.europa.eu/eurostat/databrowser/view/hlth_rs_bds1",
            "nota": (
                "Todas as camas hospitalares, públicas e privadas. Mais camas "
                "não é, por si, melhor: países com cuidados domiciliários e "
                "ambulatório fortes vivem com menos. É capacidade instalada, "
                "não desempenho."
            ),
        },
        ano,
    )


def main() -> int:
    saida_json: dict[str, dict] = {}

    for ano in ANOS:
        resultado = cesarianas(ano)
        if resultado:
            saida_json["cesarianas"] = resultado
            break
    else:
        print("Eurostat: sem ano com dados suficientes; contexto europeu não escrito")
        return 0

    # Os restantes toleram falhar um a um: cada dot plot vive sem os outros.
    for nome, funcao in (("mortalidade-evitavel", mortalidade_evitavel), ("camas", camas)):
        for ano in ANOS:
            resultado = funcao(ano)
            if resultado:
                saida_json[nome] = resultado
                break
        else:
            print(f"Eurostat: {nome} sem ano com dados suficientes; fica de fora")

    saida = DIR_SAIDA / "europa.json"
    saida.write_text(
        json.dumps(saida_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for chave, resultado in saida_json.items():
        pt = next(p for p in resultado["paises"] if p["codigo"] == "PT")
        posicao = resultado["paises"].index(pt) + 1
        print(
            f"contexto europeu · {chave} ({resultado['ano']}): "
            f"{len(resultado['paises'])} países · Portugal {pt['valor']}, "
            f"{posicao}.º mais alto"
        )
    print(f"escrito em {saida.relative_to(DIR_SAIDA.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
