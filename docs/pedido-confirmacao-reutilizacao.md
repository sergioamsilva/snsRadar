# Minuta — pedido à SPMS e à Direção Executiva do SNS

Destinatários: SPMS, E.P.E. (operadora do portal) e Direção Executiva do SNS, I.P.
Com conhecimento à ACSS, I.P. e, quanto ao ponto 3, à Entidade Reguladora da Saúde.

Assunto: **Reutilização dos dados do Portal da Transparência do SNS — pedido de
confirmação de licença e de acesso a dois conjuntos de dados**

**Estado: por enviar.**

---

Exmos. Senhores,

Contacto-vos a propósito da reutilização dos dados publicados no Portal da
Transparência do SNS.

Desenvolvi um projeto independente e sem fins lucrativos, o snsRadar, que
reorganiza os dados já publicados numa página por instituição, de modo a que um
cidadão possa consultar num único lugar os indicadores da unidade de saúde da
sua área. Todos os valores apresentados identificam o conjunto de dados de
origem, o organismo publicador, a data de atualização e uma ligação à consulta
da API que os reproduz.

Trago três pedidos e cinco observações que julgo serem do vosso interesse.

## 1. Licença de reutilização

Nenhum dos 144 conjuntos de dados do portal declara licença nos seus metadados,
e o rodapé indica «Todos os Direitos Reservados». Simultaneamente, conjuntos de
dados dos mesmos organismos estão publicados em dados.gov.pt sob licença
Creative Commons Atribuição, e a Lei n.º 68/2021 estabelece a reutilização de
informação do setor público como regra.

Vou avançar ao abrigo da Lei n.º 68/2021, com atribuição no formato CC-BY a cada
organismo publicador e identificação inequívoca do projeto como fonte não
oficial. Agradeço, ainda assim, que confirmem:

1. Se os conjuntos de dados podem ser reutilizados por terceiros e sob que licença;
2. Qual o formato de atribuição que preferem;
3. Se existe algum conjunto que, por razões específicas, entendam não dever ser reutilizado.

Sugiro que seja declarada uma licença explícita nos metadados de cada conjunto.
A sua ausência é, na prática, o principal obstáculo à reutilização dos dados que
o portal se propõe abrir.

## 2. Acesso à API de tempos de espera nas urgências

O sítio tempos.min-saude.pt disponibiliza tempos de espera em tempo real. Os
seus endpoints — `/api/institutions`, `/api/specialties/consultations` e
`/api/specialties/surgeries` — exigem um cabeçalho `x-api-key`.

Identifiquei os endpoints ao analisar o comportamento público da aplicação, mas
**não utilizei a chave de acesso que consta do cliente**, por entender que não
me cabe usar credenciais de outrem. Venho por isso pedir acesso legítimo.

Seria a funcionalidade de maior utilidade imediata ao cidadão — permitir
responder a «onde há menos espera agora» — e comprometo-me a respeitar os
limites de utilização que definirem.

## 3. Dados da Entidade Reguladora da Saúde

O SINAS+ e as estatísticas de reclamações são a única avaliação de qualidade
independente do próprio SNS, e sem elas um projeto como este apenas reproduz a
informação que o SNS publica sobre si mesmo.

Verifiquei que não existe interface de dados: o SINAS+ é uma ferramenta
interativa sem endpoints públicos e as informações de monitorização são
publicadas como páginas e PDF individuais. Agradeço indicação sobre a
possibilidade de acesso a esses dados em formato reutilizável.

---

## Observações sobre a qualidade dos dados

Comunico-as porque afetam quem use os dados de boa-fé, e porque em três casos
podem indicar problemas a montante.

**1. Séries acumuladas sem documentação.** Conjuntos designados «evolução
mensal» publicam, em cada mês, o acumulado desde janeiro, e não o valor mensal.
Nada nos metadados o indica. Quem somar os doze meses de `partos-e-cesarianas`
obtém 413 728 partos em 2024, quando o valor real ronda os 64 500 — um erro de
cinco vezes, fácil de cometer e difícil de detetar. Uma nota nos metadados
evitaria interpretações erradas dos vossos próprios dados.

**2. Contagens de registos erradas no catálogo.** O campo `records_count`
diverge do número real em 7 conjuntos. O `portal-base` anuncia 339 300 registos
e tem 44 015; o `top-50-de-prescricao-rsp-em-locais-nao-sns` anuncia 325 984 e
tem 10 277. No total, o portal sobredeclara o seu volume em cerca de 24%.

**3. Registo de óbitos aparentemente incompleto em quatro unidades.** Em
`morbilidade_mortalidade_hospit`, quatro instituições apresentam quedas de
letalidade transversais a todos os capítulos CID, que não são compatíveis com
evolução clínica:

| Unidade | Letalidade 2021 | 2025 |
|---|---:|---:|
| IPO de Coimbra | 6,6 % | 0,3 % |
| ULS de São José | 4,9 % | 1,4 % |
| ULS de Loures-Odivelas | 7,7 % | 4,4 % |
| ULS do Baixo Alentejo | 7,7 % | 4,6 % |

A letalidade nacional manteve-se estável no mesmo período (7,5% para 6,7%). Na
ULS de São José, os óbitos por doenças do aparelho circulatório caem 82%, as
neoplasias 89% e o aparelho digestivo 95%. Optei por não publicar mortalidade
ajustada ao risco para estas quatro unidades, mas sinalizo-o porque, a
confirmar-se, é um problema de registo com consequências para além deste
projeto.

**4. O espelho do Portal BASE está muito incompleto.** O dataset `portal-base`
cobre 32 unidades, 10 807 contratos e 165 M€ desde 2024. A distribuição por
instituição vai de 0,01 € a 252 € por utente inscrito — um rácio de 8 535× — e
11 unidades não têm um único contrato registado. A ULS do Algarve consta com
4 contratos e 7 615 €, para uma população de 561 mil utentes.

Passei a usar o registo integral que o IMPIC publica em dados.gov.pt, que para
as mesmas unidades tem 639 706 contratos e 31 490 M€ desde 2012 — cerca de 60
vezes mais contratos. Sinalizo-o porque o espelho, tal como está, pode induzir
em erro quem o tome pelo registo completo dos contratos do SNS.

**5. Defeito de substituição automática.** O nome do Instituto para os
Comportamentos Aditivos e as Dependências aparece como «Instituto para os
Comportamentos Aditivos e as DE. P. E.ndências, I. P.» — uma substituição de
«EPE» por «E. P. E.» corrompeu a palavra «Dependências».

---

Fico ao dispor para prestar qualquer esclarecimento e para partilhar em detalhe
o método de qualquer das verificações acima.

Com os melhores cumprimentos,

snsRadar — radar@cybersec.pt

---

*Anexos sugeridos: ligação ao repositório e ao ficheiro `reference/NOTAS.md`,
que documenta cada uma destas observações com a forma de as reproduzir.*
