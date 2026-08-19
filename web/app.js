"use strict";
/* snsRadar — painel de página única.
 *
 * Tudo é calculado no navegador a partir de DADOS, embebido na página. Não há
 * pedidos de rede: a página abre offline.
 *
 * Convenções do payload (ver scripts/build_dashboard.py):
 *   DADOS.s["i:j"] = [[m, num, den], …]   i=indicador, j=instituição, m=índice do mês
 *   den é null quando o indicador é uma contagem — nesse caso não há taxa.
 */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const { meses: MESES, inst: INST, ind: IND, s: SERIES, limiar: LIMIAR, mapa: MAPA } = DADOS;

const ANOS = [...new Set(MESES.map((m) => +m.slice(0, 4)))].sort();
const REGIOES = [...new Set(INST.map((i) => i.r))].sort();
/* Grupos de financiamento da ACSS. Filtrar por grupo é o que permite comparar
   hospitais entre pares: a região junta um IPO a uma unidade distrital só
   porque ficam perto, e o grupo junta-os por se parecerem no que custam. */
const GRUPOS_ACSS = [...new Set(INST.map((i) => i.gr).filter(Boolean))].sort();
const MES_NOME = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const QUEBRA = "2024-01"; // reforma das ULS

/* ── formatação ─────────────────────────────────────────────────────────── */

const nf = (min, max) => new Intl.NumberFormat("pt-PT", {
  minimumFractionDigits: min, maximumFractionDigits: max,
});

function fmt(v, unidade) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  switch (unidade) {
    case "percentagem": return nf(1, 1).format(v) + " %";
    case "dias": return nf(0, 1).format(v) + " dias";
    // Taxas de segurança do doente. A escala faz parte da leitura: «1,8 por mil
    // internamentos» diz o que «0,2 %» esconde — e é a unidade em que a ACSS
    // define o indicador.
    case "por_1000": return nf(1, 2).format(v) + " ‰";
    case "por_100000": return nf(0, 0).format(v) + " por 100 mil";
    case "por_1000_dias": return nf(0, 1).format(v) + " por 1000 dias";
    case "racio": return nf(2, 2).format(v);
    case "euros":
      return Math.abs(v) >= 1e6 ? nf(1, 1).format(v / 1e6) + " M€"
           : Math.abs(v) >= 1e3 ? nf(0, 0).format(v / 1e3) + " mil €"
           : nf(0, 0).format(v) + " €";
    default: return nf(0, 0).format(v);
  }
}
const fmtCurto = (v, u) => u === "percentagem" ? nf(0, 1).format(v) + "%"
  : u === "euros" ? nf(0, 0).format(v / 1e6) + "M" : nf(0, 0).format(v);
const fmtMes = (m) => MES_NOME[+m.slice(5, 7) - 1] + ". " + m.slice(0, 4);

/* ── estado, refletido no endereço da página ────────────────────────────── */

const estado = {
  de: ANOS[0], ate: ANOS[ANOS.length - 1],
  regioes: new Set(REGIOES),
  grupos: new Set(GRUPOS_ACSS),
  evo: "cesarianas", disp: "cesarianas", mapa: "lic-dentro-tmrg",
  inst: null, ordem: { col: 1, desc: true },
};

function lerHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.has("de")) estado.de = Math.max(ANOS[0], +p.get("de") || ANOS[0]);
  if (p.has("ate")) estado.ate = Math.min(ANOS[ANOS.length - 1], +p.get("ate") || estado.ate);
  if (estado.de > estado.ate) [estado.de, estado.ate] = [estado.ate, estado.de];
  if (p.has("reg")) {
    const r = p.get("reg").split("|").filter((x) => REGIOES.includes(x));
    if (r.length) estado.regioes = new Set(r);
  }
  if (p.has("gr")) {
    const g = p.get("gr").split("|").filter((x) => GRUPOS_ACSS.includes(x));
    if (g.length) estado.grupos = new Set(g);
  }
  for (const k of ["evo", "disp", "mapa"]) {
    if (p.has(k) && IND.some((i) => i.id === p.get(k))) estado[k] = p.get(k);
  }
  if (p.has("inst") && INST.some((i) => i.id === p.get("inst"))) estado.inst = p.get("inst");
}

function escreverHash() {
  const p = new URLSearchParams();
  if (estado.de !== ANOS[0]) p.set("de", estado.de);
  if (estado.ate !== ANOS[ANOS.length - 1]) p.set("ate", estado.ate);
  if (estado.regioes.size !== REGIOES.length) p.set("reg", [...estado.regioes].join("|"));
  if (estado.grupos.size !== GRUPOS_ACSS.length) p.set("gr", [...estado.grupos].join("|"));
  const OMISSO = { evo: "cesarianas", disp: "cesarianas", mapa: "lic-dentro-tmrg" };
  for (const k of ["evo", "disp", "mapa"]) if (estado[k] !== OMISSO[k]) p.set(k, estado[k]);
  if (estado.inst) p.set("inst", estado.inst);
  const h = p.toString();
  history.replaceState(null, "", h ? "#" + h : location.pathname);
}

/* ── agregação ──────────────────────────────────────────────────────────── */

const idxInd = (id) => IND.findIndex((x) => x.id === id);
const dentro = (m) => { const a = +MESES[m].slice(0, 4); return a >= estado.de && a <= estado.ate; };
const instVisiveis = () =>
  INST.map((x, j) => [x, j]).filter(
    ([x]) => estado.regioes.has(x.r) && (!x.gr || estado.grupos.has(x.gr)),
  );

