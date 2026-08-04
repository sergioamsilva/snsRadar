#!/usr/bin/env python3
"""Gera index.html: o painel de página única alimentado por data/raw.

Um só ficheiro, sem CDN e sem rede: os dados vão embebidos e a página abre
offline. É a mesma forma do csmRadar.

O payload é compacto por construção — índices em vez de nomes repetidos, e uma
série por par (indicador, instituição):

  inst  [{id, nome, regiao, distrito, tipo, lat, lon, fusao}, …]
  ind   [{id, titulo, grupo, unidade, polaridade, cautela, …}, …]
  meses ["2013-01", …]                         eixo temporal partilhado
  s     {"<i>:<j>": [[m, num, den], …]}         i=indicador, j=instituição

Os valores mensais já vêm des-acumulados (ver ingest/build.py::desacumular): a
fonte publica acumulados desde janeiro, e somá-los daria cinco vezes o real.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ingest"))

import duckdb  # noqa: E402

from build import (  # noqa: E402
    LIMIAR_DENOMINADOR,
    _nao_somavel,
    carregar_indicadores,
    extrair_series,
)
from catalog import FICHEIRO_CATALOGO  # noqa: E402
from instituicoes import carregar  # noqa: E402

# Prefixo do sítio publicado. O portal vive numa subpasta do GitHub Pages, e não
# na raiz de um domínio — sem isto, a navegação do painel apontaria para
# github.io/perguntas/, que não existe. Tem de acompanhar o `base` de
# site/astro.config.mjs; se um dia o portal mudar para domínio próprio, os dois
# passam a "".
BASE_SITIO = "/snsRadar"

# Mesmas secções e mesma ordem do sítio (site/src/layouts/Base.astro), para
# que a navegação não mude de forma consoante a página.
NAV_SITIO = f"""<a class="nav-sitio-link" href="{BASE_SITIO}/perguntas/">Perguntas</a>\
<a class="nav-sitio-link" href="{BASE_SITIO}/instituicoes/">Instituições</a>\
<a class="nav-sitio-link" href="{BASE_SITIO}/" aria-current="page">Painel</a>\
<a class="nav-sitio-link" href="{BASE_SITIO}/metodologia/">Metodologia</a>\
<span class="nav-sep" aria-hidden="true"></span>"""

MODELO = RAIZ / "web" / "template.html"

# Ícones que o painel usa. Os traçados não são copiados para aqui: são
# extraídos do componente do sítio, para que não existam duas versões do mesmo
# ícone a divergir em silêncio. Se um deles mudar de forma, muda nos dois.
COMPONENTE_ICONES = RAIZ / "site" / "src" / "components" / "Icone.astro"
ICONES_DO_PAINEL = ["hospital", "grafico", "calendario", "pessoa", "pulso"]
# Na raiz do repositório, como no csmRadar: o painel é a porta de entrada do
# portal e o ficheiro que se descarrega para abrir offline. É o mesmo
# ficheiro nos dois papéis.
SAIDA = RAIZ / "index.html"
MAPA = RAIZ / "data" / "mapa" / "continente.json"

# Projeção do mapa: a mesma com que os contornos foram gerados, para que as
# instituições assentem sobre os distritos. Só continente — os Açores e a
# Madeira têm serviços regionais de saúde próprios e não constam desta fonte.
_LON0, _LON1, _LAT0, _LAT1 = -9.60, -6.15, 36.90, 42.20
_X0, _Y0, _W, _H = 6, 6, 340 - 12, 560 - 12


def projetar(lon: float, lat: float) -> tuple[float, float]:
    import math

    k = math.cos(math.radians((_LAT0 + _LAT1) / 2))
    s = min(_W / ((_LON1 - _LON0) * k), _H / (_LAT1 - _LAT0))
    return (_X0 + (lon - _LON0) * k * s, _Y0 + (_LAT1 - lat) * s)


def construir_payload():
    con = duckdb.connect()
    cw = carregar()
    indicadores = carregar_indicadores()
    catalogo = json.loads(FICHEIRO_CATALOGO.read_text(encoding="utf-8"))

    series, _ = extrair_series(con, cw, indicadores, catalogo)

    # Só entram instituições com dados; a ordem fixa os índices do payload.
    com_dados = {
        inst_id
        for ind in indicadores
        for inst_id in series[ind["id"]]
    }
    # Entidades que saíram do setor público não pertencem a um painel sobre o
    # SNS de hoje: o Hospital de Anadia foi devolvido à Misericórdia em 2014 e
    # os seus últimos registos apareceriam como zeros — ausência de dados
    # confundida com desempenho. A sua história fica no crosswalk.
    insts = [i for i in cw.instituicoes if i.id in com_dados and i.tipo != "extinto"]
    idx_inst = {i.id: n for n, i in enumerate(insts)}
    idx_ind = {ind["id"]: n for n, ind in enumerate(indicadores)}

    meses = sorted(
        {m for ind in indicadores for inst in series[ind["id"]].values() for m in inst}
    )
    idx_mes = {m: n for n, m in enumerate(meses)}

    s: dict[str, list] = {}
    for ind in indicadores:
        i = idx_ind[ind["id"]]
        for inst_id, por_mes in series[ind["id"]].items():
            if inst_id not in idx_inst:
                continue  # entidade excluída do painel (ver `insts` acima)
            pontos = []
            for mes in sorted(por_mes):
                d = por_mes[mes]
                num = round(d["num"], 3)
                den = round(d["den"], 3) if d["tem_den"] else None
                pontos.append([idx_mes[mes], num, den])
            if pontos:
                s[f"{i}:{idx_inst[inst_id]}"] = pontos

    def xy(inst):
        if not inst.geo:
            return None, None
        x, y = projetar(inst.geo["lon"], inst.geo["lat"])
        return round(x, 1), round(y, 1)

    return {
        "meses": meses,
        "limiar": LIMIAR_DENOMINADOR,
        "mapa": json.loads(MAPA.read_text(encoding="utf-8")),
        "inst": [
            {
                "id": i.id,
                "n": i.nome_curto,
                "nome": i.nome,
                "r": i.regiao,
                "d": i.distrito,
                "t": i.tipo,
                "x": xy(i)[0],
                "y": xy(i)[1],
                # Data a partir da qual o perímetro mudou, e se veio de fusão:
                # os gráficos marcam-na e as comparações têm de a respeitar.
                "q": i.data_descontinuidade,
                "fus": i.e_fusao,
                "sucessao": [
                    {"data": str(x["data"]), "lei": x["base_legal"], "de": x.get("de", [])}
                    for x in i.sucessao
                ],
            }
            for i in insts
        ],
        "ind": [
            {
                "id": ind["id"],
                "t": ind["titulo"],
                "g": ind["grupo"],
                "u": ind["unidade"],
                "p": ind["polaridade"],
                "desc": ind.get("descricao"),
                "cau": ind.get("cautela"),
                "ref": ind.get("referencia"),
                # Percentagem que pode passar dos 100 % sem ser erro.
                "livre100": bool(ind.get("pode_exceder_100")),
                "teto": ind.get("maximo_plausivel"),
                "jaTaxa": bool(ind.get("ja_e_taxa")),
                # Sem denominador não há taxa; sem soma possível não há total.
                "taxa": bool(ind.get("denominador")) or bool(ind.get("ja_e_taxa")),
                "soma": not _nao_somavel(ind)
                and ind.get("agregacao_temporal") != "ultimo",
                "ds": ind["dataset"],
                "pub": catalogo.get(ind["dataset"], {}).get("publisher"),
                "atu": (catalogo.get(ind["dataset"], {}).get("modificado") or "")[:10],
            }
            for ind in indicadores
        ],
        "s": s,
        # Camadas que não são séries mensais: mortalidade ajustada ao risco,
        # população servida, taxas por mil habitantes e contratos públicos.
        "extra": _enriquecimento(idx_inst),
    }


def _enriquecimento(idx_inst: dict) -> dict:
    caminho = RAIZ / "data" / "out" / "enriquecimento.json"
    if not caminho.exists():
        return {}
    d = json.loads(caminho.read_text(encoding="utf-8"))
    smr = d.get("mortalidade_ajustada", {})
    manter = lambda m: {k: v for k, v in (m or {}).items() if k in idx_inst}
    return {
        "smr": manter(smr.get("smr")),
        "smrSem": manter(smr.get("instituicoes_sem_smr")),
        "smrMetodo": smr.get("metodo"),
        "smrPeriodo": (
            f"{smr['meses_usados'][0]} a {smr['meses_usados'][-1]}"
            if smr.get("meses_usados") else None
        ),
        "pop": manter(d.get("populacao", {}).get("por_instituicao")),
        "perCapita": manter(d.get("per_capita")),
        "contratos": manter(d.get("contratos")),
    }


def sprite_de_icones() -> str:
    """Extrai do componente do sítio os ícones que o painel usa.

    O painel é um ficheiro autónomo e não consegue importar um componente
    Astro. A alternativa seria copiar os traçados para `app.js` — e ficar com
    duas versões do mesmo ícone, que divergem à primeira correção. Aqui
    lêem-se do original e escrevem-se como `<symbol>`, uma só vez, para que
    `<use>` os repita sem repetir o desenho.

    A extração é deliberadamente estrita: se um nome deixar de existir ou o
    bloco mudar de forma, a construção do painel falha alto em vez de produzir
    um painel sem ícones que ninguém repara.
    """
    fonte = COMPONENTE_ICONES.read_text(encoding="utf-8")
    simbolos = []
    for nome in ICONES_DO_PAINEL:
        # `nome === "x" && (` … até ao fecho do bloco JSX correspondente.
        achado = re.search(
            rf'nome === "{nome}" &&\s*\(\s*(<>)?(?P<corpo>.*?)(</>)?\s*\)\s*\n\s*\}}',
            fonte,
            re.S,
        )
        if not achado:
            sys.exit(f"ícone «{nome}» não encontrado em {COMPONENTE_ICONES.name}")
        corpo = achado.group("corpo").strip()
        if "<" not in corpo:
            sys.exit(f"ícone «{nome}»: bloco extraído não contém desenho")
        simbolos.append(f'<symbol id="ic-{nome}" viewBox="0 0 24 24">{corpo}</symbol>')

    return (
        '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
        + "".join(simbolos)
        + "</svg>"
    )


def main() -> int:
    if not MODELO.exists():
        sys.exit(f"modelo em falta: {MODELO}")


    payload = construir_payload()
    bruto = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Impede que uma sequência dentro dos dados feche o <script> que os embebe.
    bruto = bruto.replace("</", "<\\/")

    modelo = MODELO.read_text(encoding="utf-8")
    if "__DATA_JSON__" not in modelo:
        sys.exit("marcador __DATA_JSON__ não encontrado no modelo")

    # A lógica vive em web/app.js para ser legível e revista; a saída embebe-a,
    # porque o painel tem de ser um único ficheiro que abre offline.
    modelo = modelo.replace("<!--SPRITE-ICONES-->", sprite_de_icones())

    app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    html = modelo.replace(
        '<script src="app.js"></script>',
        "<script>\n" + app.replace("</", "<\\/") + "\n</script>",
    ).replace("__DATA_JSON__", bruto)

    if "app.js" in html.split("</style>")[-1][:2000] or 'src="' in html:
        sys.exit("o resultado ainda refere um ficheiro externo — não seria autónomo")

    # Duas versões do mesmo painel, e a diferença é uma só: a navegação para o
    # resto do portal.
    #
    #   index.html na raiz  — o que o portal serve. Leva navegação, porque de lá
    #                         se chega às fichas, às perguntas e à metodologia.
    #   dist/painel.html    — para descarregar e abrir do disco. Sem navegação:
    #                         num ficheiro aberto em file:// as ligações para
    #                         /perguntas/ não vão a lado nenhum, e uma ligação
    #                         que não funciona é pior do que ligação nenhuma.
    SAIDA.write_text(html.replace("<!--NAV-SITIO-->", NAV_SITIO), encoding="utf-8")

    offline = RAIZ / "dist" / "painel.html"
    offline.parent.mkdir(exist_ok=True)
    offline.write_text(html.replace("<!--NAV-SITIO-->", ""), encoding="utf-8")

    n_pontos = sum(len(v) for v in payload["s"].values())
    print(
        f"{SAIDA.relative_to(RAIZ)} — {SAIDA.stat().st_size / 1024:,.0f} KB | "
        f"{len(payload['inst'])} instituições, {len(payload['ind'])} indicadores, "
        f"{n_pontos:,} pontos, {len(payload['meses'])} meses "
        f"({payload['meses'][0]} a {payload['meses'][-1]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
