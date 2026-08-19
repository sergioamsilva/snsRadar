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

## 19 de agosto de 2026

### Comparação direta entre duas unidades

Página nova, `/comparar/`: duas unidades à escolha, lado a lado, indicador a
indicador, com a mediana nacional por referência e o placar de quem está à
frente. O endereço guarda a escolha, para se poder partilhar uma comparação.
Avisa quando as unidades não pertencem ao mesmo grupo da ACSS — nesse caso a
diferença pode dizer mais sobre a natureza de cada uma do que sobre o
desempenho.

### Os dados de cada ficha, para descarregar

Cada ficha passa a oferecer os seus dados em **JSON** (o próprio ficheiro de
que a página é construída, com fonte, data e URL de prova por valor) e em
**CSV** (a série achatada, uma linha por indicador e mês, pronta para folha de
cálculo). É a promessa do portal — cada número reproduz-se — cumprida também
para quem não quer chamar a API.

### Gráficos novos

- **Calendário** (anos × meses) na ocupação do internamento e nos atendimentos
  em urgência: a sazonalidade, que na linha temporal fica escondida, lê-se num
  relance vertical.
- **Miniaturas do grupo** na página de cada grupo da ACSS: todas as unidades na
  mesma escala, com a mediana do grupo a tracejado — para ver se o grupo se
  move junto ou se há unidades a descolar.
- **Posição entre pares** em quatro indicadores da ficha (cirurgia no prazo,
  cesarianas, prazo de pagamento, reinternamentos): o percentil mensal da
  unidade dentro do seu grupo, de 0 a 100, com a polaridade já aplicada —
  responde a «está a melhorar face aos pares, ou só a acompanhar a maré?».
- **Antes e depois da reforma** na metodologia: a variação de cada taxa nas 32
  entidades transformadas contra as 7 do grupo de controlo, em pontos ligados
  no mesmo eixo. A tabela mantém-se, completa, dobrada por baixo.

### Este registo passou a viver no portal

Em `/alteracoes/`, com um feed Atom em `/alteracoes.xml` — quem citou um número
pode ser avisado quando ele mudar, sem precisar de saber o que é o GitHub.
Também novas: a procura em todas as páginas (tecla `/`), filtros por região,
natureza e grupo na lista, um índice dos grupos em `/grupo/`, e ligação
permanente em cada cartão de indicador.

### Correções

- **População e mortalidade ajustada voltaram a acompanhar o pipeline.** Os
  ficheiros `populacao.json` e `mortalidade-ajustada.json` só eram reescritos
  quando corridos à mão, e estavam parados desde 2 de agosto enquanto o resto
  do portal avançava. O `atualizar.py` passa a reescrevê-los sempre.
- **Os três datasets de antibióticos entraram no núcleo da descarga.**
  Alimentam seis indicadores mas não eram renovados pelo
  `atualizar.py --descarregar`; envelheciam em silêncio desde a descarga que
  os trouxe.
- **Cartão de indicador**: quando o valor estava em linha com a mediana do
  grupo, o texto colava as duas comparações («…em linha com a mediana
  nacionalda mediana do Grupo E»). Escrevia-se mal, mas os números estavam
  certos.

---

## 14 de agosto de 2026

### Navegar por cluster, e não só vê-lo

> Sugerido por [Tomás Araújo](https://www.linkedin.com/in/tom%C3%A1s-ara%C3%BAjo99/):
> «não achas que dava para comparar hospitais dentro do mesmo cluster?»

O grupo de comparação da ACSS deixou de existir apenas dentro de uma ficha:

- **uma página por grupo** (`/grupo/b/` a `/grupo/f/`), com as unidades que o
  compõem e a mediana do grupo ao lado da nacional em cada indicador — é aí que
  se vê que há grupos inteiros sistematicamente acima ou abaixo do país;
- a **lista de instituições** mostra o grupo de cada unidade, aceita-o na caixa
  de procura e tem atalhos para cada cluster;
- o **painel** filtra por grupo, a par do filtro por região, e o filtro fica no
  endereço.

### Alteração de leitura: o funil passa a comparar dentro do grupo

Os seis indicadores de segurança deixaram de ser lidos contra a taxa do país e
passam a sê-lo contra a **taxa do seu grupo**, com a nacional a traço leve por
contexto. A diferença é grande e muda vereditos: a sépsis pós-operatória corre a
3,7 ‰ no Grupo B e a 11,1 ‰ no Grupo E — três vezes mais. Um hospital do Grupo B
com 5 ‰ parecia bom contra o país e é mau contra os seus pares.

A troca só se faz quando o grupo tem cinco ou mais unidades **e** pelo menos
2 000 episódios; abaixo disso a taxa do grupo não se estima com confiança e a
referência continua a ser a nacional, dizendo-o no texto. Nos cruzamentos, os
pares do grupo aparecem marcados, mas a correlação continua a ser a de todas as
unidades: um coeficiente calculado sobre seis pontos seria um número sem amostra
que o sustente.

### Perguntas novas

Três, na página de perguntas: **«já tive uma cesariana, posso ter parto
normal?»**, **«vou ser operado a uma cirurgia complexa»** e **«o hospital onde
vou ser internado é seguro?»**.

A da segurança responde-se de forma diferente das outras: em vez de ordenar as
unidades do distrito por uma taxa, conta **quantos dos seis indicadores de
segurança saem dos limites de 99,8 %**. Ordenar hospitais por acontecimentos com
mediana de dois casos produziria um ranking de ruído — é o que o gráfico de
funil da ficha existe para evitar, e seria contraditório fazê-lo ali.

### Camada nova: poupanças estimadas pela ACSS

O cálculo da própria ACSS do que cada unidade pouparia se igualasse a mais
eficiente do seu grupo, atribuído sem ambiguidade e datado. Publica-se **2023**,
o último ano em que cobriu o sistema: a partir de 2024 a ACSS só o mantém para
os três institutos de oncologia, porque com a integração dos cuidados primários
os indicadores económico-financeiros deixaram de ser comparáveis. A
descontinuação está registada em [`reference/NOTAS.md`](reference/NOTAS.md),
secção 24 — é ela própria uma perda de transparência.

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

Segunda fonte de indicadores, a par do Portal da Transparência. **Sugerida por
[Tomás Araújo](https://www.linkedin.com/in/tom%C3%A1s-ara%C3%BAjo99/)**, a quem
se deve também a comparação dentro de cada grupo. A sua situação jurídica é mais
frágil e está declarada em [`ATRIBUICAO.md`](ATRIBUICAO.md): sem API, sem
licença aberta, «todos os direitos reservados».

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