/** Agrega uma série no período: Σnum ÷ Σden, ou o último mês quando somar não faz sentido. */
function agregar(i, j) {
  const pts = SERIES[i + ":" + j];
  if (!pts) return null;
  const dentroP = pts.filter((p) => dentro(p[0]));
  if (!dentroP.length) return null;
  const meta = IND[i];

  if (meta.jaTaxa) {
    // Mediana dos meses: a fonte escreve 0,0 nos meses ainda não apurados, e
    // tomar o último valor punha o número à mercê disso. Mesma regra do lado
    // Python — ver ingest/build.py::_agregar.
    const vals = dentroP.map((p) => p[1]).sort((a, b) => a - b);
    const med = vals[Math.floor(vals.length / 2)];
    return { num: med, den: null, mes: MESES[dentroP[dentroP.length - 1][0]],
             n: dentroP.length, valor: med };
  }
  if (!meta.soma) {
    const u = dentroP[dentroP.length - 1];
    return { num: u[1], den: u[2], mes: MESES[u[0]], n: 1, valor: valorDe(meta, u[1], u[2]) };
  }
  let num = 0, den = 0;
  for (const p of dentroP) { num += p[1]; if (p[2] !== null) den += p[2]; }
  return {
    num, den: meta.taxa && dentroP[0][2] !== null ? den : null,
    mes: MESES[dentroP[dentroP.length - 1][0]], n: dentroP.length,
    valor: valorDe(meta, num, dentroP[0][2] !== null ? den : null),
  };
}

function valorDe(meta, num, den) {
  if (den === null || den === undefined) return meta.taxa && !meta.soma ? num : num;
  if (den < LIMIAR) return null;               // denominador pequeno: a taxa seria ruído
  // `fat` é o multiplicador da taxa, e vem do indicador. As taxas de segurança
  // da ACSS são por mil ou por cem mil episódios, não percentagens. Mesma regra
  // do lado Python — ver ingest/build.py::_valor.
  const fator = meta.fat != null ? meta.fat : (meta.u === "percentagem" ? 100 : 1);
  const v = (fator * num) / den;
  // Acima do máximo plausível o denominador está errado, não o hospital: a
  // lotação da ULS da Lezíria em janeiro de 2014 dá 3 684% de ocupação. Mesma
  // regra do lado Python — ver ingest/build.py::_valor.
  if (meta.teto != null && v > meta.teto) return null;
  return v;
}

/** True quando os valores das unidades não se podem somar entre si.
 *
 * Uma taxa que a fonte publica já calculada — mortalidade por AVC — não traz
 * numerador nem denominador, e somar as 43 unidades daria 901,9 %. O mesmo
 * vale para uma média em dias. Nestes casos a única síntese nacional honesta é
 * a mediana entre unidades, porque não temos os volumes que a ponderariam.
 */
const soMediana = (meta, temDen) =>
  !temDen && (meta.u === "percentagem" || meta.u === "dias");

/** Valor de cada instituição visível, para um indicador. */
function porInstituicao(id) {
  const i = idxInd(id);
  const out = [];
  for (const [x, j] of instVisiveis()) {
    const a = agregar(i, j);
    if (a && a.valor !== null && Number.isFinite(a.valor)) out.push({ inst: x, j, ...a });
  }
  return out;
}

/** Nacional: soma dos numeradores e dos denominadores já agregados por unidade. */
function nacional(id) {
  const i = idxInd(id), meta = IND[i];
  const linhas = [];
  for (const [, j] of instVisiveis()) { const a = agregar(i, j); if (a) linhas.push(a); }
  if (!linhas.length) return null;
  const num = linhas.reduce((s, a) => s + a.num, 0);
  const temDen = linhas.some((a) => a.den !== null && a.den !== undefined);
  const den = temDen ? linhas.reduce((s, a) => s + (a.den || 0), 0) : null;
  const vals = linhas.map((a) => a.valor).filter((v) => v !== null && Number.isFinite(v)).sort((a, b) => a - b);
  const mediana = vals.length ? vals[Math.floor(vals.length / 2)] : null;
  const mediaNac = soMediana(meta, temDen);
  const valor = mediaNac ? mediana : valorDe(meta, num, den);
  return { num, den, valor, mediana, n: vals.length, vals, sintese: mediaNac
    ? "mediana entre unidades" : temDen
    ? "soma dos numeradores ÷ soma dos denominadores" : "soma das unidades" };
}

/** Série nacional mês a mês. */
function serieNacional(id) {
  const i = idxInd(id), meta = IND[i];
  const acc = new Map();
  for (const [, j] of instVisiveis()) {
    const pts = SERIES[i + ":" + j]; if (!pts) continue;
    for (const [m, num, den] of pts) {
      if (!dentro(m)) continue;
      const a = acc.get(m) || [0, 0, 0, false];
      a[0] += num; if (den !== null) { a[1] += den; a[3] = true; } a[2]++;
      acc.set(m, a);
    }
  }
  return [...acc.entries()].sort((a, b) => a[0] - b[0]).map(([m, a]) => ({
    m, mes: MESES[m],
    // Sem denominador, uma taxa mensal é a média das unidades — nunca a soma.
    v: a[3] ? valorDe(meta, a[0], a[1])
      : soMediana(meta, false) ? a[0] / a[2] : a[0],
    num: a[0], den: a[3] ? a[1] : null,
  })).filter((p) => p.v !== null && Number.isFinite(p.v));
}

/* ── desenho ────────────────────────────────────────────────────────────── */

const svgEl = (t, a = {}) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", t);
  for (const k in a) if (a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]);
  return e;
};

