# Notas sobre a fonte

Registo do que se aprendeu sobre os dados do portal Transparência SNS ao
construir o snsRadar. Cada afirmação aqui foi verificada contra os dados e é
reproduzível pelos testes em `tests/`.

Estas notas existem porque nada disto está documentado pela fonte. São o
principal motivo pelo qual os números do snsRadar diferem — e devem diferir —
de qualquer painel construído somando ingenuamente estes CSV.

---

## 1. A maioria das séries é acumulada no ano, não mensal

**O achado mais importante.** Datasets com nomes como «evolução mensal»
publicam, em cada mês, o total acumulado desde janeiro — não o valor daquele
mês. A ULS de Coimbra aparece em 2025 com 394 partos em janeiro, 759 em
fevereiro, 1160 em março.

Somar os doze meses de `partos-e-cesarianas` daria **413 728 partos em 2024**.
Portugal tem cerca de 85 000 nascimentos por ano. O valor correto, depois de
des-acumular, é **64 505** partos em hospitais do SNS — coerente com a quota
do setor público.

Colunas verificadas como acumuladas:

| Dataset | Colunas |
|---|---|
| `partos-e-cesarianas` | partos, cesarianas |
| `atendimentos-em-urgencia-triagem-manchester` | todas as cores + sem triagem |
| `01_sica_evolucao-mensal-das-consultas-medicas-hospitalares` | consultas |
| `cirurgias-em-ambulatorio` | ambos os campos |
| `consultas-em-tempo-real` | ambos os campos |
| `demora-media-antes-da-cirurgia` | dias e episódios |
| `fraturas-da-anca-cirurgias-nas-primeiras-48h` | ambos os campos |
| `intervencoes-cirurgicas` | programadas, urgentes |
| `consultas-em-telemedicina` | total |
| `ocupacao-do-internamento` | dias de internamento (mas **não** a lotação) |
| `percentagem-de-gastos-com-te-e-suplementos...` | ambos os campos |

Colunas verificadas como **não** acumuladas (são saldos ou efetivos):
`divida-total-vencida-e-pagamentos`, `inscritos-em-lic-dentro-do-tmrg-180-dias`,
`trabalhadores-por-grupo-profissional`, `lotacao_praticada`, e as taxas de
mortalidade por AVC.

Tratamento: `ingest/build.py::desacumular`, aplicado por nome de origem antes
de agregar na entidade canónica. Quando falta o mês anterior, ou quando a fonte
revê o acumulado em baixa e a diferença sairia negativa, o mês fica em falta —
um valor ausente é preferível a um valor inventado.

## 2. A «taxa anual de ocupação» é acumulada no ano

Publicada mensalmente, mas não é a ocupação do mês. A fórmula, obtida por
engenharia inversa e não documentada pela fonte, é:

```
taxa = dias_de_internamento_acumulados / (lotação_praticada × dias decorridos no ano)
```

Reproduz 99,8% dos valores publicados (`tests/test_build.py::teste_ocupacao_ytd`).
Os 0,2% restantes explicam-se pela lotação variar durante o ano, sendo a fonte
a usar uma média do período que não publica.

## 3. A reforma ULS de 2024 parte todas as séries

O Decreto-Lei n.º 102/2023 renomeou 32 entidades a 1 de janeiro de 2024. Em
`partos-e-cesarianas`, 2023 tem 31 centros hospitalares e 7 ULS; 2024 tem 1 e
39. Sem correspondência, nenhum gráfico atravessa essa data.

Sete das fusões são de vários-para-um e não preservam o perímetro:

- **ULS de Coimbra** ← Centro Hospitalar e Universitário de Coimbra + Hospital
  Arcebispo João Crisóstomo + Centro de Medicina de Reabilitação Rovisco Pais
- **ULS de São José** ← CHU de Lisboa Central + Centro Hospitalar Psiquiátrico
  de Lisboa + Instituto de Oftalmologia Dr. Gama Pinto
- **ULS da Região de Aveiro** ← Centro Hospitalar do Baixo Vouga + Hospital
  Dr. Francisco Zagalo
- **ULS de Santo António** ← CHU do Porto + Hospital de Magalhães Lemos
  (esta em fevereiro de 2023, pelo DL 6/2023, antes da reforma geral)

