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
import re
import statistics
import sys
from collections import defaultdict

import duckdb
import yaml

from common import API, DIR_BRUTO, DIR_REFERENCIA, DIR_SAIDA, garantir_dirs
from catalog import FICHEIRO_CATALOGO
from benchmarking_acss import FICHEIRO_CATALOGO_ACSS, FICHEIRO_GRUPOS
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


def _data_acss(carimbo: str | None) -> str | None:
    """«27/07/2026 12:40» — o formato em que a ACSS data as suas publicações."""
    if not carimbo:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2}))?", carimbo)
    if not m:
        return None
    dia, mes, ano, hora, minuto = m.groups()
    return f"{ano}-{mes}-{dia}" + (f"T{hora}:{minuto}:00" if hora else "")


def carregar_catalogo() -> dict:
    """O catálogo das duas fontes, na mesma forma.

    O Portal da Transparência e o Benchmarking da ACSS descrevem-se de maneiras
    diferentes — um tem `modificado` em ISO, o outro data as publicações em
    «27/07/2026 12:40». A tradução acontece aqui, uma vez, para que o resto do
    build não tenha de saber de que fonte veio cada indicador.
    """
    catalogo = json.loads(FICHEIRO_CATALOGO.read_text(encoding="utf-8"))
    if not FICHEIRO_CATALOGO_ACSS.exists():
        return catalogo

    for entrada in json.loads(FICHEIRO_CATALOGO_ACSS.read_text(encoding="utf-8")).values():
        catalogo[entrada["slug"]] = {
            "titulo": entrada["titulo"],
            "publisher": entrada.get("publisher", "ACSS"),
            "modificado": _data_acss(entrada.get("publicado_em")),
            # A exportação que reproduz o ficheiro de onde o valor saiu. Ao
            # contrário da API do portal, não se deixa filtrar por instituição:
            # o painel exporta sempre o país inteiro.
            "url": entrada.get("url"),
            "formula": entrada.get("formula"),
            "fonte_declarada": entrada.get("fonte_declarada"),
            "dimensao": entrada.get("dimensao"),
        }
    return catalogo


def carregar_grupos(cw) -> dict:
    """O grupo de comparação de cada entidade canónica.

    A ficha compara sempre com a mediana de todas as unidades, e essa mediana
    junta o IPO do Porto com a ULS da Guarda. A ACSS resolve o mesmo problema
    agrupando as instituições por clustering sobre variáveis explicativas do
    custo, e é esse agrupamento que se lê aqui: um segundo termo de comparação,
    entre pares, ao lado do nacional.

    Os nomes vêm da ACSS e são resolvidos pelo mesmo crosswalk que tudo o resto.
    Um nome que não resolva não é ignorado em silêncio: fica na lista de
    ausências, que o build imprime.
    """
    if not FICHEIRO_GRUPOS.exists():
        return {"por_instituicao": {}, "membros": {}, "definicao": None, "sem_resolucao": []}

    dados = json.loads(FICHEIRO_GRUPOS.read_text(encoding="utf-8"))
    por_instituicao: dict[str, dict] = {}
    sem_resolucao: list[str] = []
    for nome, info in dados.get("por_instituicao", {}).items():
        inst = cw.resolver(nome)
        if inst is None:
            sem_resolucao.append(nome)
            continue
        # Duas grafias da mesma entidade (antes e depois de 2024) trazem o mesmo
        # grupo atual; fica a que declara o ano mais recente.
        anterior = por_instituicao.get(inst.id)
        if anterior and max(anterior["por_ano"]) >= max(info["por_ano"]):
            continue
        por_instituicao[inst.id] = info

    membros: dict[str, list[str]] = defaultdict(list)
    for inst_id, info in por_instituicao.items():
        membros[info["atual"]].append(inst_id)

    return {
        "por_instituicao": por_instituicao,
        "membros": {g: sorted(ids) for g, ids in membros.items()},
        "definicao": dados.get("definicao"),
        "fonte": dados.get("fonte"),
        "sem_resolucao": sorted(sem_resolucao),
    }


def _dias_do_mes(mes: str) -> int:
    import calendar

    ano, m = int(mes[:4]), int(mes[5:7])
    return calendar.monthrange(ano, m)[1]


