# Validação contra fontes independentes

Os testes em `tests/` provam que o snsRadar é consistente com o Portal da
Transparência. Não provam que o portal esteja certo, nem que o nosso tratamento
das séries acumuladas seja o correto. Isso só se demonstra confrontando os
resultados com quem conta os mesmos factos por outro caminho.

Este ficheiro regista esse confronto. As âncoras marcadas com ✓ estão
automatizadas em `tests/test_validacao_externa.py` e falham se o pipeline se
desviar delas.

---

## Partos e cesarianas — a validação decisiva

É o teste mais exigente que existe para o tratamento das séries acumuladas: se
a des-acumulação estivesse errada, o número viria cerca de cinco vezes acima.

### 2025 ✓

| | snsRadar | ACSS | Desvio |
|---|---:|---:|---:|
| Partos no SNS | 63 854 | 63 897 | **−0,07 %** |
| Cesarianas | 21 158 | 21 224 | **−0,31 %** |
| Taxa de cesarianas | 33,1 % | 33,2 % | −0,1 pp |

Os valores do snsRadar excluem o Hospital de Cascais, que é uma parceria
público-privada e que a ACSS não contabiliza como SNS. Incluí-lo dá 66 568
partos — e foi exatamente esta comparação que revelou a diferença de perímetro.

Fonte: ACSS, citada por CNN Portugal, 14 de fevereiro de 2026.

### 2024

| | snsRadar | INE / ERS | Desvio |
|---|---:|---:|---:|
| Cesarianas no SNS | 20 988 | 21 073 | −0,40 % |
| Taxa de cesarianas no SNS | 32,5 % | 32,7 % | −0,2 pp |

A diferença de 85 cesarianas tem o sinal esperado: o INE conta **nados-vivos**
por cesariana e o snsRadar conta **partos**. Gravidezes gemelares produzem mais
nados-vivos do que partos, na ordem de 1,5%.

### Contexto nacional

O INE registou 84 934 nados-vivos em 2024 e 87 732 em 2025. Os 63 854 partos do
SNS em 2025 correspondem a cerca de 73% dos nascimentos do país — coerente com
a quota conhecida do setor público, e com a taxa de cesarianas nacional de
38,7% ser bastante superior à do SNS, porque as unidades não públicas rondam os
63%.

### Ao nível do hospital ✓

A ACSS identificou a ULS do Nordeste como a taxa mais alta do país em 2025, com
46%. O snsRadar dá **46,0%** (211 cesarianas em 459 partos) e também a coloca em
primeiro lugar.

**Uma divergência por explicar.** A mesma peça noticiosa aponta o Hospital de
Castelo Branco como o mais baixo, com 17,3%. O snsRadar dá **20,8%** — e também
o coloca em último lugar. O nosso valor reproduz exatamente o acumulado que a
própria fonte publica em dezembro de 2025 (105 cesarianas em 506 partos), e
nenhum recorte mensal do ano produz 17,3%. O valor citado na imprensa não é
reproduzível a partir deste conjunto de dados.

---

## Pessoal — uma diferença que se explica

| 2023 | snsRadar | INE / PORDATA | Desvio |
|---|---:|---:|---:|
| Trabalhadores | 120 008 | 114 911 | +4,4 % |
| Médicos | 23 689 | 22 466 | +5,4 % |
| Enfermeiros | 42 306 | 40 972 | +3,3 % |

A causa é conhecida: oito ULS já existiam antes da reforma de 2024 — Alto
Minho, Matosinhos, Guarda, Castelo Branco, Nordeste, Baixo Alentejo, Litoral
Alentejano e Norte Alentejano — e já integravam os seus centros de saúde. Os
seus 16 203 trabalhadores incluem pessoal de cuidados primários que a série
hospitalar do INE não conta. Excluindo essas oito, o total desce a 103 805,
agora abaixo do INE: a componente hospitalar das ULS não é separável nesta
fonte, pelo que o valor exato do INE não é reproduzível em nenhum dos sentidos.

### A descontinuidade de 2024 nos efetivos

De dezembro de 2023 para dezembro de 2024, os números do snsRadar saltam:

| | 2023-12 | 2024-12 | Variação |
|---|---:|---:|---:|
| Trabalhadores | 120 008 | 145 361 | **+21,1 %** |
| Médicos | 23 689 | 31 531 | **+33,1 %** |
| Enfermeiros | 42 306 | 51 058 | **+20,7 %** |

**Isto não é contratação.** É a reforma ULS a integrar os agrupamentos de
centros de saúde nas mesmas entidades. Ler este salto como crescimento do SNS
seria um erro grosseiro, e é por isso que os indicadores de pessoal levam a
cautela correspondente na ficha.

---

## O que continua por validar

- **Urgências e consultas hospitalares.** Não encontrámos série independente
  com o mesmo perímetro para confrontar os 5,68 milhões de atendimentos e os
  14,4 milhões de consultas.
- **Dívida a fornecedores.** A Conta do Serviço Nacional de Saúde publica
  agregados próximos e devia ser usada como âncora; ainda não foi feito.
- **Mortalidade por AVC e fraturas da anca.** São indicadores de qualidade sem
  ajuste ao risco; existem séries da OCDE (*Health at a Glance*) com
  metodologia diferente, que serviriam de ordem de grandeza mas não de
  verificação.

---

## Fontes

- INE, *Estatísticas Demográficas*: 84 934 nados-vivos em 2024; 87 732 em 2025.
- INE / ERS, dados de partos e cesarianas por setor, 2024.
- ACSS, dados de partos no SNS em 2025, citados pela imprensa em fevereiro de 2026.
- INE / PORDATA, *SNS: pessoal ao serviço nos hospitais — Continente*, 2023.
