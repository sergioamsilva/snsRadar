/**
 * A mesma ficha, achatada para folha de cálculo: uma linha por indicador e
 * mês. Convenções pt-PT, as mesmas das exportações do Portal da Transparência:
 * campos separados por «;» e decimais com vírgula — abre no Excel português
 * sem assistente de importação.
 *
 * O valor agregado da ficha (a janela de 12 meses) não vem aqui: é derivável
 * da série, e duplicá-lo convidava a somar o que já está somado. Para o dado
 * completo, com metadados e proveniência por valor, há o JSON ao lado.
 */
import type { APIRoute } from "astro";
import { ficha, indice } from "../../lib/dados";

export function getStaticPaths() {
  return indice().map((i) => ({ params: { id: i.id } }));
}

const campo = (v: string): string =>
  /[;"\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v;

const numero = (v: number | null): string =>
  v === null ? "" : String(v).replace(".", ",");

export const GET: APIRoute = ({ params }) => {
  const f = ficha(params.id!);
  const linhas = [
    [
      "instituicao_id", "instituicao", "indicador", "titulo", "grupo",
      "unidade", "mes", "valor", "numerador", "denominador",
      "fonte_dataset", "fonte_atualizado",
    ].join(";"),
  ];
  for (const [iid, d] of Object.entries(f.indicadores)) {
    for (const p of d.serie) {
      if (p.valor === null && p.numerador === null && p.denominador === null)
        continue;
      linhas.push(
        [
          f.id, campo(f.nome_curto), iid, campo(d.titulo), d.grupo,
          d.unidade, p.mes, numero(p.valor), numero(p.numerador),
          numero(p.denominador), d.fonte.dataset,
          d.fonte.atualizado?.slice(0, 10) ?? "",
        ].join(";"),
      );
    }
  }
  // O BOM é para o Excel: sem ele, «Trás-os-Montes» abre como mojibake.
  return new Response("\uFEFF" + linhas.join("\n") + "\n", {
    headers: { "Content-Type": "text/csv; charset=utf-8" },
  });
};
