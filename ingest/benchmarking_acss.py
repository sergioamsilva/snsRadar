"""Ingestão do Benchmarking Hospitalar da ACSS.

O Portal da Transparência publica *atividade*. O Benchmarking Hospitalar
publica *desempenho comparado*: 45 indicadores em seis dimensões, com as
instituições repartidas por grupos de financiamento apurados por clustering
hierárquico sobre variáveis explicativas do custo. Cerca de trinta desses
indicadores não têm equivalente no portal — nenhum indicador de segurança do
doente, nenhum volume cirúrgico, nenhuma métrica ajustada pelo case-mix.

Não há API. Há, dentro do painel, uma exportação para Excel — e essa devolve
muito mais do que o ecrã mostra: por instituição e por mês, o valor, o
numerador, o denominador e o grupo de comparação.

Quatro propriedades da exportação determinam a forma deste módulo:

  1. `entityShortName` é ignorado. O ficheiro traz sempre o país inteiro,
     qualquer que seja a instituição que se peça. Uma descarga por indicador
     chega; não é preciso uma por hospital.
  2. `time=AAAAMM` devolve o mês pedido e os vinte e três anteriores — dois
     anos civis completos quando se pede dezembro. Daí as âncoras serem os
     dezembros: treze pedidos cobrem 2013 a 2026 com sobreposição de um ano.
  3. Essa sobreposição não é desperdício: dois pedidos que descrevem o mesmo
     mês têm de trazer o mesmo valor. Quando não trazem, a ACSS reviu o número
     em silêncio, e é isso que `--verificar-sobreposicao` mostra.
  4. As folhas mensais trazem valores **do mês**, não acumulados no ano. É a
     diferença face ao portal, e é o que torna esta fonte uma verificação
     independente da des-acumulação — ver tests/test_benchmarking_acss.py.

Escreve em data/raw, junto dos datasets do portal, para que a mesma disciplina
de SHA-256 por extração (ingest/snapshot.py) apanhe também as revisões desta
fonte:

    data/raw/bh-acss-<indicador>.csv.gz   série mensal, uma linha por (unidade, mês)
    data/raw/bh-acss-_nacional.csv.gz     os totais que a própria ACSS publica
    data/raw/bh-acss-_anual.csv.gz        acumulado, índice e poupanças estimadas
    data/raw/_catalogo-acss.json          metadados, fórmula e data de publicação

Uso:
    python ingest/benchmarking_acss.py                  # tudo, 2013 a hoje
    python ingest/benchmarking_acss.py --so-catalogo    # só descobre indicadores
    python ingest/benchmarking_acss.py --indicadores X  # códigos específicos
    python ingest/benchmarking_acss.py --desde 2024     # só de 2024 para cá
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from html import unescape
from urllib.parse import urlencode

import requests

from common import DIR_BRUTO, TEMPO_LIMITE, TENTATIVAS, garantir_dirs

BASE = "https://benchmarking-acss.min-saude.pt"

# A rota de exportação **não** é uma propriedade do painel: é declarada
# indicador a indicador em `layoutActionUrls`, e dentro do mesmo painel há mais
# do que uma. No Económico-Financeiro, os gastos por doente padrão saem por
# `_3Evolution_3AditionalValues` e as percentagens de gastos por `_3Evolution`;
# na Produtividade, os doentes padrão por profissional saem por
# `_2Evolution_1EvolutionDoubleValue_2AditionalValues` e a demora média por
# `_3Evolution`. Pedir pela rota errada devolve 500 ou — pior — um ficheiro
# válido e vazio, que passaria por «a fonte não tem dados».
DASHBOARDS = {
    "BH_AcessoDashboard": "Acesso",
    "BH_DesempAssistencialDashboard": "Desempenho assistencial",
    "BH_SegurancaDashboard": "Segurança",
    "BH_VolUtilizacaoDashboard": "Volume e utilização",
    "BH_ProdutividadeDashboard": "Produtividade",
    "BH_EconFinDashboard": "Económico-financeira",
}

FICHEIRO_CATALOGO_ACSS = DIR_BRUTO / "_catalogo-acss.json"
PREFIXO = "bh-acss-"
DIR_CACHE = DIR_BRUTO / "bh-acss-exportacoes"

# Linhas que não são instituições: a exportação inclui, nas folhas
# complementares, os totais que a ACSS publica para o conjunto. Não são ruído —
# são a referência nacional oficial, e por isso vão para ficheiro próprio em vez
# de serem descartadas. O que não podem é entrar no crosswalk como se fossem
# hospitais.
_AGREGADOS = re.compile(r"^(total|ars)\b", re.IGNORECASE)

PAUSA = 0.4


def slug(texto: str) -> str:
    """Nome de ficheiro estável a partir do código do indicador.

    Os códigos da ACSS trazem ordinais e acentos («Perc_1ªas_Cesa_Gest_Uni_Cef_a_T»)
    que não têm lugar num nome de dataset citado numa URL.
    """
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t


def _sessao() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "snsRadar/1.0 (+https://github.com/sergioamsilva/snsRadar)"
    return s


def _obter(sessao, url: str, **kwargs) -> requests.Response:
    ultimo = None
    for tentativa in range(TENTATIVAS):
        try:
            r = sessao.get(url, timeout=TEMPO_LIMITE, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(2**tentativa)
    raise RuntimeError(f"{url}: {ultimo}")


# --------------------------------------------------------------------------
# Leitor de xlsx
# --------------------------------------------------------------------------
# Escrito à mão em vez de acrescentar o openpyxl às dependências. Um xlsx é um
# zip de XML e o que a ACSS exporta usa uma fração ínfima do formato: sem
# fórmulas, sem datas, sem estilos que alterem o valor. Ler isto com uma
# biblioteca completa seria trazer 250 KB de código para resolver trinta linhas.

_CELULA = re.compile(
    r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(?:<v>([^<]*)</v>|<is>.*?<t[^>]*>([^<]*)</t>.*?</is>)?</c>)',
    re.S,
)
_LINHA = re.compile(r'<row r="(\d+)"[^>]*(?:/>|>(.*?)</row>)', re.S)


def _texto_partilhado(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    xml = z.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
    return [
        unescape(re.sub(r"<[^>]+>", "", bloco))
        for bloco in re.findall(r"<si>(.*?)</si>", xml, re.S)
    ]


def ler_xlsx(dados: bytes) -> dict[str, list[dict[str, str | None]]]:
    """Devolve {nome da folha: [linha]}, cada linha um dicionário coluna→valor.

    A chave da linha é a letra da coluna, não o cabeçalho: o cabeçalho está na
    linha 8 e as linhas 2 a 6 trazem metadados soltos (data de publicação, nome
    do indicador, período). Interpretar isso é trabalho de quem chama.
    """
    z = zipfile.ZipFile(io.BytesIO(dados))
    partilhado = _texto_partilhado(z)
    workbook = z.read("xl/workbook.xml").decode("utf-8", errors="replace")
    nomes = [unescape(n) for n in re.findall(r'<sheet name="([^"]+)"', workbook)]

    folhas: dict[str, list[dict[str, str | None]]] = {}
    for i, nome in enumerate(nomes, 1):
        alvo = f"xl/worksheets/sheet{i}.xml"
        if alvo not in z.namelist():
            continue
        xml = z.read(alvo).decode("utf-8", errors="replace")
        linhas = []
        for numero, corpo in _LINHA.findall(xml):
            celulas: dict[str, str | None] = {"_linha": numero}
            for coluna, atributos, valor, inline in _CELULA.findall(corpo or ""):
                if inline:
                    celulas[coluna] = unescape(inline)
                elif valor == "" or valor is None:
                    celulas[coluna] = None
                elif 't="s"' in atributos:
                    celulas[coluna] = partilhado[int(valor)]
                else:
                    celulas[coluna] = unescape(valor)
            linhas.append(celulas)
        folhas[nome] = linhas
    return folhas


def _cabecalho(linhas: list[dict], prefixo: str) -> str | None:
    """Uma das linhas soltas do topo, procurada pelo seu prefixo."""
    for linha in linhas[:8]:
        a = linha.get("A")
        if a and a.startswith(prefixo):
            return a[len(prefixo):].strip()
    return None


def _registos(linhas: list[dict]) -> list[dict]:
    """As linhas de dados: as que vêm depois do cabeçalho da linha 8."""
    saida = []
    for linha in linhas:
        if int(linha["_linha"]) <= 8:
            continue
        ano, mes = linha.get("C"), linha.get("D")
        if not ano or not mes:
            continue
        saida.append(
            {
                "grupo": linha.get("A"),
                "instituicao": linha.get("B"),
                "tempo": f"{ano}-{str(mes).zfill(2)}-01",
                "valor": linha.get("E"),
                "indice": linha.get("F"),
                "extra_g": linha.get("G"),
                "extra_h": linha.get("H"),
                "extra_i": linha.get("I"),
            }
        )
    return saida


# --------------------------------------------------------------------------
# Descoberta
# --------------------------------------------------------------------------

def descobrir_indicadores(sessao) -> dict[str, dict]:
    """O catálogo de indicadores, lido de cada painel.

    Cada painel embebe `jsonDashboardFilter`, o produto cartesiano dos seus
    indicadores pelos meses em que cada um tem dados. É a única declaração
    fiável do que existe: os `<select>` são preenchidos por JavaScript e a
    página servida não os traz.
    """
    catalogo: dict[str, dict] = {}
    for rota, dimensao in DASHBOARDS.items():
        html = _obter(sessao, f"{BASE}/{rota}").text
        m = re.search(r"var\s+jsonDashboardFilter\s*=\s*(\[.*?\]);", html, re.S)
        if not m:
            raise RuntimeError(f"{rota}: sem jsonDashboardFilter — o painel mudou de forma")

        # A rota de exportação de cada indicador, do mesmo sítio de onde o
        # painel a lê. Sem isto ficava por adivinhar, e adivinhar mal devolve um
        # ficheiro vazio em vez de um erro.
        acao = re.search(r"var\s+layoutActionUrls\s*=\s*(\[.*?\]);", html, re.S)
        exportacao: dict[str, str] = {}
        if acao:
            for r in json.loads(acao.group(1)):
                if r.get("Key") == "ExportDataToExcel" and r.get("Value"):
                    exportacao[r["IndicatorCode"]] = r["Value"]

        for r in json.loads(m.group(1)):
            codigo = r["Filter1_id"]
            entrada = catalogo.setdefault(
                codigo,
                {
                    "codigo": codigo,
                    "slug": PREFIXO + slug(codigo),
                    "titulo": r["Filter1_text"].strip(),
                    "dimensao": dimensao,
                    "dashboard": rota,
                    "export": exportacao.get(codigo),
                    "meses": [],
                },
            )
            entrada["meses"].append(str(r["Filter2_id"]))
        time.sleep(PAUSA)

    sem_rota = [c for c, e in catalogo.items() if not e["export"]]
    if sem_rota:
        raise RuntimeError(
            "sem rota de exportação declarada para "
            f"{len(sem_rota)} indicadores: {', '.join(sorted(sem_rota)[:5])}"
        )

    for entrada in catalogo.values():
        entrada["meses"] = sorted(set(entrada["meses"]))
    return catalogo


def obter_ficha_metodologica(sessao, entrada: dict) -> dict:
    """A fórmula de cálculo e a fonte que a ACSS declara para o indicador.

    Vive num popover do painel, em HTML escapado dentro de um atributo. Vale o
    pedido: é a definição operacional do indicador, e sem ela um número destes
    não é citável — só o parágrafo diz que o denominador das úlceras de pressão
    já leva exclusões aplicadas.
    """
    url = f"{BASE}/{entrada['dashboard']}/GroupPerformanceAsync"
    parametros = {"indicatorCode": entrada["codigo"], "time": entrada["meses"][-1]}
    try:
        html = _obter(sessao, url, params=parametros).text
    except RuntimeError:
        return {}
    m = re.search(r'data-content="(.*?)"\s*>', html, re.S)
    if not m:
        return {}
    texto = re.sub(r"<[^>]+>", "\n", unescape(unescape(m.group(1))))
    texto = re.sub(r"\n{2,}", "\n", texto).strip()

    ficha = {}
    for rotulo, chave in (("Fórmula de Cálculo:", "formula"), ("Fonte:", "fonte_declarada")):
        if rotulo in texto:
            resto = texto.split(rotulo, 1)[1]
            for outro in ("Fórmula de Cálculo:", "Fonte:", "Nota:"):
                resto = resto.split(outro, 1)[0]
            valor = " ".join(resto.split())
            if valor:
                ficha[chave] = valor
    return ficha


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------

def ancoras(meses: list[str], desde: int | None = None) -> list[str]:
    """Os meses a pedir para cobrir toda a série.

    Cada pedido devolve vinte e quatro meses, pelo que os dezembros bastam — e
    o último mês disponível junta-se-lhes porque o ano corrente ainda não tem
    dezembro. Ficam de fora os dezembros anteriores ao início da série.
    """
    if not meses:
        return []
    anos = sorted({int(m[:4]) for m in meses})
    if desde is not None:
        anos = [a for a in anos if a >= desde - 1]
    escolhidos = [f"{ano}12" for ano in anos if f"{ano}12" in meses]
    if meses[-1] not in escolhidos:
        escolhidos.append(meses[-1])
    return sorted(set(escolhidos))


def _precedencia(ancora: str, tempo: str) -> tuple[int, str]:
    """Qual das âncoras manda, quando duas descrevem o mesmo mês.

    A exportação de dezembro de um ano traz esse ano com precisão completa
    (0,32432432432432434) e o ano anterior arredondado a quatro casas (0,3243)
    — é o «ano homólogo» do gráfico, e a folha guarda-o com a precisão do
    desenho. Ganha, por isso, a âncora do próprio ano; entre âncoras
    equivalentes, ganha a mais recente, que é a que traz a última revisão.
    """
    return (1 if ancora[:4] == tempo[:4] else 0, ancora)


def _mesmo_valor(a, b) -> bool:
    """Iguais à precisão com que a fonte os publica.

    Comparar as cadeias diria que 0,3243 difere de 0,32432432432432434, e cada
    série passaria a acusar dezenas de revisões que não existem.
    """
    x, y = _numero(a), _numero(b)
    if x is None or y is None:
        return x is y
    return round(x, 4) == round(y, 4)


def _exportacao(sessao, entrada: dict, ancora: str, usar_cache: bool) -> bytes:
    """A exportação de um (indicador, âncora), do disco se já lá estiver.

    São seiscentos pedidos para reconstruir a série completa. Guardar o ficheiro
    tal como veio permite voltar a processá-lo — depois de corrigir um erro de
    leitura, por exemplo — sem voltar a pedi-lo ao servidor. `data/raw` está fora
    do repositório, e é onde os dados em bruto desta casa já vivem.
    """
    DIR_CACHE.mkdir(parents=True, exist_ok=True)
    destino = DIR_CACHE / f"{entrada['slug']}-{ancora}.xlsx"
    if usar_cache and destino.exists():
        return destino.read_bytes()
    dados = _obter(
        sessao,
        f"{BASE}{entrada['export']}",
        params={"indicatorCode": entrada["codigo"], "time": ancora},
    ).content
    destino.write_bytes(dados)
    time.sleep(PAUSA)
    return dados


def descarregar_indicador(sessao, entrada: dict, desde: int | None,
                          usar_cache: bool = True) -> dict:
    """Descarrega e funde todas as âncoras de um indicador.

    A fusão tem uma regra que não é óbvia e que custou um erro: **cada mês vem
    de uma só exportação**, e não do conjunto delas. A exportação de dezembro de
    2024 traz 2023 como ano homólogo — mas com os nomes de 2024. A de dezembro
    de 2023 traz o mesmo 2023 com os nomes de 2023. Fundir as duas por nome
    deixa o ano inteiro representado duas vezes, sob duas designações que o
    crosswalk resolve — corretamente — para a mesma entidade. Resultado: 2023
    com o dobro das cesarianas do país, e sem um único nome repetido que
    denunciasse o problema.

    Manda, para cada mês, a âncora do próprio ano; na falta dela, a mais
    recente que o cubra.
    """
    por_ancora: dict[str, dict[str, dict[tuple[str, str], dict]]] = {}
    anual: dict[tuple[str, str], dict] = {}
    titulos: dict[str, str] = {}
    publicado_em = None

    marcos = ancoras(entrada["meses"], desde)
    falhadas: list[str] = []

    for ancora in marcos:
        # Uma âncora que falhe não pode levar o indicador todo atrás dela: o
        # painel devolve 500 em combinações que o seu próprio filtro anuncia.
        # Como cada pedido traz vinte e quatro meses e as âncoras são anuais, o
        # ano perdido é quase sempre reposto pela âncora seguinte — e o que não
        # for reposto aparece na cobertura, que é onde tem de aparecer.
        try:
            folhas = ler_xlsx(_exportacao(sessao, entrada, ancora, usar_cache))
        except (RuntimeError, zipfile.BadZipFile) as e:
            falhadas.append(ancora)
            print(f"      âncora {ancora} falhou ({type(e).__name__}); segue")
            continue

        for nome_folha, linhas in folhas.items():
            titulo = _cabecalho(linhas, "Indicador:")
            publicado = _cabecalho(linhas, "Dados publicados a")
            if publicado:
                publicado_em = max(publicado_em or "", publicado)

            # O papel da folha está no seu nome, não na sua posição: a folha
            # complementar 1 é o numerador do indicador principal e a 2 o seu
            # denominador — «Cesarianas» sobre «Total de Partos», «Episódios com
            # úlceras» sobre «episódios com exclusões aplicadas».
            if "Grupos" in nome_folha:
                papel = "anual"
            elif "Complementar 1" in nome_folha:
                papel = "numerador"
            elif "Complementar 2" in nome_folha:
                papel = "denominador"
            elif "Principal" in nome_folha:
                papel = "valor"
            else:
                continue
            if titulo:
                titulos[papel] = titulo

            for registo in _registos(linhas):
                chave = (registo["instituicao"], registo["tempo"])
                if papel == "anual":
                    anual[chave] = registo
                else:
                    por_ancora.setdefault(ancora, {}).setdefault(papel, {})[chave] = registo

    return {
        **_fundir_ancoras(por_ancora),
        "anual": anual,
        "titulos": titulos,
        "publicado_em": publicado_em,
        "ancoras": marcos,
        "ancoras_falhadas": falhadas,
    }


def _fundir_ancoras(por_ancora: dict) -> dict:
    """Escolhe a âncora dona de cada mês e monta a série a partir só dela."""
    dono: dict[str, str] = {}
    for ancora, papeis in por_ancora.items():
        for registos in papeis.values():
            for _, tempo in registos:
                if tempo not in dono or _precedencia(ancora, tempo) > _precedencia(
                    dono[tempo], tempo
                ):
                    dono[tempo] = ancora

    mensal: dict[str, dict[tuple[str, str], dict]] = {}
    divergencias: list[dict] = []
    for ancora, papeis in sorted(por_ancora.items()):
        for papel, registos in papeis.items():
            for chave, registo in registos.items():
                instituicao, tempo = chave
                # As âncoras sobrepõem-se de propósito: um mês descrito por duas
                # exportações, com o mesmo nome de unidade, tem de trazer o mesmo
                # número. Quando não traz, a ACSS reviu-o desde a extração
                # anterior — e é isso, e não um erro, que fica registado.
                for outra, outros_papeis in por_ancora.items():
                    if outra >= ancora:
                        continue
                    anterior = outros_papeis.get(papel, {}).get(chave)
                    if anterior and not _mesmo_valor(anterior["valor"], registo["valor"]):
                        divergencias.append(
                            {
                                "instituicao": instituicao,
                                "tempo": tempo,
                                "papel": papel,
                                "de": anterior["valor"],
                                "para": registo["valor"],
                                "ancoras": [outra, ancora],
                            }
                        )
                if dono.get(tempo) == ancora:
                    mensal.setdefault(papel, {})[chave] = {**registo, "_ancora": ancora}

    return {"mensal": mensal, "divergencias": divergencias}


def _numero(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def consolidar(descarga: dict, meses_anunciados: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Junta valor, numerador e denominador numa linha por (unidade, mês).

    Separa as instituições dos agregados que a ACSS publica na mesma folha. Os
    agregados ficam, mas noutro ficheiro: são a referência nacional oficial, não
    uma unidade prestadora.

    Descarta os meses que a fonte não declara ter. A janela de 24 meses de cada
    exportação avança um ano para trás do que o filtro do painel anuncia — a
    âncora de dezembro de 2013 traz 2012 —, e esses meses de bónus vêm com as
    folhas desalinhadas: nos internamentos longos, 1 271 linhas de 2012 em que
    o valor publicado não corresponde ao numerador e ao denominador da mesma
    linha. Ficar com eles seria publicar como série o que a fonte não assume.
    """
    mensal = descarga["mensal"]
    chaves = {c for papel in mensal.values() for c in papel}
    if meses_anunciados is not None:
        chaves = {c for c in chaves if c[1][:7].replace("-", "") in meses_anunciados}

    instituicoes, agregados = [], []
    for instituicao, tempo in sorted(chaves):
        linha = {
            "instituicao": instituicao,
            "tempo": tempo,
            "grupo": None,
            "valor": None,
            "numerador": None,
            "denominador": None,
            "ancora": None,
        }
        for papel in ("valor", "numerador", "denominador"):
            registo = mensal.get(papel, {}).get((instituicao, tempo))
            if registo is None:
                continue
            linha[papel] = _numero(registo["valor"])
            # A âncora fica na linha porque é a proveniência do número: diz de
            # que exportação saiu, e é o que permite voltar a pedi-la.
            linha["ancora"] = registo.get("_ancora")
            if registo.get("grupo") and registo["grupo"] != "-":
                linha["grupo"] = registo["grupo"]
        # Uma linha sem um único valor é a forma de a fonte dizer que a unidade
        # não reportou aquele mês. Guardá-la faria passar por lacuna o que é
        # apenas ausência de reporte — e a regra da casa é não inventar nem uma
        # coisa nem a outra.
        if all(linha[p] is None for p in ("valor", "numerador", "denominador")):
            continue
        (agregados if _AGREGADOS.match(instituicao or "") else instituicoes).append(linha)
    return instituicoes, agregados


