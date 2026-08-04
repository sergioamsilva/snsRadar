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
