"""A reforma das ULS de 2024, medida.

Em 1 de janeiro de 2024 o Decreto-Lei n.º 102/2023 renomeou 32 entidades do SNS
e fundiu sete delas, juntando ao hospital os cuidados de saúde primários da sua
área. É a maior alteração de organização do SNS em décadas, e ninguém publicou
o que aconteceu aos indicadores por causa dela — porque a própria fonte parte
todas as séries nessa data e ninguém as volta a ligar.

O snsRadar tem o crosswalk, que é exatamente a peça que falta. Este módulo usa-o
para a pergunta que ele torna possível: **mudou alguma coisa?**

## O desenho, e os seus limites

Compara os doze meses anteriores a janeiro de 2024 com os doze seguintes, e
separa as unidades em dois grupos:

  · **transformadas** — as 32 entidades que passaram a Unidade Local de Saúde
    nessa data, absorvendo os cuidados de saúde primários da sua área;
  · **controlo** — as sete que **já eram** ULS antes da reforma (Alto Minho,
    Matosinhos, Nordeste, Guarda, Castelo Branco, Baixo Alentejo e Litoral
    Alentejano). São da mesma natureza e já tinham cuidados primários
    integrados: a lei de 2023 não lhes mudou o perímetro.

É esse grupo de controlo que dá sentido à comparação. Sem ele, qualquer
variação entre 2023 e 2024 confundir-se-ia com o que aconteceu ao país inteiro
no mesmo período. A diferença entre as duas variações é uma estimativa do
efeito da transformação, no espírito de uma diferença-em-diferenças.

Ficam de fora os institutos de oncologia e a parceria público-privada: não
foram abrangidos pela reforma, mas também não têm missão comparável.

É uma **estimativa fraca** e é preciso dizê-lo alto: são sete unidades de
controlo, não há aleatorização, e as que já eram ULS antes de 2024 não o eram
por acaso — são, na maioria, do interior e de menor dimensão, e isso pode ele
próprio explicar a diferença.

O que isto **não** é: prova de que a reforma correu bem ou mal. O que isto **é**:
a única leitura quantitativa de conjunto que os dados públicos permitem, com os
seus pressupostos escritos.

Escreve data/out/reforma.json.
"""

from __future__ import annotations

import json
import statistics
import sys

import duckdb

from build import (
    LIMIAR_DENOMINADOR,
    _tem_denominador,
    _valor,
    carregar_catalogo,
    carregar_indicadores,
    extrair_series,
)
from common import DIR_SAIDA, garantir_dirs
from instituicoes import carregar

CORTE = "2024-01"
MESES = 12

# Abaixo disto não se compara: uma variação apurada em meia dúzia de unidades
# não distingue efeito de acaso, e publicá-la seria dar-lhe um peso que não tem.
MINIMO_UNIDADES = 5


def _janela(meses: list[str], ate: str, n: int) -> list[str]:
    anteriores = [m for m in meses if m < ate]
    return anteriores[-n:]


def _agregado(ind: dict, meses_dados: dict, janela: list[str]) -> float | None:
    """O valor do indicador numa janela, pela regra do próprio indicador."""
    presentes = [m for m in janela if m in meses_dados]
    if len(presentes) < len(janela) * 0.75:
        return None  # janela demasiado incompleta para comparar
    if ind.get("ja_e_taxa"):
        return statistics.median(meses_dados[m]["num"] for m in presentes)
    num = sum(meses_dados[m]["num"] for m in presentes)
    den = sum(meses_dados[m]["den"] for m in presentes) if _tem_denominador(ind) else None
    if den is not None and den < LIMIAR_DENOMINADOR:
        return None
    return _valor(ind, num, den)