O snsRadar soma as entidades antecessoras para reconstruir o perímetro atual
para trás no tempo. É o tratamento correto, mas tem de ser dito ao leitor: a
ULS de Coimbra de 2013 não é a mesma organização que a de 2025.

Ver `reference/instituicoes.yaml` para a tabela completa, com base legal por
entidade.

## 4. Datasets diferentes usam nomes diferentes para o mesmo período

`morbilidade-e-mortalidade-hospitalar` reescreveu a história: usa nomes ULS
desde 2019. Os restantes mantêm os nomes históricos até dezembro de 2023. O
mesmo hospital, no mesmo ano, tem nomes diferentes consoante o dataset.

## 5. Grafias instáveis

A fonte escreve a mesma instituição de muitas maneiras:

- `E.P.E.`, `E. P. E.`, `EPE`, e `Centro Hospitalar do Oeste, EPE, EPE`
- Maiúsculas e minúsculas: `UNIDADE LOCAL DE SAUDE DE CASTELO BRANCO, EPE`
- Com e sem preposição: «ULS **de** Castelo Branco» tornou-se «ULS Castelo
  Branco» em 2024, sem qualquer alteração legal
- Abreviaturas: `S. João` e `São João`, `Dr.` e `Doutor`
- Barras com e sem espaço: `Amadora/Sintra` e `Amadora / Sintra`

São 354 nomes distintos para 44 entidades. Resolvidos por
`ingest/common.py::normalizar_agressivo` mais as chaves declaradas em
`reference/instituicoes.yaml`.

## 6. O catálogo declara contagens erradas

O `records_count` do catálogo diverge do número real de registos em 7 dos 144
datasets. O portal anuncia 3 257 342 registos; tem 2 630 091 — uma
sobredeclaração de 24%.

| Dataset | Anuncia | Tem |
|---|---:|---:|
| `portal-base` | 339 300 | 44 015 |
| `top-50-de-prescricao-rsp-em-locais-nao-sns` | 325 984 | 10 277 |
| `atividade-operacional-do-sns-24` | 8 583 | 577 |
| `dados-financeiros` | 6 492 | 2 896 |
| `inscritos-lic-dentro-tmrg` | 6 403 | 1 890 |
| `utilizacao-de-registo-saude-eletronico...hospitais-q` | 3 865 | 3 726 |
| `utentes-admitidos-e-referenciados` | 425 | 420 |

O `total_count` do endpoint `/records` concorda com ambos os `/exports`, pelo
que é esse o número autoritativo. `ingest/catalog.py` guarda os dois.

## 7. Um defeito de substituição automática na fonte

O nome do Instituto para os Comportamentos Aditivos e as Dependências aparece
como **«Instituto para os Comportamentos Aditivos e as DE. P. E.ndências, I. P.»**.
Uma substituição automática de `EPE` por `E. P. E.` corrompeu a palavra
«Dependências», onde essa sequência de letras ocorre por acaso.

## 8. A taxa de ocupação publicada chega a 3 751 %

Em 610 linhas de `ocupacao-do-internamento` a fonte publica ocupações
superiores a 100 %, com máximos absurdos: 3 751,6 % no Hospital Distrital de
Santarém em janeiro de 2014, 2 659,5 % no Rovisco Pais em janeiro de 2022.
Concentram-se em janeiro, o que é coerente com um denominador acumulado ainda
quase vazio no primeiro mês do ano.

O snsRadar não usa a taxa publicada: recalcula-a a partir dos dias de
internamento des-acumulados e da lotação vezes os dias do mês. Ocupações
ligeiramente acima de 100 % continuam a aparecer, e são reais — abrem-se camas
além da lotação praticada. É o único indicador de percentagem em que isso pode
acontecer, e está declarado como tal em `reference/indicadores.yaml`
(`pode_exceder_100`).

**Mas o recálculo não salva tudo, porque a própria lotação vem errada.** Em 632
meses de 13 unidades, a lotação praticada está fora do intervalo plausível: a
ULS da Lezíria aparece com 10 camas em janeiro de 2014 quando tem cerca de 382,
e a ULS de São José com 12 quando tem 1 153. Nesses meses o denominador colapsa
e a ocupação recalculada dá valores como 3 684 %.

