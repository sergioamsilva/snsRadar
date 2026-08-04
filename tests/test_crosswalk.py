"""Verificações do crosswalk de instituições.

Correr com:  .venv/bin/python tests/test_crosswalk.py

Não usa pytest de propósito: o pipeline tem de poder ser verificado por quem
clona o repositório sem instalar nada além do que ingest/ já exige.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ingest"))

import duckdb  # noqa: E402
import yaml  # noqa: E402

from common import DIR_BRUTO, DIR_REFERENCIA  # noqa: E402
from instituicoes import carregar  # noqa: E402


def _nao_prestadoras() -> set[str]:
    """Chaves declaradas como não sendo instituições prestadoras de cuidados."""
    dados = yaml.safe_load(
        (DIR_REFERENCIA / "entidades-nao-prestadoras.yaml").read_text(encoding="utf-8")
    )
    return {chave for grupo in dados.values() for chave in grupo}


IGNORAR = _nao_prestadoras() | {"total", "nacional", "continente"}

# Conjuntos de dados em que a fonte manteve, durante a transição, linhas das
# entidades antecessoras a par da sucessora. Em março de 2023 o CHU de Santo
# António aparece com 115 dias de prazo médio de pagamento, ao lado do CHU do
# Porto com 193 e do Magalhães Lemos com 8 — três valores para uma entidade que
# já era uma só. São métricas que o build não soma.
TRANSICAO_TOLERADA = {"tempo-medio-de-pagamento-das-instituicoes-do-sns-a-fornecedores"}


def _rel(dataset_id: str) -> str:
    caminho = DIR_BRUTO / f"{dataset_id}.csv.gz"
    return (
        f"read_csv('{caminho}', delim=';', header=true, quote='\"', "
        "escape='\"', sample_size=-1, all_varchar=true)"
    )


def _datasets_com_instituicao(con):
    """Datasets ao nível da instituição, com a coluna de nome e a de tempo."""
    saida = []
    for caminho in sorted(DIR_BRUTO.glob("*.csv.gz")):
        dataset_id = caminho.name[: -len(".csv.gz")]
        cols = [r[0] for r in con.execute(f"describe select * from {_rel(dataset_id)}").fetchall()]
        col = "instituicao" if "instituicao" in cols else ("entidade" if "entidade" in cols else None)
        if not col:
            continue
        tempo = next((c for c in ("tempo", "periodo", "ano") if c in cols), None)
        saida.append((dataset_id, col, tempo))
    return saida


def teste_cobertura(con, cw) -> list[str]:
    """Todo o nome que a fonte usa tem de resolver para uma entidade canónica.

    Se falhar, é porque a fonte introduziu ou renomeou uma instituição: o
    crosswalk tem de ser atualizado à mão antes de o site voltar a publicar.
    """
    from common import normalizar_agressivo

    por_resolver: dict[str, set[str]] = {}
    for dataset_id, col, _ in _datasets_com_instituicao(con):
        nomes = con.execute(
            f"select distinct {col} from {_rel(dataset_id)} where {col} is not null"
        ).fetchall()
        for (nome,) in nomes:
            nome = nome.strip()
            if normalizar_agressivo(nome) in IGNORAR:
                continue
            if cw.resolver(nome) is None:
                por_resolver.setdefault(nome, set()).add(dataset_id)

    # Tolerância zero, deliberadamente. Um limiar («ignorar nomes presentes em
    # menos de N datasets») deixaria passar variantes reais de hospitais: foi
    # exatamente assim que «Centro Hospitalar Cova da Beira» e «Hospital Garcia
    # de Orta - Almada» quase ficaram de fora das fichas.
    return [f"{n}  [{len(d)} datasets: {', '.join(sorted(d)[:2])}]"
            for n, d in sorted(por_resolver.items())]


def teste_sem_sobreposicao(con, cw) -> list[str]:
    """Duas grafias da mesma entidade não podem coexistir depois da fusão.

    Antes da data de fusão, vários nomes no mesmo mês são esperados: são as
    entidades que vieram a ser fundidas, e somá-las é precisamente como se
    reconstrói o perímetro atual para trás no tempo (a ULS de Coimbra de 2013 é
    o Centro Hospitalar e Universitário mais o Arcebispo João Crisóstomo mais o
    Rovisco Pais).

    A partir da fusão — e sempre, para quem nunca foi fundido — dois nomes no
    mesmo mês só podem ser grafias duplicadas, e somá-las duplicaria a
    atividade do hospital.
    """
    erros = []
    for dataset_id, col, tempo in _datasets_com_instituicao(con):
        if not tempo:
            continue
        cols = [r[0] for r in con.execute(f"describe select * from {_rel(dataset_id)}").fetchall()]
        metricas = [
            c for c in cols
            if c not in (col, tempo, "regiao", "localizacao_geografica", "ars", "aces")
        ]
        linhas = con.execute(
            f"select {col}, {tempo} from {_rel(dataset_id)} "
            f"where {col} is not null and {tempo} is not null group by 1, 2"
        ).fetchall()

        por_entidade_periodo: dict[tuple[str, str], set[str]] = {}
        for nome, periodo in linhas:
            inst = cw.resolver(nome.strip())
            if inst is None:
                continue
            chave = (inst.id, str(periodo)[:10])
            por_entidade_periodo.setdefault(chave, set()).add(nome.strip())

        for (inst_id, periodo), nomes in sorted(por_entidade_periodo.items()):
            if len(nomes) == 1:
                continue
            inst = cw.por_id(inst_id)
            fusao = inst.data_ultima_fusao
            # `periodo` pode ser só o ano (dataset trimestral); comparamos pelo
            # prefixo comum para não dar falso negativo.
            if fusao and periodo[: len(fusao)] < fusao[: len(periodo)]:
                continue
            if _todas_sem_atividade(con, dataset_id, col, tempo, metricas, nomes, periodo):
                continue
            if dataset_id in TRANSICAO_TOLERADA:
                # Neste conjunto de dados a fonte continuou a reportar as
                # entidades antecessoras durante a transição. O build não as
                # soma — trata-as pela média, ver build.py::_nao_somavel.
                continue
            if _valores_identicos(con, dataset_id, col, tempo, metricas, nomes, periodo):
                # A fonte publica a mesma unidade sob dois rótulos, com valores
                # iguais — o Hospital de Loures aparece como EPE e como PPP.
                # O build descarta o duplicado (ver build.py::_rotulos_duplicados);
                # aqui basta reconhecer que não há dupla contagem por resolver.
                continue
            erros.append(f"{dataset_id} | {inst_id} | {periodo}: {sorted(nomes)}")
    return erros


def _valores_identicos(con, dataset_id, col, tempo, metricas, nomes, periodo) -> bool:
    """True se todos os rótulos em conflito têm exatamente as mesmas métricas."""
    if not metricas:
        return False
    assinaturas = set()
    for nome in nomes:
        expr = ", ".join(f"coalesce(try_cast({m} as double), 0)" for m in metricas)
        linhas = con.execute(
            f"select {expr} from {_rel(dataset_id)} "
            f"where {col} = ? and cast({tempo} as varchar) like ? order by all",
            [nome, f"{periodo}%"],
        ).fetchall()
        assinaturas.add(tuple(linhas))
    return len(assinaturas) == 1


def _todas_sem_atividade(con, dataset_id, col, tempo, metricas, nomes, periodo) -> bool:
    """True se, tirando uma, as grafias em conflito têm todas as métricas a zero.

    A fonte mantém registos residuais de entidades já extintas — o Centro
    Hospitalar Psiquiátrico de Lisboa, absorvido pela ULS de São José em
    janeiro de 2024, ainda aparece em setembro de 2024 e abril de 2025 com
    dívida, dívida vencida e pagamentos todos a zero. Somar zero não duplica
    nada, e por isso não é erro.
    """
    if not metricas:
        return False
    com_atividade = 0
    for nome in nomes:
        expr = " + ".join(f"coalesce(try_cast({m} as double), 0)" for m in metricas)
        total = con.execute(
            f"select sum(abs({expr})) from {_rel(dataset_id)} "
            f"where {col} = ? and cast({tempo} as varchar) like ?",
            [nome, f"{periodo}%"],
        ).fetchone()[0]
        if total:
            com_atividade += 1
    return com_atividade <= 1


def teste_continuidade(con, cw) -> list[str]:
    """As entidades que sucederam a outras têm de ter série antes e depois.

    Prova que o crosswalk faz o que promete: ligar a história partida em 2024.
    """
    erros = []
    dataset_id, col, tempo = "partos-e-cesarianas", "instituicao", "tempo"
    linhas = con.execute(
        f"select {col}, {tempo} from {_rel(dataset_id)} where {col} is not null"
    ).fetchall()

    antes: dict[str, int] = {}
    depois: dict[str, int] = {}
    for nome, periodo in linhas:
        inst = cw.resolver(nome.strip())
        if inst is None:
            continue
        alvo = antes if str(periodo)[:10] < "2024-01-01" else depois
        alvo[inst.id] = alvo.get(inst.id, 0) + 1

    for inst in cw.instituicoes:
        if not inst.sucessao:
            continue
        if inst.id in depois and inst.id not in antes:
            erros.append(f"{inst.id}: sem série anterior a 2024 (sucessão não ligou)")
    return erros


def main() -> int:
    con = duckdb.connect()
    cw = carregar()
    print(f"crosswalk: {len(cw)} entidades canónicas, "
          f"{sum(len(i.chaves) for i in cw.instituicoes)} chaves\n")

    falhou = False
    for nome, funcao in [
        ("cobertura de nomes", teste_cobertura),
        ("sem sobreposição de grafias", teste_sem_sobreposicao),
        ("continuidade através de 2024", teste_continuidade),
    ]:
        erros = funcao(con, cw)
        if erros:
            falhou = True
            print(f"  FALHA  {nome}: {len(erros)} problema(s)")
            for e in erros[:25]:
                print(f"           {e}")
            if len(erros) > 25:
                print(f"           ... e mais {len(erros) - 25}")
        else:
            print(f"  ok     {nome}")

    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
