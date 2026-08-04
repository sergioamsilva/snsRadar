"""Leitura de segredos a partir de fora da árvore do projeto.

Nada de credenciais no repositório, nem em `data/`, nem em nada que o site
publique. O ficheiro vive em `~/.config/snsradar/segredos.env` com permissões
`600`, e as variáveis de ambiente têm precedência para que o CI possa injetá-las
sem escrever ficheiro nenhum.

Formato: `CHAVE=valor` por linha, `#` inicia comentário.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

FICHEIRO = Path.home() / ".config" / "snsradar" / "segredos.env"

_cache: dict[str, str] | None = None


def _ler_ficheiro() -> dict[str, str]:
    if not FICHEIRO.exists():
        return {}
    # Um ficheiro de segredos legível por outros é um segredo que já não é
    # segredo — vale mais avisar do que fingir que está tudo bem.
    modo = FICHEIRO.stat().st_mode
    if modo & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"aviso: {FICHEIRO} está acessível a outros; corrija com chmod 600")

    valores: dict[str, str] = {}
    for linha in FICHEIRO.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip("'\"")
    return valores


def obter(chave: str, obrigatorio: bool = False) -> str | None:
    """Devolve o segredo, do ambiente ou do ficheiro, por esta ordem."""
    global _cache
    if valor := os.environ.get(chave):
        return valor
    if _cache is None:
        _cache = _ler_ficheiro()
    valor = _cache.get(chave)
    if not valor and obrigatorio:
        raise RuntimeError(
            f"falta o segredo {chave}: defina-o no ambiente ou em {FICHEIRO}"
        )
    return valor or None