function escala(vals, unidade, folgaBaixo = true) {
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const loDados = lo;
  if (hi === lo) { hi = lo + Math.abs(lo || 1) * 0.1; }
  const f = (hi - lo) * 0.1;
  lo = folgaBaixo ? lo - f : lo; hi += f;
  // O recorte apara a folga; com dados negativos (margem EBITDA) não se
  // aplica, senão a escala escondia a série. Igual a Serie.astro.
  if (unidade === "percentagem") {
    if (loDados >= 0) lo = Math.max(0, lo);
    hi = Math.min(100, hi);
  }
  return [lo, hi];
}

/** Linha temporal. */
function linha(cont, pontos, meta, opts = {}) {
  cont.textContent = "";
  if (pontos.length < 2) { cont.innerHTML = '<p class="desc">Sem série suficiente no período.</p>'; return; }
  const W = 1000, H = opts.h || 240, M = { t: 14, r: 12, b: 26, l: 52 };
  const [lo, hi] = escala(pontos.map((p) => p.v), meta.u);
  const x = (k) => M.l + (k / (pontos.length - 1)) * (W - M.l - M.r);
  const y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  svg.setAttribute("aria-label",
    `${meta.t}: de ${fmtMes(pontos[0].mes)} a ${fmtMes(pontos[pontos.length - 1].mes)}, ` +
    `valor mais recente ${fmt(pontos[pontos.length - 1].v, meta.u)}.`);

  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4, yy = y(v);
    svg.append(svgEl("line", { x1: M.l, x2: W - M.r, y1: yy, y2: yy, class: "gl" }));
    const t = svgEl("text", { x: M.l - 7, y: yy + 3, class: "ax", "text-anchor": "end" });
    t.textContent = fmtCurto(v, meta.u); svg.append(t);
  }

  const qi = pontos.findIndex((p) => p.mes >= QUEBRA);
  if (qi > 0) {
    svg.append(svgEl("line", { x1: x(qi), x2: x(qi), y1: M.t, y2: H - M.b, class: "qb" }));
    const t = svgEl("text", { x: x(qi) + 4, y: M.t + 9, class: "ax", fill: "var(--brand)" });
    t.textContent = "reforma ULS"; svg.append(t);
  }

  const d = pontos.map((p, k) => (k ? "L" : "M") + x(k).toFixed(1) + "," + y(p.v).toFixed(1)).join(" ");
  svg.append(svgEl("path", { d, fill: "none", stroke: "var(--accent)", "stroke-width": 2,
    "stroke-linejoin": "round", "stroke-linecap": "round" }));
  svg.append(svgEl("circle", { cx: x(pontos.length - 1), cy: y(pontos[pontos.length - 1].v),
    r: 3.5, fill: "var(--accent)" }));

  const passo = Math.max(1, Math.round(pontos.length / 8));
  for (let k = 0; k < pontos.length; k += passo) {
    const t = svgEl("text", { x: x(k), y: H - 8, class: "ax", "text-anchor": "middle" });
    t.textContent = fmtMes(pontos[k].mes); svg.append(t);
  }

  const alvo = svgEl("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b,
    fill: "transparent" });
  alvo.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const k = Math.max(0, Math.min(pontos.length - 1,
      Math.round(((px - M.l) / (W - M.l - M.r)) * (pontos.length - 1))));
    const p = pontos[k];
    dica(ev, `<b>${fmtMes(p.mes)}</b>${fmt(p.v, meta.u)}` +
      (p.den ? `<br>${nf(0, 0).format(p.num)} em ${nf(0, 0).format(p.den)}` : ""));
  });
  alvo.addEventListener("pointerleave", escondeDica);
  svg.append(alvo);
  cont.append(svg);
}

/** A mediana de um conjunto de valores. */
const medianaDe = (vals) => {
  const s = [...vals].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
};

/**
 * Dispersão: uma unidade por ponto, ordenada — e repartida pelos grupos de
 * comparação da ACSS.
 *
 * Uma lista única das 43 unidades ordenadas por valor põe o IPO do Porto três
 * linhas acima da ULS da Guarda e convida a lê-las como concorrentes. Não são:
 * a ACSS agrupa-as por semelhança de custo, e é dentro do grupo que a
 * comparação se aguenta. O eixo é o mesmo em todos os grupos — são pequenos
 * múltiplos, não escalas diferentes —, e cada grupo traz a sua mediana ao lado
 * da nacional.
 */
