"""Confronto com o Benchmarking Hospitalar da ACSS, unidade a unidade e mês a mês.

Correr com:  .venv/bin/python tests/test_benchmarking_acss.py

O `test_validacao_externa.py` confronta totais nacionais com o que terceiros
publicaram. Este vai muito mais fundo, e por uma razão de fundo: o Portal da
Transparência publica séries **acumuladas no ano** e a ACSS publica os mesmos
factos **mês a mês**. São duas descrições independentes da mesma realidade, e a
des-acumulação — a correção de que tudo depende, e a que transformaria 64 505
partos em 413 728 se estivesse errada — é exatamente a operação que liga uma à
outra.

Se a des-acumulação estivesse errada, não falharia aqui um valor: falhariam
todos. Não há forma de um erro sistemático de tratamento sobreviver a um
confronto de milhares de pares (unidade, mês) com a fonte que os apura por outro
caminho.

O que se compara, para cada indicador que as duas fontes publicam:

  · o numerador e o denominador de cada mês, quando a ACSS os dá em separado;
  · a taxa mensal, sempre.

O limiar não é a igualdade exata. As duas fontes têm perímetros e datas de
extração diferentes, e uma revisão de um lado que ainda não chegou ao outro é
uma divergência legítima. O que este teste apanha é o desvio sistemático.
"""

from __future__ import annotations

import collections
import csv
import gzip
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ingest"))

import duckdb  # noqa: E402

from build import (  # noqa: E402
    LIMIAR_DENOMINADOR,
    _valor,
    carregar_catalogo,
    carregar_indicadores,
    extrair_series,
)
from common import DIR_BRUTO, normalizar_agressivo  # noqa: E402
from instituicoes import carregar  # noqa: E402

# Os indicadores que as duas fontes publicam. À esquerda o id do snsRadar,
# construído a partir dos CSV acumulados do portal; à direita o dataset da ACSS,
# construído a partir da sua exportação mensal.
PARES = [
    ("cesarianas", "bh-acss-perc-partos-por-cesariana"),
    ("fratura-anca-48h", "bh-acss-perc-fract-anca-ciru-pr-48h"),
    ("cirurgia-ambulatorio", "bh-acss-perc-cir-amb-proc-amb"),
    ("lic-dentro-tmrg", "bh-acss-perc-inscritos-lic-dentro-tmrg"),
    ("consultas-tempo-adequado", "bh-acss-perc-prim-cons-tempo-adequado"),
    ("demora-antes-cirurgia", "bh-acss-dem-media-antes-cirurgia"),
    ("ocupacao-internamento", "bh-acss-tax-anual-ocup-intern"),
]

# Fração de pares (unidade, mês) que pode divergir **depois de descontadas as
# unidades de perímetro alargado** (ver `perimetro_alargado`). Aqui já não há
# desculpa de perímetro: os dois lados estão a contar as mesmas instituições, e
# 2 % dá para revisões de um lado que ainda não chegaram ao outro.
TOLERANCIA_DIVERGENTES = 0.02

# Fração tolerada contando tudo, incluindo as unidades cujo perímetro o snsRadar
# alarga de propósito. Serve de rede: se subir muito, apareceu divergência nova
# que a explicação do perímetro não cobre.
TOLERANCIA_TOTAL = 0.10

# Quanto pode divergir um valor antes de contar como divergente: meio ponto
# percentual, ou 2 % em termos relativos, o que for mais generoso.
TOLERANCIA_ABSOLUTA = 0.5
TOLERANCIA_RELATIVA = 0.02

# Abaixo deste denominador a taxa mensal é ruído e o snsRadar nem a publica.
# Compará-la seria comparar arredondamentos.
DENOMINADOR_MINIMO = LIMIAR_DENOMINADOR


def _proximo(nosso: float, deles: float) -> bool:
    if nosso is None or deles is None:
        return False
    return (
        abs(nosso - deles) <= TOLERANCIA_ABSOLUTA
        or abs(nosso - deles) <= TOLERANCIA_RELATIVA * max(abs(nosso), abs(deles))
    )


