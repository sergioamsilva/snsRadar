#!/usr/bin/env bash
#
# Atualização periódica do snsRadar.
#
# A fonte publica mensalmente e revê valores em silêncio. O sistema de snapshots
# deteta essas revisões — mas só se alguém o correr. Este script fecha o ciclo.
#
# Instalar como tarefa semanal (segundas às 06:00):
#
#   crontab -e
#   0 6 * * 1 /home/parallels/projects/snsRadar/scripts/atualizacao_agendada.sh
#
# Escreve um registo por execução em data/snapshots/registo/. Devolve 0 mesmo
# quando não há novidades; devolve 1 se a verificação falhar, para que uma
# monitorização externa possa reparar.

set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$RAIZ/.venv/bin/python"
REGISTO_DIR="$RAIZ/data/snapshots/registo"
CARIMBO="$(date -u +%Y%m%dT%H%M%SZ)"
REGISTO="$REGISTO_DIR/$CARIMBO.log"

mkdir -p "$REGISTO_DIR"
cd "$RAIZ" || exit 1

exec > >(tee -a "$REGISTO") 2>&1
echo "snsRadar — atualização de $(date -u '+%Y-%m-%d %H:%M UTC')"
echo

# --descarregar traz dados novos e o snapshot compara-os com a ingestão
# anterior, listando os datasets que a fonte reviu desde a última vez.
if ! "$PY" atualizar.py --descarregar --site; then
  echo
  echo "FALHOU. Os dados anteriores continuam publicados — nada foi substituído"
  echo "por uma reconstrução parcial, porque atualizar.py interrompe ao primeiro erro."
  exit 1
fi

echo
echo "── alterações detetadas na fonte ──"
"$PY" - <<'FIM'
import json, pathlib, sys

snaps = sorted(pathlib.Path("data/snapshots").glob("manifesto-2*.json"))
if len(snaps) < 2:
    print("  primeira ingestão: nada com que comparar")
    sys.exit()

anterior = json.loads(snaps[-2].read_text(encoding="utf-8"))["datasets"]
atual = json.loads(snaps[-1].read_text(encoding="utf-8"))["datasets"]

revistos = [k for k in anterior.keys() & atual.keys()
            if anterior[k]["sha256"] != atual[k]["sha256"]]
novos = sorted(atual.keys() - anterior.keys())
sumidos = sorted(anterior.keys() - atual.keys())

if not (revistos or novos or sumidos):
    print("  nenhum dataset mudou desde a última execução")
for k in sorted(revistos):
    d = atual[k]["registos"] - anterior[k]["registos"]
    print(f"  revisto   {k} ({d:+,} registos)")
for k in novos:
    print(f"  novo      {k}")
for k in sumidos:
    # Um dataset que desaparece da fonte é notícia, não um detalhe técnico.
    print(f"  SUMIU     {k} — deixou de ser publicado pela fonte")
FIM

echo
echo "registo em ${REGISTO#$RAIZ/}"

# Mantém os últimos 60 registos; os manifestos ficam todos, porque são a prova
# do que a fonte dizia em cada data.
ls -1t "$REGISTO_DIR" | tail -n +61 | while read -r f; do rm -f "$REGISTO_DIR/$f"; done