def fundir_por_indicador(caminho, novas: list[dict], colunas: list[str],
                         alvos: set[str]) -> list[dict]:
    """Substitui no ficheiro só as linhas dos indicadores acabados de descarregar.

    Os ficheiros `_nacional` e `_anual` juntam todos os indicadores num só. Sem
    esta fusão, uma execução com `--indicadores` reescrevia-os apenas com o que
    tinha pedido, e os restantes quarenta e quatro desapareciam em silêncio.
    """
    antigas: list[dict] = []
    if caminho.exists():
        with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
            antigas = [
                linha for linha in csv.DictReader(f, delimiter=";")
                if linha.get("indicador") not in alvos
            ]
    return antigas + novas


def escrever_csv(caminho, linhas: list[dict], colunas: list[str]) -> int:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=colunas, delimiter=";",
                              extrasaction="ignore", lineterminator="\n")
    escritor.writeheader()
    for linha in linhas:
        escritor.writerow(linha)
    with gzip.open(caminho, "wt", encoding="utf-8", newline="") as f:
        f.write(buffer.getvalue())
    return len(linhas)


def url_reprodutivel(entrada: dict, ancora: str) -> str:
    """A ligação que reproduz o ficheiro de onde o número saiu.

    O equivalente, nesta fonte, à URL da API que acompanha cada valor vindo do
    portal: quem quiser verificar um número descarrega o mesmo Excel que nós.
    """
    parametros = urlencode({"indicatorCode": entrada["codigo"], "time": ancora})
    return f"{BASE}{entrada['export']}?{parametros}"


