"""Junta às fichas o que não vem dos indicadores mensais.

Três acrescentos, cada um a responder a uma limitação real:

  **Mortalidade ajustada ao risco** — remove a cautela que hoje acompanha todos
  os indicadores de qualidade. Ver ingest/mortalidade.py.

  **População servida** — converte contagens em taxas por mil habitantes, sem o
  que um hospital pequeno parece melhor só por ser pequeno. Ver
  ingest/populacao.py.

  **Contratos públicos** — 93% dos 44 015 contratos do Portal BASE resolvem para
  uma unidade do crosswalk. Mostra para onde vai o dinheiro e por que via.

Escreve data/out/enriquecimento.json, que o sítio e o painel juntam às fichas.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ingest"))

import duckdb  # noqa: E402

import impic  # noqa: E402

from common import DIR_BRUTO, DIR_SAIDA, garantir_dirs  # noqa: E402
from contratos import agregar as contratos_impic  # noqa: E402
from contratos import conferir_com_servidor  # noqa: E402
from instituicoes import carregar  # noqa: E402
from mortalidade import calcular as calcular_smr  # noqa: E402
from populacao import inscritos_por_instituicao  # noqa: E402

# As cores da Triagem de Manchester não são uma paleta escolhida: são um código
# clínico com significado fixo, que qualquer pessoa que tenha estado numa
# urgência reconhece da pulseira. Substituí-las por cores «melhores» destruiria
# o significado, por isso ficam como são — e cada segmento leva sempre rótulo,
# porque a cor sozinha nunca basta.
TRIAGEM = [
    ("vermelha", "Vermelho", "emergente", "#e30613"),
    ("laranja", "Laranja", "muito urgente", "#f39200"),
    ("amarela", "Amarelo", "urgente", "#ffed00"),
    ("verde", "Verde", "pouco urgente", "#009640"),
    ("azul", "Azul", "não urgente", "#009fe3"),
    ("branca", "Branco", "sem prioridade", "#f2f2f2"),
]

# Contagens que ganham sentido quando divididas pela população servida.
POR_MIL_HABITANTES = [
    "urgencia-atendimentos",
    "consultas-hospitalares",
    "intervencoes-cirurgicas",
    "consultas-telemedicina",
]

# Ajustes diretos são legais, mas concentrar neles a despesa reduz a
# concorrência. O peso relativo é o que interessa, não o valor absoluto.
AJUSTE_DIRETO = "ajuste direto"


def contratos_por_instituicao(con, cw) -> dict:
    """Contratos por instituição, da melhor fonte disponível.

    Preferimos sempre o registo integral do IMPIC: cobre 2012–2026 contra os
    2024–2026 do espelho, resolve 38 unidades contra 32, e é o único que traz
    as modificações contratuais. O espelho do Portal da Transparência fica como
    reserva, para que o pipeline continue a correr numa máquina onde ainda não
    se descarregou o IMPIC.
    """
    if impic.ficheiros("contratos") and impic.ficheiros("entidades"):
        return contratos_impic(cw)
    print("  IMPIC ausente; a recorrer ao espelho do Portal da Transparência")
    return _contratos_do_espelho(con, cw)


def conferir_contratos(agregado: dict, cw) -> list[dict]:
    """Confere os totais contra o servidor do Portal BASE, quando há token."""
    if not agregado or not impic.ficheiros("entidades"):
        return []
    try:
        return conferir_com_servidor(agregado, cw)
    except Exception as erro:  # a verificação é um extra, nunca um bloqueio
        print(f"  verificação contra o Portal BASE indisponível: {erro}")
        return []


def _contratos_do_espelho(con, cw, desde: str = "2024-01-01") -> dict:
    caminho = DIR_BRUTO / "portal-base.csv.gz"
    if not caminho.exists():
        return {}
    rel = (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1, all_varchar=true)"
    )
    linhas = con.execute(
        f"select entidades_adjudicantes_normalizado, tipo_de_procedimento, "
        f"try_cast(preco_contratual as double), entidades_adjudicatarias_normalizado "
        f"from {rel} where data_de_celebracao_do_contrato >= '{desde}'"
    ).fetchall()

    acc: dict[str, dict] = collections.defaultdict(
        lambda: {"n": 0, "valor": 0.0, "n_ajuste": 0, "valor_ajuste": 0.0,
                 "fornecedores": collections.Counter()}
    )
    for adjudicante, procedimento, preco, adjudicataria in linhas:
        inst = cw.resolver(adjudicante or "")
        if inst is None:
            continue
        a = acc[inst.id]
        a["n"] += 1
        a["valor"] += preco or 0
        if AJUSTE_DIRETO in (procedimento or "").lower():
            a["n_ajuste"] += 1
            a["valor_ajuste"] += preco or 0
        if adjudicataria:
            a["fornecedores"][adjudicataria.split("(")[0].strip()[:60]] += preco or 0

    # A cobertura do Portal BASE por instituição é muito desigual — de 0,01 € a
    # 252 € por utente, um rácio de 8 535×, e 11 unidades sem um único contrato
    # desde 2024. Isso não é variação de despesa: é registo em falta. Sem
    # conseguir distinguir «gasta pouco» de «reporta mal», o total por
    # instituição não é publicável, e é isso que `cobertura_suficiente` declara.
    MIN_CONTRATOS, MIN_VALOR = 50, 1_000_000

    return {
        k: {
            "fonte": "Portal da Transparência do SNS (espelho parcial)",
            "desde": desde[:4],
            "ate": None,
            "por_ano": [],
            "maiores_areas": [],
            "modificacoes": None,
            "cobertura_suficiente": v["n"] >= MIN_CONTRATOS and v["valor"] >= MIN_VALOR,
            "contratos": v["n"],
            "valor": round(v["valor"]),
            "peso_ajuste_direto": round(100 * v["valor_ajuste"] / v["valor"], 1)
            if v["valor"] else None,
            "maiores_fornecedores": [
                {"nome": n, "valor": round(x)}
                for n, x in v["fornecedores"].most_common(5)
            ],
        }
        for k, v in acc.items()
    }


def triagem_nacional(con, cw, meses: int = 12) -> dict:
    """Composição das urgências do país por cor de triagem, último ano móvel."""
    from build import desacumular

    caminho = DIR_BRUTO / "atendimentos-em-urgencia-triagem-manchester.csv.gz"
    if not caminho.exists():
        return {}
    rel = (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1)"
    )

    todos = sorted({
        str(m)[:7] for (m,) in con.execute(f"select distinct tempo from {rel}").fetchall()
    })
    janela = set(todos[-meses:])

    total: dict[str, float] = {}
    for chave, _, _, _ in TRIAGEM:
        coluna = f"no_de_atendimentos_em_urgencia_su_triagem_manchester_{chave}"
        bruto: dict[str, dict[str, float]] = collections.defaultdict(dict)
        for nome, tempo, valor in con.execute(
            f'select instituicao, tempo, "{coluna}" from {rel} '
            "where instituicao is not null"
        ).fetchall():
            bruto[nome][str(tempo)[:7]] = valor or 0
        soma = 0.0
        for nome, serie in bruto.items():
            if cw.resolver(nome) is None:
                continue
            for mes, v in desacumular(serie).items():
                if v is not None and mes in janela:
                    soma += v
        total[chave] = soma

    geral = sum(total.values()) or 1
    return {
        "total": round(geral),
        "periodo": f"{min(janela)} a {max(janela)}",
        "niveis": [
            {
                "id": chave,
                "rotulo": rotulo,
                "significado": significado,
                "cor": cor,
                "valor": round(total[chave]),
                "peso": round(100 * total[chave] / geral, 2),
            }
            for chave, rotulo, significado, cor in TRIAGEM
        ],
    }


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    cw = carregar()

    smr = calcular_smr(con, cw)
    inscritos, _, periodo_pop = inscritos_por_instituicao(con, cw)
    contratos = contratos_por_instituicao(con, cw)
    triagem = triagem_nacional(con, cw)
    verificacao_contratos = conferir_contratos(contratos, cw)

    # Taxas por mil habitantes, a partir das fichas já construídas.
    dir_inst = DIR_SAIDA / "instituicao"
    per_capita: dict[str, dict] = {}
    for ficheiro in sorted(dir_inst.glob("*.json")):
        ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
        pop = inscritos.get(ficha["id"], {}).get("inscritos")
        if not pop:
            continue
        taxas = {}
        for iid in POR_MIL_HABITANTES:
            d = ficha["indicadores"].get(iid)
            if d and d.get("valor") is not None:
                taxas[iid] = round(1000 * d["valor"] / pop, 1)
        if taxas:
            per_capita[ficha["id"]] = {"populacao": pop, "por_mil": taxas}

    saida = DIR_SAIDA / "enriquecimento.json"
    saida.write_text(
        json.dumps(
            {
                "mortalidade_ajustada": smr,
                "populacao": {
                    "periodo": periodo_pop,
                    "por_instituicao": inscritos,
                },
                "per_capita": per_capita,
                "contratos": contratos,
                "contratos_verificacao": verificacao_contratos,
                "triagem_nacional": triagem,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"mortalidade ajustada: {len(smr['smr'])} unidades com SMR, "
          f"{len(smr['instituicoes_sem_smr'])} excluídas por registo não fiável")
    print(f"população: {len(inscritos)} unidades, "
          f"{sum(v['inscritos'] for v in inscritos.values()):,} utentes inscritos")
    print(f"taxas per capita: {len(per_capita)} unidades")
    if contratos:
        amostra = next(iter(contratos.values()))
        publicaveis = sum(1 for v in contratos.values() if v["cobertura_suficiente"])
        print(
            f"contratos ({amostra['fonte']}) {amostra['desde']}–{amostra['ate']}: "
            f"{len(contratos)} unidades, {publicaveis} publicáveis, "
            f"{sum(v['valor'] for v in contratos.values()) / 1e6:,.0f} M€"
        )
        alterados = [v["modificacoes"] for v in contratos.values() if v["modificacoes"]]
        if alterados:
            print(
                f"  modificados depois de assinados: "
                f"{sum(m['contratos_modificados'] for m in alterados):,} contratos, "
                f"{sum(m['acrescimo'] for m in alterados) / 1e6:+,.0f} M€"
            )
    if verificacao_contratos:
        pior = max(verificacao_contratos, key=lambda l: abs(l["desvio_pct"] or 0))
        print(
            f"  conferido contra o Portal BASE em {len(verificacao_contratos)} unidades; "
            f"maior desvio {pior['desvio_pct']:+.1f}% ({pior['instituicao']})"
        )
    pesos = [v["peso_ajuste_direto"] for v in contratos.values() if v["peso_ajuste_direto"]]
    if pesos:
        pesos.sort()
        print(f"  peso do ajuste direto: mediana {pesos[len(pesos) // 2]:.0f} %, "
              f"máximo {pesos[-1]:.0f} %")
    if triagem:
        maior = max(triagem["niveis"], key=lambda x: x["peso"])
        print(f"triagem: {triagem['total']:,} atendimentos; "
              f"maior nível {maior['rotulo']} com {maior['peso']:.1f} %")
    print(f"escrito em {saida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
