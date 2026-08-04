/**
 * Verificação do painel: erros de consola, autonomia (nenhum pedido de rede),
 * acessibilidade e ausência de transbordo horizontal.
 *
 *   node scripts/verificar_dashboard.mjs [caminho]
 */
import { chromium } from "playwright";
import { AxeBuilder } from "@axe-core/playwright";
import { pathToFileURL } from "node:url";
import path from "node:path";

const alvo = process.argv[2] ?? "../index.html";
const url = pathToFileURL(path.resolve(alvo)).href;
const navegador = await chromium.launch();
let falhas = 0;

for (const tema of ["light", "dark"]) {
  const ctx = await navegador.newContext({ colorScheme: tema, locale: "pt-PT",
    viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  const erros = [], pedidos = [];
  p.on("console", (m) => { if (m.type() === "error") erros.push(m.text()); });
  p.on("pageerror", (e) => erros.push(String(e)));
  // Autonomia: nada pode sair para a rede.
  p.on("request", (r) => { if (!r.url().startsWith("file:") && !r.url().startsWith("data:")) pedidos.push(r.url()); });

  await p.goto(url, { waitUntil: "networkidle" });
  await p.waitForTimeout(700);

  if (erros.length) { falhas += erros.length;
    console.log(`  FALHA  ${tema}: ${erros.length} erros de consola`);
    erros.slice(0, 5).forEach((e) => console.log("           " + e.slice(0, 160)));
  } else console.log(`  ok     ${tema}: sem erros de consola`);

  if (pedidos.length) { falhas++;
    console.log(`  FALHA  ${tema}: ${pedidos.length} pedidos de rede — o painel não é autónomo`);
    pedidos.slice(0, 4).forEach((u) => console.log("           " + u.slice(0, 120)));
  } else console.log(`  ok     ${tema}: nenhum pedido de rede`);

  const n = await p.evaluate(() => ({
    stats: document.querySelectorAll("#stats .stat").length,
    dst: document.querySelectorAll("#destaques .dst").length,
    cards: document.querySelectorAll(".grid .card").length,
    svgs: document.querySelectorAll("svg").length,
    linhasTab: document.querySelectorAll("#tab tbody tr").length,
    mini: document.querySelectorAll("#ficha .mini").length,
    bolhas: document.querySelectorAll("#mapa circle").length,
  }));
  console.log(`         conteúdo: ${JSON.stringify(n)}`);
  if (n.cards < 20 || n.svgs < 20 || n.linhasTab < 20 || n.mini < 10 || n.bolhas < 20) {
    falhas++; console.log(`  FALHA  ${tema}: conteúdo insuficiente`);
  }

  // Nenhuma percentagem apresentada pode passar de 100 %. Foi assim que a
  // mortalidade por AVC apareceu com 901,9 %: a taxa vem já calculada da fonte,
  // sem denominador, e estava a ser somada entre as 43 unidades.
  const absurdas = await p.evaluate(() => {
    const mal = [];
    // A ocupação do internamento pode passar dos 100 % sem ser erro — camas
    // extra abertas. Nos restantes, o numerador está contido no denominador.
    const livresId = new Set(DADOS.ind.filter((i) => i.livre100).map((i) => i.id));
    const livres = new Set(DADOS.ind.filter((i) => i.livre100).map((i) => i.t));
    for (const el of document.querySelectorAll("b, .cmp, td, .stat b, .dst b")) {
      const t = el.textContent.trim();
      const m = t.match(/^(-?[\d\s.]+,\d+)\s*%$/);
      if (!m) continue;
      const v = parseFloat(m[1].replace(/[\s.]/g, "").replace(",", "."));
      // Nas células da tabela o indicador vem no atributo; nos cartões, do título.
      const ctx = el.dataset.ind
        || (el.closest(".card, .mini, .dst")?.querySelector("h3, h4, i")?.textContent || "?").trim();
      const podeExceder = livresId.has(el.dataset.ind)
        || [...livres].some((n) => ctx.startsWith(n.slice(0, 20)));
      const limite = podeExceder ? 200 : 100;
      if (v > limite || v < -100) mal.push(`${t} (limite ${limite} %) — ${ctx.slice(0, 50)}`);
    }
    return mal;
  });
  if (absurdas.length) {
    falhas += absurdas.length;
    console.log(`  FALHA  ${tema}: ${absurdas.length} percentagens fora de 0–100 %`);
    absurdas.slice(0, 5).forEach((x) => console.log("           " + x));
  } else console.log(`  ok     ${tema}: percentagens dentro de 0–100 %`);

  const r = await new AxeBuilder({ page: p })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  if (r.violations.length) { falhas += r.violations.length;
    console.log(`  FALHA  ${tema}: ${r.violations.length} violações WCAG`);
    for (const v of r.violations) console.log(`           [${v.impact}] ${v.id} (${v.nodes.length}x) — ${v.nodes[0].target}`);
  } else console.log(`  ok     ${tema}: WCAG 2.1 AA`);

  await ctx.close();
}

const ctx = await navegador.newContext({ viewport: { width: 390, height: 844 } });
const p = await ctx.newPage();
await p.goto(url, { waitUntil: "networkidle" });
await p.waitForTimeout(500);
const [lg, jn] = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
if (lg > jn) { falhas++; console.log(`  FALHA  transbordo horizontal a 390px: ${lg} > ${jn}`); }
else console.log("  ok     sem transbordo horizontal a 390px");

await navegador.close();
process.exit(falhas ? 1 : 0);