def _numero(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def serie_acss(cw, dataset: str) -> dict[tuple[str, str], dict]:
    """A série da ACSS, agregada nas mesmas entidades canónicas que a nossa.

    A agregação importa: até 2023 a ACSS publica os centros hospitalares que a
    reforma de 2024 veio a fundir, com os nomes de então. É o crosswalk — o
    mesmo, sem exceções — que os junta na ULS que hoje lhes sucede. Sem isto, a
    comparação partia-se em janeiro de 2024, que é precisamente o mês que este
    projeto existe para atravessar.
    """
    caminho = DIR_BRUTO / f"{dataset}.csv.gz"
    if not caminho.exists():
        return {}

    somas: dict[tuple[str, str], dict] = collections.defaultdict(
        lambda: {"num": 0.0, "den": 0.0, "valor": None, "n": 0}
    )
    with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            inst = cw.resolver(linha["instituicao"])
            if inst is None:
                continue
            num, den = _numero(linha["numerador"]), _numero(linha["denominador"])
            if num is None or den is None:
                continue
            alvo = somas[(inst.id, linha["tempo"][:7])]
            alvo["num"] += num
            alvo["den"] += den
            alvo["n"] += 1
    return somas


def perimetro_alargado(cw, dataset: str, nossos_nomes: set[str], inst_id: str) -> set[str]:
    """Os rótulos que o snsRadar soma naquela entidade e que a ACSS não conhece.

    É a única diferença de fundo entre as duas séries, e não é um erro de
    nenhuma das partes. O Benchmarking cobre entidades hospitalares EPE e PPP; a
    reforma de 2024 fez as ULS absorverem também unidades que nunca lá
    estiveram — o Centro Hospitalar Psiquiátrico de Lisboa e o Instituto Gama
    Pinto na ULS de São José, o Hospital Dr. Francisco Zagalo na Região de
    Aveiro, o Rovisco Pais e o Arcebispo João Crisóstomo em Coimbra.

    O snsRadar reconstrói o perímetro **de hoje** para trás no tempo, que é o
    que responde à pergunta de quem lê («o meu hospital»); a ACSS mostra a
    entidade que benchmarkava então. Antes de 2024, os dois números são
    diferentes com razão, e o nosso é legitimamente maior.
    """
    caminho = DIR_BRUTO / f"{dataset}.csv.gz"
    if not caminho.exists():
        return set()
    deles: set[str] = set()
    with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            inst = cw.resolver(linha["instituicao"])
            if inst is not None and inst.id == inst_id:
                deles.add(normalizar_agressivo(linha["instituicao"]))
    return {normalizar_agressivo(n) for n in nossos_nomes} - deles


def comparar_indicador(con, cw, indicadores, catalogo, iid: str, dataset: str) -> dict:
    ind = next((i for i in indicadores if i["id"] == iid), None)
    if ind is None:
        return {"erro": f"{iid}: não existe em reference/indicadores.yaml"}

    deles = serie_acss(cw, dataset)
    if not deles:
        return {"erro": f"{dataset}: ficheiro em falta — corra ingest/benchmarking_acss.py"}

    # Passa pelo build a sério, com o mesmo código que escreve as fichas. Um
    # teste que reimplementasse a des-acumulação estaria a validar a sua própria
    # cópia, e não o que o site publica.
    series, nomes_fonte = extrair_series(con, cw, [ind], catalogo)
    nosso = series[iid]

    alargadas = {
        inst_id
        for inst_id in nosso
        if perimetro_alargado(cw, dataset, nomes_fonte[(iid, inst_id)], inst_id)
    }

    comparados = divergentes = 0
    comuns = divergentes_comuns = 0
    num_iguais = den_iguais = pares_com_contagens = 0
    exemplos: list[str] = []

    for inst_id, meses in nosso.items():
        mesmo_perimetro = inst_id not in alargadas
        for mes, d in meses.items():
            chave = (inst_id, mes)
            if chave not in deles:
                continue
            outro = deles[chave]
            if d["den"] < DENOMINADOR_MINIMO or outro["den"] < DENOMINADOR_MINIMO:
                continue

            pares_com_contagens += 1
            if _proximo(d["num"], outro["num"]):
                num_iguais += 1
            if _proximo(d["den"], outro["den"]):
                den_iguais += 1

            nossa_taxa = _valor(ind, d["num"], d["den"])
            taxa_deles = _valor(ind, outro["num"], outro["den"])
            if nossa_taxa is None or taxa_deles is None:
                continue
            comparados += 1
            comuns += mesmo_perimetro
            if not _proximo(nossa_taxa, taxa_deles):
                divergentes += 1
                divergentes_comuns += mesmo_perimetro
                if mesmo_perimetro and len(exemplos) < 3:
                    exemplos.append(
                        f"{inst_id} {mes}: nós {nossa_taxa:.2f} "
                        f"({d['num']:.0f}/{d['den']:.0f}), "
                        f"ACSS {taxa_deles:.2f} ({outro['num']:.0f}/{outro['den']:.0f})"
                    )

    return {
        "comparados": comparados,
        "divergentes": divergentes,
        "comuns": comuns,
        "divergentes_comuns": divergentes_comuns,
        "alargadas": sorted(alargadas),
        "pares_com_contagens": pares_com_contagens,
        "num_iguais": num_iguais,
        "den_iguais": den_iguais,
        "unidades": len({i for i, _ in deles}),
        "exemplos": exemplos,
    }


def teste_pares(con, cw, indicadores, catalogo) -> list[str]:
    erros = []
    for iid, dataset in PARES:
        r = comparar_indicador(con, cw, indicadores, catalogo, iid, dataset)
        if "erro" in r:
            erros.append(r["erro"])
            print(f"    {iid}: {r['erro']}")
            continue
        if not r["comparados"]:
            erros.append(f"{iid}: nenhum par (unidade, mês) comparável com a ACSS")
            continue

        fracao = r["divergentes"] / r["comparados"]
        fracao_comuns = r["divergentes_comuns"] / r["comuns"] if r["comuns"] else 0.0
        pares = r["pares_com_contagens"] or 1
        print(
            f"    {iid}: {r['comparados']:,} pares (unidade, mês) em "
            f"{r['unidades']} unidades — {100 * (1 - fracao):.1f} % coincidem; "
            f"a perímetro igual, {100 * (1 - fracao_comuns):.1f} % "
            f"({r['comuns']:,} pares)"
        )
        print(
            f"        numerador {100 * r['num_iguais'] / pares:.1f} %, "
            f"denominador {100 * r['den_iguais'] / pares:.1f} %"
            + (f" · perímetro alargado em {', '.join(r['alargadas'])}"
               if r["alargadas"] else "")
        )
        for e in r["exemplos"]:
            print(f"        por explicar: {e}")
        if fracao_comuns > TOLERANCIA_DIVERGENTES:
            erros.append(
                f"{iid}: {r['divergentes_comuns']:,}/{r['comuns']:,} pares divergem da "
                f"ACSS em unidades com o mesmo perímetro ({100 * fracao_comuns:.1f} %, "
                f"tolerância {100 * TOLERANCIA_DIVERGENTES:.0f} %)"
            )
        if fracao > TOLERANCIA_TOTAL:
            erros.append(
                f"{iid}: {r['divergentes']:,}/{r['comparados']:,} pares divergem no "
                f"total ({100 * fracao:.1f} %, tolerância "
                f"{100 * TOLERANCIA_TOTAL:.0f} %)"
            )
    return erros


def teste_desacumulacao(con, cw, indicadores, catalogo) -> list[str]:
    """A prova direta: somar os doze meses de um ano tem de dar o mesmo dos dois lados.

    É aqui que um erro de des-acumulação apareceria em toda a sua dimensão. A
    série do portal é acumulada; a da ACSS não é. Se a des-acumulação falhasse,
    o total anual do snsRadar viria várias vezes acima do da ACSS — e nenhuma
    tolerância o esconderia.
    """
    iid, dataset = PARES[0]
    ind = next(i for i in indicadores if i["id"] == iid)
    deles = serie_acss(cw, dataset)
    if not deles:
        return [f"{dataset}: ficheiro em falta"]
    series, _ = extrair_series(con, cw, [ind], catalogo)

    erros = []
    for ano in ("2019", "2023", "2025"):
        nosso_num = sum(
            d["num"] for meses in series[iid].values()
            for m, d in meses.items() if m[:4] == ano
        )
        deles_num = sum(
            v["num"] for (_, m), v in deles.items() if m[:4] == ano
        )
        if not deles_num:
            continue
        razao = nosso_num / deles_num
        print(f"    {ano}: {nosso_num:,.0f} cesarianas no snsRadar contra "
              f"{deles_num:,.0f} na ACSS — razão {razao:.3f}")
        if not 0.95 <= razao <= 1.05:
            erros.append(
                f"{ano}: o total anual de cesarianas dá {razao:.2f}× o da ACSS "
                f"({nosso_num:,.0f} contra {deles_num:,.0f})"
            )
    return erros


def teste_universo(cw) -> list[str]:
    """Toda a unidade que a ACSS conhece tem de existir no crosswalk.

    A ACSS mantém a sua própria lista de entidades hospitalares. Confrontá-la
    com a nossa é a verificação que faltava ao crosswalk: até aqui só sabíamos
    que resolvíamos os nomes do portal, não que conhecíamos as mesmas
    instituições que o organismo que financia o SNS.
    """
    caminho = DIR_BRUTO / "bh-acss-_grupos.json"
    if not caminho.exists():
        return ["bh-acss-_grupos.json em falta — corra ingest/benchmarking_acss.py"]

    import json

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    sem_resolucao = [
        nome for nome in dados.get("por_instituicao", {}) if cw.resolver(nome) is None
    ]
    canonicas = {
        cw.resolver(n).id for n in dados.get("por_instituicao", {}) if cw.resolver(n)
    }
    print(f"    {len(dados.get('por_instituicao', {}))} nomes da ACSS → "
          f"{len(canonicas)} entidades canónicas do snsRadar")

    erros = []
    if sem_resolucao:
        erros.append(
            f"{len(sem_resolucao)} nomes da ACSS não resolvem para entidade "
            f"canónica: {', '.join(sorted(sem_resolucao)[:3])}"
        )
    return erros


def main() -> int:
    con = duckdb.connect()
    cw = carregar()
    indicadores = carregar_indicadores()
    catalogo = carregar_catalogo()

    print(f"benchmarking ACSS: {len(PARES)} indicadores publicados pelas duas fontes\n")

    falhou = False
    for nome, funcao in [
        ("séries mensais vs ACSS, unidade a unidade",
         lambda: teste_pares(con, cw, indicadores, catalogo)),
        ("totais anuais: acumulado do portal vs mensal da ACSS",
         lambda: teste_desacumulacao(con, cw, indicadores, catalogo)),
        ("universo de instituições da ACSS vs crosswalk", lambda: teste_universo(cw)),
    ]:
        erros = funcao()
        if erros:
            falhou = True
            print(f"  FALHA  {nome}")
            for e in erros:
                print(f"           {e}")
        else:
            print(f"  ok     {nome}\n")

    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