Um hospital genuinamente cheio chega aos 130 %. Acima de 200 % o denominador
está errado, não o hospital — e nesses meses não se apresenta taxa nenhuma, só
as contagens. São 20 pontos em 6 906 (0,29 %). O limiar está declarado em
`maximo_plausivel`, e não escondido no código, para que possa ser discutido.

## 9. Registos residuais de entidades extintas

O Centro Hospitalar Psiquiátrico de Lisboa, absorvido pela ULS de São José em
janeiro de 2024, continua a aparecer em `divida-total-vencida-e-pagamentos` em
setembro de 2024 e abril de 2025 — com todos os valores a zero. Inofensivo,
mas o pipeline reconhece-o explicitamente em vez de o ignorar.

## 10. Óbitos por registar em quatro instituições

Quatro unidades têm a letalidade a cair de forma que o registo não sustenta.
Na ULS de São José, entre 2021 e 2025, os óbitos por doenças do aparelho
circulatório caem 82%, as neoplasias 89% e o aparelho digestivo 95% — uma queda
transversal a **todos** os capítulos CID. Isso não é melhoria clínica.

| Unidade | Letalidade 2021 | 2025 |
|---|---:|---:|
| IPO de Coimbra | 6,6 % | 0,3 % |
| ULS de São José | 4,9 % | 1,4 % |
| ULS de Loures-Odivelas | 7,7 % | 4,4 % |
| ULS do Baixo Alentejo | 7,7 % | 4,6 % |

A letalidade nacional mantém-se estável (7,5% em 2021, 6,7% em 2025), pelo que
não é um fenómeno geral. Estas quatro unidades não recebem mortalidade ajustada
ao risco: publicá-la colocá-las-ia entre as melhores do país sem fundamento.
Deteção automática em `ingest/mortalidade.py::instituicoes_nao_fiaveis`.

## 11. Atraso de reporte nos meses recentes

Os meses mais recentes de `morbilidade_mortalidade_hospit` estão incompletos e
vão sendo preenchidos: junho de 2026 traz 6 926 internamentos contra os ~65 000
habituais. A letalidade mantém-se estável, pelo que o defeito está no volume e
não nos óbitos — mas os oito meses mais recentes são excluídos do cálculo do
SMR.

## 12. O espelho de contratos do SNS estava quase vazio — resolvido

**O problema.** O dataset `portal-base` do Portal da Transparência é um espelho
parcial: 32 unidades, 10 807 contratos, 165 M€, e só desde 2024. A distribuição
era impossível — de 0,01 € a 252 € por utente inscrito, um rácio de 8 535×, e
11 unidades sem um único contrato. A ULS do Algarve constava com 4 contratos e
7 615 € para 561 mil utentes. Não era variação de despesa: era registo em
falta. Só 9 das 43 unidades tinham cobertura suficiente para publicar seja o
que for.

**A solução.** O IMPIC publica o registo integral do Portal BASE em
dados.gov.pt, em domínio público declarado (`other-pd`), atualizado ao dia:
contratos, modificações contratuais e entidades, de 2012 a 2026.

|  | Espelho do SNS | Registo do IMPIC |
|---|---:|---:|
| Unidades resolvidas | 32 | **43** |
| Contratos | 10 807 | **639 706** |
| Valor | 165 M€ | **31 490 M€** |
| Período | 2024–2026 | **2012–2026** |
| Publicáveis | 9 de 43 | **43 de 43** |

Fica de fora uma única unidade: o **Hospital de Cascais**. Confirmado que é
ausência real da fonte e não falha de correspondência — sendo uma PPP em gestão
privada, não consta do registo de entidades adjudicantes do IMPIC, onde só
aparecem privados de Cascais com uma mão-cheia de contratos.

**Duas fontes, de propósito.** Há também uma API (`base.gov.pt/APIBase2`, token
concedido pelo IMPIC) que devolve exatamente os mesmos 39 campos e consulta por
`nifEntidade` sem descarregar nada. Não substitui os ficheiros: devolve
`idContrato` **sempre a `null`** — verificado em 5 091 de 5 091 registos — e é
esse o campo que liga um contrato às suas modificações. Usamo-la para o que os
ficheiros não fazem:

- `GetInfoEntidades` dá o total que o próprio servidor atribui a cada NIF, o
  que permite conferir as nossas somas contra a fonte;
- `numDias` (máximo 90) atualiza sem repuxar 55 MB por ano.

