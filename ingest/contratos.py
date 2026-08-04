"""Agregação dos contratos públicos por instituição do SNS.

Consome o registo do IMPIC (ver ingest/impic.py) e produz, para cada unidade,
o que uma pessoa quer mesmo saber sobre o dinheiro:

  · quanto contratou, por ano, desde 2012
  · por que via — o peso do ajuste direto, que dispensa concorrência
  · a quem — os maiores fornecedores
  · em quê — os maiores capítulos de CPV
  · quanto **cresceu depois de assinado** — as modificações contratuais

A última é a que não existia em lado nenhum do portal. Um contrato adjudicado
por X e modificado para X+Y conta, nas estatísticas oficiais de despesa, pelo
valor inicial. A modificação é publicada, mas em separado, e ninguém as junta.

## Regras herdadas do resto do pipeline

  · **A cobertura declara-se, não se disfarça.** Uma unidade com poucos
    contratos registados não gasta pouco — reporta mal. `cobertura_suficiente`
    diz qual é qual, e o sítio esconde o total quando é falso.
  · **Somas, nunca médias de rácios.** O peso do ajuste direto é
    Σvalor_ajuste ÷ Σvalor, não a média dos pesos anuais.
  · **Anos em falta são lacunas.** Um ano sem contratos registados não entra
    como zero na série.
"""

from __future__ import annotations

import collections
import re

import impic

# Os mesmos limiares que o espelho do SNS usava, mantidos para que a mudança de
# fonte se leia na cobertura e não numa régua diferente.
MIN_CONTRATOS, MIN_VALOR = 50, 1_000_000

AJUSTE_DIRETO = "ajuste direto"

# O CPV vem como «33622000-6 - Medicamentos para o aparelho cardiovascular».
# Os dois primeiros dígitos são a divisão, que é a granularidade legível: 33 é
# equipamento e produtos médicos, 45 construção, 79 serviços a empresas.
_CPV = re.compile(r"^\s*(\d{2})\d*")

# As divisões do Vocabulário Comum para os Contratos Públicos (Regulamento (CE)
# n.º 213/2008). A lista está completa para as divisões que aparecem na despesa
# hospitalar; as restantes caem no rótulo genérico.
#
# A divisão 33 merece o nome exato: o vocabulário chama-lhe «equipamento médico,
# medicamentos e produtos para cuidados pessoais», e num hospital são os
# **medicamentos** que pesam quase todo o valor. Rotulá-la só como «equipamento»
# faria parecer que o dinheiro vai para máquinas quando vai para fármacos.
DIVISOES_CPV = {
    "03": "Produtos agrícolas e alimentares",
    "09": "Combustíveis e eletricidade",
    "14": "Metais e produtos das indústrias extrativas",
    "15": "Produtos alimentares e bebidas",
    "18": "Vestuário e calçado",
    "19": "Couro, plásticos e borracha",
    "22": "Impressos e material gráfico",
    "24": "Produtos químicos",
    "30": "Equipamento informático e de escritório",
    "31": "Máquinas e equipamento elétrico",
    "32": "Equipamento de comunicações",
    "33": "Medicamentos e equipamento médico",
    "34": "Equipamento de transporte",
    "35": "Equipamento de segurança",
    "37": "Artigos de desporto e recreio",
    "38": "Equipamento de laboratório e precisão",
    "39": "Mobiliário e produtos de limpeza",
    "41": "Água",
    "42": "Máquinas industriais",
    "43": "Máquinas de construção",
    "44": "Materiais de construção",
    "45": "Trabalhos de construção",
    "48": "Software e sistemas de informação",
    "50": "Reparação e manutenção",
    "51": "Serviços de instalação",
    "55": "Hotelaria e restauração",
    "60": "Transportes",
    "63": "Serviços auxiliares de transporte",
    "64": "Correios e telecomunicações",
    "65": "Serviços públicos essenciais",
    "66": "Serviços financeiros e de seguros",
    "70": "Serviços imobiliários",
    "71": "Arquitetura e engenharia",
    "72": "Serviços informáticos",
    "73": "Investigação e desenvolvimento",
    "75": "Administração pública e segurança social",
    "77": "Serviços agrícolas e florestais",
    "79": "Serviços a empresas e consultoria",
    "80": "Educação e formação",
    "85": "Serviços de saúde e ação social",
    "90": "Resíduos, limpeza e ambiente",
    "92": "Serviços recreativos e culturais",
    "98": "Outros serviços",
}


