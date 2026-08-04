"""Mortalidade hospitalar ajustada ao risco.

Calcula a Razão de Mortalidade Padronizada (SMR) por instituição: os óbitos
observados a dividir pelos que seriam de esperar dado o tipo de doentes que o
hospital recebe. É a única forma honesta de comparar mortalidade entre
hospitais — sem isto, um centro oncológico parece sempre pior do que um
hospital de proximidade.

Método: padronização indireta. Para cada estrato (capítulo CID × faixa etária ×
sexo) calcula-se a letalidade nacional, aplica-se ao número de internamentos que
cada hospital teve nesse estrato, e somam-se os óbitos esperados.

    SMR = Σ observados ÷ Σ esperados        SMR > 1 = mais mortes do que o esperado

Duas defesas antes de publicar qualquer número, porque os dados têm defeitos
que produziriam um ranking invertido:

  1. **Atraso de reporte.** Os meses mais recentes estão incompletos — junho de
     2026 traz 6 926 internamentos contra os ~65 000 habituais. Excluem-se os
     meses cujo volume nacional está abaixo de um limiar do normal.

  2. **Falha de registo de óbitos.** Quatro instituições têm a letalidade a cair
     de forma transversal a todos os capítulos CID — na ULS de São José, o
     aparelho circulatório cai 82% e o digestivo 95% entre 2021 e 2025. Não é
     melhoria clínica, é registo em falta. Estas instituições não recebem SMR.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ingest"))

import duckdb  # noqa: E402

from common import DIR_BRUTO, DIR_SAIDA, garantir_dirs  # noqa: E402
from instituicoes import carregar  # noqa: E402

DATASET = "morbilidade_mortalidade_hospit"

# Um mês cujo volume nacional esteja abaixo desta fração da mediana dos meses
# estáveis ainda está a ser preenchido pela fonte.
LIMIAR_COMPLETUDE = 0.80

# Uma letalidade que caia abaixo desta fração da que a instituição tinha no
# primeiro ano é implausível como evolução clínica em quatro anos.
LIMIAR_QUEDA_LETALIDADE = 0.60

# Abaixo deste número de óbitos esperados o SMR é ruído estatístico.
MIN_ESPERADOS = 30


def _rel() -> str:
    caminho = DIR_BRUTO / f"{DATASET}.csv.gz"
    return (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1)"
    )


def meses_completos(con) -> tuple[list[str], list[str]]:
    """Separa os meses utilizáveis dos que a fonte ainda está a preencher."""
    linhas = con.execute(
        f"select periodo, sum(internamentos) from {_rel()} group by 1 order by 1"
    ).fetchall()
    volumes = sorted(v or 0 for _, v in linhas)
    mediana = volumes[len(volumes) // 2]
    limiar = mediana * LIMIAR_COMPLETUDE

    completos = [p for p, v in linhas if (v or 0) >= limiar]
    incompletos = [p for p, v in linhas if (v or 0) < limiar]
    return completos, incompletos


def instituicoes_nao_fiaveis(con, cw) -> dict[str, str]:
    """Instituições cuja letalidade cai de forma que o registo não sustenta.

    Compara a letalidade do primeiro e do último ano completo. Uma queda
    transversal a todos os capítulos é sinal de óbitos por registar, não de
    cuidados melhores.
    """
    linhas = con.execute(
        f"select instituicao, substr(periodo, 1, 4) as ano, "
        f"sum(internamentos), sum(obitos) from {_rel()} "
        f"where periodo < '2026' group by 1, 2"
    ).fetchall()

    por_inst: dict[str, dict[str, tuple[float, float]]] = collections.defaultdict(dict)
    for nome, ano, internos, obitos in linhas:
        por_inst[nome][ano] = (internos or 0, obitos or 0)

    fora: dict[str, str] = {}
    for nome, anos in por_inst.items():
        inst = cw.resolver(nome)
        if inst is None or len(anos) < 3:
            continue
        chaves = sorted(anos)
        primeiro, ultimo = anos[chaves[0]], anos[chaves[-1]]
        if not primeiro[0] or not ultimo[0] or not primeiro[1]:
            continue
        let_ini = primeiro[1] / primeiro[0]
        let_fim = ultimo[1] / ultimo[0]
        if let_fim / let_ini < LIMIAR_QUEDA_LETALIDADE:
            fora[inst.id] = (
                f"letalidade caiu de {100 * let_ini:.1f}% em {chaves[0]} para "
                f"{100 * let_fim:.1f}% em {chaves[-1]}"
            )
    return fora


def calcular(con, cw, periodo_de: str | None = None) -> dict:
    """SMR por instituição, com as duas defesas aplicadas."""
    completos, incompletos = meses_completos(con)
    if periodo_de:
        completos = [m for m in completos if m >= periodo_de]
    nao_fiaveis = instituicoes_nao_fiaveis(con, cw)

    lista = "', '".join(completos)
    linhas = con.execute(
        f"select instituicao, cod_capitulo, faixa_etaria, sexo, "
        f"sum(internamentos), sum(obitos) from {_rel()} "
        f"where periodo in ('{lista}') and sexo <> 'T' group by 1, 2, 3, 4"
    ).fetchall()

    # Letalidade nacional por estrato — a referência contra a qual se compara.
    nacional: dict[tuple, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for _, cap, faixa, sexo, internos, obitos in linhas:
        alvo = nacional[(cap, faixa, sexo)]
        alvo[0] += internos or 0
        alvo[1] += obitos or 0

    obs: dict[str, float] = collections.defaultdict(float)
    esp: dict[str, float] = collections.defaultdict(float)
    intern: dict[str, float] = collections.defaultdict(float)
    for nome, cap, faixa, sexo, internos, obitos in linhas:
        inst = cw.resolver(nome)
        if inst is None or inst.id in nao_fiaveis:
            continue
        n_int, n_obi = nacional[(cap, faixa, sexo)]
        obs[inst.id] += obitos or 0
        esp[inst.id] += (internos or 0) * (n_obi / n_int if n_int else 0)
        intern[inst.id] += internos or 0

    resultados = {}
    for inst_id, esperados in esp.items():
        if esperados < MIN_ESPERADOS:
            continue
        smr = obs[inst_id] / esperados
        # Intervalo de confiança de 95% por aproximação de Byar, adequada a
        # contagens de Poisson. Sem ele, uma diferença de acaso lê-se como facto.
        o = obs[inst_id]
        lo = ((o * (1 - 1 / (9 * o) - 1.96 / (3 * o**0.5)) ** 3) / esperados) if o else 0
        hi = ((o + 1) * (1 - 1 / (9 * (o + 1)) + 1.96 / (3 * (o + 1) ** 0.5)) ** 3) / esperados
        resultados[inst_id] = {
            "smr": round(smr, 3),
            "ic95": [round(lo, 3), round(hi, 3)],
            "observados": round(obs[inst_id]),
            "esperados": round(esperados, 1),
            "internamentos": round(intern[inst_id]),
            # Só se afirma diferença quando o intervalo não contém 1.
            "significativo": lo > 1 or hi < 1,
        }

    return {
        "smr": resultados,
        "meses_usados": completos,
        "meses_excluidos_por_incompletude": incompletos,
        "instituicoes_sem_smr": nao_fiaveis,
        "metodo": (
            "Padronização indireta por capítulo CID, faixa etária e sexo. "
            "SMR = óbitos observados ÷ esperados dada a casuística do hospital. "
            "Intervalo de confiança de 95% pela aproximação de Byar."
        ),
    }


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    cw = carregar()
    r = calcular(con, cw)

    saida = DIR_SAIDA / "mortalidade-ajustada.json"
    saida.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(r['smr'])} instituições com SMR")
    print(f"  {len(r['meses_usados'])} meses usados; "
          f"{len(r['meses_excluidos_por_incompletude'])} excluídos por reporte incompleto:")
    print(f"    {', '.join(r['meses_excluidos_por_incompletude'])}")
    print(f"  {len(r['instituicoes_sem_smr'])} instituições sem SMR por registo de óbitos não fiável:")
    for k, v in r["instituicoes_sem_smr"].items():
        print(f"    {k}: {v}")

    ordenados = sorted(r["smr"].items(), key=lambda x: -x[1]["smr"])
    sig = [x for x in ordenados if x[1]["significativo"]]
    print(f"\n  {len(sig)} com diferença estatisticamente significativa "
          f"(intervalo de 95% não contém 1)")
    print(f"\n  {'instituição':38s} {'SMR':>6s} {'IC 95%':>16s} {'obs':>7s} {'esp':>8s}")
    for inst_id, d in ordenados[:5]:
        i = cw.por_id(inst_id)
        marca = "*" if d["significativo"] else " "
        print(f"  {marca} {i.nome_curto[:36]:36s} {d['smr']:6.2f} "
              f"[{d['ic95'][0]:5.2f};{d['ic95'][1]:5.2f}] {d['observados']:7d} {d['esperados']:8.1f}")
    print("    ...")
    for inst_id, d in ordenados[-4:]:
        i = cw.por_id(inst_id)
        marca = "*" if d["significativo"] else " "
        print(f"  {marca} {i.nome_curto[:36]:36s} {d['smr']:6.2f} "
              f"[{d['ic95'][0]:5.2f};{d['ic95'][1]:5.2f}] {d['observados']:7d} {d['esperados']:8.1f}")
    print(f"\n  escrito em {saida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