**A verificação apanhou um erro real.** Os totais do servidor ficavam
sistematicamente 1 a 3,4% acima dos nossos. A causa: `adjudicante` é uma
*lista* — numa aquisição conjunta várias entidades assinam o mesmo contrato — e
estávamos a ler só a primeira posição. Perdiam-se 288 contratos e 1 379 M€.
Corrigido percorrendo a lista inteira; o desvio residual (≤3,6%) explica-se
pelos ficheiros começarem em 2012 enquanto o total do servidor conta desde
sempre.

**Dois nomes custaram 84 500 contratos.** O registo do IMPIC grafa a ULS do
Alto Minho como «Unidade Local de Saúde do Alto Minho, EPE (ULSAM)» — a sigla
final impedia a correspondência (11 072 contratos) — e o IPO do Porto como «IPO
Porto FG, EPE» (73 468 contratos, 2 915 M€). O primeiro caso é um padrão da
fonte e resolveu-se em `normalizar()`; o segundo é uma abreviatura própria e
entrou como chave em `instituicoes.yaml`.

**Dado novo: a derrapagem.** As estatísticas de despesa contam o preço da
adjudicação. A modificação contratual é publicada, mas num registo à parte que
ninguém junta ao primeiro. Cruzando os dois por `idcontrato`: **4 034 contratos
do SNS foram alterados depois de assinados, com +115 M€ líquidos**. Nem toda a
modificação é derrapagem — algumas baixam o preço, e entram com sinal negativo.

**Limitação assumida.** `adjudicatarios` também é uma lista, e atribuímos o
valor inteiro ao primeiro fornecedor. Afeta 0,5% dos contratos (3 065 em
667 725) e só distorce o *ranking* de fornecedores, nunca os totais.

## 13. Limites técnicos da API

- `/records` recusa `offset + limit > 10000`. A ingestão completa **tem** de
  usar `/exports/{csv,json}`, que não tem esse limite.
- `group_by` e `sum()` funcionam do lado do servidor, o que permite construir,
  para cada número publicado, uma URL que o reproduz.
- Sem chave de API. Usamos 4 downloads em paralelo, por cortesia para com um
  serviço público.

---

## Situação jurídica da reutilização

**Por resolver — decisão necessária antes de publicar.**

- Nenhum dos 144 datasets do portal declara licença nos seus metadados.
- O rodapé do portal diz «© 2026 Todos os Direitos Reservados ao Governo da
  República Portuguesa — Ministério da Saúde».
- As notas legais do portal SNS são restritivas: «os conteúdos não podem ser
  copiados para uso comercial ou distribuição, nem ser modificados ou
  reenviados para outros sites».
- **Mas** os mesmos datasets, dos mesmos publicadores (DGS, INEM), estão
  publicados em dados.gov.pt sob licença **CC-BY**.
- E a Lei n.º 68/2021, que transpõe a Diretiva (UE) 2019/1024 sobre dados
  abertos, estabelece a reutilização livre de informação do setor público como
  regra, não como exceção.

Leitura defensável: as notas legais restritivas dizem respeito ao conteúdo
editorial do portal sns.gov.pt (notícias, artigos), não aos dados estatísticos
agregados publicados num portal chamado «Transparência», com API pública sem
chave e endpoints de exportação. Os dados são agregados e não pessoais.

Recomendação: publicar ao abrigo da Lei n.º 68/2021, com atribuição no formato
CC-BY a cada publicador (ACSS, DE-SNS, INFARMED, SPMS, INEM), e pedir
confirmação escrita à SPMS e à DE-SNS antes do lançamento público.

## 14. Dois meses de consumo de antibióticos por preencher

O registo de antibióticos do INFARMED publica, por hospital e por mês, as DDD
(doses diárias definidas) de cada classe e as do resto dos antibióticos. Em
**outubro e novembro de 2025** o volume nacional total cai para 68% e 57% da
mediana — com os 42 hospitais a reportar nos dois meses.

O que torna isto perigoso é a assimetria: o **numerador mantém-se completo** e
só o **denominador** encolhe.

| Mês | Carbapenemes (DDD) | Restantes (DDD) | Peso |
|---|---:|---:|---:|
| 2025-09 | 23 540 | 357 201 | 6,2 % |
| **2025-10** | 24 471 | **256 460** | **8,7 %** |
| **2025-11** | 22 364 | **214 102** | **9,5 %** |
| 2025-12 | 23 010 | 411 035 | 5,3 % |