def _preco(valor) -> float:
    """Preços do IMPIC são decimais simples — mas confirmamos sempre.

    Nos exemplos da documentação da API aparecem como «105000,00», à
    portuguesa; nos dados reais chegam como `2158.99`. Tratar as duas formas
    custa três linhas e evita um erro de duas ordens de grandeza — que é
    exatamente o que acontece se se retirar o ponto decimal a pensar que é
    separador de milhares.
    """
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _primeiro(campo) -> str:
    """Vários campos vêm como lista de um elemento, outros como texto."""
    if isinstance(campo, list):
        return str(campo[0]) if campo else ""
    return str(campo or "")


def _nome_do_fornecedor(entrada: str) -> str:
    """De «500113270 - FERRAZ LYNCE SA» para «FERRAZ LYNCE SA»."""
    _, _, nome = entrada.partition(" - ")
    return (nome or entrada).strip()[:70]


def _subconjunto_do_sns(con, crosswalk):
    """Materializa só os contratos das unidades do SNS, numa tabela magra.

    Os 15 ficheiros de contratos somam mais de 6 GB descomprimidos — carregá-los
    em memória mata o processo, e uma primeira versão deste módulo fê-lo. O
    DuckDB lê o `.gz` diretamente e só materializa as sete colunas de que
    precisamos, depois de já ter filtrado pelo NIF. O que sobra são algumas
    centenas de milhares de linhas, sobre as quais todas as agregações correm
    instantaneamente.
    """
    nifs = impic.nifs_por_instituicao(crosswalk)
    if not nifs:
        raise RuntimeError("nenhum NIF resolveu para o crosswalk — verifique entidades.json")

    con.execute("create or replace temp table nif_instituicao(nif varchar, instituicao varchar)")
    con.executemany(
        "insert into nif_instituicao values (?, ?)", sorted(nifs.items())
    )

    padrao = str(impic.DIR_IMPIC / "contratos__*.json.gz")
    con.execute(
        f"""
        create or replace temp table contratos_sns as
        select distinct
            n.instituicao,
            cast(c."Ano" as varchar)                        as ano,
            coalesce(c."precoContratual", 0)                as preco,
            lower(coalesce(c."tipoprocedimento", ''))       as procedimento,
            c."adjudicatarios"[1]                           as fornecedor,
            c."cpv"[1]                                      as cpv,
            c."idcontrato"                                  as idcontrato
        from read_json_auto('{padrao}', union_by_name=true, ignore_errors=true) c
        -- `adjudicante` é uma lista: numa aquisição conjunta, várias entidades
        -- assinam o mesmo contrato. Ler só a primeira posição perdia 288
        -- contratos e 1 379 M€, e era o que explicava o desvio sistemático de
        -- -1 a -3% contra os totais do próprio Portal BASE. Percorrer a lista
        -- inteira atribui o contrato a cada unidade que o assinou — que é como
        -- o Portal BASE também o contabiliza.
        cross join unnest(c."adjudicante") as a(entidade)
        join nif_instituicao n
          on n.nif = regexp_extract(a.entidade, '^\\s*(\\d{{9}})', 1)
        """
    )
    return len(nifs)


