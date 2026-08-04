/**
 * As duas implementações têm de dar o mesmo resultado.
 *
 * As regras de agregação vivem duas vezes: em Python (ingest/build.py), que
 * produz data/out, e em JavaScript (web/app.js), que alimenta o painel. Já
 * divergiram — a mortalidade por AVC apareceu no painel com 901,9 % porque a
 * regra «uma taxa sem denominador não se soma entre instituições» estava só do
 * lado Python.
 *
 * O teste chama as *próprias funções do painel* — `nacional()` e `agregar()` —
 * e não uma reimplementação delas. A primeira versão deste ficheiro recalculava
 * a agregação por conta própria e por isso passava mesmo com o defeito
 * reintroduzido de propósito: comparava-se a si mesma com o Python, e nunca o
 * painel. Verificado que esta versão falha quando o defeito volta.
 *
 * O período de comparação é um ano civil, porque é a única janela que as duas
 * implementações sabem exprimir — o painel filtra por ano, o build por «últimos
 * doze meses». O lado Python é recalculado aqui a partir das séries das fichas.
 *
 *   node scripts/verificar_coerencia.mjs [ano] [caminho-do-painel]
 */
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import fs from "node:fs";
import path from "node:path";

const ANO = process.argv[2] ?? "2024";
const alvo = process.argv[3] ?? "../index.html";
const RAIZ = path.resolve("..", "data", "out");
const ler = (p) => JSON.parse(fs.readFileSync(path.join(RAIZ, p), "utf-8"));

const indice = ler("instituicoes.json");
const nacional = ler("nacional.json");
const fichas = indice.map((i) => ler(`instituicao/${i.id}.json`));

// Tolerância relativa: o payload do painel arredonda a três casas para não
// pesar 3 MB, e essa perda propaga-se na soma.
const TOL = 0.005;

/** Lado Python: agrega as séries das fichas com as regras documentadas. */
function esperadoPython(iid) {
  const meta = nacional[iid];
  if (!meta) return null;
  const naoSomavel = meta.sintese === "mediana entre unidades";

  const porInst = [];
  for (const f of fichas) {
    const d = f.indicadores[iid];
    if (!d) continue;
    // Filtrar por `valor` excluiria os meses cuja taxa foi suprimida por
    // denominador pequeno — meses que ambas as implementações somam na mesma
    // forma. O que interessa é haver numerador.
    const pts = d.serie.filter((p) => p.mes.startsWith(ANO) && p.numerador !== null);
    if (!pts.length) continue;
    const temDen = pts[0].denominador !== null;
    // Taxa que a fonte publica já calculada: o build toma a mediana dos meses,
    // porque a fonte escreve 0,0 nos meses ainda não apurados.
    if (d.sintese_temporal === "mediana dos meses") {
      const vals = pts.map((x) => x.numerador).sort((a, b) => a - b);
      porInst.push({ id: f.id, num: vals[Math.floor(vals.length / 2)], den: null });
      continue;
    }
    // `agregacao_temporal: ultimo` — saldos e efetivos não se somam no tempo.
    const soma = meta.sintese !== "mediana entre unidades" && d.meses_usados > 1;
    if (!soma) {
      const u = pts[pts.length - 1];
      porInst.push({ id: f.id, num: u.numerador, den: temDen ? u.denominador : null });
    } else {
      porInst.push({
        id: f.id,
        num: pts.reduce((s, p) => s + p.numerador, 0),
        den: temDen ? pts.reduce((s, p) => s + (p.denominador ?? 0), 0) : null,
      });
    }
  }
  if (!porInst.length) return null;
  return { naoSomavel, porInst };
}

const navegador = await chromium.launch();
const ctx = await navegador.newContext({ locale: "pt-PT", viewport: { width: 1280, height: 900 } });
const p = await ctx.newPage();
await p.goto(pathToFileURL(path.resolve(alvo)).href, { waitUntil: "networkidle" });
await p.waitForTimeout(500);

