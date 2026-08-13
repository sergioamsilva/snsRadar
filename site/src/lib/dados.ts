import fs from "node:fs";
import path from "node:path";

const RAIZ = path.resolve(process.cwd(), "..", "data", "out");

export type Ponto = {
  mes: string;
  valor: number | null;
  numerador: number | null;
  denominador: number | null;
};

export type Indicador = {
  titulo: string;
  grupo: "acesso" | "qualidade" | "seguranca" | "capacidade" | "dinheiro";
  unidade:
    | "percentagem"
    | "contagem"
    | "dias"
    | "euros"
    | "por_1000"
    | "por_100000"
    | "por_1000_dias";
  polaridade: "subir_e_bom" | "subir_e_mau" | "neutro";
  descricao: string | null;
  cautela: string | null;
  referencia: { valor: number; rotulo: string; fonte: string } | null;
  /** Literatura que sustenta o que a descrição afirma. Ver a metodologia. */
  evidencia?: { citacao: string; url: string; nota?: string }[] | null;
  /** Percentagem que pode legitimamente passar dos 100 %. */
  pode_exceder_100?: boolean;
  valor: number | null;
  numerador: number;
  denominador: number | null;
  periodo: string;
  meses_usados: number;
  /** Meses em que o 0,0 da fonte era lacuna. Ver `_zeros_nao_apurados`. */
  nao_apurado?: { meses: number; de: string; ate: string };
  serie: Ponto[];
  fonte: {
    dataset: string;
    titulo: string;
    publisher: string;
    atualizado: string;
    url: string;
  };
};

/** Uma unidade num gráfico de funil: a taxa lê-se contra a sua própria dimensão. */
export type PontoFunil = {
  id: string;
  nome_curto: string;
  numerador: number;
  denominador: number;
  /** Grupo da ACSS: é dentro dele que o funil compara. */
  grupo: string | null;
};

/** Uma unidade num ordenamento por volume. */
export type Barra = { id: string; nome_curto: string; valor: number };

/** Uma unidade num gráfico de declive, entre duas medidas relacionadas. */
export type ParDeclive = {
  id: string;
  nome_curto: string;
  de: number;
  para: number;
};

/** Uma unidade num cruzamento entre dois indicadores. */
export type PontoCruzamento = {
  id: string;
  nome_curto: string;
  x: number;
  y: number;
  /** Grupo da ACSS, para marcar os pares na nuvem. */
  grupo?: string | null;
};

export type Sucessao = {
  data: string;
  base_legal: string;
  de: string[];
  nota: string | null;
};

export type MortalidadeAjustada = {
  smr?: number;
  ic95?: [number, number];
  observados?: number;
  esperados?: number;
  significativo?: boolean;
  metodo?: string;
  periodo?: string;
  /** Preenchido quando o registo de óbitos da unidade não é fiável. */
  indisponivel?: string;
};