COLUNAS_MENSAL = ["instituicao", "tempo", "grupo", "valor", "numerador",
                  "denominador", "ancora"]
COLUNAS_ANUAL = ["indicador", "instituicao", "tempo", "grupo", "valor", "indice",
                 "extra_g", "extra_h", "extra_i"]

FICHEIRO_GRUPOS = DIR_BRUTO / f"{PREFIXO}_grupos.json"

# A definição, tal como a ACSS a escreve em BH_Enquadramento/AbordagemMetodologica.
# Fica gravada com os grupos porque um grupo sem o critério que o formou é uma
# letra arbitrária, e o site tem de poder explicar ao leitor porque é que a ULS
# do Nordeste se compara com a da Guarda e não com o São João.
DEFINICAO_GRUPOS = (
    "Grupos de financiamento determinados pela ACSS com recurso a clustering "
    "hierárquico, após standardização de variáveis com capacidade explicativa "
    "dos custos e análise de componentes principais."
)


def extrair_grupos_enquadramento(sessao) -> dict[str, dict[str, list[str]]]:
    """Os grupos tal como a ACSS os publica, antes e depois da reforma de 2024.

    Esta página vale mais do que a composição atual: ao listar as duas eras
    lado a lado, dá uma lista de entidades independente da nossa para confrontar
    com o crosswalk. Se a ACSS conhece uma unidade que o snsRadar não resolve,
    ou o contrário, é aqui que se vê.
    """
    html = _obter(sessao, f"{BASE}/BH_Enquadramento/GrupoInstituicoes").text
    eras: dict[str, dict[str, list[str]]] = {}
    for identificador, era in (("collapse1", "desde-2024"), ("collapse2", "ate-2023")):
        m = re.search(rf'id="{identificador}".*?(?=id="collapse|</body>)', html, re.S)
        if not m:
            continue
        composicao: dict[str, list[str]] = {}
        for grupo, corpo in re.findall(
            r"<p><strong>\s*(Grupo\s+\w)\s*</strong></p>(.*?)</div>", m.group(0), re.S
        ):
            nomes = [
                " ".join(unescape(n).split())
                for n in re.findall(r"<p>(?!<strong)(.*?)</p>", corpo, re.S)
            ]
            composicao[grupo.strip()] = [n for n in nomes if n and n != "&nbsp;"]
        if composicao:
            eras[era] = composicao
    return eras


