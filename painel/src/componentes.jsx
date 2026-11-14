// Peças pequenas usadas em mais de uma aba. Nada de regra de negócio aqui: os textos e valores já vêm prontos de logica.js.
import {Card, LineChart, Metric, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow, Text} from '@tremor/react';
import {VELHO_H, fmt, linhasDoGrafico} from './logica.js';

// Logos das lojas (docs/logos): os .webp vêm do Wikimedia Commons (domínio público); os .png/.jpg são o ícone do site,
// para as lojas sem logo lá. Loja fora da lista sai pelo nome. A foto do produto (docs/produtos) entra no lugar do nome.
const LOGOS = {'amazon': 'amazon.webp', 'magazine luiza': 'magalu.webp', 'kabum!': 'kabum.webp', 'mercado livre': 'mercadolivre.webp',
  'americanas': 'americanas.webp', 'casas bahia': 'casasbahia.webp', 'netshoes': 'netshoes.webp', 'aliexpress': 'aliexpress.webp',
  'shopee': 'shopee.webp', 'playstation store': 'psstore.webp', 'loja tcl': 'tcl.webp', 'mais correios': 'correios.webp',
  'fast shop': 'fastshop.webp', 'carrefour': 'carrefour.png', 'webcontinental': 'webcontinental.png', 'nuuvem': 'nuuvem.png',
  'hype': 'hype.jpg', 'telegram': 'telegram.webp'};
// ícone quadrado (aplicativo/site) ocupa o selo inteiro, sem a margem branca dos logos horizontais
const QUADRADOS = new Set(['kabum.webp', 'carrefour.png', 'nuuvem.png', 'hype.jpg', 'telegram.webp']);
const FOTOS = {PS5_DIGITAL: 'produtos/ps5-slim.webp', GTA6_CODE_IN_BOX: 'produtos/gta6.webp'};

// logo em selo branco (legível nos dois temas); altura pela classe
export function Logo({loja, className = 'h-[22px] max-w-[92px]'}) {
  const f = LOGOS[String(loja ?? '').trim().toLowerCase()];
  if (!f) return <span className="font-bold">{loja}</span>;
  return <img className={`inline-block w-auto object-contain align-middle bg-white ring-1 ring-linha-2 ${QUADRADOS.has(f) ? 'rounded' : 'rounded-[3px] px-1.5 py-[3px]'} ${className}`}
    src={`logos/${f}`} alt={loja} title={loja} />;
}

export const NomeOuFoto = ({id, nome, className = 'h-16'}) => FOTOS[id]
  ? <img className={`block w-auto max-w-full object-contain object-left ${className}`} src={FOTOS[id]} alt={nome} title={nome} />
  : <>{nome}</>;

const CHIP = {ok: 'bg-ok-bg text-ok', warn: 'bg-warn-bg text-warn', bad: 'bg-bad-bg text-bad', mute: 'bg-mudo text-tinta-2',
  m55: 'bg-m55-bg text-m55', m65: 'bg-m65-bg text-m65', mp: 'bg-mudo text-tinta-2'};
export const Chip = ({tipo = 'mute', title, children}) =>
  <span title={title} className={`inline-block whitespace-nowrap rounded-[2px] px-2 text-xs font-bold leading-5 ${CHIP[tipo] || CHIP.mute}`}>{children}</span>;

export const Sub = ({children}) => children ? <span className="block text-[13.5px] text-tinta-3">{children}</span> : null;
export const Nota = ({children}) => <p className="mx-0.5 mt-2 max-w-[80ch] text-sm text-tinta-3">{children}</p>;
export const H2 = ({children, id}) => <h2 id={id} className="mb-3 mt-10 font-cond text-[32px] font-bold leading-tight">{children}</h2>;
export const H3 = ({children}) => <h3 className="mb-2 mt-6 text-lg font-bold">{children}</h3>;
export const Abrir = ({url, children = 'abrir'}) => url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}</a> : null;

// cartão de número grande (Tremor Card + Metric): o resumo do topo e os destaques das TVs
export const Fato = ({k, d}) => (
  <Card className="rounded-[3px] p-3 ring-2">
    <Text className="text-sm text-tinta-2">{k}</Text>
    <Metric className="mt-0.5 font-cond text-[30px] leading-tight text-tinta">{d?.v ?? '—'}</Metric>
    <p className="mt-0.5 line-clamp-2 break-words text-[13.5px] text-tinta-3">{d?.s ?? '—'}</p>
  </Card>
);

