"""Transforma os dados brutos nas fichas de instituição.

Produz:
    data/out/instituicoes.json          índice de entidades para a homepage
    data/out/nacional.json              agregado nacional por indicador
    data/out/instituicao/<id>.json      ficha completa de cada instituição

Regras impostas aqui, não apenas documentadas:
  - Uma taxa é sempre soma(numerador) / soma(denominador). Nunca a média de
    percentagens mensais.
  - Um denominador abaixo de LIMIAR_DENOMINADOR não gera taxa.
  - Meses em falta são lacunas, não zeros.
  - Cada valor leva consigo o dataset de origem e a data em que a fonte o
    atualizou.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

import duckdb
import yaml

from common import API, DIR_BRUTO, DIR_REFERENCIA, DIR_SAIDA, garantir_dirs
from catalog import FICHEIRO_CATALOGO
from instituicoes import carregar

# Abaixo deste denominador uma percentagem é ruído: num hospital com 8 partos
# num mês, uma cesariana a mais move a taxa 12 pontos.
LIMIAR_DENOMINADOR = 20

# Um ano móvel: janela de referência das fichas.
MESES_JANELA = 12

# Quantos zeros exatos seguidos bastam para deixar de os ler como resultado.
# Ver `_zeros_nao_apurados`. Seis meses: menos do que isso ainda cabe no acaso
# de uma unidade pequena; a partir daí, e vindo de uma série que reportava
# valores, o que mudou foi o reporte, não a mortalidade.
MESES_ZERO_SUSPEITO = 6


def _rel(dataset_id: str) -> str:
    caminho = DIR_BRUTO / f"{dataset_id}.csv.gz"
    return (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1)"
    )


def _soma(coluna: str, extras: list[str]) -> str:
    """Expressão SQL que soma uma coluna e, opcionalmente, outras com ela."""
    colunas = [coluna, *extras]
    return " + ".join(f'coalesce("{c}", 0)' for c in colunas)


# Um mês cujo volume nacional caia abaixo desta fração da mediana está a ser
# preenchido, não é um mês de baixa atividade. É o mesmo limiar que
# ingest/mortalidade.py usa para os internamentos.
LIMIAR_COMPLETUDE = 0.80


def _meses_incompletos(bruto_num: dict, bruto_den: dict | None) -> set[str]:
    """Meses em que a fonte ainda não terminou de reportar.

    Descoberto no registo de antibióticos: em outubro e novembro de 2025 o
    numerador manteve-se nos 22–24 mil DDD habituais, mas o denominador — o
    consumo dos restantes antibióticos — caiu de 380 mil para 214 mil. O peso
    dos carbapenemes saltava assim de 5,8 % para 9,5 %, e o IPO do Porto
    aparecia com um pico de 33,7 % que não corresponde a nada de clínico.

    A deteção é feita sobre o **volume total** (numerador mais denominador,
    quando existe), porque é aí que o défice se vê: um denominador incompleto
    com numerador completo não se distingue olhando só para o numerador.
    """
    volume_por_mes: dict[str, float] = defaultdict(float)
    for nome, meses in bruto_num.items():
        for mes, v in meses.items():
            volume_por_mes[mes] += v or 0
    if bruto_den is not None:
        for nome, meses in bruto_den.items():
            for mes, v in meses.items():
                volume_por_mes[mes] += v or 0

    if len(volume_por_mes) < 12:
        return set()
    ordenados = sorted(volume_por_mes.values())
    limiar = ordenados[len(ordenados) // 2] * LIMIAR_COMPLETUDE
    return {mes for mes, v in volume_por_mes.items() if v < limiar}


def carregar_indicadores() -> list[dict]:
    return yaml.safe_load(
        (DIR_REFERENCIA / "indicadores.yaml").read_text(encoding="utf-8")
    )


def _dias_do_mes(mes: str) -> int:
    import calendar

    ano, m = int(mes[:4]), int(mes[5:7])
    return calendar.monthrange(ano, m)[1]


def desacumular(valores_por_mes: dict[str, float]) -> dict[str, float | None]:
    """Converte uma série acumulada no ano em fluxos mensais.

    A maioria dos datasets do portal publica o acumulado desde janeiro, não o
    valor do mês: em 2025, a ULS de Coimbra aparece com 394 partos em janeiro,
    759 em fevereiro, 1160 em março. Somar os doze meses daria cinco vezes o
    número real de partos.

    Devolve None no mês em que a diferença não é fiável — quando falta o mês
    anterior, ou quando a fonte reviu o acumulado em baixa e a diferença sairia
    negativa. Um valor em falta é preferível a um valor inventado.
    """
    saida: dict[str, float | None] = {}
    por_ano: dict[str, list[str]] = defaultdict(list)
    for mes in valores_por_mes:
        por_ano[mes[:4]].append(mes)

    for ano, meses in por_ano.items():
        meses.sort()
        anterior_mes = None
        for mes in meses:
            m = int(mes[5:7])
            if m == 1:
                saida[mes] = valores_por_mes[mes]
            elif anterior_mes is not None and int(anterior_mes[5:7]) == m - 1:
                delta = valores_por_mes[mes] - valores_por_mes[anterior_mes]
                saida[mes] = delta if delta >= 0 else None
            else:
                # Sem o mês imediatamente anterior não há forma honesta de
                # isolar o fluxo deste mês a partir do acumulado.
                saida[mes] = None
            anterior_mes = mes
    return saida


def _rotulos_duplicados(cw, bruto: dict[str, dict[str, float]]) -> set[str]:
    """Deteta dois rótulos da fonte que são a mesma unidade contada duas vezes.

    O Hospital de Loures aparece simultaneamente como «Hospital de Loures, EPE»
    e «Hospital de Loures, PPP», com valores idênticos, de janeiro de 2013 a
    dezembro de 2021. Somar os dois duplicaria toda a história do hospital.

    Só descartamos quando as séries coincidem *exatamente* em pelo menos três
    meses sobrepostos: duas instituições diferentes podem ter o mesmo valor num
    mês por acaso, mas não durante um trimestre inteiro. Fica o rótulo com
    série mais longa.
    """
    por_entidade: dict[str, list[str]] = defaultdict(list)
    for nome in bruto:
        inst = cw.resolver(nome)
        if inst is not None:
            por_entidade[inst.id].append(nome)

    descartar: set[str] = set()
    for nomes in por_entidade.values():
        if len(nomes) < 2:
            continue
        nomes = sorted(nomes, key=lambda n: (-len(bruto[n]), n))
        for i, a in enumerate(nomes):
            if a in descartar:
                continue
            for b in nomes[i + 1:]:
                if b in descartar:
                    continue
                comuns = bruto[a].keys() & bruto[b].keys()
                if len(comuns) >= 3 and all(
                    bruto[a][m] == bruto[b][m] for m in comuns
                ):
                    descartar.add(b)
    return descartar


def extrair_series(con, cw, indicadores, catalogo) -> dict:
    """Constrói (indicador, instituicao, mês) -> {numerador, denominador}.

    É a tabela de que tudo o resto deriva. Guardamos numerador e denominador
    separados de propósito: é o que permite agregar taxas corretamente mais à
    frente, em vez de voltar a somar percentagens.

    A des-acumulação acontece por *nome de origem*, antes de somar na entidade
    canónica: cada instituição que veio a ser fundida publicava a sua própria
    série acumulada, e subtrair meses depois de as juntar daria lixo.
    """
    series: dict = defaultdict(lambda: defaultdict(dict))
    nomes_fonte: dict = defaultdict(set)

    for ind in indicadores:
        dataset_id = ind["dataset"]
        col_ent = ind.get("coluna_entidade", "instituicao")
        col_tempo = ind.get("coluna_tempo", "tempo")

        num = _soma(ind["numerador"], ind.get("soma_tambem", []))
        den_col = ind.get("denominador")
        den = (
            _soma(den_col, ind.get("denominador_soma_tambem", []))
            if den_col
            else "NULL"
        )

        # `count` do numerador principal distingue «zero» de «não reportado».
        # Sem isto, o coalesce(...,0) transformava em zero um mês que a fonte
        # deixou vazio — e a mortalidade por AVC do Alentejo aparecia a 0,0 %
        # em cinco meses seguidos, logo a seguir a 11,5 %.
        linhas = con.execute(
            f'select "{col_ent}", "{col_tempo}", sum({num}), sum({den}), '
            f'count("{ind["numerador"]}") '
            f"from {_rel(dataset_id)} "
            f'where "{col_ent}" is not null and "{col_tempo}" is not null '
            f"group by 1, 2"
        ).fetchall()

        bruto_num: dict[str, dict[str, float]] = defaultdict(dict)
        bruto_den: dict[str, dict[str, float]] = defaultdict(dict)
        for nome, periodo, numerador, denominador, n_reportado in linhas:
            mes = str(periodo)[:7]
            if len(mes) != 7:
                continue
            # Um mês sem qualquer valor reportado é uma lacuna, não um zero.
            if not n_reportado:
                continue
            bruto_num[nome][mes] = numerador or 0
            if den_col:
                bruto_den[nome][mes] = denominador or 0

        descartados = _rotulos_duplicados(cw, bruto_num)
        for nome in descartados:
            bruto_num.pop(nome, None)
            bruto_den.pop(nome, None)

        if ind.get("exigir_mes_completo"):
            for mes in _meses_incompletos(bruto_num, bruto_den if den_col else None):
                for nome in bruto_num:
                    bruto_num[nome].pop(mes, None)
                    bruto_den.get(nome, {}).pop(mes, None)

        for nome in bruto_num:
            inst = cw.resolver(nome)
            if inst is None:
                continue
            nomes_fonte[(ind["id"], inst.id)].add(nome)

            vals_num = (
                desacumular(bruto_num[nome])
                if ind.get("acumulado_no_ano")
                else bruto_num[nome]
            )
            if den_col:
                vals_den = (
                    desacumular(bruto_den[nome])
                    if ind.get("denominador_acumulado_no_ano",
                               ind.get("acumulado_no_ano"))
                    else bruto_den[nome]
                )
            else:
                vals_den = {}

            for mes, v_num in vals_num.items():
                if v_num is None:
                    continue
                if den_col:
                    v_den = vals_den.get(mes)
                    if v_den is None:
                        continue
                    if ind.get("denominador_x_dias_do_mes"):
                        v_den = v_den * _dias_do_mes(mes)
                else:
                    v_den = 0.0

                alvo = series[ind["id"]][inst.id].setdefault(
                    mes,
                    {"num": 0.0, "den": 0.0, "tem_den": bool(den_col), "n_rotulos": 0},
                )
                alvo["num"] += v_num
                alvo["den"] += v_den
                alvo["n_rotulos"] += 1

        # Uma taxa ou uma média não se soma entre as entidades que vieram a ser
        # fundidas: 115 + 193 + 8 não é um prazo médio de pagamento. Nestes
        # casos fazemos a média entre os rótulos. É uma aproximação — o correto
        # seria ponderar pelos volumes, que a fonte não publica — mas é a única
        # síntese defensável, e muito melhor do que uma soma sem sentido.
        if _nao_somavel(ind):
            for meses in series[ind["id"]].values():
                for d in meses.values():
                    if d["n_rotulos"] > 1:
                        d["num"] /= d["n_rotulos"]

    return series, nomes_fonte


def _nao_somavel(ind: dict) -> bool:
    """True quando somar o indicador entre instituições não faz sentido."""
    if ind.get("ja_e_taxa"):
        return True
    return ind["unidade"] == "dias" and not ind.get("denominador")


def _valor(ind: dict, num: float, den: float | None) -> float | None:
    """Aplica a regra de agregação. Devolve None quando não é apresentável."""
    if ind.get("ja_e_taxa"):
        return num
    if not ind.get("denominador"):
        return num
    if den is None or den < LIMIAR_DENOMINADOR:
        return None
    v = 100.0 * num / den if ind["unidade"] == "percentagem" else num / den
    # Um valor acima do máximo fisicamente plausível diz que o denominador está
    # errado, não que a unidade atingiu aquele desempenho. Ver
    # `maximo_plausivel` em reference/indicadores.yaml.
    teto = ind.get("maximo_plausivel")
    if teto is not None and v > teto:
        return None
    return v


def _zeros_nao_apurados(ind: dict, meses: dict, janela: list[str]) -> list[str]:
    """Os meses em que o 0,0 da fonte é lacuna, não resultado.

    Nos indicadores em que a fonte publica só a taxa — sem numerador nem
    denominador que permitam desmentir o número — um mês não apurado sai como
    `0.0`, indistinguível de um mês sem mortes. A ULS de São José reportou
    entre 8 % e 18 % de mortalidade por AVC durante 144 meses e, a partir de
    2025, dezasseis zeros exatos seguidos: não foi a mortalidade que caiu a
    pique, foi o reporte que parou na transição para ULS. Publicado como está,
    o zero aparece na ficha como o melhor resultado do país.

    A assinatura de uma falha de reporte é um degrau: uma corrida longa de
    zeros exatos logo a seguir a meses que vinham a reportar valores. Três
    condições, todas necessárias:

    - a corrida tem pelo menos MESES_ZERO_SUSPEITO meses — abaixo disso ainda
      cabe no acaso de uma unidade com poucos casos;
    - os meses imediatamente anteriores reportavam (mediana acima de zero) —
      quem nunca reportou outra coisa pode estar mesmo a zero;
    - a corrida toca a janela em publicação — a lacuna que ainda dura é a que
      falseia um número exposto. Zeros antigos ficam como a fonte os escreveu:
      não se reescreve história que já não se consegue arbitrar.

    Devolve os meses a tratar como não apurados, para que o resto do módulo os
    veja como lacuna, que é a regra da casa: meses em falta são lacunas, não
    zeros.
    """
    if not ind.get("ja_e_taxa") or not janela:
        return []

    ordem = sorted(meses)
    fora: list[str] = []
    i = 0
    while i < len(ordem):
        if meses[ordem[i]]["num"] != 0:
            i += 1
            continue
        fim = i
        while fim + 1 < len(ordem) and meses[ordem[fim + 1]]["num"] == 0:
            fim += 1
        corrida = ordem[i:fim + 1]
        antes = [meses[m]["num"] for m in ordem[max(0, i - MESES_JANELA):i]]
        if (
            len(corrida) >= MESES_ZERO_SUSPEITO
            and antes
            and statistics.median(antes) > 0
            and corrida[-1] >= janela[0]
        ):
            fora.extend(corrida)
        i = fim + 1
    return fora


def _agregar(ind: dict, meses: dict, janela: list[str]) -> dict | None:
    """Agrega os meses da janela num único valor, segundo o tipo do indicador."""
    presentes = [m for m in janela if m in meses]
    if not presentes:
        return None

    if ind.get("ja_e_taxa"):
        # Taxa que a fonte publica já calculada, sem volumes. Tomar o último
        # mês punha o valor à mercê do que a fonte escreveu por último — e a
        # fonte escreve 0,0 nos meses ainda não apurados: em janeiro de 2026 os
        # zeros exatos saltaram de 1 unidade para 10. A mediana da janela é
        # robusta a esses zeros e ao ruído de um mês isolado.
        vals = sorted(meses[m]["num"] for m in presentes)
        return {
            "valor": vals[len(vals) // 2],
            "numerador": vals[len(vals) // 2],
            "denominador": None,
            "periodo": f"{min(presentes)}..{max(presentes)}",
            "meses_usados": len(presentes),
            "sintese_temporal": "mediana dos meses",
        }

    if ind.get("agregacao_temporal") == "ultimo":
        # Saldos e efetivos: somá-los ao longo do tempo contaria a mesma dívida
        # ou o mesmo trabalhador vezes sem conta.
        ultimo = max(presentes)
        d = meses[ultimo]
        return {
            "valor": _valor(ind, d["num"], d["den"] if d["tem_den"] else None),
            "numerador": d["num"],
            "denominador": d["den"] if d["tem_den"] else None,
            "periodo": ultimo,
            "meses_usados": 1,
        }

    num = sum(meses[m]["num"] for m in presentes)
    den = sum(meses[m]["den"] for m in presentes) if ind.get("denominador") else None
    return {
        "valor": _valor(ind, num, den),
        "numerador": num,
        "denominador": den,
        "periodo": f"{min(presentes)}..{max(presentes)}",
        "meses_usados": len(presentes),
        "meses_em_falta": [m for m in janela if m not in meses],
    }


def _url_fonte(ind: dict, nomes: set[str]) -> str:
    """URL da API que reproduz o número apresentado.

    A prova de cada valor. Usa os nomes que a fonte deu à instituição ao longo
    do tempo — que é precisamente o que o crosswalk resolve.
    """
    col_ent = ind.get("coluna_entidade", "instituicao")
    condicao = " or ".join(f'{col_ent}:"{n}"' for n in sorted(nomes))
    num = ind["numerador"]
    select = f"sum({num}) as numerador"
    if ind.get("denominador"):
        select += f", sum({ind['denominador']}) as denominador"
    from urllib.parse import quote
    return (
        f"{API}/catalog/datasets/{ind['dataset']}/records"
        f"?select={quote(select)}&where={quote(condicao)}&limit=1"
    )


def _faixa_nacional(ind: dict, series_ind: dict, meses: list[str]) -> list[dict]:
    """Percentis 25, 50 e 75 entre as unidades, mês a mês.

    É o que falta a uma linha isolada: sozinha, a série de um hospital é uma
    ondulação sem referência. Contra a faixa onde vive metade do país, passa a
    responder à pergunta que o leitor tem — «isto é normal?».
    """
    saida = []
    for mes in meses:
        vals = []
        for por_mes in series_ind.values():
            d = por_mes.get(mes)
            if d is None:
                continue
            v = _valor(ind, d["num"], d["den"] if d["tem_den"] else None)
            if v is not None and not (v != v):  # exclui NaN
                vals.append(v)
        # Abaixo de cinco unidades os quartis são ruído, não distribuição.
        if len(vals) < 5:
            continue
        vals.sort()
        q = lambda f: vals[min(int(f * len(vals)), len(vals) - 1)]
        saida.append({"mes": mes, "p25": round(q(0.25), 3),
                      "p50": round(q(0.50), 3), "p75": round(q(0.75), 3)})
    return saida


def construir(con, cw, indicadores, catalogo):
    series, nomes_fonte = extrair_series(con, cw, indicadores, catalogo)

    # Janela: os últimos MESES_JANELA meses com dados, por indicador. Calculada
    # antes da limpeza dos zeros, e não depois: a janela é o calendário da
    # fonte, e uma instituição que deixou de reportar não deve encolhê-lo para
    # as outras.
    janelas = {}
    for ind in indicadores:
        todos = sorted({m for inst in series[ind["id"]].values() for m in inst})
        janelas[ind["id"]] = todos[-MESES_JANELA:] if todos else []

    # Os zeros que são lacunas saem aqui, antes de tudo o resto: assim a série,
    # a mediana nacional e a faixa de percentis veem uma lacuna e não um zero,
    # sem que cada uma delas tenha de repetir a regra.
    retirados: dict[tuple[str, str], list[str]] = {}
    for ind in indicadores:
        for inst_id, meses in series[ind["id"]].items():
            fora = _zeros_nao_apurados(ind, meses, janelas[ind["id"]])
            if not fora:
                continue
            retirados[(ind["id"], inst_id)] = fora
            for m in fora:
                del meses[m]
    for (iid_z, inst_z), fora in sorted(retirados.items()):
        print(f"  zeros não apurados: {inst_z} · {iid_z} · "
              f"{len(fora)} meses ({min(fora)} a {max(fora)})")

    por_indicador = {i["id"]: i for i in indicadores}
    fichas: dict[str, dict] = {}
    nacional: dict[str, dict] = {}

    for ind in indicadores:
        iid = ind["id"]
        janela = janelas[iid]
        valores_inst = {}

        for inst_id, meses in series[iid].items():
            agg = _agregar(ind, meses, janela)
            fora = retirados.get((iid, inst_id), [])
            if agg is None and not fora:
                continue
            if agg is None:
                # A janela inteira era feita de zeros não apurados. O cartão
                # fica, sem valor e com a nota: desaparecer em silêncio
                # esconderia que a fonte parou de reportar, que é a única
                # coisa que aqui se sabe.
                agg = {
                    "valor": None,
                    "numerador": 0.0,
                    "denominador": None,
                    "periodo": f"{janela[0]}..{janela[-1]}" if janela else None,
                    "meses_usados": 0,
                    "sintese_temporal": "mediana dos meses",
                }
            if fora:
                agg["nao_apurado"] = {
                    "meses": len(fora),
                    "de": min(fora),
                    "ate": max(fora),
                }
            agg["fonte"] = {
                "dataset": ind["dataset"],
                "titulo": catalogo.get(ind["dataset"], {}).get("titulo"),
                "publisher": catalogo.get(ind["dataset"], {}).get("publisher"),
                "atualizado": catalogo.get(ind["dataset"], {}).get("modificado"),
                "url": _url_fonte(ind, nomes_fonte[(iid, inst_id)]),
            }
            agg["serie"] = [
                {
                    "mes": m,
                    "valor": _valor(
                        ind, d["num"], d["den"] if d["tem_den"] else None
                    ),
                    "numerador": d["num"],
                    "denominador": d["den"] if d["tem_den"] else None,
                }
                for m, d in sorted(meses.items())
            ]
            fichas.setdefault(inst_id, {})[iid] = agg
            if agg["valor"] is not None:
                valores_inst[inst_id] = agg["valor"]

        # Nacional: soma dos numeradores e dos denominadores já agregados por
        # instituição — não uma nova soma sobre os meses em bruto. É o que
        # respeita `agregacao_temporal: ultimo`: a dívida do país é a soma dos
        # saldos de cada instituição no último mês, não a soma de doze meses de
        # saldos, que contaria a mesma dívida doze vezes.
        agregados = [fichas.get(i, {}).get(iid) for i in series[iid]]
        agregados = [a for a in agregados if a is not None]
        num_nac = sum(a["numerador"] for a in agregados)
        den_nac = (
            sum(a["denominador"] for a in agregados if a["denominador"] is not None)
            if ind.get("denominador")
            else None
        )

        ordenados = sorted(valores_inst.values())
        mediana = ordenados[len(ordenados) // 2] if ordenados else None

        # Uma regra única, partilhada com web/app.js::soMediana. Ter esta
        # decisão em dois sítios com formulações diferentes foi o que produziu
        # 901,9 % de mortalidade por AVC no painel; agora a formulação é a mesma
        # e site/scripts/verificar_coerencia.mjs verifica que assim continua.
        so_mediana = not ind.get("denominador") and ind["unidade"] in ("percentagem", "dias")
        valor_nac = mediana if so_mediana else _valor(ind, num_nac, den_nac)
        todos_meses = sorted({m for inst in series[iid].values() for m in inst})
        nacional[iid] = {
            "faixa": _faixa_nacional(ind, series[iid], todos_meses),
            "titulo": ind["titulo"],
            "grupo": ind["grupo"],
            "unidade": ind["unidade"],
            "polaridade": ind["polaridade"],
            "descricao": ind.get("descricao"),
            "cautela": ind.get("cautela"),
            "referencia": ind.get("referencia"),
            "janela": {"de": janela[0], "a": janela[-1]} if janela else None,
            "valor": valor_nac,
            "sintese": (
                "mediana entre unidades"
                if so_mediana
                else "soma dos numeradores ÷ soma dos denominadores"
                if ind.get("denominador")
                else "soma das instituições"
            ),
            "numerador": num_nac,
            "denominador": den_nac,
            "mediana_instituicoes": mediana,
            "n_instituicoes": len(valores_inst),
        }

    return fichas, nacional, por_indicador


def _enriquecimento() -> dict:
    """Camadas que não vêm dos indicadores mensais: mortalidade ajustada ao
    risco, população servida, taxas per capita e contratos públicos.

    Produzido por ingest/enriquecer.py, que corre depois deste build porque
    precisa das fichas já escritas para calcular as taxas per capita. Na
    primeira execução ainda não existe, e as fichas saem sem ele.
    """
    caminho = DIR_SAIDA / "enriquecimento.json"
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def escrever(cw, fichas, nacional, por_indicador):
    dir_inst = DIR_SAIDA / "instituicao"
    dir_inst.mkdir(parents=True, exist_ok=True)
    extra = _enriquecimento()
    smr = extra.get("mortalidade_ajustada", {})

    indice = []
    for inst in cw.instituicoes:
        if inst.id not in fichas:
            continue
        indicadores_inst = fichas[inst.id]
        ficha = {
            "id": inst.id,
            "nome": inst.nome,
            "nome_curto": inst.nome_curto,
            "regiao": inst.regiao,
            "distrito": inst.distrito,
            "tipo": inst.tipo,
            "nota": inst.nota,
            "descontinuidade": (
                {
                    "data": inst.data_descontinuidade,
                    "e_fusao": inst.e_fusao,
                    "sucessao": [
                        {
                            "data": str(s["data"]),
                            "base_legal": s["base_legal"],
                            "de": s.get("de", []),
                            "nota": s.get("nota"),
                        }
                        for s in inst.sucessao
                    ],
                }
                if inst.sucessao
                else None
            ),
            "mortalidade_ajustada": (
                {
                    **smr.get("smr", {})[inst.id],
                    "metodo": smr.get("metodo"),
                    "periodo": (
                        f"{smr['meses_usados'][0]} a {smr['meses_usados'][-1]}"
                        if smr.get("meses_usados") else None
                    ),
                }
                if inst.id in smr.get("smr", {}) else
                {"indisponivel": smr.get("instituicoes_sem_smr", {}).get(inst.id)}
                if inst.id in smr.get("instituicoes_sem_smr", {}) else None
            ),
            "populacao": extra.get("populacao", {}).get("por_instituicao", {}).get(inst.id),
            "per_capita": extra.get("per_capita", {}).get(inst.id),
            "contratos": extra.get("contratos", {}).get(inst.id),
            "indicadores": {
                iid: {**dados, **{
                    k: por_indicador[iid].get(k)
                    for k in ("titulo", "grupo", "unidade", "polaridade",
                              "descricao", "cautela", "referencia",
                              "pode_exceder_100", "maximo_plausivel")
                }}
                for iid, dados in indicadores_inst.items()
            },
        }
        (dir_inst / f"{inst.id}.json").write_text(
            json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        indice.append(
            {
                "id": inst.id,
                "nome_curto": inst.nome_curto,
                "regiao": inst.regiao,
                "distrito": inst.distrito,
                "tipo": inst.tipo,
                # Coordenadas curadas à mão em reference/instituicoes.yaml. A
                # homepage desenha com elas o mapa do país; sem isto ficariam
                # a servir apenas a ficha individual.
                "geo": inst.geo,
                "n_indicadores": sum(
                    1 for d in indicadores_inst.values() if d["valor"] is not None
                ),
            }
        )

    (DIR_SAIDA / "instituicoes.json").write_text(
        json.dumps(sorted(indice, key=lambda x: x["nome_curto"]),
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DIR_SAIDA / "nacional.json").write_text(
        json.dumps(nacional, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return indice


def main() -> int:
    garantir_dirs()
    con = duckdb.connect()
    cw = carregar()
    indicadores = carregar_indicadores()
    catalogo = json.loads(FICHEIRO_CATALOGO.read_text(encoding="utf-8"))

    fichas, nacional, por_indicador = construir(con, cw, indicadores, catalogo)
    indice = escrever(cw, fichas, nacional, por_indicador)

    print(f"{len(indice)} fichas de instituição escritas em {DIR_SAIDA}")
    print(f"{len(indicadores)} indicadores; nacional.json com "
          f"{sum(1 for v in nacional.values() if v['valor'] is not None)} valores")
    sem_dados = [i.id for i in cw.instituicoes if i.id not in fichas]
    if sem_dados:
        print(f"  {len(sem_dados)} entidades sem indicadores: {', '.join(sem_dados)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
