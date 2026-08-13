"""Verificações da aritmética e da honestidade do build.

Correr com:  .venv/bin/python tests/test_build.py

O teste mais importante é `teste_aritmetica`: recalcula cada taxa a partir do
numerador e do denominador e compara com a percentagem que a própria fonte
publica na mesma linha. Se divergirem, ou emparelhámos mal as colunas, ou a
fonte mudou de metodologia — e em qualquer dos casos não devemos publicar.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ingest"))

import duckdb  # noqa: E402

from build import (  # noqa: E402
    LIMIAR_DENOMINADOR,
    _rel,
    _soma,
    carregar_indicadores,
)
from common import DIR_SAIDA  # noqa: E402
from instituicoes import carregar  # noqa: E402

TOLERANCIA_PP = 0.6  # pontos percentuais


def teste_aritmetica(con, indicadores) -> list[str]:
    """soma(num)/soma(den) tem de reproduzir a taxa publicada pela fonte."""
    erros = []
    for ind in indicadores:
        if not ind.get("publicado") or not ind.get("denominador"):
            continue
        if ind.get("denominador_x_dias_do_mes"):
            # O denominador destes indicadores não está numa coluna: constrói-se
            # a partir da lotação e do calendário. Verificados à parte, em
            # teste_ocupacao_ytd.
            continue
        col_ent = ind.get("coluna_entidade", "instituicao")
        col_tempo = ind.get("coluna_tempo", "tempo")
        num = _soma(ind["numerador"], ind.get("soma_tambem", []))
        den = _soma(ind["denominador"], ind.get("denominador_soma_tambem", []))
        # A mesma regra que build._valor aplica: `fator` existe para as taxas
        # por 100 000 episódios da ACSS, que não são percentagens nem rácios
        # simples. Repetir a regra com outra formulação era garantir que as duas
        # divergiriam.
        escala = float(ind.get("fator", 100.0 if ind["unidade"] == "percentagem" else 1.0))
        # Nem toda a fonte publica a taxa nas mesmas unidades em que a
        # apresentamos: o registo de antibióticos publica `peso` como fração
        # (0,0503) e não em pontos percentuais. `publicado_escala` põe os dois
        # lados na mesma unidade antes de comparar; sem isto o teste acusaria
        # divergência em todas as linhas destes indicadores.
        escala_publicado = float(ind.get("publicado_escala", 1))

        # Há fontes que se contradizem a si próprias durante um período: no
        # Benchmarking da ACSS, os internamentos com mais de 30 dias trazem, em
        # 2013 e 2014, uma taxa publicada que não corresponde ao numerador e ao
        # denominador da mesma linha — e as duas exportações que descrevem esses
        # meses concordam uma com a outra e discordam de si mesmas. O período
        # fica declarado em reference/indicadores.yaml e impresso aqui, em vez de
        # ser dissolvido numa tolerância maior para todos.
        desde = ind.get("publicado_reconcilia_desde")
        filtro_data = f' and "{col_tempo}" >= \'{desde}\'' if desde else ""

        linhas = con.execute(
            f'select "{col_ent}", "{col_tempo}", {num}, {den}, "{ind["publicado"]}" '
            f"from {_rel(ind['dataset'])} "
            f'where "{ind["publicado"]}" is not null and {den} >= {LIMIAR_DENOMINADOR}'
            f"{filtro_data}"
        ).fetchall()
        if desde:
            print(f"    {ind['id']}: taxa publicada só confrontada a partir de "
                  f"{desde} — a fonte não a reconcilia com as suas contagens antes disso")

        divergentes = 0
        exemplo = None
        for nome, periodo, n, d, publicado in linhas:
            nosso = escala * n / d
            publicado = publicado * escala_publicado
            if abs(nosso - publicado) > TOLERANCIA_PP:
                divergentes += 1
                if exemplo is None:
                    exemplo = f"{nome} {periodo}: nós {nosso:.2f}, fonte {publicado:.2f}"

        if linhas and divergentes / len(linhas) > 0.02:
            erros.append(
                f"{ind['id']}: {divergentes}/{len(linhas)} linhas divergem "
                f"(>{TOLERANCIA_PP}pp). ex.: {exemplo}"
            )
        elif divergentes:
            print(
                f"    {ind['id']}: {divergentes}/{len(linhas)} linhas divergem "
                f"— abaixo do limiar de 2%, aceite"
            )
    return erros


def teste_sem_media_de_percentagens(con, indicadores) -> list[str]:
    """A agregação anual não pode coincidir com a média das taxas mensais.

    É a forma de provar que a regra Σnum÷Σden está mesmo a ser aplicada: se o
    build fizesse a média das percentagens, os dois valores seriam iguais.
    Testamos num caso onde a diferença é matematicamente garantida — meses com
    denominadores muito diferentes.
    """
    erros = []
    ind = next((i for i in indicadores if i["id"] == "cesarianas"), None)
    if ind is None:
        return ["indicador 'cesarianas' não encontrado"]

    ficheiro = DIR_SAIDA / "instituicao" / "uls-coimbra.json"
    if not ficheiro.exists():
        return ["ficha uls-coimbra.json em falta"]
    ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
    dados = ficha["indicadores"]["cesarianas"]

    serie = [p for p in dados["serie"] if p["valor"] is not None][-12:]
    if len(serie) < 6:
        return ["série de cesarianas demasiado curta para o teste"]

    media_das_taxas = sum(p["valor"] for p in serie) / len(serie)
    correto = 100.0 * sum(p["numerador"] for p in serie) / sum(
        p["denominador"] for p in serie
    )
    if abs(dados["valor"] - correto) > 0.01:
        erros.append(
            f"cesarianas/uls-coimbra: ficha diz {dados['valor']:.3f}, "
            f"Σnum÷Σden dá {correto:.3f}"
        )
    print(
        f"    cesarianas/uls-coimbra: Σnum÷Σden={correto:.3f}% "
        f"vs média das taxas mensais={media_das_taxas:.3f}%"
    )
    return erros


def teste_ocupacao_ytd(con, indicadores) -> list[str]:
    """A taxa de ocupação publicada segue a fórmula acumulada no ano.

    A fonte chama-lhe «taxa anual de ocupação» e publica-a mensalmente. Não é
    a ocupação daquele mês: é o acumulado desde janeiro dividido pela lotação
    vezes os dias já decorridos no ano. Descobriu-se por engenharia inversa —
    o portal não o documenta — e é por isso que fica verificado aqui.
    """
    import datetime

    linhas = con.execute(
        "select tempo, no_de_dias_de_internamento, lotacao_praticada, "
        "taxa_anual_de_ocupacao_em_internamento "
        f"from {_rel('ocupacao-do-internamento')} "
        "where taxa_anual_de_ocupacao_em_internamento > 0 and lotacao_praticada > 0"
    ).fetchall()

    divergentes = 0
    exemplo = None
    for tempo, dias, lotacao, publicado in linhas:
        ano, mes = int(str(tempo)[:4]), int(str(tempo)[5:7])
        fim = datetime.date(ano + (mes == 12), (mes % 12) + 1, 1)
        dias_ytd = (fim - datetime.date(ano, 1, 1)).days
        nosso = 100.0 * dias / (lotacao * dias_ytd)
        # Tolerância larga: a lotação praticada muda ao longo do ano e a fonte
        # usa a média do período, que não publica.
        if abs(nosso - publicado) > 4.0:
            divergentes += 1
            if exemplo is None:
                exemplo = f"{tempo}: nós {nosso:.1f}, fonte {publicado:.1f}"

    if not linhas:
        return ["sem linhas de ocupação para verificar"]
    fracao = divergentes / len(linhas)
    print(f"    ocupação YTD: {len(linhas) - divergentes}/{len(linhas)} "
          f"linhas reproduzidas ({100 * (1 - fracao):.1f}%)")
    if fracao > 0.10:
        return [f"fórmula YTD falha em {divergentes}/{len(linhas)}. ex.: {exemplo}"]
    return []


def teste_desacumulacao(con, indicadores) -> list[str]:
    """Os fluxos mensais têm de ser plausíveis à escala do país.

    Sem des-acumulação, somar os doze meses de `partos-e-cesarianas` daria
    413 728 partos em 2024 — cinco vezes os nascimentos que ocorrem em
    Portugal. Este teste é o travão contra essa classe de erro voltar.
    """
    import collections

    total = collections.defaultdict(float)
    for ficheiro in (DIR_SAIDA / "instituicao").glob("*.json"):
        ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
        dados = ficha["indicadores"].get("cesarianas")
        if not dados:
            continue
        for ponto in dados["serie"]:
            if ponto.get("denominador"):
                total[ponto["mes"][:4]] += ponto["denominador"]

    erros = []
    for ano in sorted(total):
        if ano >= "2026":  # ano incompleto
            continue
        partos = total[ano]
        # Portugal tem entre 80 e 90 mil nascimentos por ano; os hospitais do
        # SNS respondem por cerca de três quartos.
        if not (50_000 <= partos <= 90_000):
            erros.append(
                f"{ano}: {partos:,.0f} partos no SNS — fora do intervalo "
                f"plausível (50k–90k). Sinal de série acumulada mal tratada."
            )
    return erros


def teste_supressao(con, indicadores) -> list[str]:
    """Nenhuma taxa publicada pode assentar num denominador abaixo do limiar."""
    erros = []
    for ficheiro in (DIR_SAIDA / "instituicao").glob("*.json"):
        ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
        for iid, d in ficha["indicadores"].items():
            if d["valor"] is None or d.get("denominador") is None:
                continue
            if d["denominador"] < LIMIAR_DENOMINADOR:
                erros.append(
                    f"{ficha['id']}/{iid}: valor publicado com denominador "
                    f"{d['denominador']} (< {LIMIAR_DENOMINADOR})"
                )
    return erros


def teste_cautelas_presentes(con, indicadores) -> list[str]:
    """Indicadores não ajustados ao risco têm de levar a cautela na ficha."""
    exigem_cautela = {
        "cesarianas",
        "mortalidade-avc-isquemico",
        "mortalidade-avc-hemorragico",
        "ocupacao-internamento",
    }
    erros = []
    for ficheiro in (DIR_SAIDA / "instituicao").glob("*.json"):
        ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
        for iid in exigem_cautela & set(ficha["indicadores"]):
            if not ficha["indicadores"][iid].get("cautela"):
                erros.append(f"{ficha['id']}/{iid}: sem texto de cautela")
    return erros


def teste_fonte_por_valor(con, indicadores) -> list[str]:
    """Cada valor apresentado tem de trazer dataset, data e URL de prova."""
    erros = []
    for ficheiro in (DIR_SAIDA / "instituicao").glob("*.json"):
        ficha = json.loads(ficheiro.read_text(encoding="utf-8"))
        for iid, d in ficha["indicadores"].items():
            fonte = d.get("fonte") or {}
            em_falta = [k for k in ("dataset", "atualizado", "url") if not fonte.get(k)]
            if em_falta:
                erros.append(f"{ficha['id']}/{iid}: fonte sem {', '.join(em_falta)}")
    return erros


def main() -> int:
    con = duckdb.connect()
    indicadores = carregar_indicadores()
    cw = carregar()
    n_fichas = len(list((DIR_SAIDA / "instituicao").glob("*.json")))
    print(f"build: {n_fichas} fichas, {len(indicadores)} indicadores, "
          f"{len(cw)} entidades no crosswalk\n")

    falhou = False
    for nome, funcao in [
        ("aritmética contra a fonte", teste_aritmetica),
        ("fórmula da ocupação (acumulada no ano)", teste_ocupacao_ytd),
        ("des-acumulação: fluxos plausíveis", teste_desacumulacao),
        ("regra Σnum÷Σden aplicada", teste_sem_media_de_percentagens),
        ("supressão de denominadores pequenos", teste_supressao),
        ("cautelas presentes", teste_cautelas_presentes),
        ("fonte por valor", teste_fonte_por_valor),
    ]:
        erros = funcao(con, indicadores)
        if erros:
            falhou = True
            print(f"  FALHA  {nome}: {len(erros)} problema(s)")
            for e in erros[:12]:
                print(f"           {e}")
            if len(erros) > 12:
                print(f"           ... e mais {len(erros) - 12}")
        else:
            print(f"  ok     {nome}")

    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