function dispersao(cont, linhas, meta, mediana) {
  cont.textContent = "";
  if (!linhas.length) { cont.innerHTML = '<p class="desc">Sem unidades com dados no período.</p>'; return; }

  // Agrupa só quando toda a gente tem grupo; senão, a lista corrida de sempre.
  const porGrupo = new Map();
  const temGrupos = linhas.every((d) => d.inst.gr);
  if (temGrupos) {
    for (const d of linhas) {
      if (!porGrupo.has(d.inst.gr)) porGrupo.set(d.inst.gr, []);
      porGrupo.get(d.inst.gr).push(d);
    }
  }
  const blocos = temGrupos
    ? [...porGrupo.entries()].sort(([a], [b]) => a.localeCompare(b))
        .map(([nome, ds]) => ({ nome, ds: ds.sort((a, b) => b.valor - a.valor) }))
    : [{ nome: null, ds: [...linhas].sort((a, b) => b.valor - a.valor) }];

  const ord = blocos.flatMap((b) => b.ds);
  const CAB = 26;  // altura da faixa que abre cada grupo
  const W = 1000, LH = 21, TOPO = 22, M = { l: 220, r: 60 };
  const H = ord.length * LH + blocos.filter((b) => b.nome).length * CAB + TOPO + 30;
  const vals = ord.map((d) => d.valor);
  if (meta.ref) {
    const amp = Math.max(...vals) - Math.min(...vals);
    const fora = meta.ref.valor < Math.min(...vals)
      ? Math.min(...vals) - meta.ref.valor : meta.ref.valor - Math.max(...vals);
    // Só alarga a escala se a referência não esmagar a dispersão entre unidades.
    if (fora <= amp * 0.7) vals.push(meta.ref.valor);
  }
  const [lo, hi] = escala(vals, meta.u);
  const x = (v) => M.l + ((v - lo) / (hi - lo)) * (W - M.l - M.r);

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  svg.setAttribute("aria-label",
    `${meta.t} em ${ord.length} unidades; mediana nacional ${fmt(mediana, meta.u)}.`);

  if (mediana !== null) {
    svg.append(svgEl("line", { x1: x(mediana), x2: x(mediana), y1: TOPO, y2: H - 22, class: "bl" }));
    const t = svgEl("text", { x: x(mediana), y: H - 8, class: "ax", "text-anchor": "middle" });
    t.textContent = "mediana " + fmt(mediana, meta.u); svg.append(t);
  }
  if (meta.ref) {
    svg.append(svgEl("line", { x1: x(meta.ref.valor), x2: x(meta.ref.valor), y1: TOPO, y2: H - 22,
      stroke: "var(--brand)", "stroke-width": 1, "stroke-dasharray": "3 3" }));
    const r = svgEl("text", { x: x(meta.ref.valor), y: H - 8, class: "ax",
      "text-anchor": "middle", fill: "var(--brand)" });
    r.textContent = meta.ref.rotulo || "referência"; svg.append(r);
  }

  let linha = 0;
  for (const bloco of blocos) {
    if (bloco.nome) {
      const yCab = TOPO + linha * LH + 14;
      const cab = svgEl("text", { x: 0, y: yCab, class: "ax" });
      cab.setAttribute("font-weight", "700");
      cab.textContent = `${bloco.nome} · ${bloco.ds.length} unidades`;
      svg.append(cab);
      const med = medianaDe(bloco.ds.map((d) => d.valor));
      if (med !== null) {
        // Mediana do grupo: um segmento que abrange só as linhas do grupo, para
        // não se confundir com a nacional, que atravessa o gráfico todo.
        svg.append(svgEl("line", {
          x1: x(med), x2: x(med),
          y1: yCab + 6, y2: yCab + 6 + bloco.ds.length * LH,
          stroke: "var(--accent)", "stroke-width": 2, opacity: 0.55,
        }));
        const t = svgEl("text", { x: x(med) + 6, y: yCab, class: "ax", fill: "var(--accent)" });
        t.textContent = "mediana do grupo " + fmt(med, meta.u);
        svg.append(t);
      }
      linha += CAB / LH;
    }
    dispersaoLinhas(svg, bloco.ds, { x, meta, mediana, W, M, LH, TOPO, base: linha });
    linha += bloco.ds.length;
  }
  cont.append(svg);
}

/** As linhas de um bloco da dispersão. Extraído para o desenho não repetir. */
function dispersaoLinhas(svg, ord, { x, meta, mediana, W, M, LH, TOPO, base }) {
  const bom = (v) => meta.p === "neutro" ? null
    : (meta.p === "subir_e_bom" ? v >= mediana : v <= mediana);
  ord.forEach((d, k) => {
    const yy = TOPO + (base + k) * LH + 12;
    const nome = svgEl("text", { x: M.l - 10, y: yy + 4, class: "ax", "text-anchor": "end" });
    nome.textContent = d.inst.n.length > 34 ? d.inst.n.slice(0, 33) + "…" : d.inst.n;
    svg.append(nome);
    svg.append(svgEl("line", { x1: M.l, x2: W - M.r, y1: yy, y2: yy, class: "gl" }));
    const b = bom(d.valor);
    const g = svgEl("g", { style: "cursor:pointer" });
    g.append(svgEl("circle", { cx: x(d.valor), cy: yy, r: 5,
      fill: b === null ? "var(--accent)" : b ? "var(--cmp-bom)" : "var(--cmp-mau)" }));
    const v = svgEl("text", { x: W - M.r + 8, y: yy + 4, class: "ax" });
    v.textContent = fmt(d.valor, meta.u); svg.append(v);
    g.addEventListener("pointerenter", (ev) => dica(ev,
      `<b>${d.inst.n}</b>${fmt(d.valor, meta.u)}` +
      (d.den ? `<br>${nf(0, 0).format(d.num)} em ${nf(0, 0).format(d.den)}` : "") +
      `<br>${d.inst.d} · ${d.inst.r}`));
    g.addEventListener("pointerleave", escondeDica);
    g.addEventListener("click", () => { estado.inst = d.inst.id; escreverHash(); renderFicha();
      $("#sec-hospital").scrollIntoView({ behavior: "smooth" }); });
    svg.append(g);
  });
}

/* ── dica ───────────────────────────────────────────────────────────────── */

const elTip = $("#tip");
function dica(ev, html) {
  elTip.innerHTML = html; elTip.classList.add("on");
  const m = 14, r = elTip.getBoundingClientRect();
  elTip.style.left = Math.min(ev.clientX + m, innerWidth - r.width - 8) + "px";
  elTip.style.top = Math.min(ev.clientY + m, innerHeight - r.height - 8) + "px";
}
const escondeDica = () => elTip.classList.remove("on");

/* ── secções ────────────────────────────────────────────────────────────── */

const DESTAQUE_IDS = ["cesarianas", "lic-dentro-tmrg", "fratura-anca-48h", "urgencia-atendimentos", "divida-vencida"];

let primeiraPintura = true;

