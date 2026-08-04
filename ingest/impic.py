"""Contratos públicos do Portal BASE, na fonte primária (IMPIC).

## Porque não bastava o que já havia

O Portal da Transparência do SNS espelha uma fatia do Portal BASE no dataset
`portal-base`: 32 unidades, 10 807 contratos, 165 M€, e só desde 2024. Com esse
espelho apenas 9 das 43 instituições tinham volume suficiente para publicar
alguma coisa — as outras 34 ficavam com a secção do dinheiro vazia.

O IMPIC publica o registo integral em dados.gov.pt, em **domínio público**
declarado (`other-pd`), atualizado ao dia: contratos, modificações contratuais e
entidades, de 2012 a 2026. Só o ano de 2025 traz 80 640 contratos das unidades
do SNS — sete vezes mais do que o espelho tem em dois anos e meio.

## Duas fontes, de propósito

Existem dois caminhos para os mesmos 39 campos, e nenhum deles chega sozinho:

- **Os *dumps* de dados.gov.pt** são a espinha. São os únicos que preenchem
  `idcontrato`, e é esse campo que liga um contrato às suas modificações — sem
  ele perdia-se a derrapagem, que é o dado mais interessante de todos.
- **A API do Portal BASE** (`APIBase2`, token do IMPIC) consulta por
  `nifEntidade` sem descarregar nada, mas devolve `idContrato` sempre a `null`.
  Serve para duas coisas que os *dumps* não fazem: confirmar os nossos totais
  contra os do próprio servidor (`GetInfoEntidades`) e atualizar os últimos
  90 dias sem repuxar 55 MB (`numDias`).

A API é sempre opcional. Sem token o pipeline corre na mesma, só perde a
verificação independente.

## A chave de junção é o NIF

O nome de uma entidade muda — «Centro Hospitalar Lisboa Norte, EPE» passou a
«Unidade Local de Saúde de Santa Maria, E. P. E.». O NIF não muda. Por isso a
correspondência instituição↔contratos faz-se por NIF, semeado a partir do
ficheiro de entidades do IMPIC e resolvido pelo crosswalk que já existe.
"""

from __future__ import annotations

import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from common import DIR_BRUTO, TEMPO_LIMITE, TENTATIVAS
from segredos import obter

DIR_IMPIC = DIR_BRUTO / "impic"

CATALOGO = "https://dados.gov.pt/api/1/datasets/?q=contratos%20base%20impic&page_size=30"

# Os títulos dos datasets do IMPIC trazem o intervalo de anos lá dentro, que
# muda todos os janeiros. Casar por um fragmento estável evita partir a cada ano.
FAMILIAS = {
    "contratos": "Contratos de 2012 a",
    "modificacoes": "Modificações Contratuais",
    "entidades": "Entidades",
}

API_BASE = "https://www.base.gov.pt/APIBase2"
CABECALHO_TOKEN = "_AcessToken"  # a grafia é do IMPIC, não é gralha nossa.

_NIF = re.compile(r"\b(\d{9})\b")


# ── descarga ────────────────────────────────────────────────────────────────


def _obter(url: str) -> bytes:
    ultimo: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": "snsRadar/1.0"})
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
                return resposta.read()
        except (urllib.error.URLError, TimeoutError) as erro:  # noqa: PERF203
            ultimo = erro
            time.sleep(2**tentativa)
    raise RuntimeError(f"falhou {url}: {ultimo}")


def recursos() -> dict[str, list[dict]]:
    """Enumera os ficheiros publicados pelo IMPIC, por família."""
    catalogo = json.loads(_obter(CATALOGO))
    saida: dict[str, list[dict]] = {}
    for dataset in catalogo.get("data", []):
        org = ((dataset.get("organization") or {}).get("name") or "").upper()
        if "IMPIC" not in org:
            continue
        familia = next(
            (nome for nome, marca in FAMILIAS.items() if marca in dataset["title"]),
            None,
        )
        if not familia:
            continue
        saida[familia] = [
            {"titulo": r["title"], "url": r["url"], "bytes": r.get("filesize")}
            for r in dataset.get("resources", [])
            if r.get("format") in ("zip", "json")
        ]
    em_falta = set(FAMILIAS) - set(saida)
    if em_falta:
        raise RuntimeError(f"famílias do IMPIC não encontradas em dados.gov.pt: {em_falta}")
    return saida


def _descomprimir(bruto: bytes, titulo: str) -> bytes:
    """Os contratos vêm em ZIP; modificações e entidades vêm em JSON simples."""
    if not titulo.endswith(".zip"):
        return bruto
    with zipfile.ZipFile(io.BytesIO(bruto)) as z:
        nomes = [n for n in z.namelist() if n.lower().endswith(".json")]
        if len(nomes) != 1:
            raise RuntimeError(f"{titulo}: esperava um JSON no ZIP, encontrei {nomes}")
        return z.read(nomes[0])


