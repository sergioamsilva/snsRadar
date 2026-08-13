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


def doente_padrao_por_instituicao(cw, anos: int = 3) -> dict[str, dict]:
    """Produção ajustada à complexidade, por unidade, nos últimos anos.

    O «doente padrão» é a métrica com que a ACSS converte atividade heterogénea
    — internamentos, consultas, urgências, ambulatório — numa unidade única de
    produção. Aqui serve um propósito que a ACSS não lhe dá: pôr os contratos
    públicos numa escala comparável.

    Sem ele, o que o snsRadar sabia dizer sobre compras era o valor absoluto (um
    hospital central compra mais do que uma unidade local — e depois?) ou o
    valor por habitante inscrito (que ignora quem trata doentes de fora e quem
    trata casos complexos). Por doente padrão, a pergunta passa a ser a certa:
    quanto custa comprar por unidade de produção ajustada.

    Vem do denominador dos gastos operacionais por doente padrão, que é a série
    de doente padrão que a ACSS exporta mês a mês.
    """
    caminho = DIR_BRUTO / "bh-acss-cust-opr-doente-padrao-sncap.csv.gz"
    if not caminho.exists():
        return {}

    import csv
    import gzip

    limite = None
    linhas: list[tuple[str, str, float]] = []
    with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            try:
                dp = float(linha["denominador"])
            except (TypeError, ValueError):
                continue
            # Um doente padrão negativo é uma correção contabilística lançada
            # num mês, não produção. Somá-la subtrairia atividade que existiu.
            if dp <= 0:
                continue
            inst = cw.resolver(linha["instituicao"])
            if inst is None:
                continue
            mes = linha["tempo"][:7]
            limite = max(limite or mes, mes)
            linhas.append((inst.id, mes, dp))

    if not limite:
        return {}
    primeiro = f"{int(limite[:4]) - anos + 1}-01"

    saida: dict[str, dict] = {}
    for inst_id, mes, dp in linhas:
        if mes < primeiro:
            continue
        alvo = saida.setdefault(inst_id, {"doente_padrao": 0.0, "meses": set()})
        alvo["doente_padrao"] += dp
        alvo["meses"].add(mes)

    return {
        k: {
            "doente_padrao": round(v["doente_padrao"]),
            "meses": len(v["meses"]),
            "de": min(v["meses"]),
            "a": max(v["meses"]),
        }
        for k, v in saida.items()
        if len(v["meses"]) >= 12
    }


def compras_por_doente_padrao(contratos: dict, doente_padrao: dict) -> dict:
    """Junta o registo de contratos do IMPIC à produção ajustada da ACSS.

    Duas fontes que nunca se encontraram: uma é o registo de contratação
    pública, a outra é o painel de benchmarking hospitalar. O único sítio onde
    se tocam é a entidade canónica do crosswalk.

    Só se calcula sobre o mesmo período de que há doente padrão — comparar
    catorze anos de contratos com três de produção daria um número sem sentido.
    """
    saida = {}
    for inst_id, dp in doente_padrao.items():
        c = contratos.get(inst_id)
        if not c or not c.get("cobertura_suficiente"):
            continue
        anos = {a["ano"] for a in c.get("por_ano", [])} & {
            str(x) for x in range(int(dp["de"][:4]), int(dp["a"][:4]) + 1)
        }
        valor = sum(a["valor"] for a in c.get("por_ano", []) if a["ano"] in anos)
        if not valor or not dp["doente_padrao"]:
            continue
        saida[inst_id] = {
            "valor_contratado": round(valor),
            "doente_padrao": dp["doente_padrao"],
            "euros_por_doente_padrao": round(valor / dp["doente_padrao"], 1),
            "periodo": f"{min(anos)}..{max(anos)}",
            "anos": len(anos),
        }
    return saida