def calcular(con, cw, indicadores, catalogo) -> dict:
    series, _ = extrair_series(con, cw, indicadores, catalogo)

    # Tratamento e controlo. O controlo são as ULS que já o eram: mesma
    # natureza, cuidados primários já integrados, e nenhuma alteração de
    # perímetro em 2024.
    transformadas = {i.id for i in cw.instituicoes if i.sucessao}
    controlo = {
        i.id for i in cw.instituicoes
        if not i.sucessao and i.tipo == "uls"
    }

    por_indicador = []
    por_instituicao: dict[str, list[dict]] = {}

    for ind in indicadores:
        iid = ind["id"]
        todos = sorted({m for inst in series[iid].values() for m in inst})
        antes = _janela(todos, CORTE, MESES)
        depois = [m for m in todos if m >= CORTE][:MESES]
        if len(antes) < MESES or len(depois) < MESES:
            continue

        variacoes: dict[str, float] = {}
        for inst_id, meses_dados in series[iid].items():
            a = _agregado(ind, meses_dados, antes)
            d = _agregado(ind, meses_dados, depois)
            if a is None or d is None or a == 0:
                continue
            variacao = 100 * (d / a - 1)
            variacoes[inst_id] = variacao
            por_instituicao.setdefault(inst_id, []).append(
                {
                    "indicador": iid,
                    "titulo": ind["titulo"],
                    "unidade": ind["unidade"],
                    "antes": a,
                    "depois": d,
                    "variacao": round(variacao, 1),
                }
            )

        grupo = lambda ids: [v for k, v in variacoes.items() if k in ids]  # noqa: E731
        v_trans, v_ctrl = grupo(transformadas), grupo(controlo)
        if len(v_trans) < MINIMO_UNIDADES or len(v_ctrl) < MINIMO_UNIDADES:
            continue

        med_trans = statistics.median(v_trans)
        med_ctrl = statistics.median(v_ctrl)
        por_indicador.append(
            {
                "indicador": iid,
                "titulo": ind["titulo"],
                "grupo": ind["grupo"],
                "unidade": ind["unidade"],
                "polaridade": ind["polaridade"],
                # Uma contagem muda mecanicamente com a reforma: a ULS passou a
                # contar os médicos, os enfermeiros e a atividade dos centros de
                # saúde que absorveu. Os +52 % de médicos não são contratação, é
                # perímetro. Numa taxa o efeito cancela-se em larga medida,
                # porque numerador e denominador crescem juntos — e é por isso
                # que só as taxas admitem leitura de desempenho.
                "mecanico": not _tem_denominador(ind) and not ind.get("ja_e_taxa"),
                "n_transformadas": len(v_trans),
                "n_controlo": len(v_ctrl),
                "variacao_transformadas": round(med_trans, 1),
                "variacao_controlo": round(med_ctrl, 1),
                # A diferença entre as duas variações: o que sobra depois de
                # descontar o que aconteceu a toda a gente no mesmo período.
                "diferenca": round(med_trans - med_ctrl, 1),
            }
        )

    por_indicador.sort(key=lambda x: -abs(x["diferenca"]))
    return {
        "corte": CORTE,
        "meses_por_janela": MESES,
        "base_legal": "Decreto-Lei n.º 102/2023, de 7 de novembro",
        "n_transformadas": len(transformadas),
        "n_controlo": len(controlo),
        "controlo": sorted(controlo),
        "por_indicador": por_indicador,
        "por_instituicao": {
            k: sorted(v, key=lambda x: -abs(x["variacao"]))
            for k, v in por_instituicao.items()
        },
    }


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    cw = carregar()
    r = calcular(con, cw, carregar_indicadores(), carregar_catalogo())

    (DIR_SAIDA / "reforma.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"reforma de 2024: {len(r['por_indicador'])} indicadores comparáveis "
          f"({r['n_transformadas']} entidades transformadas em ULS, "
          f"{r['n_controlo']} de controlo)")
    taxas = [x for x in r["por_indicador"] if not x["mecanico"]]
    print(f"  {sum(1 for x in r['por_indicador'] if x['mecanico'])} são contagens, "
          f"em que a variação é sobretudo mudança de perímetro")
    print("  maiores diferenças entre as taxas (leitura de desempenho):")
    for x in taxas[:6]:
        print(f"    {x['titulo'][:40]:40s} transformadas {x['variacao_transformadas']:+7.1f} % "
              f"· controlo {x['variacao_controlo']:+7.1f} % "
              f"· diferença {x['diferenca']:+7.1f} pp")
    print("  todas, por ordem de diferença:")
    for x in r["por_indicador"][:4]:
        print(f"  {x['titulo'][:42]:42s} transformadas {x['variacao_transformadas']:+7.1f} % "
              f"· controlo {x['variacao_controlo']:+7.1f} % "
              f"· diferença {x['diferenca']:+7.1f} pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