function contarAte(el, alvo, casas) {
  if (!Number.isFinite(alvo) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const nf = new Intl.NumberFormat("pt-PT",
    { minimumFractionDigits: casas, maximumFractionDigits: casas });
  const dur = Math.min(1100, 420 + Math.log10(Math.max(alvo, 10)) * 130);
  const t0 = performance.now();
  const passo = (agora) => {
    const t = Math.min(1, (agora - t0) / dur);
    const e = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
    el.textContent = nf.format(alvo * e);
    if (t < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}

function renderStats() {
  const el = $("#stats"); el.textContent = "";
  const nInst = instVisiveis().length;
  const periodo = estado.de === estado.ate ? String(estado.de) : `${estado.de}–${estado.ate}`;
  // O ícone vem do sprite gerado por scripts/build_dashboard.py a partir do
  // componente do sítio — não há aqui traçados que possam divergir dos de lá.
  const cartoes = [
    ["Unidades de saúde", nInst, "com dados no filtro atual", nInst, "hospital"],
    ["Indicadores", IND.length, "acesso, qualidade, capacidade, contas", IND.length, "grafico"],
    ["Período", periodo, `${MESES.length} meses disponíveis`, undefined, "calendario"],
  ];
  const n = nacional("consultas-hospitalares");
  if (n) cartoes.push(["Consultas hospitalares", fmt(n.valor, "contagem"), "no período selecionado", n.valor, "pessoa"]);
  const u = nacional("urgencia-atendimentos");
  if (u) cartoes.push(["Atendimentos em urgência", fmt(u.valor, "contagem"), "no período selecionado", u.valor, "pulso"]);

  for (const [t, v, sub, cru, ic] of cartoes) {
    const d = document.createElement("div"); d.className = "stat";
    const icone = ic
      ? `<svg class="icone" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true"><use href="#ic-${ic}"/></svg>`
      : "";
    d.innerHTML = `${icone}<b class="num">${v}</b><span>${t}</span><em>${sub}</em>`;
    el.append(d);
    if (primeiraPintura && cru !== undefined) contarAte(d.querySelector("b"), cru, 0);
  }
  primeiraPintura = false;
}

function renderDestaques() {
  const el = $("#destaques"); el.textContent = "";
  for (const id of DESTAQUE_IDS) {
    const meta = IND[idxInd(id)]; if (!meta) continue;
    const n = nacional(id); if (!n || n.valor === null) continue;
    const linhas = porInstituicao(id);
    let nota = "";
    if (linhas.length > 1) {
      const ord = [...linhas].sort((a, b) => b.valor - a.valor);
      const alto = ord[0], baixo = ord[ord.length - 1];
      nota = `Entre ${fmt(baixo.valor, meta.u)} e ${fmt(alto.valor, meta.u)} conforme a unidade.`;
    }
    if (meta.ref) nota += ` Referência: ${meta.ref.valor} %.`;
    const d = document.createElement("div"); d.className = "dst reveal";
    d.innerHTML = `<i>${meta.g}</i><b class="num">${fmt(n.valor, meta.u)}</b>` +
      `<p>${meta.t}. ${nota}</p>`;
    el.append(d);
  }
}

function chipsIndicador(cont, chave, aoMudar) {
  cont.textContent = "";
  for (const meta of IND) {
    const b = document.createElement("button");
    b.className = "chip"; b.textContent = meta.t.length > 42 ? meta.t.slice(0, 41) + "…" : meta.t;
    b.title = meta.t;
    b.setAttribute("aria-pressed", String(estado[chave] === meta.id));
    b.addEventListener("click", () => { estado[chave] = meta.id; escreverHash(); aoMudar(); });
    cont.append(b);
  }
}

function renderEvo() {
  const meta = IND[idxInd(estado.evo)];
  chipsIndicador($("#evo-chips"), "evo", renderEvo);
  linha($("#evo"), serieNacional(estado.evo), meta, { h: 260 });
  $("#evo-fonte").textContent =
    `Fonte: ${meta.ds} · ${meta.pub || "SNS"}${meta.atu ? " · atualizado " + meta.atu : ""}.` +
    (meta.desc ? " " + meta.desc : "");
}

function renderDisp() {
  const meta = IND[idxInd(estado.disp)];
  chipsIndicador($("#disp-chips"), "disp", renderDisp);
  const n = nacional(estado.disp);
  dispersao($("#disp"), porInstituicao(estado.disp), meta, n ? n.mediana : null);
  const c = $("#disp-cautela");
  if (meta.cau) { c.hidden = false; c.innerHTML = "<strong>Cautela.</strong> " + meta.cau; }
  else c.hidden = true;
}

function renderGrupos() {
  for (const grupo of ["acesso", "qualidade", "capacidade", "dinheiro"]) {
    const alvo = $("#g-" + grupo); alvo.textContent = "";
    for (const meta of IND.filter((m) => m.g === grupo)) {
      const n = nacional(meta.id); if (!n) continue;
      const sec = document.createElement("section");
      sec.className = "card reveal";
      sec.innerHTML =
        `<h3>${meta.t}</h3>` +
        `<p class="desc">${meta.desc || ""}</p>` +
        `<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px">` +
        `<b class="num" style="font-family:'Iowan Old Style',Georgia,serif;font-size:30px;line-height:1">` +
        `${fmt(n.valor, meta.u)}</b>` +
        `<span class="desc" style="margin:0">${n.sintese === "mediana entre unidades"
          ? "mediana das " + n.n + " unidades — a fonte publica este valor já calculado, sem os volumes que permitiriam agregá-lo de outra forma"
          : "nacional · mediana das unidades " + fmt(n.mediana, meta.u)}</span></div>` +
        `<div class="serie"></div>` +
        (meta.cau ? `<p class="cautela"><strong>Cautela.</strong> ${meta.cau}</p>` : "") +
        `<p class="fonte-lin">${meta.ds} · ${meta.pub || "SNS"}${meta.atu ? " · atualizado " + meta.atu : ""}</p>`;
      alvo.append(sec);
      linha($(".serie", sec), serieNacional(meta.id), meta, { h: 170 });
    }
  }
}

function renderMapa() {
  const sel = $("#mapa-sel");
  if (!sel.firstChild) {
    const s = document.createElement("select");
    s.id = "sel-mapa";
    for (const m of IND) s.append(new Option(m.t, m.id));
    s.addEventListener("change", () => { estado.mapa = s.value; escreverHash(); renderMapa(); });
    const l = document.createElement("label");
    l.className = "flabel"; l.setAttribute("for", "sel-mapa"); l.textContent = "Indicador ";
    sel.append(l, s);
  }
  $("#sel-mapa").value = estado.mapa;

  const meta = IND[idxInd(estado.mapa)];
  const n = nacional(estado.mapa);
  const linhas = porInstituicao(estado.mapa).filter((d) => d.inst.x !== null);
  const cont = $("#mapa"); cont.textContent = "";

  const svg = svgEl("svg", { viewBox: `0 0 ${MAPA.w} ${MAPA.h}`, role: "img",
    style: "max-height:560px;margin-inline:auto;width:auto" });
  svg.setAttribute("aria-label", `Mapa de ${meta.t} em ${linhas.length} unidades de saúde.`);
  for (const p of MAPA.paths) {
    svg.append(svgEl("path", { d: p.d, fill: "var(--surface-2)", stroke: "var(--grid)",
      "stroke-width": 0.7 }));
  }
  const vols = linhas.map((d) => Math.abs(d.den || d.num) || 1);
  const vmax = Math.max(...vols, 1);
  const raio = (v) => 4 + 13 * Math.sqrt(Math.abs(v) / vmax);
  const bom = (v) => meta.p === "neutro" ? null
    : (meta.p === "subir_e_bom" ? v >= n.mediana : v <= n.mediana);

  for (const d of [...linhas].sort((a, b) => (b.den || b.num) - (a.den || a.num))) {
    const b = bom(d.valor);
    const c = svgEl("circle", { cx: d.inst.x, cy: d.inst.y, r: raio(d.den || d.num),
      fill: b === null ? "var(--accent)" : b ? "var(--cmp-bom)" : "var(--cmp-mau)",
      "fill-opacity": .62, stroke: "var(--surface)", "stroke-width": 1, style: "cursor:pointer" });
    c.addEventListener("pointerenter", (ev) => dica(ev,
      `<b>${d.inst.n}</b>${fmt(d.valor, meta.u)}<br>${d.inst.d} · ${d.inst.r}`));
    c.addEventListener("pointerleave", escondeDica);
    c.addEventListener("click", () => { estado.inst = d.inst.id; escreverHash(); renderFicha();
      $("#sec-hospital").scrollIntoView({ behavior: "smooth" }); });
    svg.append(c);
  }
  cont.append(svg);

  $("#mapa-legenda").innerHTML = meta.p === "neutro"
    ? `<span><i style="background:var(--accent)"></i>unidade de saúde</span>` +
      `<span>tamanho conforme o volume</span>`
    : `<span><i style="background:var(--cmp-bom)"></i>melhor que a mediana</span>` +
      `<span><i style="background:var(--cmp-mau)"></i>pior que a mediana</span>` +
      `<span>tamanho conforme o volume</span>`;
}

function renderTabela() {
  const cols = [
    { t: "Unidade", f: (d) => d.inst.n },
    { t: "Distrito", f: (d) => d.inst.d },
  ];
  const usados = ["cesarianas", "lic-dentro-tmrg", "fratura-anca-48h", "ocupacao-internamento",
    "prazo-medio-pagamento", "urgencia-atendimentos"].filter((id) => idxInd(id) >= 0);
  for (const id of usados) {
    const meta = IND[idxInd(id)];
    cols.push({ t: meta.t.length > 22 ? meta.t.slice(0, 21) + "…" : meta.t, tit: meta.t,
      num: true, u: meta.u, id });
  }

  const dados = instVisiveis().map(([x, j]) => {
    const r = { inst: x };
    for (const id of usados) { const a = agregar(idxInd(id), j); r[id] = a ? a.valor : null; }
    return r;
  });

  const thead = $("#tab thead"); thead.textContent = "";
  const tr = document.createElement("tr");
  cols.forEach((c, k) => {
    const th = document.createElement("th");
    th.textContent = c.t; if (c.tit) th.title = c.tit;
    th.setAttribute("scope", "col");
    if (estado.ordem.col === k) th.textContent += estado.ordem.desc ? " ▾" : " ▴";
    th.addEventListener("click", () => {
      if (estado.ordem.col === k) estado.ordem.desc = !estado.ordem.desc;
      else estado.ordem = { col: k, desc: true };
      renderTabela();
    });
    tr.append(th);
  });
  thead.append(tr);

  const c = cols[estado.ordem.col];
  const val = (d) => c.id ? d[c.id] : c.f(d);
  dados.sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va === null) return 1; if (vb === null) return -1;
    const r = typeof va === "string" ? va.localeCompare(vb, "pt") : va - vb;
    return estado.ordem.desc ? -r : r;
  });

  const tbody = $("#tab tbody"); tbody.textContent = "";
  for (const d of dados) {
    const row = document.createElement("tr");
    // data-ind identifica o indicador de cada célula: sem isso, uma verificação
    // que percorra a tabela não sabe a que indicador o valor pertence.
    row.innerHTML = cols.map((col) => col.id
      ? `<td class="num" data-ind="${col.id}">${fmt(d[col.id], col.u)}</td>`
      : `<td>${col.f(d)}</td>`).join("");
    row.addEventListener("click", () => { estado.inst = d.inst.id; escreverHash(); renderFicha();
      $("#sec-hospital").scrollIntoView({ behavior: "smooth" }); });
    tbody.append(row);
  }
}

