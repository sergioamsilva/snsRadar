"""Definições partilhadas pelo pipeline de ingestão do snsRadar."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data"
DIR_BRUTO = DIR_DADOS / "raw"
DIR_SAIDA = DIR_DADOS / "out"
DIR_SNAPSHOTS = DIR_DADOS / "snapshots"
DIR_REFERENCIA = RAIZ / "reference"

API = "https://transparencia.sns.gov.pt/api/explore/v2.1"
PORTAL = "https://transparencia.sns.gov.pt"

# O endpoint /records recusa offset+limit > 10000, pelo que a ingestão completa
# tem obrigatoriamente de passar por /exports. Ver reference/NOTAS.md.
LIMITE_RECORDS = 10_000

TEMPO_LIMITE = 180
TENTATIVAS = 4


# Palavras de ligação e sufixos jurídicos que a fonte grafa de forma instável.
# Ex.: «Unidade Local de Saúde de Castelo Branco, EPE» (2013-2023) passou a
# «Unidade Local de Saúde Castelo Branco, EPE» (2024-) — mesma entidade.
_LIGACAO = {"de", "da", "do", "das", "dos", "e"}

# A forma jurídica aparece como EPE, E.P.E., E. P. E., e até «, EPE, EPE».
# Aplicada depois de a pontuação virar espaço, para que todas as variantes se
# reduzam à mesma sequência de tokens («e p e» ou «epe»).
_FORMA_JURIDICA = re.compile(
    r"(?:^|\s)(?:e\s+p\s+e|epe|s\s+a|sa|ppp|p\s+p\s+p|ipss|spa|i\s+p|ip)(?=\s|$)"
)

# Sigla acrescentada ao fim do nome, entre parênteses: «(ULSAM)», «(CHUC)».
# Só maiúsculas, dígitos e pontos, para não apanhar «(Hospital de Dia)» nem
# nenhuma outra qualificação que faça parte do nome.
_SIGLA_FINAL = re.compile(r"\s*\([A-ZÇÃÕÁÉÍÓÚÂÊÔ][A-Z0-9ÇÃÕÁÉÍÓÚÂÊÔ.\- ]{1,14}\)\s*$")


def normalizar(texto: str) -> str:
    """Reduz um nome de instituição à sua forma comparável.

    Remove acentos, pontuação e sufixos jurídicos (EPE / E.P.E. / E. P. E.).
    Usado apenas para *semear* o crosswalk — a correspondência final é sempre
    por chave declarada em reference/instituicoes.yaml, curada à mão.
    """
    if not texto:
        return ""
    # O registo de entidades do IMPIC junta a sigla ao nome — «Unidade Local de
    # Saúde do Alto Minho, EPE (ULSAM)». A sigla não distingue nada, mas
    # impedia a correspondência e custou 11 072 contratos dessa unidade. Cai
    # antes de tudo o resto, enquanto os parênteses ainda existem.
    texto = _SIGLA_FINAL.sub("", texto)
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    for c in ",.;:/\\-–—()'\"":
        t = t.replace(c, " ")
    t = " ".join(t.split())
    # Repetido porque «oeste epe epe» precisa de duas passagens: cada remoção
    # consome o espaço à esquerda de que a seguinte necessita.
    anterior = None
    while anterior != t:
        anterior = t
        t = " ".join(_FORMA_JURIDICA.sub(" ", t).split())
    return t


def normalizar_agressivo(texto: str) -> str:
    """Forma ainda mais reduzida, para *sugerir* fusões à revisão humana.

    Descarta também palavras de ligação. É demasiado permissiva para decidir
    sozinha — «ULS do Alto Ave» e «ULS do Médio Ave» continuam distintas, mas
    o risco de falsos positivos existe. Nunca usar para juntar automaticamente.
    """
    return " ".join(p for p in normalizar(texto).split() if p not in _LIGACAO)


def garantir_dirs() -> None:
    for d in (DIR_BRUTO, DIR_SAIDA, DIR_SNAPSHOTS, DIR_REFERENCIA):
        d.mkdir(parents=True, exist_ok=True)
