"""Confronto com fontes independentes do Portal da Transparência.

Correr com:  .venv/bin/python tests/test_validacao_externa.py

Os outros testes provam que somos consistentes com a fonte. Este prova que a
fonte, tratada como a tratamos, bate certo com quem conta os mesmos factos por
outro caminho — o INE e a ACSS. É o único teste que apanharia um erro
sistemático de tratamento, como falhar a des-acumulação das séries: nesse caso
os partos viriam cerca de cinco vezes acima e este ficheiro falharia.

O raciocínio por trás de cada âncora está em reference/VALIDACAO-EXTERNA.md.
"""

from __future__ import annotations

import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ingest"))

import duckdb  # noqa: E402
import yaml  # noqa: E402

from build import desacumular  # noqa: E402
from common import DIR_BRUTO, DIR_REFERENCIA  # noqa: E402
from instituicoes import carregar  # noqa: E402

# O Hospital de Cascais é uma parceria público-privada; a ACSS não o conta como
# SNS. Sem o excluir, a comparação erra por cerca de 4%.
FORA_DO_SNS = {"hospital-cascais"}

# Tolerâncias por âncora. Largas o suficiente para absorver revisões da fonte e
# diferenças de perímetro conhecidas; apertadas o suficiente para que um erro
# de tratamento — que produziria desvios de centenas por cento — não passe.
# Cada fonte externa tem o seu perímetro, e ignorá-lo produziria uma falha
# falsa. A ACSS reporta o SNS sem a parceria público-privada de Cascais; o INE
# conta os nascimentos em todas as unidades públicas e, além disso, conta
# nados-vivos e não partos — as gravidezes gemelares explicam a diferença
# residual, sempre no mesmo sentido.
ANCORAS_PARTOS = [
    # (ano, partos, cesarianas, taxa, tolerância, exclui PPP, fonte)
    ("2025", 63_897, 21_224, 33.2, 0.02, True,
     "ACSS, via CNN Portugal, fev. 2026 — SNS sem a PPP de Cascais"),
    ("2024", None, 21_073, 32.7, 0.03, False,
     "INE/ERS, 2024 — nados-vivos por cesariana em unidades públicas"),
]

# ACSS: a ULS do Nordeste teve a taxa mais alta do país em 2025, com 46%.
ANCORA_NORDESTE = ("uls-nordeste", "2025", 46.0, 1.0)

def _referencias() -> dict:
    """Valores publicados por terceiros, curados em reference/."""
    return yaml.safe_load(
        (DIR_REFERENCIA / "referencias-externas.yaml").read_text(encoding="utf-8")
    )


REF = _referencias()
NADOS_VIVOS_INE = {str(x["ano"]): x["nados_vivos"] for x in REF["nascimentos"]}


def _serie_partos(cw):
    """Partos e cesarianas por instituição e ano, tratados como no build."""
    con = duckdb.connect()
    caminho = DIR_BRUTO / "partos-e-cesarianas.csv.gz"
    rel = (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1)"
    )
    linhas = con.execute(
        f"select instituicao, tempo, no_de_partos, no_de_cesarianas from {rel} "
        "where instituicao is not null"
    ).fetchall()

    bruto_p: dict[str, dict[str, float]] = collections.defaultdict(dict)
    bruto_c: dict[str, dict[str, float]] = collections.defaultdict(dict)
    for nome, tempo, partos, ces in linhas:
        mes = str(tempo)[:7]
        bruto_p[nome][mes] = partos or 0
        bruto_c[nome][mes] = ces or 0

    por_inst: dict[str, dict[str, list[float]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: [0.0, 0.0])
    )
    for nome in bruto_p:
        inst = cw.resolver(nome)
        if inst is None:
            continue
        mensal_p = desacumular(bruto_p[nome])
        mensal_c = desacumular(bruto_c[nome])
        for mes, valor in mensal_p.items():
            if valor is None or mensal_c.get(mes) is None:
                continue
            alvo = por_inst[inst.id][mes[:4]]
            alvo[0] += valor
            alvo[1] += mensal_c[mes]
    return por_inst


def _total(por_inst, ano: str, excluir=frozenset()):
    partos = ces = 0.0
    for inst_id, anos in por_inst.items():
        if inst_id in excluir or ano not in anos:
            continue
        partos += anos[ano][0]
        ces += anos[ano][1]
    return partos, ces