def descarregar(forcar: bool = False) -> list[Path]:
    """Traz os ficheiros do IMPIC para `data/raw/impic/`, em JSON comprimido.

    Descomprimido, o registo completo passa dos 6 GB — os contratos de um só ano
    chegam aos 500 MB. Guardado em `.gz` fica na ordem dos 400 MB, e tanto o
    DuckDB como o `gzip` do Python leem-no diretamente, pelo que nada a jusante
    precisa de saber a diferença. É a mesma convenção do resto de `data/raw/`.
    """
    import gzip

    DIR_IMPIC.mkdir(parents=True, exist_ok=True)
    guardados: list[Path] = []
    for familia, lista in recursos().items():
        for recurso in lista:
            nome = recurso["titulo"].removesuffix(".zip").removesuffix(".json")
            destino = DIR_IMPIC / f"{familia}__{nome}.json.gz"
            if destino.exists() and not forcar:
                guardados.append(destino)
                continue
            bruto = _descomprimir(_obter(recurso["url"]), recurso["titulo"])
            # `mtime=0` para que dois ficheiros com o mesmo conteúdo tenham o
            # mesmo SHA-256 — senão o manifesto de snapshots acusava alteração
            # em todas as execuções.
            with gzip.GzipFile(destino, "wb", compresslevel=6, mtime=0) as saida:
                saida.write(bruto)
            print(
                f"  {destino.name}  {len(bruto) / 1e6:.0f} MB "
                f"→ {destino.stat().st_size / 1e6:.0f} MB"
            )
            guardados.append(destino)
    return guardados


def ficheiros(familia: str) -> list[Path]:
    return sorted(DIR_IMPIC.glob(f"{familia}__*.json.gz"))


def ler(caminho: Path) -> list[dict]:
    import gzip

    with gzip.open(caminho, "rt", encoding="utf-8") as ficheiro:
        return json.load(ficheiro)


# ── correspondência NIF ↔ instituição ───────────────────────────────────────


def nifs_por_instituicao(crosswalk) -> dict[str, str]:
    """Devolve `{nif: id_da_instituicao}`.

    Semeia-se do ficheiro `entidades` do IMPIC, que dá o par NIF↔designação
    para todo o universo de entidades adjudicantes do país. O crosswalk decide
    quais dessas designações são instituições do SNS que já conhecemos — e como
    já reconhece todas as grafias históricas, apanha os NIF das entidades
    extintas em 2024 e liga-os à ULS que as sucedeu.
    """
    caminhos = ficheiros("entidades")
    if not caminhos:
        raise RuntimeError("falta o ficheiro de entidades do IMPIC; corra descarregar()")

    mapa: dict[str, str] = {}
    for caminho in caminhos:
        for entidade in ler(caminho):
            designacao = entidade.get("desigEntidade") or ""
            nif = str(entidade.get("nifEntidade") or "").strip()
            if not nif or not _NIF.fullmatch(nif):
                continue
            instituicao = crosswalk.resolver(designacao)
            if instituicao:
                mapa[nif] = instituicao.id
    return mapa


def nif_do_adjudicante(contrato: dict) -> str | None:
    """Extrai o NIF do adjudicante, que vem como `["508481287 - Nome, E. P. E."]`."""
    adjudicantes = contrato.get("adjudicante") or []
    if isinstance(adjudicantes, str):
        adjudicantes = [adjudicantes]
    for entrada in adjudicantes:
        if achado := _NIF.match(str(entrada).strip()):
            return achado.group(1)
    return None


# ── API do Portal BASE (opcional) ───────────────────────────────────────────


def token() -> str | None:
    return obter("BASE_GOV_TOKEN")


def _api(recurso: str, **parametros) -> list[dict]:
    chave = token()
    if not chave:
        raise RuntimeError("sem BASE_GOV_TOKEN: a API do Portal BASE não está disponível")
    consulta = "&".join(f"{k}={v}" for k, v in parametros.items() if v is not None)
    pedido = urllib.request.Request(
        f"{API_BASE}/{recurso}?{consulta}",
        headers={CABECALHO_TOKEN: chave, "User-Agent": "snsRadar/1.0"},
    )
    with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
        dados = json.loads(resposta.read())
    if isinstance(dados, dict):
        # Os erros chegam com HTTP 200 e um objeto no corpo, não com estado 4xx.
        if erro := dados.get("Error") or dados.get("error"):
            raise RuntimeError(f"{recurso}: {erro}")
        return [dados]
    return dados


def totais_do_servidor(nif: str) -> dict | None:
    """Totais que o próprio Portal BASE atribui a uma entidade.

    Usado só para conferir os nossos: se a nossa soma se afastar destes, é
    porque perdemos contratos ou contámos a dobrar.
    """
    try:
        registos = _api("GetInfoEntidades", nifEntidade=nif)
    except (RuntimeError, urllib.error.URLError):
        return None
    return registos[0] if registos else None


def contratos_recentes(nif: str, dias: int = 90) -> list[dict]:
    """Contratos dos últimos `dias` (máximo 90, imposto pela API)."""
    return _api("GetInfoContrato", nifEntidade=nif, numDias=min(dias, 90))


if __name__ == "__main__":
    import sys

    if "--descarregar" in sys.argv:
        print("A descarregar o registo do IMPIC…")
        descarregar(forcar="--forcar" in sys.argv)
    else:
        for familia, lista in recursos().items():
            total = sum(r["bytes"] or 0 for r in lista)
            print(f"{familia:14s} {len(lista):2d} ficheiros · {total / 1e6:7.1f} MB")