O consumo de carbapenemes não mudou; mudou o que a fonte registou do resto. Sem
correção, o IPO do Porto aparecia com um pico de **33,7%** em outubro de 2025 e
uma média de 11,8% em vez de 10,6%.

Resolvido com `exigir_mes_completo` em `indicadores.yaml`, que descarta os meses
cujo volume nacional fica abaixo de 80% da mediana — o mesmo limiar que
`ingest/mortalidade.py` já aplicava aos internamentos, agora genérico em
`build.py`. A deteção corre sobre numerador **mais** denominador: um denominador
incompleto com numerador completo não se vê olhando só para o numerador.

**Nota sobre esta fonte, ao contrário das outras:** não é acumulada no ano. São
fluxos mensais, verificados. É das poucas séries do portal em que somar os meses
diretamente está correto.

---

# Benchmarking Hospitalar da ACSS

Segunda fonte, ligada em agosto de 2026. Traz o que o Portal da Transparência
não publica: segurança do doente, volume cirúrgico, métricas ajustadas pelo
case-mix e os grupos de comparação entre instituições. Não tem API — o que se
segue foi apurado a ler o painel por dentro, e cada ponto custou pelo menos um
erro.

## 15. A rota de exportação é por indicador, não por painel

O painel declara em `layoutActionUrls` uma rota de exportação **por indicador**,
e dentro do mesmo painel há mais do que uma. No Económico-Financeiro, os gastos
por doente padrão saem por `ExportDataToExcel_3Evolution_3AditionalValuesAsync` e
as percentagens de gastos por `ExportDataToExcel_3EvolutionAsync`; na
Produtividade, os doentes padrão por profissional e a demora média antes da
cirurgia saem por rotas diferentes.

Assumir uma rota por painel — que foi a primeira tentativa — produz dois
comportamentos, e o segundo é o perigoso:

- **500 Internal Server Error**, que se vê;
- **um ficheiro Excel válido e vazio**, que não se vê. Dois indicadores ficaram
  com 116 bytes: cabeçalho e nada mais. Sem uma verificação de cobertura,
  passariam por «a ACSS não tem estes dados».

A rota passou a ser lida de `layoutActionUrls`, e a descoberta falha alto se
algum indicador não a declarar.

## 16. Cada mês tem de vir de uma só exportação

Cada exportação devolve o mês pedido e os 23 anteriores. Pedir os dezembros
cobre a série toda com um ano de sobreposição — o que é bom, porque duas
descrições do mesmo mês têm de coincidir e a discordância denuncia uma revisão
silenciosa da fonte.

Mas há uma armadilha. A exportação de dezembro de 2024 traz 2023 como **ano
homólogo, com os nomes de 2024**; a de dezembro de 2023 traz o mesmo 2023 com os
nomes de então. Fundir as duas por nome de instituição deixa o ano inteiro
representado **duas vezes**, sob duas designações que o crosswalk resolve — e
resolve bem — para a mesma entidade.

O resultado foi 2023 com 40 562 cesarianas no país em vez de 21 436: quase o
dobro, sem um único nome repetido que denunciasse o problema. Foi o confronto de
totais anuais com a ACSS que o apanhou (`tests/test_benchmarking_acss.py`), e
não haveria outra forma de o ver.

Regra em vigor: **manda, para cada mês, a âncora do próprio ano**; na falta
dela, a mais recente que o cubra. A linha guarda a âncora de onde saiu.

## 17. Precisão diferente conforme a âncora

A exportação do próprio ano traz o valor completo (0,32432432432432434); a do
ano homólogo traz-o arredondado a quatro casas (0,3243). Comparar as cadeias
acusava dezenas de revisões inexistentes. A comparação é feita ao arredondamento
com que a fonte publica, e a precedência prefere sempre a âncora mais precisa.

## 18. Meses que a fonte não anuncia vêm na mesma — e vêm mal

A janela de 24 meses avança um ano para trás do que o filtro do painel declara:
a âncora de dezembro de 2013 traz 2012, que a fonte não anuncia ter. Esses meses
de bónus vêm com as folhas desalinhadas — nos internamentos com mais de 30 dias,
1 271 linhas de 2012 em que a taxa publicada não corresponde ao numerador e ao
denominador da mesma linha.

