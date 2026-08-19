/**
 * Nenhuma página fica presa a uma largura fixa.
 *
 * O portal usa **largura total com goteira** (`.wrap` em global.css): o
 * conteúdo ocupa o ecrã e é a goteira `--gutter` que dá o respiro. A medida de
 * leitura — 62 a 78 caracteres — aplica-se à **prosa**, em `ch`, e nunca ao
 * contentor da página.
 *
 * A regra existe porque foi quebrada: a página de grupo nasceu com
 * `max-width: 54rem` no contentor, e num ecrã de 1600 px punha o mapa do
 * tamanho de um selo com dois terços da largura vazios. Ninguém dá por isso a
 * desenvolver em 1280 px — dá-se por isso quando alguém abre o portal num
 * monitor a sério.
 *
 * Corre com um servidor a servir o sítio:
 *     node scripts/verificar_larguras.mjs 4321
 */
import { chromium } from "playwright";

const BASE = `http://127.0.0.1:${process.argv[2] ?? "4321"}/snsRadar`;
const PAGINAS = [
  "/instituicoes/",
  "/perguntas/",
  "/metodologia/",
  "/instituicao/uls-sao-joao/",
  "/grupo/c/",
  "/grupo/",
  "/comparar/",
  "/alteracoes/",
];

/* A goteira come ~6 % a 1600 px (3vw de cada lado). Abaixo de 90 % há mais do
   que a goteira a limitar, e é isso que este teste procura. */
const MINIMO = 0.9;
const LARGURA = 1600;

const b = await chromium.launch();
const p = await (
  await b.newContext({ viewport: { width: LARGURA, height: 1000 } })
).newPage();

let falhas = 0;
for (const url of PAGINAS) {
  await p.goto(BASE + url, { waitUntil: "load" });
  const r = await p.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const blocos = [...document.querySelectorAll("main > *, main > * > *")]
      .map((el) => ({
        tag:
          el.tagName.toLowerCase() +
          (el.className ? "." + String(el.className).split(" ")[0] : ""),
        w: Math.round(el.getBoundingClientRect().width),
      }))
      .filter((x) => x.w > 100);
    const maior = blocos.reduce((a, x) => (x.w > a.w ? x : a), { w: 0, tag: "—" });
    return { vw, maior };
  });

  const fracao = r.maior.w / r.vw;
  const marca = fracao >= MINIMO ? "ok    " : "FALHA ";
  if (fracao < MINIMO) falhas++;
  console.log(
    `  ${marca} ${url.padEnd(28)} ${String(r.maior.w).padStart(5)}px de ${r.vw} ` +
      `(${Math.round(100 * fracao)} %)  ${r.maior.tag}`,
  );
}

await b.close();
if (falhas) {
  console.log(
    `\n  ${falhas} página(s) presas a uma largura fixa. O contentor da página não ` +
      `leva max-width — a medida de leitura é da prosa, em ch.`,
  );
}
process.exit(falhas ? 1 : 0);
