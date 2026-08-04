# Base legal e atribuição

## Posição adotada

O snsRadar reutiliza informação do setor público ao abrigo da **Lei n.º 68/2021,
de 26 de agosto**, que transpõe a Diretiva (UE) 2019/1024 relativa aos dados
abertos e à reutilização de informações do setor público.

## Fundamentação

A situação declarada pela fonte é contraditória e foi analisada antes de
publicar.

**Contra a reutilização:**
- Nenhum dos 144 conjuntos de dados de `transparencia.sns.gov.pt` declara
  licença nos seus metadados.
- O rodapé do portal indica «© 2026 Todos os Direitos Reservados ao Governo da
  República Portuguesa — Ministério da Saúde».
- As notas legais do portal `sns.gov.pt` afirmam que «os conteúdos não podem
  ser copiados para uso comercial ou distribuição, nem ser modificados ou
  reenviados para outros sites».

**A favor da reutilização:**
- A Lei n.º 68/2021 estabelece a reutilização de informação do setor público
  como **regra**, e não como exceção carecida de autorização prévia. As
  restrições admissíveis são taxativas e nenhuma se aplica a estatísticas
  agregadas de atividade hospitalar.
- Os mesmos conjuntos de dados, dos mesmos organismos publicadores (DGS, INEM),
  estão disponíveis em `dados.gov.pt` sob licença **Creative Commons
  Atribuição (CC-BY)**.
- Os dados são **agregados e não pessoais**: contagens e taxas por instituição
  e por mês. Não há dados de saúde individuais, pelo que o RGPD não é
  convocado.
- O portal chama-se «Transparência», disponibiliza API pública sem chave de
  acesso e endpoints de exportação em massa — comportamento de plataforma de
  dados abertos, não de conteúdo reservado.
- As notas legais restritivas do `sns.gov.pt` respeitam, pela sua letra e
  contexto, ao **conteúdo editorial** desse portal — notícias, artigos,
  imagens — e não aos dados estatísticos publicados no portal de transparência.

**Conclusão.** A reutilização é legítima. O snsRadar atribui a autoria a cada
organismo publicador no formato CC-BY, não reclama direitos sobre os dados
originais, e identifica-se de forma inequívoca como fonte não oficial.

Foi enviado pedido de confirmação escrita à SPMS e à DE-SNS (minuta em
`docs/pedido-confirmacao-reutilizacao.md`). A resposta, quando existir, será
registada neste ficheiro.

**Estado do pedido:** minuta redigida; por enviar.

## Formato de atribuição

Cada valor apresentado no snsRadar identifica o conjunto de dados de origem, o
organismo publicador e a data da última atualização na fonte, com ligação à
consulta da API que o reproduz.

Atribuição geral, presente no rodapé de todas as páginas:

> Dados: Portal da Transparência do SNS (transparencia.sns.gov.pt), Ministério
> da Saúde — ACSS, DE-SNS, INFARMED, SPMS e INEM. Reutilizados ao abrigo da
> Lei n.º 68/2021. O snsRadar não é um serviço oficial do SNS.

## Organismos publicadores

| Sigla | Organismo |
|---|---|
| ACSS | Administração Central do Sistema de Saúde, I.P. |
| DE-SNS | Direção Executiva do Serviço Nacional de Saúde, I.P. |
| INFARMED | Autoridade Nacional do Medicamento e Produtos de Saúde, I.P. |
| SPMS | Serviços Partilhados do Ministério da Saúde, E.P.E. |
| INEM | Instituto Nacional de Emergência Médica, I.P. |

## Licença do trabalho derivado

O código do snsRadar e os ficheiros de referência construídos neste projeto —
em especial `reference/instituicoes.yaml`, que não existe em lado nenhum e
custou trabalho de curadoria contra a legislação — são publicados sob licença
[MIT](LICENSE), para que quem quiser possa verificar, corrigir e reutilizar.

Os dados originais permanecem do respetivo organismo publicador.

## Citação sugerida

A atribuição acima é a que o snsRadar faz à fonte. Esta é a que se pede a quem
cite o snsRadar:

> snsRadar — O SNS, hospital a hospital, 2013–2026. Compilação a partir do
> Portal da Transparência do SNS (ACSS, DE-SNS, INFARMED, SPMS e INEM), do
> registo de contratos públicos do IMPIC, do INE e do Eurostat. Disponível em
> https://sergioamsilva.github.io/snsRadar/ (consultado em [data]).

## Contacto

**radar@cybersec.pt**

A qualquer dos organismos publicadores aqui identificados: este endereço serve
para o que for preciso quanto à reutilização dos vossos dados — confirmar a
licença, corrigir a forma de atribuição, assinalar um erro de tratamento ou
pedir a remoção de um conjunto de dados. Respondemos e agimos.