Descartados: só entra o que a fonte declara ter.

## 19. A fonte contradiz-se a si própria em 2013 e 2014

Feita a limpeza anterior, sobraram 185 linhas em 6 858 no mesmo indicador — «%
de Internamentos com Demora Superior a 30 Dias» — todas em 2013 e 2014, em que a
taxa publicada não bate com as contagens publicadas ao lado. Exemplo: Centro
Hospitalar Barreiro/Montijo, agosto de 2013, valor 3,95 % com 46 episódios em
969, que dão 4,75 %.

Não é ruído de extração: **duas exportações diferentes trazem exatamente os
mesmos números**, e concordam uma com a outra ao mesmo tempo que discordam de si
mesmas. A partir de 2015 reconciliam.

Mantém-se a regra da casa — a taxa é Σnumerador ÷ Σdenominador — e deixa-se de
confrontar o valor publicado antes de 2015, com o período declarado em
`indicadores.yaml` (`publicado_reconcilia_desde`) e impresso pelo teste. A
alternativa seria alargar a tolerância para todos os indicadores, que é como se
esconde um defeito da fonte.

## 20. A ocupação usa um mês de 30,4375 dias

A fórmula que a ACSS publica para a taxa anual de ocupação é

    (dias de internamento de agudos) / (camas × 30,4375 × meses acumulados)

— 30,4375 é 365,25 ÷ 12. O snsRadar usa os dias reais de cada mês, o que é mais
exato ao mês e converge com a ACSS ao ano. Verificado: 33 424 dias sobre 1 172
camas dá 93,7 % com a constante da ACSS, que é exatamente o valor que publica.

## 21. Escalas que a exportação não aplica

As úlceras de pressão e as infeções por cateter venoso central são definidas por
**mil** episódios, e a sépsis e a embolia pós-operatórias por **cem mil** — está
nas fórmulas que a ACSS publica. A coluna exportada traz, em todas, a proporção
em bruto. O `fator` de cada indicador põe o valor na escala da definição; sem
ele, uma taxa de sépsis apareceria como 0,0004.

Os doentes padrão por médico e por enfermeiro são caso à parte: a ACSS divide o
doente padrão pelos profissionais **ETC**, mas exporta as horas semanais. O
quociente entre os dois varia de 7 a 35 horas por ETC, porque os regimes de
horário convivem. Sem constante defensável, fica a taxa que a fonte publica.

## 22. O indicador de primeiras cesarianas não é publicável

«% de Primeiras Cesarianas em Gestações Unifetais, Cefálicas, a Termo» seria o
indicador mais valioso do conjunto: a taxa de cesarianas no grupo em que a
decisão depende da prática da equipa e não do risco que a grávida já trazia — o
equivalente português da medida PC-02 da Joint Commission.

Não é o que a exportação traz. A fórmula publicada declara como denominador o
«Nº de Partos em Gestações Unifetais, Cefálicas, a Termo, **sem Cesariana
Anterior**». Na ULS de São João, junho de 2025:

| Grandeza | Valor |
|---|---:|
| Partos unifetais, cefálicos, de termo | 118 |
| Dos quais, com cesariana anterior | 14 |
| Denominador que a fórmula descreve | ≈ 104 |
| **Denominador que a exportação traz** | **29** |
| Numerador (primeiras cesarianas) | 28 |

O quociente dá 96,6 %, e a mediana nacional 97,6 %. Nenhuma leitura razoável de
«primeiras cesarianas» produz 97,6 %: o denominador exportado não são os partos
sem cesariana anterior, são as cesarianas dessas mulheres — e a razão entre uma
coisa e quase ela própria não informa ninguém.

O valor publicado pela ACSS coincide com o quociente que ela exporta, pelo que a
incoerência é entre a fórmula declarada e os dados, não um erro de extração
nosso.

Indicador retirado da ficha. Os dados continuam em `data/raw` — se a ACSS
corrigir o denominador, volta a entrar mudando uma linha em `indicadores.yaml`.

