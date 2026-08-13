#!/usr/bin/env python3
"""Reconstrói o snsRadar de ponta a ponta, pela ordem certa.

A ordem não é arbitrária e não é óbvia: `enriquecer` precisa das fichas já
escritas para calcular taxas por mil habitantes, e as fichas precisam do
enriquecimento para o mostrarem. Daí a dupla passagem pelo `build`. Quem correr
os passos à mão pela ordem errada obtém fichas silenciosamente incompletas —
sem erro nenhum, apenas cartões em falta.

    python atualizar.py                 # tudo, sem voltar a descarregar
    python atualizar.py --descarregar   # inclui nova ingestão da fonte
    python atualizar.py --site          # inclui a construção do sítio Astro

Cada passo falha alto: um erro a meio interrompe tudo em vez de deixar meia
reconstrução no lugar.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PY = RAIZ / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)


def passo(descricao: str, comando: list[str], cwd: Path | None = None) -> float:
    inicio = time.monotonic()
    print(f"\n\033[1m▸ {descricao}\033[0m")
    r = subprocess.run(comando, cwd=cwd or RAIZ)
    if r.returncode != 0:
        print(f"\n\033[31m✗ falhou: {descricao}\033[0m")
        sys.exit(r.returncode)
    return time.monotonic() - inicio


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--descarregar", action="store_true",
                   help="volta a descarregar os dados da fonte")
    p.add_argument("--site", action="store_true",
                   help="constrói também o sítio Astro (exige npm install)")
    p.add_argument("--sem-testes", action="store_true",
                   help="salta a verificação; use apenas em iteração local")
    args = p.parse_args()

    tempos: list[tuple[str, float]] = []

    if args.descarregar:
        tempos.append(("catálogo", passo(
            "Espelhar o catálogo dos 144 datasets",
            [str(PY), "ingest/catalog.py"])))
        tempos.append(("ingestão", passo(
            "Descarregar os datasets do núcleo",
            [str(PY), "ingest/fetch.py"])))
        # O registo de contratos vem do IMPIC, não do portal do SNS, e por isso
        # tem descarga própria. São ~420 MB comprimidos; os ficheiros que já
        # existirem em disco não voltam a ser pedidos.
        tempos.append(("contratos IMPIC", passo(
            "Descarregar o registo de contratos do IMPIC",
            [str(PY), "ingest/impic.py", "--descarregar"])))
        # O Benchmarking da ACSS é a segunda fonte de indicadores: traz a
        # dimensão de segurança do doente, o volume cirúrgico e as métricas por
        # doente padrão, que o portal não publica — e os grupos de comparação.
        # As exportações já descarregadas ficam em cache; só se pedem de novo as
        # que faltam.
        tempos.append(("benchmarking ACSS", passo(
            "Descarregar o Benchmarking Hospitalar da ACSS",
            [str(PY), "ingest/benchmarking_acss.py"])))
        tempos.append(("snapshot", passo(
            "Registar hashes e validar contra a fonte",
            [str(PY), "ingest/snapshot.py"])))

    # Primeira passagem: as fichas que o enriquecimento precisa de ler.
    tempos.append(("build 1/2", passo(
        "Construir as fichas (1.ª passagem)",
        [str(PY), "ingest/build.py"])))

    # Contexto europeu: rede externa, e por isso tolerante a falhas — sem ele
    # o sítio constrói na mesma, apenas sem a comparação internacional.
    tempos.append(("contexto europeu", passo(
        "Contexto europeu (Eurostat)",
        [str(PY), "ingest/eurostat.py"])))

    tempos.append(("enriquecimento", passo(
        "Mortalidade ajustada ao risco, população, per capita e contratos",
        [str(PY), "ingest/enriquecer.py"])))

    # Segunda passagem: agora com o enriquecimento disponível para embeber.
    tempos.append(("build 2/2", passo(
        "Reconstruir as fichas já com o enriquecimento",
        [str(PY), "ingest/build.py"])))

    tempos.append(("painel", passo(
        "Gerar o painel autónomo",
        [str(PY), "scripts/build_dashboard.py"])))

    if args.site:
        tempos.append(("sítio", passo(
            "Construir o sítio Astro",
            ["npx", "astro", "build"], cwd=RAIZ / "site")))

    if not args.sem_testes:
        for nome in ("test_crosswalk", "test_build", "test_validacao_externa",
                     "test_benchmarking_acss"):
            tempos.append((nome, passo(
                f"Verificar: {nome}", [str(PY), f"tests/{nome}.py"])))

    total = sum(t for _, t in tempos)
    print("\n\033[1m✓ reconstrução completa\033[0m")
    for nome, t in tempos:
        print(f"    {t:6.1f}s  {nome}")
    print(f"    {'─' * 6}")
    print(f"    {total:6.1f}s  total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