export type Ficha = {
  id: string;
  nome: string;
  nome_curto: string;
  regiao: string;
  distrito: string;
  tipo: string;
  nota: string | null;
  descontinuidade: {
    data: string;
    e_fusao: boolean;
    sucessao: Sucessao[];
  } | null;
  /**
   * Grupo de financiamento da ACSS, e as unidades com que esta é comparada
   * dentro dele. É o segundo termo de comparação da ficha: a mediana nacional
   * junta o IPO do Porto com a ULS da Guarda, esta não.
   */
  grupo_comparacao: {
    grupo: string;
    n_pares: number;
    pares: { id: string; nome_curto: string }[];
    historico: Record<string, string>;
    definicao: string | null;
    fonte: string | null;
  } | null;
  indicadores: Record<string, Indicador>;
  mortalidade_ajustada: MortalidadeAjustada | null;
  populacao: {
    inscritos: number;
    sem_medico_familia: number;
    percentagem_sem_medico: number | null;
    periodo: string;
  } | null;
  per_capita: { populacao: number; por_mil: Record<string, number> } | null;
  /**
   * Os seis indicadores de segurança resumidos numa régua só: a média dos
   * desvios padronizados face à taxa do país. Zero é indistinguível do
   * conjunto. Serve para confrontar segurança com mortalidade ajustada, que são
   * dois métodos independentes de medir resultado.
   */
  /**
   * O que a ACSS estima que esta unidade pouparia se igualasse a mais eficiente
   * do seu grupo. É uma afirmação da ACSS, não do snsRadar — e a ACSS deixou de
   * a calcular para as ULS depois da reforma de 2024.
   */
  poupancas_estimadas: {
    ano: string;
    grupo: string;
    poupanca_estimada: number;
    resultado_operacional: number | null;
    resultado_potencial: number | null;
    fonte: string;
    descontinuado_desde: string | null;
  } | null;
  indice_seguranca: {
    z_medio: number;
    n_indicadores: number;
    fora_do_funil: number;
  } | null;
  contratos: {
    /** «IMPIC · Portal BASE» ou, em recurso, o espelho parcial do SNS. */
    fonte: string;
    desde: string | null;
    ate: string | null;
    /** Falso quando o registo do Portal BASE é demasiado esparso para publicar. */
    cobertura_suficiente: boolean;
    contratos: number;
    valor: number;
    peso_ajuste_direto: number | null;
    por_ano: { ano: string; contratos: number; valor: number }[];
    maiores_fornecedores: { nome: string; valor: number }[];
    /** Divisões de CPV — o que a unidade compra, não a quem. */
    maiores_areas: { divisao: string; rotulo: string; valor: number }[];
    /**
     * Compras por unidade de produção ajustada à complexidade. Liga o registo
     * do IMPIC ao doente padrão da ACSS — a única escala em que a compra de um
     * hospital central se compara com a de uma unidade local.
     */
    por_doente_padrao: {
      valor_contratado: number;
      doente_padrao: number;
      euros_por_doente_padrao: number;
      periodo: string;
      anos: number;
    } | null;
    /** Contratos alterados depois de assinados. `acrescimo` pode ser negativo. */
    modificacoes: {
      contratos_modificados: number;
      valor_inicial: number;
      valor_final: number;
      acrescimo: number;
    } | null;
  } | null;
};

export type Nacional = Record<
  string,
  {
    titulo: string;
    grupo: string;
    unidade: string;
    polaridade: string;
    descricao: string | null;
    cautela: string | null;
    referencia: { valor: number; rotulo: string; fonte: string } | null;
    janela: { de: string; a: string } | null;
    valor: number | null;
    sintese: string;
    numerador: number;
    denominador: number | null;
    mediana_instituicoes: number | null;
    /** A mesma mediana dentro de cada grupo da ACSS, quando há 5 ou mais. */
    mediana_por_grupo: Record<
      string,
      { mediana: number; n_instituicoes: number }
    >;
    n_instituicoes: number;
    /** Percentis 25/50/75 entre as unidades, mês a mês. */
    faixa: { mes: string; p25: number; p50: number; p75: number }[];
  }
>;

/**
 * Uma ligação interna, com o prefixo do sítio.
 *
 * O portal é servido em `/snsRadar/`, e não na raiz de um domínio. Uma
 * ligação escrita `/instituicao/uls-coimbra/` apontaria para fora do sítio.
 * Este ajudante põe o prefixo que o Astro conhece (`base`), para que exista um
 * só sítio onde mudar se o endereço mudar — passar para um domínio próprio é
 * alterar `base` no `astro.config.mjs` e mais nada.
 */
export const ligacao = (caminho: string): string =>
  `${import.meta.env.BASE_URL.replace(/\/$/, "")}${caminho}`;

const ler = <T>(p: string): T =>
  JSON.parse(fs.readFileSync(path.join(RAIZ, p), "utf-8"));

export const indice = (): {
  id: string;
  nome_curto: string;
  regiao: string;
  distrito: string;
  tipo: string;
  /** Coordenadas curadas à mão; todas as unidades do SNS são do continente. */
  geo: { lat: number; lon: number } | null;
  /** Grupo de financiamento da ACSS, para agrupar sem abrir cada ficha. */
  grupo_acss: string | null;
  n_indicadores: number;
}[] => ler("instituicoes.json");