def teste_partos_nacionais(por_inst) -> list[str]:
    erros = []
    for ano, ref_p, ref_c, ref_taxa, tol, sem_ppp, fonte in ANCORAS_PARTOS:
        partos, ces = _total(por_inst, ano, FORA_DO_SNS if sem_ppp else frozenset())
        if not partos:
            erros.append(f"{ano}: sem dados")
            continue
        taxa = 100 * ces / partos
        print(f"    {ano}: {partos:,.0f} partos, {ces:,.0f} cesarianas, {taxa:.1f} %"
              f"   [{fonte}]")

        if ref_p is not None:
            desvio = abs(partos - ref_p) / ref_p
            print(f"           partos vs {ref_p:,}: {100 * (partos / ref_p - 1):+.2f} %")
            if desvio > tol:
                erros.append(
                    f"{ano}: {partos:,.0f} partos contra {ref_p:,} da fonte externa "
                    f"({100 * (partos / ref_p - 1):+.1f} %, tolerância {100 * tol:.0f} %)"
                )
        desvio_c = abs(ces - ref_c) / ref_c
        print(f"           cesarianas vs {ref_c:,}: {100 * (ces / ref_c - 1):+.2f} %")
        if desvio_c > tol:
            erros.append(
                f"{ano}: {ces:,.0f} cesarianas contra {ref_c:,} da fonte externa "
                f"({100 * (ces / ref_c - 1):+.1f} %, tolerância {100 * tol:.0f} %)"
            )
        if abs(taxa - ref_taxa) > 1.0:
            erros.append(f"{ano}: taxa {taxa:.1f} % contra {ref_taxa} % da fonte externa")
    return erros


def teste_quota_do_sns(por_inst) -> list[str]:
    """Os partos do SNS têm de ser uma fração plausível dos nascimentos do país.

    Trava independente da anterior: apanha um erro de escala mesmo que as
    âncoras de cesarianas fossem removidas.
    """
    erros = []
    for ano, nados in NADOS_VIVOS_INE.items():
        partos, _ = _total(por_inst, ano, FORA_DO_SNS)
        quota = partos / nados
        print(f"    {ano}: {partos:,.0f} partos no SNS para {nados:,} nados-vivos "
              f"(INE) — {100 * quota:.0f} %")
        if not 0.60 <= quota <= 0.85:
            erros.append(
                f"{ano}: os partos do SNS dariam {100 * quota:.0f} % dos nascimentos "
                f"do país — fora do intervalo plausível de 60 % a 85 %"
            )
    return erros


def teste_hospital_extremo(por_inst, cw) -> list[str]:
    """A instituição que a ACSS aponta como a mais alta tem de o ser aqui."""
    inst_id, ano, ref, tol = ANCORA_NORDESTE
    ordenados = sorted(
        (
            (100 * v[ano][1] / v[ano][0], k)
            for k, v in por_inst.items()
            if ano in v and v[ano][0] > 200
        ),
        reverse=True,
    )
    if not ordenados:
        return [f"sem instituições com dados em {ano}"]
    taxa_topo, id_topo = ordenados[0]
    nossa = next((t for t, k in ordenados if k == inst_id), None)
    print(f"    {ano}: taxa mais alta = {cw.por_id(id_topo).nome_curto} "
          f"({taxa_topo:.1f} %); ACSS aponta {cw.por_id(inst_id).nome_curto} ({ref} %)")
    erros = []
    if id_topo != inst_id:
        erros.append(
            f"a taxa mais alta de {ano} é {id_topo}, não {inst_id} como a ACSS indica"
        )
    if nossa is None or abs(nossa - ref) > tol:
        erros.append(
            f"{inst_id} em {ano}: {nossa:.1f} % contra os {ref} % da ACSS"
            if nossa is not None
            else f"{inst_id} sem dados em {ano}"
        )
    return erros


def main() -> int:
    cw = carregar()
    por_inst = _serie_partos(cw)
    print(f"validação externa: {len(por_inst)} instituições\n")

    falhou = False
    for nome, funcao in [
        ("partos e cesarianas vs ACSS e INE/ERS", lambda: teste_partos_nacionais(por_inst)),
        ("quota do SNS nos nascimentos do país", lambda: teste_quota_do_sns(por_inst)),
        ("hospital com a taxa mais alta vs ACSS", lambda: teste_hospital_extremo(por_inst, cw)),
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
