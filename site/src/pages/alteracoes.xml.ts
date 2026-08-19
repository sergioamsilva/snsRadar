/**
 * O registo de alterações como feed Atom. Quem citou um número não volta todos
 * os dias a ver se ele mudou; um leitor de feeds volta por ele.
 */
import type { APIRoute } from "astro";
import { alteracoes } from "../lib/alteracoes";

const SITIO = "https://sergioamsilva.github.io/snsRadar";

const escapar = (s: string) =>
  s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

export const GET: APIRoute = () => {
  const { entradas } = alteracoes();
  const atualizado = entradas[0] ? `${entradas[0].iso}T12:00:00Z` : "";
  const itens = entradas
    .map((e) => {
      const titulo =
        e.titulos.length > 0
          ? `${e.data} — ${e.titulos.join("; ")}`
          : e.data;
      return `  <entry>
    <title>${escapar(titulo)}</title>
    <link href="${SITIO}/alteracoes/#${e.iso}"/>
    <id>${SITIO}/alteracoes/#${e.iso}</id>
    <updated>${e.iso}T12:00:00Z</updated>
    <content type="html">${escapar(e.html)}</content>
  </entry>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>snsRadar — registo de alterações</title>
  <subtitle>O que mudou nos números publicados: indicadores novos, definições alteradas, correções.</subtitle>
  <link href="${SITIO}/alteracoes/"/>
  <link rel="self" href="${SITIO}/alteracoes.xml"/>
  <id>${SITIO}/alteracoes/</id>
  <updated>${atualizado}</updated>
${itens}
</feed>
`;
  return new Response(xml, {
    headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
  });
};