def derivar_grupos(sessao) -> dict:
    """O grupo de cada unidade, ano a ano, a partir do que já foi descarregado.

    Sai do ficheiro anual em vez de um pedido novo: o grupo vem em todas as
    folhas, e a exportação já o trouxe. Um mesmo ano pode aparecer com grupos
    diferentes conforme o indicador — quando isso acontece fica o mais frequente,
    e a discordância fica registada em vez de desaparecer.
    """
    caminho = DIR_BRUTO / f"{PREFIXO}_anual.csv.gz"
    if not caminho.exists():
        raise RuntimeError(
            f"{caminho.name} em falta — corra primeiro a descarga dos indicadores"
        )

    votos: dict[str, dict[str, dict[str, int]]] = {}
    with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            grupo, instituicao = linha["grupo"], linha["instituicao"]
            if not grupo or grupo == "-" or _AGREGADOS.match(instituicao or ""):
                continue
            ano = linha["tempo"][:4]
            votos.setdefault(instituicao, {}).setdefault(ano, {})
            votos[instituicao][ano][grupo] = votos[instituicao][ano].get(grupo, 0) + 1

    por_instituicao, discordantes = {}, []
    for instituicao, anos in sorted(votos.items()):
        por_ano = {}
        for ano, contagem in sorted(anos.items()):
            escolhido = max(contagem, key=lambda g: (contagem[g], g))
            if len(contagem) > 1:
                discordantes.append(
                    {"instituicao": instituicao, "ano": ano, "contagem": contagem}
                )
            por_ano[ano] = escolhido
        por_instituicao[instituicao] = {
            "atual": por_ano[max(por_ano)],
            "por_ano": por_ano,
        }

    return {
        "definicao": DEFINICAO_GRUPOS,
        "fonte": f"{BASE}/BH_Enquadramento/GrupoInstituicoes",
        "publicado": extrair_grupos_enquadramento(sessao),
        "por_instituicao": por_instituicao,
        "discordancias": discordantes,
    }


