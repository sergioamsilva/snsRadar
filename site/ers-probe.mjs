import { chromium } from 'playwright';

const b = await chromium.launch();
const ctx = await b.newContext({ locale: 'pt-PT', viewport: { width: 1280, height: 1200 } });
const p = await ctx.newPage();

// Regista o que a página vai buscar: se houver API por trás, aparece aqui.
const apis = [];
p.on('response', (r) => {
  const u = r.url();
  if (/\.(json|xlsx?|csv)(\?|$)/i.test(u) || /\/api\//i.test(u)) apis.push(`${r.status()} ${u}`);
});

for (const url of [
  'https://www.ers.pt/pt/atividade/supervisao/selecionar/informacao-de-monitorizacao/informacoes/',
  'https://www.ers.pt/pt/sinas/',
]) {
  await p.goto(url, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(2500);
  const r = await p.evaluate(() => {
    const ls = [...document.querySelectorAll('a[href]')].map((a) => a.href);
    return {
      titulo: document.title,
      total: ls.length,
      ficheiros: ls.filter((h) => /\.(pdf|xlsx?|csv)(\?|$)/i.test(h)).slice(0, 10),
      relatorios: ls.filter((h) => /informacoes\/[a-z0-9-]{10,}/i.test(h)).slice(0, 10),
      sinas: ls.filter((h) => /sinas/i.test(h)).slice(0, 8),
    };
  });
  console.log('\n===', url.slice(20, 90));
  console.log('  título:', r.titulo, '| ligações:', r.total);
  for (const [k, v] of Object.entries(r)) {
    if (Array.isArray(v) && v.length) {
      console.log(`  ${k}:`);
      v.forEach((x) => console.log('    ', x.slice(0, 108)));
    }
  }
}
console.log('\n=== pedidos de dados observados ===');
[...new Set(apis)].slice(0, 12).forEach((a) => console.log('  ', a.slice(0, 120)));
await b.close();