**O que se perde, e o que se percebe na mesma.** Sem ele, a taxa de cesarianas
ajustada ao risco não existe para Portugal. Mas os três indicadores que
sobraram contam a história toda: a taxa global é de 33,7 %; restringida às
gravidezes de termo, unifetais e cefálicas **sobe** para 37,9 % — em 35 das 37
maternidades; e a taxa de parto vaginal depois de uma cesariana tem mediana
**zero**. A subida não é um paradoxo: é a consequência aritmética da última
linha. Quem teve uma cesariana volta a tê-la, e esses partos são quase todos de
termo, unifetais e cefálicos.

## 23. Formas que os dados novos obrigaram a inventar

Três indicadores novos não cabiam na forma que a ficha usava para tudo — uma
série mensal com a faixa interquartil do país e uma régua de posição. A forma
segue o dado, e estes dados pedem outra coisa.

**Segurança do doente → funnel plot.** Os denominadores variam por um fator de
228 entre a maior e a menor unidade, e o numerador tem mediana de dois casos.
Ordenar 43 hospitais por uma taxa destas é publicar ruído com aparência de
ranking. O funil põe a dimensão no eixo horizontal e abre os limites de controlo
onde há poucos casos: com os limites de 99,8 %, entre duas e sete unidades por
indicador são distinguíveis do acaso, e as restantes não. A alternativa — uma
tabela ordenada — teria posto no topo hospitais com dois eventos em noventa
episódios.

**Cesarianas → gráfico de declive.** A taxa restrita a gestações de termo,
unifetais e cefálicas é *mais alta* do que a global em 35 das 37 maternidades.
Nenhum dos dois números explica o outro; a ligação entre eles explica os dois, e
a explicação está num terceiro indicador (parto vaginal após cesariana, mediana
zero).

**Volume cirúrgico → ordenamento do país.** Para uma resseção do pâncreas, a
pergunta de quem vai ser operado não é uma taxa: é quantas aquela equipa faz por
ano. Três centros fazem 43 % das do país; há unidades com um caso anual.

**Dispersão do painel → repartida por grupo.** A lista das 43 unidades ordenadas
por valor punha o IPO do Porto a três linhas da ULS da Guarda. Passou a pequenos
múltiplos por grupo de financiamento, com o mesmo eixo em todos e a mediana de
cada grupo ao lado da nacional.

## 24. A ACSS deixou de estimar poupanças para as ULS

A exportação económico-financeira traz, ao lado do valor de cada indicador, três
colunas que o painel mostra mas que ninguém publica em série: **poupanças
estimadas**, resultado operacional e resultado operacional potencial. É o
cálculo da própria ACSS do que cada instituição pouparia se igualasse a mais
eficiente do seu grupo.

Ao ligá-lo, a cobertura revelou-se descontínua:

| Ano | Unidades com poupança estimada |
|---|---:|
| 2020 a 2023 | 33 a 34 |
| **2024** | **3** |
| **2025** | **3** |
| 2026 (até maio) | 3 |

As três são os institutos de oncologia — as únicas entidades que a reforma de
2024 não transformou em ULS. Para as restantes quarenta, a ACSS deixou de
publicar o cálculo, e a razão está escrita na sua própria abordagem
metodológica: com a integração dos cuidados de saúde primários, «os resultados
dos indicadores Económico-Financeiros não são comparáveis com os anos
anteriores».

Não é um defeito da exportação. É a fonte a suspender um cálculo, e a suspensão
é ela própria uma perda de transparência que vale a pena registar: entre 2020 e
2023 era possível saber quanto a ACSS estimava que cada hospital pudesse poupar;
a partir de 2024 já não é, para 93 % das unidades.

**O que o portal faz.** Publica o último ano em que o cálculo cobriu o sistema —
2023, 34 unidades, 1 450 M€ no conjunto — com o ano no próprio texto do cartão e
a descontinuação declarada a seguir. Publicar 2025 seria descrever o país com
três unidades; não publicar nada seria deixar cair um dado que existiu.

**O que não se faz.** Somar as poupanças das várias tipologias de custo. A ACSS
avisa que são «indicativas e não cumulativas» — cada uma reflete o mesmo
posicionamento medido por outra via, e somá-las contaria a mesma poupança
várias vezes. Fica só a dos gastos operacionais, que é o total.

**Nota sobre a série mensal.** A descontinuidade é só do cálculo anual das
poupanças. O doente padrão mensal continua a ser publicado para as 43 unidades
em 2024, 2025 e 2026 — é por isso que os contratos por doente padrão cobrem o
sistema inteiro e as poupanças estimadas não.

