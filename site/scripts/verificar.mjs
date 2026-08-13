/**
 * Verificação do site: acessibilidade, transbordo horizontal e funcionamento
 * sem JavaScript. Correr com o `astro preview` a servir.
 *
 *   node scripts/verificar.mjs [porta]
 */
import { chromium } from "playwright";
import { AxeBuilder } from "@axe-core/playwright";

const porta = process.argv[2] ?? "4321";
const base = `http://localhost:${porta}`;
// Prefixo do portal — o mesmo `base` de astro.config.mjs. A raiz não entra
// nesta lista: é o painel, um ficheiro estático fora do Astro, verificado por
// `verificar_dashboard.mjs`.
const RAIZ = "/snsRadar";
const PAGINAS = [
  `${RAIZ}/instituicoes/`,
  `${RAIZ}/perguntas/`,
  `${RAIZ}/instituicao/uls-tras-os-montes-alto-douro/`,
  `${RAIZ}/metodologia/`,
  // Página de grupo: entrou com a navegação por cluster e tem tabela com
  // rolamento próprio, que é onde a acessibilidade costuma partir.
  `${RAIZ}/grupo/c/`,
];

const navegador = await chromium.launch();
let falhas = 0;

// WCAG 2.1 AA, nos dois temas e em ecrã estreito — é um portal público.
for (const tema of ["light", "dark"]) {
  for (const url of PAGINAS) {
    const ctx = await navegador.newContext({
      viewport: { width: 390, height: 844 },
      colorScheme: tema,
      locale: "pt-PT",
    });
    const p = await ctx.newPage();
    await p.goto(base + url, { waitUntil: "networkidle" });
    const r = await new AxeBuilder({ page: p })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    if (r.violations.length) {
      falhas += r.violations.length;
      console.log(`  FALHA  ${tema} ${url}`);
      for (const v of r.violations) {
        console.log(`           [${v.impact}] ${v.id} (${v.nodes.length}x)`);
      }
    }
    await ctx.close();
  }
}
console.log(falhas ? `  ${falhas} violações WCAG` : "  ok     WCAG 2.1 AA (claro e escuro, 390px)");

// A página nunca pode deslizar na horizontal num telemóvel.
for (const url of PAGINAS) {
  const ctx = await navegador.newContext({ viewport: { width: 390, height: 844 } });
  const p = await ctx.newPage();
  await p.goto(base + url, { waitUntil: "networkidle" });
  const [largura, janela] = await p.evaluate(() => [
    document.documentElement.scrollWidth,
    window.innerWidth,
  ]);
  if (largura > janela) {
    falhas++;
    console.log(`  FALHA  transbordo horizontal em ${url}: ${largura} > ${janela}`);
  }
  await ctx.close();
}
console.log(falhas ? "" : "  ok     sem transbordo horizontal a 390px");

// O conteúdo tem de existir sem JavaScript: os gráficos são SVG do servidor.
const ctx = await navegador.newContext({ javaScriptEnabled: false, locale: "pt-PT" });
const p = await ctx.newPage();
// A ficha de instituição é a que tem de continuar legível sem JavaScript;
// referida pelo nome e não por índice, para não partir ao acrescentar páginas.
const FICHA = PAGINAS.find((u) => u.includes("/instituicao/"));
await p.goto(base + FICHA, { waitUntil: "domcontentloaded" });
const semJs = await p.evaluate(() => ({
  indicadores: document.querySelectorAll(".ind").length,
  graficos: document.querySelectorAll(".serie svg").length,
}));
if (semJs.indicadores < 10 || semJs.graficos < 10) {
  falhas++;
  console.log(`  FALHA  sem JavaScript: ${JSON.stringify(semJs)}`);
} else {
  console.log(
    `  ok     sem JavaScript: ${semJs.indicadores} indicadores, ${semJs.graficos} gráficos`,
  );
}

await navegador.close();
process.exit(falhas ? 1 : 0);
