/**
 * Gera og.png — o cartão que aparece quando alguém partilha o portal.
 *
 * Não é uma imagem desenhada à parte: é a própria abertura do sítio, recortada
 * a 1200×630. Uma imagem promocional feita à mão envelhece assim que o portal
 * muda; esta é o portal.
 *
 *   node scripts/gerar_og.mjs [url]
 *
 * Corre contra um `astro preview` já a servir. O resultado fica em
 * site/public/og.png, versionado — como no csmRadar, para que a publicação não
 * dependa de um navegador estar instalado no servidor de integração. Em
 * `public/`, o Astro copia-o para o build, e o mesmo ficheiro serve o
 * desenvolvimento, o preview e a produção; na raiz do repositório só existia
 * em produção, porque o workflow o copiava à mão.
 */
import { chromium } from "playwright";
import path from "node:path";

const url = process.argv[2] ?? "http://127.0.0.1:4400/snsRadar/instituicoes/";
const saida = path.resolve(process.cwd(), "public", "og.png");

const nav = await chromium.launch();
// Tema escuro: a abertura é uma banda escura, e o cartão fica com o contraste
// que a torna reconhecível numa linha do tempo cheia de cartões brancos.
const ctx = await nav.newContext({
  viewport: { width: 1200, height: 630 },
  colorScheme: "dark",
  locale: "pt-PT",
  deviceScaleFactor: 1,
});
const p = await ctx.newPage();
await p.goto(url, { waitUntil: "networkidle" });

// Esconde a barra fixa e o cabeçalho: num cartão de 1200×630 o que interessa é
// o mapa e a frase, não a navegação.
await p.addStyleTag({
  content: `
    .masthead, .anchors { display: none !important; }
    .wrap { padding-top: 0 !important; }
    .abr { padding-top: 40px !important; }
    /* Um campo de procura numa imagem é um convite que não se pode aceitar,
       e a legenda da escala não se lê a este tamanho. Fora ambos: sobra o
       título, a frase, os números do país e o mapa. */
    .abr__procura, .abr__dica, .mapa__legenda { display: none !important; }
    .abr__mostrador { margin-top: 26px !important; }
  `,
});
await p.waitForTimeout(1800);

const banda = await p.locator(".abr").boundingBox();
await p.screenshot({
  path: saida,
  clip: { x: 0, y: banda.y, width: 1200, height: 630 },
});
await nav.close();
console.log(`og.png — 1200×630, a partir de ${url}`);