// Chama as funções reais do painel, com o mesmo período.
const doPainel = await p.evaluate((ano) => {
  estado.de = +ano;
  estado.ate = +ano;
  const out = {};
  for (const meta of IND) {
    const n = nacional(meta.id);            // ← a função do painel, não uma cópia
    const i = IND.findIndex((x) => x.id === meta.id);
    const porInst = {};
    for (let j = 0; j < INST.length; j++) {
      const a = agregar(i, j);              // ← idem
      if (a) porInst[INST[j].id] = { num: a.num, den: a.den, valor: a.valor };
    }
    out[meta.id] = n ? { ...n, porInst } : null;
  }
  return out;
}, ANO);

let falhas = 0;

// 1. O valor nacional que o painel mostra tem de ser reproduzível.
const problemas = [];
for (const meta of Object.keys(nacional)) {
  const esp = esperadoPython(meta);
  const obt = doPainel[meta];
  if (!esp || !obt) continue;

  // As fichas trazem a janela dos últimos doze meses; o payload traz a série
  // completa. Uma unidade que deixou de reportar — o IPO de Coimbra na
  // mortalidade por AVC — está no painel e ausente da ficha, e comparar somas
  // sobre universos diferentes acusaria uma divergência que não existe.
  const comuns = esp.porInst.filter((a) => obt.porInst[a.id]);
  const num = comuns.reduce((s, a) => s + a.num, 0);
  const temDen = comuns.some((a) => a.den !== null);
  const den = temDen ? comuns.reduce((s, a) => s + (a.den ?? 0), 0) : null;
  const obtNum = comuns.reduce((s, a) => s + obt.porInst[a.id].num, 0);

  for (const [rotulo, a, b] of [["numerador", num, obtNum], ["denominador", den, obt.den]]) {
    if (a === null || b === null || b === undefined) continue;
    const desvio = Math.abs(a - b) / Math.max(Math.abs(a), 1);
    if (desvio > TOL) {
      problemas.push(`${meta}.${rotulo}: python ${Math.round(a).toLocaleString("pt-PT")} vs painel ${Math.round(b).toLocaleString("pt-PT")}`);
    }
  }

  // A regra que já falhou: sem denominador, o valor nacional é a mediana das
  // unidades. Se for a soma, sai um número maior do que qualquer unidade.
  if (esp.naoSomavel && obt.valor !== null) {
    const maior = Math.max(...esp.porInst.map((a) => a.num));
    if (obt.valor > maior * 1.001) {
      problemas.push(
        `${meta}: valor nacional ${obt.valor.toFixed(1)} excede o maior valor de ` +
        `qualquer unidade (${maior.toFixed(1)}) — as taxas estão a ser somadas`,
      );
    }
  }
}
falhas += problemas.length;
console.log(
  problemas.length
    ? `  FALHA  agregados nacionais: ${problemas.length} divergências`
    : `  ok     agregados nacionais coincidem (${Object.keys(nacional).length} indicadores, ${ANO})`,
);
problemas.slice(0, 8).forEach((x) => console.log("           " + x));

// 2. Valores por instituição.
let mau = 0, comparados = 0;
for (const meta of Object.keys(nacional)) {
  const esp = esperadoPython(meta);
  if (!esp || !doPainel[meta]) continue;
  for (const linha of esp.porInst) {
    const b = doPainel[meta].porInst[linha.id];
    if (!b) continue;
    comparados++;
    const desvio = Math.abs(linha.num - b.num) / Math.max(Math.abs(linha.num), 1);
    if (desvio > TOL) {
      mau++;
      if (mau <= 6) console.log(`           ${linha.id}/${meta}: python ${linha.num} vs painel ${b.num}`);
    }
  }
}
falhas += mau;
console.log(
  mau
    ? `  FALHA  valores por instituição: ${mau} de ${comparados} divergem`
    : `  ok     valores por instituição coincidem (${comparados} comparações)`,
);

await navegador.close();
process.exit(falhas ? 1 : 0);