export const enriquecimento = (): {
  populacao: {
    periodo: string;
    por_instituicao: Record<
      string,
      {
        inscritos: number;
        sem_medico_familia: number;
        percentagem_sem_medico: number | null;
      }
    >;
  };
} => ler("enriquecimento.json");

export const nacional = (): Nacional => ler("nacional.json");

/**
 * A reforma de 2024, medida contra o grupo das ULS que já o eram.
 * Ver ingest/reforma.py para o desenho e para os seus limites.
 */
export const reforma = (): {
  corte: string;
  n_transformadas: number;
  n_controlo: number;
  controlo: string[];
  por_indicador: {
    indicador: string;
    titulo: string;
    grupo: string;
    unidade: string;
    polaridade: string;
    /** True quando a variação é sobretudo mudança de perímetro, não desempenho. */
    mecanico: boolean;
    n_transformadas: number;
    n_controlo: number;
    variacao_transformadas: number;
    variacao_controlo: number;
    diferenca: number;
  }[];
} => ler("reforma.json");

export const ficha = (id: string): Ficha => ler(`instituicao/${id}.json`);

export const GRUPOS = [
  { id: "acesso", titulo: "Acesso", legenda: "Quanto se espera para ser atendido" },
  { id: "qualidade", titulo: "Qualidade", legenda: "Resultados dos cuidados prestados" },
  {
    id: "seguranca",
    titulo: "Segurança",
    legenda: "Danos que o internamento causou, e não a doença",
  },
  { id: "capacidade", titulo: "Capacidade", legenda: "Meios humanos e atividade" },
  { id: "dinheiro", titulo: "Dinheiro", legenda: "Contas e pagamentos a fornecedores" },
] as const;

/** Formatação pt-PT. Percentagens com uma casa; contagens sem casas. */
export function formatar(valor: number | null, unidade: string): string {
  if (valor === null || Number.isNaN(valor)) return "—";
  const nf = (min: number, max: number) =>
    new Intl.NumberFormat("pt-PT", {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
    });
  switch (unidade) {
    case "percentagem":
      return `${nf(1, 1).format(valor)} %`;
    case "dias":
      return `${nf(0, 1).format(valor)} dias`;
    // Taxas de segurança do doente, na escala em que a ACSS as define. «1,8 por
    // mil internamentos» diz o que «0,2 %» esconde.
    case "por_1000":
      return `${nf(1, 2).format(valor)} ‰`;
    case "por_100000":
      return `${nf(0, 0).format(valor)} por 100 mil`;
    // Doses diárias definidas de antibiótico. A escala é a da ECDC, e sem ela o
    // número não se compara com nada publicado.
    case "por_1000_dias":
      return `${nf(0, 1).format(valor)} por 1000 dias`;
    // Rácios e desvios padronizados: sem casas decimais, um SMR de 0,75 e um de
    // 1,29 aparecem os dois como «1».
    case "racio":
      return nf(2, 2).format(valor);
    case "euros":
      // «3806,0 M€» obriga a contar os dígitos para perceber a ordem de
      // grandeza. Com o registo completo do IMPIC os totais por instituição
      // passam facilmente os mil milhões, por isso há um patamar acima.
      if (Math.abs(valor) >= 1e9) return `${nf(1, 2).format(valor / 1e9)} mil M€`;
      if (Math.abs(valor) >= 1e6) return `${nf(1, 1).format(valor / 1e6)} M€`;
      return `${nf(0, 0).format(valor)} €`;
    default:
      return nf(0, 0).format(valor);
  }
}

const MESES_CURTOS = [
  "jan", "fev", "mar", "abr", "mai", "jun",
  "jul", "ago", "set", "out", "nov", "dez",
];
const MESES_LONGOS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

export function formatarMes(mes: string): string {
  const [ano, m] = mes.split("-");
  return `${MESES_CURTOS[Number(m) - 1]}. ${ano}`;
}

