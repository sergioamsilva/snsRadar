# Registo de alterações

Este ficheiro existe por uma razão que não é a arrumação: **os números deste
portal são citáveis, e alguns já mudaram.**

Um indicador pode ser acrescentado, mudar de definição, mudar de escala ou ser
retirado. Quem tiver citado um valor precisa de saber se ainda é o mesmo — e
quem tiver encontrado uma diferença precisa de saber se foi a fonte que se
corrigiu, se fomos nós, ou se está a olhar para outra coisa.

Regista-se aqui o que muda a leitura de um número publicado. Alterações de
código que não mexem em valores ficam no histórico de commits, que neste projeto
é detalhado de propósito. O que se aprendeu sobre cada fonte está em
[`reference/NOTAS.md`](reference/NOTAS.md); as verificações contra terceiros, em
[`reference/VALIDACAO-EXTERNA.md`](reference/VALIDACAO-EXTERNA.md).

---

## 14 de agosto de 2026

### Correções a números que estiveram publicados

- **Gastos operacionais por utente inscrito** — o cartão mostrava `118 €` com o
  título «Gastos operacionais por utente inscrito», que se lê como um valor
  anual. É **mensal**: o anual, para a mesma unidade, são cerca de 1 417 €. A
  causa é que os inscritos são um *stock* e não um fluxo — a fonte repete a
  mesma população em cada mês, e a soma de doze meses dá doze populações.
  Descoberto ao confrontar o denominador da ACSS com a população que o projeto
  apura do INE, que dava +1 083 %, ou seja, exatamente doze vezes.
  O título passou a **«Gastos operacionais por utente inscrito, por mês»**.
  Esteve online cerca de 57 minutos, entre as 23:11 de 13 de agosto e as 00:08
  de 14 de agosto. Verificado que nenhum dos outros 51 indicadores tem
  denominador de stock.

### Indicadores novos

- **Consumo de antibióticos por 1000 dias de internamento** (total, carbapenemes
  e fluoroquinolonas). É a escala com que a ECDC compara hospitais e países.
  Junta o registo do INFARMED ao de ocupação do internamento — duas fontes que
  só se encontram depois de o crosswalk as reduzir à mesma entidade. Os
  indicadores de *peso* de cada classe mantêm-se: medem a composição do consumo,
  estes medem o volume.

### Camadas novas

- **Contratos públicos por doente padrão** — o registo do IMPIC lido na escala de
  produção ajustada à complexidade da ACSS. Aparece no cartão de contratos.
- **Índice de segurança** — os seis indicadores de segurança resumidos na média
  dos desvios padronizados face à taxa do país.
- **A reforma de 2024, medida** — comparação dos doze meses anteriores e
  posteriores a janeiro de 2024, entre as 32 entidades que passaram a ULS e as
  sete que já o eram. Publicada na página de metodologia, com os seus limites.

### Gráficos novos

- **Cruzamentos** entre dois indicadores, com a cautela ecológica visível:
  enfermeiros e úlceras de pressão; segurança e mortalidade ajustada ao risco.

---

## 13 de agosto de 2026

### Fonte nova: Benchmarking Hospitalar da ACSS

Segunda fonte de indicadores, a par do Portal da Transparência. A sua situação
jurídica é mais frágil e está declarada em [`ATRIBUICAO.md`](ATRIBUICAO.md):
sem API, sem licença aberta, «todos os direitos reservados».

### Indicadores novos

Vinte e quatro, dos quais uma dimensão inteira que não existia:

- **Segurança do doente** (6): úlceras de pressão, infeções por cateter venoso
  central, sépsis e embolia/trombose pós-operatórias, lacerações graves em
  partos instrumentados e não instrumentados.
- **Volume cirúrgico de alto risco** (6): resseções do pâncreas e do esófago,
  aneurismas da aorta abdominal, bypass coronário, angioplastia coronária,
  endarterectomia da carótida.
- **Resultados**: reinternamentos até 30 dias, internamentos com mais de 30
  dias, cesarianas em gestações de termo unifetais e cefálicas, partos vaginais
  após cesariana.
- **Produtividade e gastos por doente padrão** (8), a partir de 2018 — a
  contabilidade pública mudou para o SNC-AP nesse ano e a própria ACSS mantém as
  séries separadas.

### Alterações de leitura

- **Comparação entre pares.** Cada ficha passou a comparar-se também com o seu
  grupo de financiamento da ACSS (B a F), e não só com a mediana de todas as
  unidades — que junta um instituto de oncologia a uma unidade local. A mediana
  nacional mantém-se, ao lado.
- **Escalas novas** — por mil e por cem mil episódios, nas taxas de segurança,
  porque é assim que a ACSS as define. Uma taxa de sépsis apresentada como
  proporção apareceria como 0,0004.

### Indicador retirado antes de ser publicado

- **% de Primeiras Cesarianas em Gestações Unifetais, Cefálicas, a Termo.** Seria
  o indicador mais valioso do conjunto — o equivalente português da medida PC-02
  da Joint Commission. Não é o que a exportação traz: o denominador exportado
  contradiz a fórmula que a ACSS declara, e o resultado dava 97,6 % de mediana
  nacional. Retirado antes de qualquer publicação. Ver
  [`reference/NOTAS.md`](reference/NOTAS.md), secção 22.

### Gráficos novos

- **Funnel plot** nos indicadores de segurança. Ordenar 43 hospitais por taxas
  de acontecimentos raros, com denominadores que variam por um fator de 228, é
  publicar ruído: o funil mostra que só duas a sete unidades por indicador se
  distinguem do acaso.
- **Gráfico de declive** nas cesarianas, que explica porque é que a taxa sobe ao
  restringir ao grupo de menor risco.
- **Ordenamento nacional** no volume cirúrgico.
- **Dispersão do painel repartida por grupo**, com o mesmo eixo em todos.

### Verificação nova

- Confronto com a ACSS **unidade a unidade e mês a mês**, e não apenas em totais
  nacionais. Nos indicadores que as duas fontes publicam e a perímetro igual,
  cinco dos sete coincidem a 100 % — incluindo o numerador e o denominador de
  cada mês nas cesarianas e nas fraturas da anca. É a verificação mais exigente
  do tratamento das séries acumuladas que existe, porque a ACSS publica os
  mesmos factos sem acumulação.

---

## 4 de agosto de 2026

Primeira publicação. 43 fichas de instituição, 25 indicadores, séries de 2013 a
2026 atravessando a reforma das ULS.