def agregar(crosswalk, con=None) -> dict:
    """Constrói o bloco de contratos por instituição, pronto a publicar."""
    import duckdb

    con = con or duckdb.connect()
    n_nifs = _subconjunto_do_sns(con, crosswalk)
    # Distinto porque um contrato assinado por duas unidades ocupa duas linhas:
    # o total por instituição está certo, o total do país precisa de deduplicar.
    linhas, distintos = con.execute(
        "select count(*), count(distinct idcontrato) from contratos_sns"
    ).fetchone()
    print(
        f"  {n_nifs} NIF do SNS · {distintos:,} contratos distintos"
        + (f" ({linhas - distintos:,} em aquisição conjunta)" if linhas != distintos else "")
    )

    totais = con.execute(
        f"""
        select instituicao, count(*), sum(preco), min(ano), max(ano),
               sum(case when procedimento like '%{AJUSTE_DIRETO}%' then preco else 0 end)
        from contratos_sns group by 1
        """
    ).fetchall()

    por_ano = collections.defaultdict(list)
    for chave, ano, n, valor in con.execute(
        "select instituicao, ano, count(*), sum(preco) from contratos_sns "
        "where ano is not null group by 1, 2 order by 1, 2"
    ).fetchall():
        por_ano[chave].append({"ano": ano, "contratos": n, "valor": round(valor or 0)})

    fornecedores = _topo(
        con,
        "select instituicao, fornecedor, sum(preco) v from contratos_sns "
        "where fornecedor is not null group by 1, 2",
    )
    areas = _topo(
        con,
        "select instituicao, regexp_extract(cpv, '^\\s*(\\d{2})', 1) d, sum(preco) v "
        "from contratos_sns where cpv is not null group by 1, 2",
    )
    derrapagens = _derrapagens(con)

    saida = {}
    for chave, n, valor, ano_min, ano_max, valor_ajuste in totais:
        valor = valor or 0.0
        d = derrapagens.get(chave)
        saida[chave] = {
            "fonte": "IMPIC · Portal BASE",
            "desde": ano_min,
            "ate": ano_max,
            "cobertura_suficiente": n >= MIN_CONTRATOS and valor >= MIN_VALOR,
            "contratos": n,
            "valor": round(valor),
            "peso_ajuste_direto": round(100 * (valor_ajuste or 0) / valor, 1)
            if valor
            else None,
            "por_ano": por_ano.get(chave, []),
            "maiores_fornecedores": [
                {"nome": _nome_do_fornecedor(nome), "valor": round(v)}
                for nome, v in fornecedores.get(chave, [])
            ],
            "maiores_areas": [
                {
                    "divisao": c,
                    "rotulo": DIVISOES_CPV.get(c, "Outras aquisições"),
                    "valor": round(v),
                }
                for c, v in areas.get(chave, [])
            ],
            "modificacoes": d,
        }
    return saida


def _topo(con, consulta: str, quantos: int = 5) -> dict[str, list[tuple[str, float]]]:
    """Os `quantos` maiores de cada instituição, por valor."""
    acc: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
    for chave, rotulo, valor in con.execute(
        f"select * from ({consulta}) order by instituicao, v desc"
    ).fetchall():
        if rotulo and len(acc[chave]) < quantos:
            acc[chave].append((rotulo, valor or 0.0))
    return acc