def poupancas_estimadas(cw) -> dict[str, dict]:
    """O que a ACSS estima que cada unidade pouparia igualando o melhor do grupo.

    É uma afirmação da ACSS, não do snsRadar, e a distinção não é formalidade:
    o cálculo assume que a instituição mais eficiente do grupo é um alvo
    atingível para as outras, e isso é uma escolha de política — não um facto
    que os dados imponham. Aqui reproduz-se com a atribuição à vista.

    Três ressalvas, todas da própria ACSS ou verificáveis no ficheiro:

      · **Não é cumulativa.** A exportação traz poupanças estimadas para várias
        tipologias de custo, e somá-las contaria a mesma poupança várias vezes.
        Fica só a dos gastos operacionais, que é o total.
      · **Refletem posicionamento, não desperdício.** A ACSS escreve-o na sua
        abordagem metodológica: são indicativas.
      · **A unidade mais eficiente do grupo tem poupança zero por construção.**
        Não quer dizer que não tenha margem; quer dizer que é o metro.

    E uma quarta, que é da fonte e não do método: **a ACSS deixou de calcular
    isto para as ULS.** Até 2023 publicava as poupanças estimadas para 34
    unidades; a partir de 2024 só para os três institutos de oncologia — os
    únicos que a reforma não transformou. A própria abordagem metodológica da
    ACSS avisa que, com a integração dos cuidados primários, os indicadores
    económico-financeiros deixaram de ser comparáveis com os anos anteriores.

    Por isso publica-se o último ano em que o cálculo cobriu o sistema, e
    não o mais recente: um valor apurado em três unidades não descreve o país.
    O ano vai no próprio texto, porque três anos é tempo que chegue para o
    leitor merecer sabê-lo.
    """
    caminho = DIR_BRUTO / "bh-acss-_anual.csv.gz"
    if not caminho.exists():
        return {}

    import csv
    import gzip

    INDICADOR = "Cust_Opr_Doente_Padrao_SNCAP"
    linhas = []
    with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            if linha["indicador"] != INDICADOR or not linha["extra_g"]:
                continue
            linhas.append(linha)
    if not linhas:
        return {}

    # O último dezembro em que o cálculo cobre o sistema, e não o último
    # dezembro. Cobrir o sistema é, aqui, ter mais de metade das unidades que
    # alguma vez tiveram este cálculo.
    por_dezembro: dict[str, int] = {}
    for l in linhas:
        if l["tempo"][5:7] == "12":
            por_dezembro[l["tempo"][:7]] = por_dezembro.get(l["tempo"][:7], 0) + 1
    if not por_dezembro:
        return {}
    cobertura_maxima = max(por_dezembro.values())
    completos = [m for m, n in por_dezembro.items() if n >= cobertura_maxima * 0.5]
    if not completos:
        return {}
    periodo = max(completos)
    descontinuado = max(por_dezembro) if max(por_dezembro) != periodo else None

    def numero(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    saida = {}
    for linha in linhas:
        if linha["tempo"][:7] != periodo:
            continue
        inst = cw.resolver(linha["instituicao"])
        if inst is None:
            continue
        poupanca = numero(linha["extra_g"])
        resultado = numero(linha["extra_h"])
        potencial = numero(linha["extra_i"])
        if poupanca is None:
            continue
        saida[inst.id] = {
            "ano": periodo[:4],
            "grupo": linha["grupo"],
            "poupanca_estimada": round(poupanca),
            "resultado_operacional": round(resultado) if resultado is not None else None,
            "resultado_potencial": round(potencial) if potencial is not None else None,
            "fonte": "ACSS, Benchmarking Hospitalar — dimensão Económico-Financeira",
            # Preenchido quando a ACSS continua a publicar o cálculo, mas só
            # para uma minoria de unidades. Diz ao leitor que o número que está
            # a ver é o último que descreveu o sistema, não o último que existe.
            "descontinuado_desde": descontinuado,
        }
    return saida


def indice_seguranca(fichas: list[dict]) -> dict[str, dict]:
    """Resume os seis indicadores de segurança do doente num só número.

    Cada indicador é um acontecimento raro com denominadores muito desiguais, e
    é por isso que a ficha os desenha em funil: a pergunta não é «qual é a
    taxa», é «este valor distingue-se do acaso». O resumo aplica a mesma régua a
    todos e faz a média:

        z = (p − θ) / √(θ(1−θ)/n)

    onde θ é a proporção do país. Um z médio de zero é uma unidade indistinguível
    do conjunto; positivo, mais eventos do que o acaso explica.

    Serve para uma pergunta que nenhum indicador responde sozinho: as unidades
    que se destacam na segurança são as mesmas que se destacam na mortalidade
    ajustada ao risco? São dois métodos independentes, e concordarem ou não é,
    em qualquer dos casos, informação.
    """
    import math

    ids = [
        iid
        for iid in (
            "ulceras-pressao",
            "infecao-cateter-venoso-central",
            "sepsis-pos-operatoria",
            "embolia-trombose-pos-operatoria",
            "laceracoes-parto-instrumentado",
            "laceracoes-parto-nao-instrumentado",
        )
        if any(iid in f["indicadores"] for f in fichas)
    ]

    zs: dict[str, list[float]] = collections.defaultdict(list)
    for iid in ids:
        pontos = [
            (f["id"], f["indicadores"][iid]["numerador"], f["indicadores"][iid]["denominador"])
            for f in fichas
            if iid in f["indicadores"] and f["indicadores"][iid].get("denominador")
        ]
        total_den = sum(d for _, _, d in pontos)
        total_num = sum(n for _, n, _ in pontos)
        if not total_den:
            continue
        theta = total_num / total_den
        for inst_id, num, den in pontos:
            se = math.sqrt(theta * (1 - theta) / den) if den else 0
            if se:
                zs[inst_id].append((num / den - theta) / se)

    return {
        inst_id: {
            "z_medio": round(sum(v) / len(v), 2),
            "n_indicadores": len(v),
            # Fora do funil de 99,8 % — o mesmo limiar que a ficha desenha.
            "fora_do_funil": sum(1 for z in v if abs(z) > 3.09),
        }
        for inst_id, v in zs.items()
        if len(v) >= 3
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
    doente_padrao = doente_padrao_por_instituicao(cw)
    poupancas = poupancas_estimadas(cw)
    compras = compras_por_doente_padrao(contratos, doente_padrao)

    # Taxas por mil habitantes, a partir das fichas já construídas.
    dir_inst = DIR_SAIDA / "instituicao"
    todas_fichas = [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(dir_inst.glob("*.json"))
    ]
    seguranca = indice_seguranca(todas_fichas)
    per_capita: dict[str, dict] = {}
    for ficha in todas_fichas:
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
                "compras_por_doente_padrao": compras,
                "indice_seguranca": seguranca,
                "poupancas_estimadas": poupancas,
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
    if poupancas:
        tot = sum(v["poupanca_estimada"] for v in poupancas.values())
        ano = next(iter(poupancas.values()))["ano"]
        desc = next(iter(poupancas.values()))["descontinuado_desde"]
        print(f"poupanças estimadas pela ACSS em {ano}: {len(poupancas)} unidades, "
              f"{tot / 1e6:,.0f} M€ no conjunto"
              + (f" — a fonte deixou de as calcular para as ULS (último: {desc})"
                 if desc else ""))
    if seguranca:
        fora = sum(1 for v in seguranca.values() if v["fora_do_funil"])
        print(f"índice de segurança: {len(seguranca)} unidades; "
              f"{fora} com pelo menos um indicador fora do funil")
    if compras:
        vals = sorted(v["euros_por_doente_padrao"] for v in compras.values())
        print(f"compras por doente padrão: {len(compras)} unidades, "
              f"mediana {vals[len(vals) // 2]:,.0f} € por doente padrão "
              f"({vals[0]:,.0f} a {vals[-1]:,.0f})")
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
