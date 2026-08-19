// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

import fs from 'node:fs';
import path from 'node:path';

/**
 * A raiz do portal é o painel: `index.html` na raiz do repositório, 2,8 MB
 * gerados por `scripts/build_dashboard.py`, com o seu próprio `<head>`. É a
 * forma do csmRadar. Não é uma página do Astro e não pode ser — envolvê-lo num
 * layout partia a autonomia que o define.
 *
 * Em produção, a ação de publicação copia esse ficheiro para o topo do que vai
 * para o ar. Aqui serve-se o mesmo ficheiro, lido do disco a cada pedido, para
 * que quem trabalha veja em `/snsRadar/` exatamente o que o portal serve. Já
 * houve um 404 no painel que só existia em desenvolvimento; a lição foi manter
 * os dois ambientes iguais.
 */
const painelNaRaiz = {
  name: 'painel-na-raiz',
  configureServer(servidor) {
    servidor.middlewares.use((pedido, resposta, seguinte) => {
      const caminho = (pedido.url ?? '').split('?')[0];
      if (caminho !== '/snsRadar/' && caminho !== '/snsRadar') return seguinte();
      const ficheiro = path.resolve(process.cwd(), '..', 'index.html');
      if (!fs.existsSync(ficheiro)) {
        resposta.statusCode = 404;
        return resposta.end('index.html ainda não foi gerado: corra scripts/build_dashboard.py');
      }
      resposta.setHeader('content-type', 'text/html; charset=utf-8');
      resposta.end(fs.readFileSync(ficheiro));
    });
  },
};

/**
 * O portal é servido pelo GitHub Pages em
 * https://sergioamsilva.github.io/snsRadar/ — numa subpasta, e não na raiz de
 * um domínio. `base` fica aplicado também em desenvolvimento, de propósito: foi
 * uma diferença entre os dois ambientes que deixou passar o 404 de `/painel/`.
 *
 * Nenhuma ligação interna do sítio é escrita à mão com o prefixo. Passam todas
 * pelo ajudante `ligacao()` de `src/lib/dados.ts`, que lê este valor. Mudar
 * para um domínio próprio é mudar as duas linhas abaixo — e a constante
 * `BASE_SITIO` em `scripts/build_dashboard.py`, que faz o mesmo para o painel.
 */
// https://astro.build/config
export default defineConfig({
  site: 'https://sergioamsilva.github.io',
  base: '/snsRadar',
  integrations: [
    // O sitemap só conhece as páginas do Astro; a raiz é o painel, que vem de
    // fora (ver `painelNaRaiz`), e entra aqui à mão para não ficar invisível
    // aos motores de busca.
    sitemap({
      customPages: ['https://sergioamsilva.github.io/snsRadar/'],
    }),
  ],
  vite: { plugins: [painelNaRaiz] },
});