## 25. Os agregados económico-financeiros e a margem EBITDA

O dataset `agregados-economico-financeiros` publica EBITDA, gastos,
rendimentos e resultados por entidade, mensais e **acumulados no ano** — como
quase tudo no portal, e igualmente sem o dizer nos metadados. Confirmado na
ULS de Coimbra em 2025: os rendimentos crescem de 76 M€ em janeiro para
896 M€ em dezembro, linearmente.

Três coisas que o tratamento teve de aprender:

- **O fluxo mensal de EBITDA pode ser negativo**, e é-o na maior parte dos
  meses da maior parte das ULS. A regra geral da des-acumulação — delta
  negativo é revisão da fonte, sai `None` — destruiria a série. O campo
  `pode_ser_negativa` do YAML existe por isto, e só o EBITDA o usa.
- **O perímetro muda em 2024.** Antes da reforma, os cuidados de saúde
  primários eram despesa das ARS e não apareciam nos agregados por entidade;
  a soma das entidades salta 4,8 mil M€ de 2023 para 2024, e não é despesa
  nova — é a reforma a aparecer nas contas. Comparações com anos anteriores
  a 2024 comparam perímetros diferentes.
- **Publica-se a margem (EBITDA ÷ rendimentos), não o valor absoluto**: em
  euros, o indicador diria sobretudo a dimensão da unidade. No SNS a margem
  negativa é a regra — a mediana nacional ronda os −18 % — e por isso a
  comparação útil é com os pares, não com o zero.

Três rótulos do dataset são organismos sem atividade assistencial (ICAD,
INEM, DE-SNS) e ficam fora pela via normal das entidades não prestadoras.

## 26. A Conta do SNS ancora a despesa — e não publica a dívida

A `conta-do-servico-nacional-de-saude` publica 67 séries mensais de orçamento
e execução, **em milhões de euros** (também sem o declarar: 15 468 no campo da
despesa corrente de 2024 só faz sentido como 15,5 mil M€). Serve de âncora
externa aos agregados por entidade: em 2024, os gastos operacionais das
entidades são 0,91 da despesa corrente da Conta — o resto é o que o SNS paga
fora das EPE (convenções, serviços centrais). O teste de validação externa
trava este rácio entre 0,75 e 1,00, só de 2024 em diante (ver §25).

O que a Conta **não** tem: dívida, pagamentos em atraso ou qualquer outro
stock de passivo. A pendência antiga de ancorar a dívida vencida a uma fonte
independente continua por resolver — e fica agora escrito porquê: a fonte que
parecia próxima não publica o número.

## 27. Certificados de óbito: a prova independente das exclusões do SMR

O SICO certifica todos os óbitos ocorridos em cada instituição; a morbilidade
hospitalar regista os do internamento. Em 2025, o internamento é 0,63 dos
certificados a nível nacional — o resto morre na urgência ou fora do
internamento. O dataset vem por subunidade («ULS X, E.P.E. - Hospital Y»),
agregável à entidade-mãe pelo prefixo — exceto nos IPO, onde o « - Cidade» é
parte do nome e o rótulo inteiro resolve diretamente no crosswalk.

O que isto compra: as três ULS excluídas do SMR por registo de óbitos não
fiável na morbilidade (Baixo Alentejo, Loures-Odivelas, São José) certificam
998, 1 317 e 2 609 óbitos no SICO em 2025. **Os óbitos existem; é o registo
da morbilidade que falha.** A exclusão deixou de ser uma inferência interna e
passou a ter fonte independente. O IPO de Coimbra certifica menos (336) — os
seus doentes morrem frequentemente noutras unidades ou em casa —, pelo que a
trava do teste aplica-se só às ULS.

## 28. O RNCCI é diário, e a fila começa depois da alta

`rncci-episodios` publica, dia a dia, os utentes a aguardar vaga na Rede de
Cuidados Continuados, por região e tipologia (ULDM, UMDR, UC, ECCI…, siglas
da fonte que o portal não expande por conta própria). Não é indicador de
instituição — a vaga é da Rede — e entra como contexto nacional na página de
perguntas. Quem aguarda já foi referenciado pela equipa de gestão de altas:
a fila mede-se depois de o hospital dizer que a pessoa precisa.