function renderFicha() {
  const sel = $("#sel-inst");
  if (!sel.options.length) {
    for (const x of [...INST].sort((a, b) => a.n.localeCompare(b.n, "pt"))) sel.append(new Option(x.n, x.id));
    sel.addEventListener("change", () => { estado.inst = sel.value; escreverHash(); renderFicha(); });
  }
  if (!estado.inst) {
    // Abre na unidade com mais indicadores preenchidos, não na primeira da
    // lista: uma ficha vazia como primeira impressão não serve ninguém.
    let melhor = null, max = -1;
    INST.forEach((x, j) => {
      const n = IND.reduce((s, _, i) => s + (SERIES[i + ":" + j] ? 1 : 0), 0);
      if (n > max) { max = n; melhor = x.id; }
    });
    estado.inst = melhor || sel.options[0].value;
  }
  sel.value = estado.inst;

  const x = INST.find((i) => i.id === estado.inst);
  const j = INST.indexOf(x);
  const el = $("#ficha"); el.textContent = "";

  const cab = document.createElement("div");
  cab.innerHTML = `<h3 style="font-family:'Iowan Old Style',Georgia,serif;font-size:22px">${x.nome}</h3>` +
    `<p class="desc">${x.d} · ${x.r}</p>`;
  if (x.sucessao && x.sucessao.length) {
    const s = x.sucessao.map((v) => v.de.length > 1
      ? `Em ${v.data} resultou da fusão de ${v.de.length} entidades: ${v.de.join("; ")} (${v.lei}).`
      : `Em ${v.data} sucedeu a ${v.de[0]} (${v.lei}).`).join(" ");
    cab.innerHTML += `<p class="cautela">${s} As séries somam as antecessoras para não se
      partirem — mas a organização de hoje não é a mesma de antes.</p>`;
  }
  el.append(cab);

  const g = document.createElement("div");
  g.className = "fichagrid"; g.style.marginTop = "16px";
  for (const meta of IND) {
    const a = agregar(idxInd(meta.id), j); if (!a || a.valor === null) continue;
    const n = nacional(meta.id);
    let cls = "neu", txt = n && n.mediana !== null ? "mediana " + fmt(n.mediana, meta.u) : "";
    // Um saldo ou um efetivo a zero é quase sempre ausência de registo, e não
    // um resultado: apresentá-lo como «100 % melhor que a mediana» seria falso.
    const zeroSuspeito = a.valor === 0 && !meta.soma && n && n.mediana;
    if (zeroSuspeito) txt = "sem registo no período";
    else if (n && n.mediana !== null && meta.p !== "neutro") {
      const dif = a.valor - n.mediana;
      const melhor = meta.p === "subir_e_bom" ? dif > 0 : dif < 0;
      if (Math.abs(dif / (n.mediana || 1)) >= 0.03) {
        // A seta indica a direção (acima ou abaixo); a cor indica se isso é bom
        // ou mau. Juntar as duas coisas numa só seta faria um valor acima da
        // mediana aparecer com uma seta para baixo só por ser mau.
        cls = melhor ? "pos" : "neg";
        const magnitude = meta.u === "percentagem"
          ? nf(0, 1).format(Math.abs(dif)) + " pontos"
          : nf(0, 0).format(100 * Math.abs(dif / (n.mediana || 1))) + " %";
        txt = (dif > 0 ? "▲ " : "▼ ") + magnitude +
          (dif > 0 ? " acima" : " abaixo") + " da mediana";
      } else txt = "em linha com a mediana";
    }
    const d = document.createElement("div");
    d.className = "mini reveal";
    d.innerHTML = `<h4>${meta.t}</h4><b class="num">${fmt(a.valor, meta.u)}</b>` +
      `<div class="cmp ${cls}">${txt}</div>` +
      (a.den ? `<div class="frac num">${nf(0, 0).format(a.num)} em ${nf(0, 0).format(a.den)}</div>` : "");
    g.append(d);
  }
  el.append(g);
}