/** «maio de 2026» — para texto corrido, onde a forma abreviada soa a etiqueta. */
export function formatarMesPorExtenso(mes: string): string {
  const [ano, m] = mes.split("-");
  return `${MESES_LONGOS[Number(m) - 1]} de ${ano}`;
}

/** Data ISO da fonte em forma legível: «30 de julho de 2026». */
export function formatarData(iso: string): string {
  const [ano, m, dia] = iso.split("-");
  if (!dia) return iso;
  return `${Number(dia)} de ${MESES_LONGOS[Number(m) - 1]} de ${ano}`;
}

/** Descreve o período agregado («12 meses até maio de 2026»). */
export function descreverPeriodo(periodo: string, meses: number): string {
  if (!periodo.includes("..")) return `situação em ${formatarMes(periodo)}`;
  const fim = periodo.split("..")[1];
  return `${meses} ${meses === 1 ? "mês" : "meses"} até ${formatarMes(fim)}`;
}

export type LinhaComparada = {
  id: string;
  titulo: string;
  estado: "melhor" | "pior" | "semelhante";
  seta: string;
  texto: string;
  valor: number;
  unidade: string;
  /** Distância relativa à mediana; serve para escolher os extremos. */
  desvio: number;
};

/**
 * Todos os indicadores de uma ficha confrontados com a mediana das unidades.
 *
 * Vive aqui, e não dentro do componente que a desenha, porque a página precisa
 * de saber se há alguma comparação **antes** de decidir se põe a secção no
 * índice lateral. Duas contagens em sítios diferentes acabariam por divergir.
 */
export function comparacoes(
  f: Ficha,
  nac: Nacional,
): { linhas: LinhaComparada[]; neutros: number } {
  const linhas: LinhaComparada[] = [];
  let neutros = 0;
  for (const [id, d] of Object.entries(f.indicadores)) {
    if (d.valor === null) continue;
    if (d.polaridade === "neutro") {
      neutros++;
      continue;
    }
    const mediana = nac[id]?.mediana_instituicoes ?? null;
    const cmp = comparar(d.valor, mediana, d.polaridade, d.unidade);
    if (!cmp || mediana === null) continue;
    linhas.push({
      id,
      titulo: d.titulo,
      estado: cmp.estado,
      seta: cmp.seta,
      texto: cmp.texto,
      valor: d.valor,
      unidade: d.unidade,
      desvio: mediana === 0 ? 0 : Math.abs((d.valor - mediana) / mediana),
    });
  }
  return { linhas, neutros };
}

/**
 * Compara com o nacional respeitando a polaridade do indicador.
 * Devolve null quando o indicador é neutro — nesses casos dizer «melhor» ou
 * «pior» seria uma afirmação que os dados não sustentam.
 */
export function comparar(
  valor: number | null,
  referencia: number | null,
  polaridade: string,
  unidade: string,
): { estado: "melhor" | "pior" | "semelhante"; seta: string; texto: string } | null {
  if (valor === null || referencia === null || polaridade === "neutro") return null;
  const diferenca = valor - referencia;
  const relativa = referencia === 0 ? 0 : Math.abs(diferenca / referencia);
  if (relativa < 0.03) {
    return { estado: "semelhante", seta: "■", texto: "em linha com a mediana nacional" };
  }
  const acima = diferenca > 0;
  const bom = polaridade === "subir_e_bom" ? acima : !acima;
  const magnitude =
    unidade === "percentagem"
      ? `${new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(
          Math.abs(diferenca),
        )} pontos`
      : `${new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 }).format(
          relativa * 100,
        )} %`;
  return {
    estado: bom ? "melhor" : "pior",
    // A seta indica a direção; a cor indica se isso é bom ou mau. Juntar as
    // duas coisas numa só seta produzia «▼ 1524 % acima da mediana».
    seta: acima ? "▲" : "▼",
    texto: `${magnitude} ${acima ? "acima" : "abaixo"} da mediana nacional`,
  };
}