def desacumular(
    valores_por_mes: dict[str, float], permite_negativo: bool = False
) -> dict[str, float | None]:
    """Converte uma série acumulada no ano em fluxos mensais.

    A maioria dos datasets do portal publica o acumulado desde janeiro, não o
    valor do mês: em 2025, a ULS de Coimbra aparece com 394 partos em janeiro,
    759 em fevereiro, 1160 em março. Somar os doze meses daria cinco vezes o
    número real de partos.

    Devolve None no mês em que a diferença não é fiável — quando falta o mês
    anterior, ou quando a fonte reviu o acumulado em baixa e a diferença sairia
    negativa. Um valor em falta é preferível a um valor inventado.

    `permite_negativo` existe para as grandezas contabilísticas: o EBITDA
    acumulado desce legitimamente de um mês para o outro, e aí a diferença
    negativa É o fluxo do mês, não uma revisão da fonte. Só o declara quem o é
    (`pode_ser_negativa` no YAML); numa contagem, um delta negativo continua a
    ser sinal de revisão e continua a sair None.
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
                saida[mes] = delta if (delta >= 0 or permite_negativo) else None
            else:
                # Sem o mês imediatamente anterior não há forma honesta de
                # isolar o fluxo deste mês a partir do acumulado.
                saida[mes] = None
            anterior_mes = mes
    return saida


def _ecos_pos_fusao(cw, bruto: dict[str, dict[str, float]]) -> set[tuple[str, str]]:
    """Resíduos contabilísticos nos nomes antigos, depois da fusão.

    Nos agregados económico-financeiros, a fonte lançou o fecho de contas de
    2023 nos nomes antecessores — o CHU do Porto tem onze meses a zero e
    36 M€ em dezembro — ao lado da série que já corria no nome novo. Depois
    da última fusão a entidade é uma só: somar o resíduo ao sucessor
    arriscaria dupla contagem, e descartá-lo é a opção conservadora. Só cai
    o mês em que os dois rótulos têm atividade ao mesmo tempo, e fica
    impresso.

    Devolve os pares (nome, mês) a descartar. O rótulo que sobrevive é o de
    série pós-fusão mais longa — o sucessor —, não o de valor maior.
    """
    por_ent: dict[str, list[str]] = defaultdict(list)
    for nome in bruto:
        inst = cw.resolver(nome)
        if inst is not None and inst.data_ultima_fusao:
            por_ent[inst.id].append(nome)

    fora: set[tuple[str, str]] = set()
    for inst_id, nomes in por_ent.items():
        if len(nomes) < 2:
            continue
        fusao = cw.por_id(inst_id).data_ultima_fusao[:7]
        pos = {
            n: {m for m, v in bruto[n].items() if m >= fusao and v}
            for n in nomes
        }
        # A decisão é mês a mês, entre os rótulos ativos NESSE mês: a entidade
        # pode ter mudado de nome outra vez entretanto (CHU do Porto → CHU de
        # Santo António → ULS), e um dominante global nunca se sobreporia ao
        # eco de uma transição anterior.
        meses_conflito = {
            m for n in nomes for m in pos[n]
            if sum(1 for outro in nomes if m in pos[outro]) >= 2
        }
        for mes in sorted(meses_conflito):
            ativos = [n for n in nomes if mes in pos[n]]
            fica = max(ativos, key=lambda n: len(pos[n]))
            for n in ativos:
                if n != fica:
                    fora.add((n, mes))
    return fora


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


def _denominador_externo(con, cw, ind: dict) -> dict[tuple[str, str], float]:
    """Denominador vindo de outro dataset, já resolvido na entidade canónica.

    Existe para uma pergunta que nenhuma fonte responde sozinha: quanto
    antibiótico se consome por dia de internamento. O numerador é do INFARMED, o
    denominador é do registo de ocupação, e os dois só se encontram depois de o
    crosswalk os reduzir à mesma entidade — as duas fontes escrevem os nomes de
    maneiras diferentes, e uma delas nem sequer usa a coluna `instituicao`.

    Devolve (entidade, mês) → denominador, somado entre os rótulos que a fonte
    usa para a mesma unidade.
    """
    dataset = ind["denominador_dataset"]
    col_ent = ind.get("denominador_coluna_entidade", "instituicao")
    col_tempo = ind.get("denominador_coluna_tempo", "tempo")
    coluna = ind["denominador_coluna"]

    linhas = con.execute(
        f'select "{col_ent}", "{col_tempo}", sum(coalesce("{coluna}", 0)), count("{coluna}") '
        f"from {_rel(dataset)} "
        f'where "{col_ent}" is not null and "{col_tempo}" is not null '
        f"group by 1, 2"
    ).fetchall()

    bruto: dict[str, dict[str, float]] = defaultdict(dict)
    for nome, periodo, valor, n_reportado in linhas:
        mes = str(periodo)[:7]
        if len(mes) != 7 or not n_reportado:
            continue
        bruto[nome][mes] = valor or 0

    for nome in _rotulos_duplicados(cw, bruto):
        bruto.pop(nome, None)

    saida: dict[tuple[str, str], float] = defaultdict(float)
    for nome, meses in bruto.items():
        inst = cw.resolver(nome)
        if inst is None:
            continue
        vals = (
            desacumular(meses)
            if ind.get("denominador_acumulado_no_ano")
            else meses
        )
        for mes, v in vals.items():
            if v is None:
                continue
            saida[(inst.id, mes)] += v
    return saida


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

        ecos = _ecos_pos_fusao(cw, bruto_num)
        for nome, mes in ecos:
            bruto_num[nome].pop(mes, None)
            bruto_den.get(nome, {}).pop(mes, None)
        if ecos:
            por_nome: dict[str, list[str]] = defaultdict(list)
            for nome, mes in sorted(ecos):
                por_nome[nome].append(mes)
            for nome, meses_eco in por_nome.items():
                print(f"  eco pós-fusão descartado: {ind['id']} · {nome} · "
                      f"{', '.join(meses_eco)}")

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
                desacumular(bruto_num[nome], ind.get("pode_ser_negativa", False))
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

        # Denominador de outro dataset: entra por atribuição e não por soma, e
        # entra agora — depois de os rótulos da fonte estarem todos somados na
        # entidade canónica. Somá-lo dentro do ciclo por rótulo contá-lo-ia
        # tantas vezes quantos os nomes com que a fonte designa a mesma unidade.
        if ind.get("denominador_dataset"):
            externo = _denominador_externo(con, cw, ind)
            for inst_id, meses in list(series[ind["id"]].items()):
                for mes, d in list(meses.items()):
                    den = externo.get((inst_id, mes))
                    # Um mês sem denominador não gera taxa: a regra da casa é
                    # que a ausência se declara, não se preenche.
                    if den is None or den <= 0:
                        del meses[mes]
                        continue
                    d["den"] = den
                    d["tem_den"] = True

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


def _tem_denominador(ind: dict) -> bool:
    """True quando o indicador é uma taxa — venha o denominador de onde vier.

    Um denominador de outro dataset conta tanto como uma coluna do próprio:
    testar só `denominador` fazia os antibióticos por dia de internamento
    saírem como contagem de DDD, sem divisão nenhuma.
    """
    return bool(ind.get("denominador") or ind.get("denominador_dataset"))


def _nao_somavel(ind: dict) -> bool:
    """True quando somar o indicador entre instituições não faz sentido."""
    if ind.get("ja_e_taxa"):
        return True
    return ind["unidade"] == "dias" and not _tem_denominador(ind)


def _valor(ind: dict, num: float, den: float | None) -> float | None:
    """Aplica a regra de agregação. Devolve None quando não é apresentável."""
    if ind.get("ja_e_taxa"):
        return num
    if not _tem_denominador(ind):
        return num
    if den is None or den < LIMIAR_DENOMINADOR:
        return None
    # `fator` existe para as taxas que a ACSS publica por 100 000 episódios —
    # sépsis e embolia pós-operatórias. Sem ele sairiam como proporções de
    # 0,0004, que não se leem nem se comparam com nada.
    fator = ind.get("fator", 100.0 if ind["unidade"] == "percentagem" else 1.0)
    v = fator * num / den
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
    den = sum(meses[m]["den"] for m in presentes) if _tem_denominador(ind) else None
    return {
        "valor": _valor(ind, num, den),
        "numerador": num,
        "denominador": den,
        "periodo": f"{min(presentes)}..{max(presentes)}",
        "meses_usados": len(presentes),
        "meses_em_falta": [m for m in janela if m not in meses],
    }


def _url_fonte(ind: dict, nomes: set[str], catalogo: dict) -> str:
    """URL que reproduz o número apresentado.

    A prova de cada valor. No portal é uma consulta à API filtrada pelos nomes
    que a fonte deu à instituição ao longo do tempo — que é precisamente o que o
    crosswalk resolve. No Benchmarking da ACSS não há API nem filtro: a prova é
    a mesma exportação que descarregámos, com o país inteiro lá dentro.
    """
    do_catalogo = catalogo.get(ind["dataset"], {}).get("url")
    if do_catalogo:
        return do_catalogo

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


def construir(con, cw, indicadores, catalogo, grupos):
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
                "url": _url_fonte(ind, nomes_fonte[(iid, inst_id)], catalogo),
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
            if _tem_denominador(ind)
            else None
        )

        ordenados = sorted(valores_inst.values())
        mediana = ordenados[len(ordenados) // 2] if ordenados else None

        # A mesma mediana, dentro de cada grupo de comparação da ACSS. Abaixo de
        # cinco unidades com valor não se publica: numa mediana de três, cada
        # unidade é um terço da referência contra a qual está a ser lida.
        por_grupo: dict[str, list[float]] = defaultdict(list)
        for inst_id, valor in valores_inst.items():
            grupo = grupos["por_instituicao"].get(inst_id, {}).get("atual")
            if grupo:
                por_grupo[grupo].append(valor)
        mediana_grupo = {
            g: {"mediana": sorted(v)[len(v) // 2], "n_instituicoes": len(v)}
            for g, v in sorted(por_grupo.items())
            if len(v) >= 5
        }

        # Uma regra única, partilhada com web/app.js::soMediana. Ter esta
        # decisão em dois sítios com formulações diferentes foi o que produziu
        # 901,9 % de mortalidade por AVC no painel; agora a formulação é a mesma
        # e site/scripts/verificar_coerencia.mjs verifica que assim continua.
        so_mediana = not _tem_denominador(ind) and ind["unidade"] in ("percentagem", "dias")
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
            "evidencia": ind.get("evidencia"),
            "janela": {"de": janela[0], "a": janela[-1]} if janela else None,
            "valor": valor_nac,
            "sintese": (
                "mediana entre unidades"
                if so_mediana
                else "soma dos numeradores ÷ soma dos denominadores"
                if _tem_denominador(ind)
                else "soma das instituições"
            ),
            "numerador": num_nac,
            "denominador": den_nac,
            "mediana_instituicoes": mediana,
            "mediana_por_grupo": mediana_grupo,
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


def _grupo_da_ficha(cw, grupos, inst_id: str) -> dict | None:
    """O grupo de comparação da unidade, com os pares que o compõem.

    Os pares vão por nome curto porque é o que a página mostra: dizer «Grupo C»
    não informa ninguém; dizer com que dezasseis unidades a sua está a ser
    comparada, sim.
    """
    info = grupos["por_instituicao"].get(inst_id)
    if not info:
        return None
    pares = [i for i in grupos["membros"].get(info["atual"], []) if i != inst_id]
    return {
        "grupo": info["atual"],
        "n_pares": len(pares),
        "pares": [
            {"id": i, "nome_curto": cw.por_id(i).nome_curto}
            for i in pares
            if cw.por_id(i) is not None
        ],
        "historico": info["por_ano"],
        "definicao": grupos["definicao"],
        "fonte": grupos["fonte"],
    }


def escrever(cw, fichas, nacional, por_indicador, grupos):
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
            "grupo_comparacao": _grupo_da_ficha(cw, grupos, inst.id),
            "populacao": extra.get("populacao", {}).get("por_instituicao", {}).get(inst.id),
            "per_capita": extra.get("per_capita", {}).get(inst.id),
            "indice_seguranca": extra.get("indice_seguranca", {}).get(inst.id),
            "poupancas_estimadas": extra.get("poupancas_estimadas", {}).get(inst.id),
            # As compras por doente padrão vão dentro do bloco dos contratos, e
            # não ao lado: é a mesma coisa noutra escala, e separá-las convidava
            # a lê-las como grandezas independentes.
            "contratos": (
                {
                    **extra["contratos"][inst.id],
                    "por_doente_padrao": extra.get("compras_por_doente_padrao", {}).get(inst.id),
                }
                if inst.id in extra.get("contratos", {})
                else None
            ),
            "indicadores": {
                iid: {**dados, **{
                    k: por_indicador[iid].get(k)
                    for k in ("titulo", "grupo", "unidade", "polaridade",
                              "descricao", "cautela", "referencia", "evidencia",
                              "pode_exceder_100", "pode_ser_negativa",
                              "maximo_plausivel")
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
                # O grupo vai também para o índice: é por ele que o painel
                # filtra e ordena sem ter de abrir as 43 fichas.
                "grupo_acss": grupos["por_instituicao"].get(inst.id, {}).get("atual"),
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
    catalogo = carregar_catalogo()

    grupos = carregar_grupos(cw)

    fichas, nacional, por_indicador = construir(con, cw, indicadores, catalogo, grupos)
    indice = escrever(cw, fichas, nacional, por_indicador, grupos)

    print(f"{len(indice)} fichas de instituição escritas em {DIR_SAIDA}")
    print(f"{len(indicadores)} indicadores; nacional.json com "
          f"{sum(1 for v in nacional.values() if v['valor'] is not None)} valores")
    if grupos["por_instituicao"]:
        print(f"  grupos de comparação da ACSS em {len(grupos['por_instituicao'])} "
              f"unidades, {len(grupos['membros'])} grupos")
    if grupos["sem_resolucao"]:
        print(f"  {len(grupos['sem_resolucao'])} nomes da ACSS sem entidade canónica: "
              f"{', '.join(grupos['sem_resolucao'][:3])}")
    sem_dados = [i.id for i in cw.instituicoes if i.id not in fichas]
    if sem_dados:
        print(f"  {len(sem_dados)} entidades sem indicadores: {', '.join(sem_dados)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
