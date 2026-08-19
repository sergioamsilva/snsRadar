/**
 * Os dados de uma ficha, tal como o sítio os lê.
 *
 * Não é uma exportação «inspirada» nos dados: é o próprio ficheiro de
 * `data/out/instituicao/` de que a página é construída, servido no mesmo
 * endereço do portal. Quem quiser verificar um número tem aqui exatamente o
 * que o gerou — com o dataset de origem, a data e a URL de prova por valor.
 */
import type { APIRoute } from "astro";
import { ficha, indice } from "../../lib/dados";

export function getStaticPaths() {
  return indice().map((i) => ({ params: { id: i.id } }));
}

export const GET: APIRoute = ({ params }) =>
  new Response(JSON.stringify(ficha(params.id!), null, 1), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