def escrever_grupos(sessao) -> int:
    grupos = derivar_grupos(sessao)
    FICHEIRO_GRUPOS.write_text(
        json.dumps(grupos, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    composicao = grupos["publicado"].get("desde-2024", {})
    print(f"grupos: {len(grupos['por_instituicao'])} unidades, "
          f"{len(composicao)} grupos publicados desde 2024 "
          f"({sum(len(v) for v in composicao.values())} unidades listadas)")
    if grupos["discordancias"]:
        print(f"  {len(grupos['discordancias'])} pares unidade/ano com grupos "
              f"discordantes entre indicadores")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--indicadores", nargs="*", help="códigos ACSS específicos")
    p.add_argument("--so-catalogo", action="store_true",
                   help="descobre os indicadores e sai, sem descarregar séries")
    p.add_argument("--so-grupos", action="store_true",
                   help="refaz apenas os grupos de comparação, do que já está em disco")
    p.add_argument("--desde", type=int, help="primeiro ano a descarregar")
    p.add_argument("--sem-ficha", action="store_true",
                   help="salta a fórmula de cálculo (um pedido a menos por indicador)")
    p.add_argument("--ignorar-cache", action="store_true",
                   help="volta a pedir as exportações mesmo que já estejam em disco")
    args = p.parse_args()

    garantir_dirs()
    sessao = _sessao()

    if args.so_grupos:
        return escrever_grupos(sessao)

    print(f"a descobrir indicadores em {len(DASHBOARDS)} painéis")
    catalogo = descobrir_indicadores(sessao)
    print(f"  {len(catalogo)} indicadores em {len({e['dimensao'] for e in catalogo.values()})} dimensões")
    for dimensao in sorted({e["dimensao"] for e in catalogo.values()}):
        n = sum(1 for e in catalogo.values() if e["dimensao"] == dimensao)
        print(f"    {dimensao}: {n}")

    if args.indicadores:
        desconhecidos = set(args.indicadores) - set(catalogo)
        if desconhecidos:
            print(f"  códigos desconhecidos: {', '.join(sorted(desconhecidos))}")
            return 1
        alvos = {c: catalogo[c] for c in args.indicadores}
    else:
        alvos = catalogo

    if args.so_catalogo:
        FICHEIRO_CATALOGO_ACSS.write_text(
            json.dumps(catalogo, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"  catálogo escrito em {FICHEIRO_CATALOGO_ACSS.name}")
        return 0

    nacionais: list[dict] = []
    anuais: list[dict] = []
    total_linhas = 0
    revistos: list[str] = []

    lacunas_totais: dict[str, list[str]] = {}

    for i, (codigo, entrada) in enumerate(sorted(alvos.items()), 1):
        descarga = descarregar_indicador(sessao, entrada, args.desde,
                                         usar_cache=not args.ignorar_cache)
        marcos = descarga["ancoras"]
        instituicoes, agregados = consolidar(descarga, set(entrada["meses"]))

        destino = DIR_BRUTO / f"{entrada['slug']}.csv.gz"
        n = escrever_csv(destino, instituicoes, COLUNAS_MENSAL)
        total_linhas += n

        for chave, registo in descarga["anual"].items():
            anuais.append({"indicador": codigo, **registo})
        for linha in agregados:
            nacionais.append({"indicador": codigo, **linha})

        ficha = {} if args.sem_ficha else obter_ficha_metodologica(sessao, entrada)
        meses_com_dados = sorted({l["tempo"][:7] for l in instituicoes})

        # A fonte anuncia, no seu próprio filtro, os meses em que diz ter dados.
        # Trazer menos do que isso é uma lacuna, e uma lacuna declara-se — a
        # alternativa é uma série com buracos que ninguém sabe explicar.
        anunciados = {f"{m[:4]}-{m[4:]}" for m in entrada["meses"]}
        if args.desde:
            anunciados = {m for m in anunciados if int(m[:4]) >= args.desde}
        lacunas = sorted(anunciados - set(meses_com_dados))
        if lacunas:
            lacunas_totais[codigo] = lacunas

        entrada.update(
            {
                **ficha,
                "publisher": "ACSS",
                "titulo_numerador": descarga["titulos"].get("numerador"),
                "titulo_denominador": descarga["titulos"].get("denominador"),
                "publicado_em": descarga["publicado_em"],
                "n_registos": n,
                "n_instituicoes": len({l["instituicao"] for l in instituicoes}),
                "cobertura": (
                    {"de": meses_com_dados[0], "a": meses_com_dados[-1]}
                    if meses_com_dados else None
                ),
                "ancoras": marcos,
                "ancoras_falhadas": descarga["ancoras_falhadas"],
                "meses_sem_dados": lacunas,
                "url": url_reprodutivel(entrada, marcos[-1]) if marcos else None,
                "divergencias_entre_ancoras": len(descarga["divergencias"]),
            }
        )
        if descarga["divergencias"]:
            revistos.append(codigo)

        print(f"  [{i}/{len(alvos)}] {codigo}: {n:,} linhas, "
              f"{entrada['n_instituicoes']} unidades, {len(marcos)} pedidos"
              + (f", {len(descarga['divergencias'])} meses revistos"
                 if descarga["divergencias"] else "")
              + (f", {len(lacunas)} meses sem dados" if lacunas else ""))

    codigos = set(alvos)
    caminho_nacional = DIR_BRUTO / f"{PREFIXO}_nacional.csv.gz"
    caminho_anual = DIR_BRUTO / f"{PREFIXO}_anual.csv.gz"
    nacionais = fundir_por_indicador(caminho_nacional, nacionais,
                                     ["indicador", *COLUNAS_MENSAL], codigos)
    anuais = fundir_por_indicador(caminho_anual, anuais, COLUNAS_ANUAL, codigos)
    escrever_csv(caminho_nacional, nacionais, ["indicador", *COLUNAS_MENSAL])
    escrever_csv(caminho_anual, anuais, COLUNAS_ANUAL)

    # Os indicadores que esta execução não pediu mantêm o que já se sabia deles:
    # a descoberta só traz título e meses, e sobrepor isso a uma entrada
    # completa apagaria a fórmula e a cobertura da descarga anterior.
    if FICHEIRO_CATALOGO_ACSS.exists():
        anterior = json.loads(FICHEIRO_CATALOGO_ACSS.read_text(encoding="utf-8"))
        for codigo, entrada in catalogo.items():
            if codigo not in alvos and codigo in anterior:
                catalogo[codigo] = {**anterior[codigo], **entrada}
    FICHEIRO_CATALOGO_ACSS.write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    escrever_grupos(sessao)

    print(f"\n{len(alvos)} indicadores, {total_linhas:,} linhas mensais, "
          f"{len(anuais):,} linhas anuais, {len(nacionais):,} linhas de agregados")
    if revistos:
        # Não é erro: é a fonte a corrigir-se, e é exatamente o que se quer ver.
        print(f"  {len(revistos)} indicadores com meses revistos entre âncoras: "
              f"{', '.join(revistos[:5])}{' …' if len(revistos) > 5 else ''}")
    if lacunas_totais:
        print(f"  {len(lacunas_totais)} indicadores com meses anunciados pela fonte "
              f"mas sem dados:")
        for codigo, meses in sorted(lacunas_totais.items()):
            print(f"    {codigo}: {len(meses)} meses ({meses[0]} a {meses[-1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
