/**
 * O CHANGELOG.md, lido e convertido em build.
 *
 * O registo de alterações vivia só no GitHub, e quem cita números não vive lá.
 * Este módulo traz o ficheiro para dentro do sítio sem o duplicar: a fonte
 * continua a ser o CHANGELOG.md da raiz, e a conversão suporta exatamente o
 * dialeto que ele usa — títulos, listas, negrito, ligações, citações e código
 * em linha. Não é um conversor de Markdown geral, de propósito: um dialeto
 * fechado converte-se com quarenta linhas auditáveis, sem dependência nova.
 */
import fs from "node:fs";
import path from "node:path";

const FICHEIRO = path.resolve(process.cwd(), "..", "CHANGELOG.md");
const REPO = "https://github.com/sergioamsilva/snsRadar/blob/main";

const MESES: Record<string, string> = {
  janeiro: "01", fevereiro: "02", março: "03", abril: "04", maio: "05",
  junho: "06", julho: "07", agosto: "08", setembro: "09", outubro: "10",
  novembro: "11", dezembro: "12",
};

const escapar = (s: string) =>
  s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

/** Negrito, código e ligações — o nível de dentro das linhas. */
function linha(s: string): string {
  return escapar(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, texto, url) => {
      // Ligações relativas apontam para ficheiros do repositório; aqui, para
      // os mesmos ficheiros no GitHub — o sítio não os serve.
      const destino = /^[a-z]+:/.test(url) ? url : `${REPO}/${url}`;
      const externo = ' rel="noopener" target="_blank"';
      return `<a href="${destino}"${externo}>${texto}</a>`;
    });
}

/** Blocos: títulos ###, listas, citações e parágrafos. */
export function converter(md: string): string {
  const blocos: string[] = [];
  let lista: string[] = [];
  let paragrafo: string[] = [];
  let citacao: string[] = [];

  /* As linhas acumulam-se em bruto e convertem-se ao fechar o bloco: o
     ficheiro parte frases aos 80 caracteres, e um negrito ou uma ligação que
     atravesse a quebra não se converte linha a linha. */
  const fecharLista = () => {
    if (lista.length) {
      blocos.push(`<ul>${lista.map((i) => `<li>${linha(i)}</li>`).join("")}</ul>`);
      lista = [];
    }
  };
  const fecharParagrafo = () => {
    if (paragrafo.length) {
      blocos.push(`<p>${linha(paragrafo.join(" "))}</p>`);
      paragrafo = [];
    }
  };
  const fecharCitacao = () => {
    if (citacao.length) {
      blocos.push(`<blockquote><p>${linha(citacao.join(" "))}</p></blockquote>`);
      citacao = [];
    }
  };

  for (const bruta of md.split("\n")) {
    const l = bruta.trimEnd();
    if (l.startsWith("### ")) {
      fecharLista(); fecharParagrafo(); fecharCitacao();
      blocos.push(`<h3>${linha(l.slice(4))}</h3>`);
    } else if (l.startsWith("- ")) {
      fecharParagrafo(); fecharCitacao();
      lista.push(l.slice(2));
    } else if (/^ {2,}\S/.test(bruta) && lista.length) {
      // Continuação do item anterior, indentada.
      lista[lista.length - 1] += ` ${l.trim()}`;
    } else if (l.startsWith("> ")) {
      fecharLista(); fecharParagrafo();
      citacao.push(l.slice(2));
    } else if (l === "" || l === "---") {
      fecharLista(); fecharParagrafo(); fecharCitacao();
    } else {
      fecharLista(); fecharCitacao();
      paragrafo.push(l);
    }
  }
  fecharLista(); fecharParagrafo(); fecharCitacao();
  return blocos.join("\n");
}

export type Entrada = {
  /** «14 de agosto de 2026», tal como o ficheiro a escreve. */
  data: string;
  /** «2026-08-14» — âncora da secção e data do feed. */
  iso: string;
  html: string;
  /** Os títulos ### da entrada, para o resumo do feed. */
  titulos: string[];
};

export function alteracoes(): { intro: string; entradas: Entrada[] } {
  const md = fs.readFileSync(FICHEIRO, "utf-8");
  const partes = md.split(/^## /m);
  const intro = converter(partes[0].replace(/^# .*\n/, ""));
  const entradas = partes.slice(1).map((parte) => {
    const [primeira, ...resto] = parte.split("\n");
    const data = primeira.trim();
    const m = data.match(/^(\d{1,2}) de (\S+) de (\d{4})$/);
    const iso = m
      ? `${m[3]}-${MESES[m[2]] ?? "01"}-${m[1].padStart(2, "0")}`
      : data;
    const corpo = resto.join("\n");
    const titulos = [...corpo.matchAll(/^### (.+)$/gm)].map((t) => t[1]);
    return { data, iso, html: converter(corpo), titulos };
  });
  return { intro, entradas };
}