def _derrapagens(con) -> dict[str, dict]:
    """Quanto cresceu, por instituição, o que já estava assinado.

    `modifContratoPrecoAlterado` é o **preço já alterado**, não o acréscimo —
    li-o mal à primeira e dava números absurdos. O acréscimo obtém-se
    subtraindo o preço inicial do contrato, que temos porque a junção é por
    `idcontrato`. Uma modificação que baixe o preço entra com sinal negativo,
    como deve ser: nem toda a modificação é derrapagem.

    Só entram as modificações que casam com um contrato do universo SNS; as
    outras pertencem a entidades que não seguimos.
    """
    padrao = str(impic.DIR_IMPIC / "modificacoes__*.json.gz")
    linhas = con.execute(
        f"""
        with m as (
            select "idcontrato" as idcontrato,
                   max(coalesce("modifContratoPrecoAlterado", 0)) as preco_final
            from read_json_auto('{padrao}', union_by_name=true, ignore_errors=true)
            where "modifContratoPrecoAlterado" is not null
            group by 1
        )
        select c.instituicao, count(*), sum(m.preco_final), sum(c.preco)
        from m join contratos_sns c on c.idcontrato = m.idcontrato
        group by 1
        """
    ).fetchall()
    return {
        chave: {
            "contratos_modificados": n,
            "valor_inicial": round(inicial or 0),
            "valor_final": round(final or 0),
            "acrescimo": round((final or 0) - (inicial or 0)),
        }
        for chave, n, final, inicial in linhas
    }


def conferir_com_servidor(agregado: dict, crosswalk, limite: int = 8) -> list[dict]:
    """Compara os nossos totais com os que o Portal BASE atribui a cada NIF.

    Verificação independente, opcional: sem token não corre, e nunca falha o
    pipeline. Uma divergência grande significa que perdemos contratos — por
    exemplo por um NIF que o crosswalk não resolveu — ou que contámos a dobrar.

    O total do servidor é por **NIF**, e várias instituições resultam da fusão
    de entidades com NIF próprio; por isso somam-se os NIF de cada instituição
    antes de comparar.
    """
    if not impic.token():
        print("  sem BASE_GOV_TOKEN: verificação contra o servidor ignorada")
        return []

    nifs = impic.nifs_por_instituicao(crosswalk)
    por_instituicao: dict[str, list[str]] = collections.defaultdict(list)
    for nif, chave in nifs.items():
        por_instituicao[chave].append(nif)

    maiores = sorted(agregado, key=lambda k: -agregado[k]["valor"])[:limite]
    relatorio = []
    for chave in maiores:
        servidor_n = servidor_valor = 0
        for nif in por_instituicao.get(chave, []):
            if totais := impic.totais_do_servidor(nif):
                servidor_n += int(totais.get("totAdjudicante") or 0)
                servidor_valor += _preco(totais.get("totAdjudicanteValorContratIni"))
        if not servidor_n:
            continue
        nosso = agregado[chave]
        desvio = 100 * (nosso["valor"] - servidor_valor) / servidor_valor if servidor_valor else None
        relatorio.append(
            {
                "instituicao": chave,
                "nossos_contratos": nosso["contratos"],
                "servidor_contratos": servidor_n,
                "nosso_valor": nosso["valor"],
                "servidor_valor": round(servidor_valor),
                "desvio_pct": round(desvio, 1) if desvio is not None else None,
            }
        )
    return relatorio


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from instituicoes import carregar

    cw = carregar()
    print("A agregar o registo do IMPIC…")
    resultado = agregar(cw)
    publicaveis = sum(1 for v in resultado.values() if v["cobertura_suficiente"])
    modificados = sum(
        v["modificacoes"]["contratos_modificados"]
        for v in resultado.values()
        if v["modificacoes"]
    )
    acrescimo = sum(
        v["modificacoes"]["acrescimo"] for v in resultado.values() if v["modificacoes"]
    )
    print(f"\n{len(resultado)} unidades · publicáveis {publicaveis}")
    print(
        f"modificações contratuais: {modificados:,} contratos alterados depois de "
        f"assinados · {acrescimo / 1e6:+,.0f} M€"
    )
    print("\nverificação contra o servidor do Portal BASE:")
    for linha in conferir_com_servidor(resultado, cw):
        print(
            f"  {linha['instituicao'][:28]:28s} "
            f"nós {linha['nosso_valor'] / 1e6:8,.0f} M€ · "
            f"servidor {linha['servidor_valor'] / 1e6:8,.0f} M€ · "
            f"desvio {linha['desvio_pct']:+.1f}%"
        )