/* ── exportação PNG ─────────────────────────────────────────────────────── */

function exportarPNG(idAlvo) {
  const svg = $("#" + idAlvo + " svg"); if (!svg) return;
  const est = getComputedStyle(document.body);
  const clone = svg.cloneNode(true);
  // As variáveis CSS não sobrevivem à serialização: fixamo-las no clone.
  for (const el of [clone, ...clone.querySelectorAll("*")]) {
    for (const at of ["fill", "stroke"]) {
      const v = el.getAttribute(at);
      if (v && v.startsWith("var(")) {
        el.setAttribute(at, est.getPropertyValue(v.slice(4, -1).trim()).trim() || "#888");
      }
    }
    if (el.classList.contains("gl")) el.setAttribute("stroke", est.getPropertyValue("--grid").trim());
    if (el.classList.contains("bl")) el.setAttribute("stroke", est.getPropertyValue("--baseline").trim());
    if (el.classList.contains("qb")) el.setAttribute("stroke", est.getPropertyValue("--brand").trim());
    if (el.classList.contains("ax") && !el.getAttribute("fill")) {
      el.setAttribute("fill", est.getPropertyValue("--muted").trim());
    }
  }
  const vb = (clone.getAttribute("viewBox") || "0 0 1000 300").split(/\s+/).map(Number);
  const [W, H] = [vb[2], vb[3] + 26];
  clone.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const cr = svgEl("text", { x: 4, y: H - 6, "font-size": 11,
    fill: est.getPropertyValue("--muted").trim() });
  cr.textContent = "snsRadar · dados: Portal da Transparência do SNS · fonte não oficial";
  clone.append(cr);

  const s = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  img.onload = () => {
    const esc = 2, c = document.createElement("canvas");
    c.width = W * esc; c.height = H * esc;
    const ctx = c.getContext("2d");
    ctx.fillStyle = est.getPropertyValue("--surface").trim() || "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    const a = document.createElement("a");
    a.download = `snsradar-${idAlvo}.png`; a.href = c.toDataURL("image/png"); a.click();
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(s);
}

/* ── arranque ───────────────────────────────────────────────────────────── */

function renderTudo() {
  renderStats(); renderDestaques(); renderEvo(); renderDisp();
  renderGrupos(); renderMapa(); renderTabela(); renderFicha();
  observarReveal();
}

function montarFiltros() {
  for (const [id, chave] of [["#sel-de", "de"], ["#sel-ate", "ate"]]) {
    const s = $(id);
    for (const a of ANOS) s.append(new Option(a, a));
    s.value = estado[chave];
    s.addEventListener("change", () => {
      estado[chave] = +s.value;
      if (estado.de > estado.ate) { if (chave === "de") estado.ate = estado.de; else estado.de = estado.ate; }
      $("#sel-de").value = estado.de; $("#sel-ate").value = estado.ate;
      $$("[data-range]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      escreverHash(); renderTudo();
    });
  }
  $$("[data-range]").forEach((b) => b.addEventListener("click", () => {
    const [a, z] = b.dataset.range.split(",").map(Number);
    estado.de = a || ANOS[0]; estado.ate = z || ANOS[ANOS.length - 1];
    $("#sel-de").value = estado.de; $("#sel-ate").value = estado.ate;
    $$("[data-range]").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    escreverHash(); renderTudo();
  }));

  const cr = $("#chips-regiao");
  const todas = document.createElement("button");
  todas.className = "chip"; todas.textContent = "Todas";
  todas.setAttribute("aria-pressed", String(estado.regioes.size === REGIOES.length));
  todas.addEventListener("click", () => { estado.regioes = new Set(REGIOES); montarChipsRegiao(); escreverHash(); renderTudo(); });
  cr.append(todas);
  for (const r of REGIOES) {
    const b = document.createElement("button");
    b.className = "chip"; b.textContent = r; b.dataset.reg = r;
    b.addEventListener("click", () => {
      if (estado.regioes.size === REGIOES.length) estado.regioes = new Set([r]);
      else if (estado.regioes.has(r)) { estado.regioes.delete(r); if (!estado.regioes.size) estado.regioes = new Set(REGIOES); }
      else estado.regioes.add(r);
      montarChipsRegiao(); escreverHash(); renderTudo();
    });
    cr.append(b);
  }
  montarChipsRegiao();

  const cg = $("#chips-grupo");
  if (GRUPOS_ACSS.length) {
    const todosG = document.createElement("button");
    todosG.className = "chip"; todosG.textContent = "Todos";
    todosG.addEventListener("click", () => {
      estado.grupos = new Set(GRUPOS_ACSS); montarChipsGrupo(); escreverHash(); renderTudo();
    });
    cg.append(todosG);
    for (const g of GRUPOS_ACSS) {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = g.replace(/^Grupo\s+/, ""); b.dataset.gr = g;
      b.title = g;
      b.addEventListener("click", () => {
        if (estado.grupos.size === GRUPOS_ACSS.length) estado.grupos = new Set([g]);
        else if (estado.grupos.has(g)) {
          estado.grupos.delete(g);
          if (!estado.grupos.size) estado.grupos = new Set(GRUPOS_ACSS);
        } else estado.grupos.add(g);
        montarChipsGrupo(); escreverHash(); renderTudo();
      });
      cg.append(b);
    }
    montarChipsGrupo();
  }

  $("#btn-tema").addEventListener("click", () => {
    const raiz = document.documentElement;
    const escuro = raiz.dataset.theme === "dark" ||
      (!raiz.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    raiz.dataset.theme = escuro ? "light" : "dark";
    localStorage.setItem("snsradar-tema", raiz.dataset.theme);
  });

  $$(".png").forEach((b) => b.addEventListener("click", () => exportarPNG(b.dataset.png)));
}

function montarChipsGrupo() {
  const todos = estado.grupos.size === GRUPOS_ACSS.length;
  const cg = $("#chips-grupo");
  if (!cg) return;
  cg.firstChild?.setAttribute("aria-pressed", String(todos));
  $$("[data-gr]", cg).forEach((b) =>
    b.setAttribute("aria-pressed", String(!todos && estado.grupos.has(b.dataset.gr))),
  );
}

function montarChipsRegiao() {
  const todas = estado.regioes.size === REGIOES.length;
  $("#chips-regiao").firstChild.setAttribute("aria-pressed", String(todas));
  $$("#chips-regiao [data-reg]").forEach((b) =>
    b.setAttribute("aria-pressed", String(!todas && estado.regioes.has(b.dataset.reg))));
}

let obs;
function observarReveal() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
    $$(".reveal").forEach((e) => e.classList.add("in")); return;
  }
  obs = obs || new IntersectionObserver((ents) => {
    for (const e of ents) if (e.isIntersecting) { e.target.classList.add("in"); obs.unobserve(e.target); }
  }, { rootMargin: "0px 0px -40px 0px" });
  $$(".reveal:not(.in)").forEach((e) => obs.observe(e));
}

lerHash();
$("#lim-txt") && ($("#lim-txt").textContent = LIMIAR);
montarFiltros();
renderTudo();
addEventListener("hashchange", () => { lerHash(); renderTudo(); });
