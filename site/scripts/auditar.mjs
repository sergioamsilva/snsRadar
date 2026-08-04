/** Auditoria do sítio: peso, desempenho, SEO, teclado e impressão. */
import { chromium } from "playwright";
import fs from "node:fs";

const base = `http://127.0.0.1:${process.argv[2] ?? "4500"}`;
const PAGINAS = ["/", "/perguntas/", "/instituicao/uls-coimbra/", "/metodologia/", "/painel/"];
const b = await chromium.launch();

console.log("=== PESO E TEMPO ===");
for (const url of PAGINAS) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  const p = await ctx.newPage();
  let bytes = 0;
  const porTipo = {};
  p.on("response", async (r) => {
    try {
      const l = +(r.headers()["content-length"] ?? 0);
      const t = (r.headers()["content-type"] ?? "?").split(";")[0].split("/").pop();
      bytes += l; porTipo[t] = (porTipo[t] ?? 0) + l;
    } catch {}
  });
  const t0 = Date.now();
  await p.goto(base + url, { waitUntil: "load" });
  const carga = Date.now() - t0;
  const m = await p.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    return {
      dom: Math.round(n?.domContentLoadedEventEnd ?? 0),
      nos: document.querySelectorAll("*").length,
    };
  });
  console.log(`  ${url.padEnd(34)} ${(bytes / 1024).toFixed(0).padStart(6)} KB  ` +
    `carga ${String(carga).padStart(4)} ms  DOM ${String(m.dom).padStart(4)} ms  ${m.nos} nós`);
  await ctx.close();
}

console.log("\n=== SEO E PARTILHA ===");
const ctx = await b.newContext();
const p = await ctx.newPage();
for (const url of ["/", "/instituicao/uls-coimbra/"]) {
  await p.goto(base + url, { waitUntil: "domcontentloaded" });
  const r = await p.evaluate(() => {
    const meta = (n) => document.querySelector(`meta[name="${n}"],meta[property="${n}"]`)?.content ?? null;
    return {
      titulo: document.title,
      descricao: meta("description"),
      canonical: document.querySelector('link[rel="canonical"]')?.href ?? null,
      ogTitle: meta("og:title"), ogImage: meta("og:image"), ogUrl: meta("og:url"),
      jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].length,
      h1: [...document.querySelectorAll("h1")].map((h) => h.textContent.trim().slice(0, 40)),
      lang: document.documentElement.lang,
    };
  });
  console.log(`  ${url}`);
  for (const [k, v] of Object.entries(r)) {
    const falta = v === null || (Array.isArray(v) && !v.length) || v === 0;
    console.log(`    ${falta ? "✗" : "·"} ${k}: ${JSON.stringify(v)?.slice(0, 70)}`);
  }
}

console.log("\n=== FICHEIROS DE DESCOBERTA ===");
for (const f of ["/robots.txt", "/sitemap.xml", "/sitemap-index.xml", "/favicon.svg", "/og.png", "/404.html"]) {
  const r = await p.goto(base + f).catch(() => null);
  console.log(`  ${r && r.status() === 200 ? "·" : "✗"} ${f} ${r ? r.status() : "erro"}`);
}

console.log("\n=== TECLADO ===");
await p.goto(base + "/perguntas/", { waitUntil: "networkidle" });
const tab = await p.evaluate(async () => {
  const focaveis = document.querySelectorAll(
    'a[href],button,select,input,[tabindex]:not([tabindex="-1"])');
  return { focaveis: focaveis.length, primeiro: focaveis[0]?.textContent?.trim().slice(0, 30) };
});
console.log(`  ${tab.focaveis} elementos focáveis; primeiro: ${tab.primeiro}`);
const saltar = await p.evaluate(() => !!document.querySelector(".saltar"));
console.log(`  ${saltar ? "·" : "✗"} ligação «saltar para o conteúdo»`);

console.log("\n=== IMPRESSÃO ===");
const temPrint = fs.readFileSync("src/styles/global.css", "utf-8").includes("@media print");
console.log(`  ${temPrint ? "·" : "✗"} folha de estilos para impressão`);

console.log("\n=== TIPOGRAFIA E LEITURA ===");
await p.goto(base + "/instituicao/uls-coimbra/", { waitUntil: "networkidle" });
const tipo = await p.evaluate(() => {
  const corpo = getComputedStyle(document.body);
  const p1 = document.querySelector(".ind__desc");
  return {
    tamanhoBase: corpo.fontSize,
    menorTexto: Math.min(...[...document.querySelectorAll("p,span,td,li")]
      .map((e) => parseFloat(getComputedStyle(e).fontSize)).filter((x) => x > 0)),
    familia: corpo.fontFamily.split(",")[0],
  };
});
console.log(`  base ${tipo.tamanhoBase}; menor texto ${tipo.menorTexto}px; ${tipo.familia}`);

await b.close();