// a tabela de ofertas de loja de um produto (as linhas vêm de painelDoModelo em logica.js)
const COR_LINHA = {best: 'bg-destaque-suave', sus: 'text-tinta-3', velho: 'text-tinta-3'};
export function TabelaLojas({linhas, vazio}) {
  return (
    <Tabela cab={['Loja', 'À vista', 'Pix', 'Parcelado (total)', 'Cupom', 'Fonte', 'Visto', '']}>
      {linhas.length ? linhas.map((l, i) => (
        <TableRow key={i} className={COR_LINHA[l.classe] || ''}>
          <TableCell className="whitespace-normal">
            <b className="text-tinta">{l.loja}</b>
            {l.selo && <span className="ml-1.5 align-[1px]"><Chip tipo={l.selo.tipo === 'risco' ? 'bad' : 'warn'} title={l.selo.titulo}>{l.selo.rotulo}</Chip></span>}
            {l.vendedor && <Sub>vendido por {l.vendedor}</Sub>}
            {l.oferta && <Sub>{l.oferta}</Sub>}
            {l.info.map((t, j) => <Sub key={j}>{t}</Sub>)}
          </TableCell>
          <TableCell>{l.avista}</TableCell>
          <TableCell><b className={l.classe === 'sus' ? 'line-through' : 'text-tinta'}>{l.pix}</b>{l.pixCupom && <Sub>c/ cupom {l.pixCupom}</Sub>}</TableCell>
          <TableCell>{l.parc
            ? <><b className="text-tinta">{l.parc.total}</b>{l.parc.melhor && <> <Chip tipo="ok">melhor</Chip></>}<Sub>{l.parc.texto}</Sub></>
            : l.parcTexto}</TableCell>
          <TableCell>{l.cupom ? <code>{l.cupom}</code> : '—'}</TableCell>
          <TableCell><Chip>{l.fonte}</Chip>{l.agregador && <Sub>agregador</Sub>}</TableCell>
          <TableCell>{l.visto}{l.velho && <> <Chip tipo="warn" title={`coleta com mais de ${VELHO_H} h`}>antigo</Chip></>}</TableCell>
          <TableCell><Abrir url={l.url} /></TableCell>
        </TableRow>))
        : <TableRow><TableCell colSpan={8} className="text-tinta-3">{vazio}</TableCell></TableRow>}
    </Tabela>
  );
}

// Tremor Table com o cabeçalho; no celular a tabela rola de lado dentro do quadro, a página não
export const Tabela = ({cab, children, className = ''}) => (
  <Card className={`overflow-hidden rounded-[3px] p-0 ring-2 ${className}`}>
    <Table>
      <TableHead><TableRow className="border-b-2 border-linha">
        {cab.map((c, i) => <TableHeaderCell key={i} className="whitespace-nowrap px-3 py-2 text-sm text-tinta-2">{c}</TableHeaderCell>)}
      </TableRow></TableHead>
      <TableBody className="text-[15px] [&_td]:px-3 [&_td]:py-2 [&_td]:align-top">{children}</TableBody>
    </Table>
  </Card>
);

// cor de cada loja nos gráficos: a ordem do mais barato (s1..s8), igual nas barras, na rosca e nas linhas
export const corDaPosicao = i => i < 8 ? `s${i + 1}` : 'outras';

// histórico por dia (Tremor LineChart): as 8 lojas mais baratas e a linha da meta
export function GraficoHistorico({serie, alvo, vazio = 'O histórico aparece a partir da segunda coleta.', altura = 'h-72'}) {
  const g = linhasDoGrafico(serie, alvo);
  if (!g.dados.length) return <p className="py-3 text-[15px] text-tinta-3">{vazio}</p>;
  return <LineChart className={altura} data={g.dados} index="dia" categories={g.categorias}
    colors={[...g.lojas.map((_, i) => corDaPosicao(i)), ...(alvo ? ['meta'] : [])]}
    valueFormatter={fmt} yAxisWidth={84} connectNulls autoMinValue showAnimation={false} />;
}

// uma postagem (Pelando, Promobit, Telegram): o selo do produto, o preço, a loja e o título
export function Postagem({p}) {
  return (
    <li className="break-words border-b border-linha-2 px-3 py-2.5 text-[15px] last:border-b-0">
      <Chip tipo={p.chip.classe}>{p.chip.texto}</Chip>{' '}
      {p.expirada && <><Chip>expirada</Chip>{' '}</>}
      <b>{p.preco}</b> · {p.loja}{p.cupom && <> · <code>{p.cupom}</code></>}
      <br />{p.titulo}
      <span className="block text-[13.5px] text-tinta-3">
        {p.telegram && <><Logo loja="Telegram" className="h-4 max-w-[92px]" />{' '}</>}{p.fonte} · {p.quando} · <Abrir url={p.url} />
      </span>
    </li>
  );
}

export const Lista = ({children, vazio}) => (
  <Card className="rounded-[3px] p-0 ring-2"><ul className="m-0 list-none p-0">
    {children?.length ? children : <li className="px-3 py-3.5 text-[15px] text-tinta-3">{vazio}</li>}
  </ul></Card>
);
