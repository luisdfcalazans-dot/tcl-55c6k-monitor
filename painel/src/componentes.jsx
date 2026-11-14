// Peças pequenas usadas em mais de uma aba. Nada de regra de negócio aqui: os textos e valores já vêm prontos de logica.js.
// Tremor só nos cartões, tabelas e acordeão; os gráficos são uPlot (linhas) e SVG/HTML à mão (barras, rosca, sparkline).
import {Fragment, useEffect, useMemo, useRef, useState} from 'react';
import {Card, Metric, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow, Text} from './tremor.js';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import {VELHO_H, fmt, reais, seriesDoGrafico} from './logica.js';

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

const arquivoLogo = loja => LOGOS[String(loja ?? '').trim().toLowerCase()];
// logos de traço escuro (contraste WCAG < 3 contra o cartão do tema escuro na maior parte dos pixels): no tema escuro
// invertem só a luminosidade (invert + hue-rotate 180° mantém o tom: o preto vira branco, o azul-marinho, azul-claro).
// Fast Shop e TCL (caixa vermelha com letra branca) e os ícones quadrados ficam como são.
const CLAREAR_NO_ESCURO = new Set(['amazon.webp', 'americanas.webp', 'casasbahia.webp', 'correios.webp', 'mercadolivre.webp', 'netshoes.webp']);

// logo sem fundo nos dois temas; altura pela classe
export function Logo({loja, className = 'h-[22px] max-w-[92px]'}) {
  const f = arquivoLogo(loja);
  if (!f) return <span className="font-bold">{loja}</span>;
  return <img className={`inline-block w-auto object-contain align-middle ${QUADRADOS.has(f) ? 'rounded' : ''} ${CLAREAR_NO_ESCURO.has(f) ? 'dark:hue-rotate-180 dark:invert' : ''} ${className}`}
    src={`logos/${f}`} alt={loja} title={loja} />;
}

export const NomeOuFoto = ({id, nome, className = 'h-16'}) => FOTOS[id]
  ? <img className={`block w-auto max-w-full object-contain object-left ${className}`} src={FOTOS[id]} alt={nome} title={nome} />
  : <>{nome}</>;

const CHIP = {ok: 'bg-ok-bg text-ok', warn: 'bg-warn-bg text-warn', bad: 'bg-bad-bg text-bad', mute: 'bg-mudo text-tinta-2',
  m55: 'bg-m55-bg text-m55', m65: 'bg-m65-bg text-m65', mp: 'bg-mudo text-tinta-2'};
export const Chip = ({tipo = 'mute', title, children}) =>
  <span title={title} className={`inline-block whitespace-nowrap rounded-[2px] px-2 text-xs font-bold leading-5 ${CHIP[tipo] || CHIP.mute}`}>{children}</span>;

// código de cupom com o botão de copiar ao lado (vira ✓ por 1,5 s depois de copiar)
export function CodigoCupom({codigo}) {
  const [ok, setOk] = useState(false);
  const copia = () => navigator.clipboard?.writeText(codigo)
    .then(() => { setOk(true); setTimeout(() => setOk(false), 1500); }).catch(() => { /* sem permissão: nada a fazer */ });
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap"><code>{codigo}</code>
      <button type="button" onClick={copia} aria-label={ok ? 'Cupom copiado' : `Copiar o cupom ${codigo}`} title={ok ? 'Copiado' : 'Copiar'}
        className={`inline-flex rounded p-0.5 transition-colors duration-150 ${ok ? 'text-ok' : 'text-tinta-3 hover:text-tinta'}`}>
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {ok ? <path d="M5 12.5l4.5 4.5L19 7.5" /> : <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>}
        </svg>
      </button>
    </span>
  );
}

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
          <TableCell>{l.cupom ? <CodigoCupom codigo={l.cupom} /> : '—'}</TableCell>
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

// cor de cada loja nos gráficos: a ordem do mais barato (--s1..--s8), igual nas barras, na rosca e nas linhas.
// No HTML/SVG vai como CSS (troca sozinha com o tema); o canvas do uPlot não lê var(), então lê o valor na hora (cssCor).
export const corDaPosicao = i => i < 8 ? `--s${i + 1}` : '--ink-3';
const css = v => `rgb(var(${v}))`;
const cssCor = v => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(v).trim().split(/\s+/).join(',')})`;

// muda quando o tema troca (classe .dark no <html>), para o uPlot redesenhar com as cores novas
function useTema() {
  const [escuro, setEscuro] = useState(() => document.documentElement.classList.contains('dark'));
  useEffect(() => { const ob = new MutationObserver(() => setEscuro(document.documentElement.classList.contains('dark')));
    ob.observe(document.documentElement, {attributes: true, attributeFilter: ['class']}); return () => ob.disconnect(); }, []);
  return escuro;
}

const Vazio = ({children}) => <p className="py-3 text-[15px] text-tinta-3">{children}</p>;

// gráfico por dia (uPlot): as 8 lojas mais baratas e a meta tracejada; a legenda mostra o valor sob o cursor.
// minDias: o placar só desenha com 2 dias ou mais (com 1, avisa); o histórico desenha a partir do primeiro.
// soMaisBarata: abre só com a meta e a loja mais barata; as outras ficam apagadas na legenda e aparecem ao clicar
// no quadro delas (o liga/desliga é do próprio uPlot; volta ao padrão quando o gráfico é refeito, ex.: outro período).
export function Grafico({serie, meta, altura = 300, minDias = 1, soMaisBarata = false,
  vazio = 'O histórico aparece a partir da segunda coleta.', poucos = 'O gráfico aparece quando o período tem pelo menos dois dias de coleta.'}) {
  const caixa = useRef(null), escuro = useTema();
  const g = useMemo(() => seriesDoGrafico(serie), [serie]);
  const desenha = g.dias.length >= minDias;
  useEffect(() => {
    if (!desenha) return;
    const el = caixa.current, xs = g.dias.map(d => Date.parse(d + 'T12:00:00') / 1000);
    const dados = [xs, ...g.valores];
    const series = [{label: 'Dia', value: (u, v) => v == null ? '—' : new Date(v * 1000).toLocaleDateString('pt-BR')},
      ...g.lojas.map((l, i) => ({label: l, show: !soMaisBarata || i === 0, stroke: cssCor(corDaPosicao(i)), width: 2, spanGaps: true,
        points: {size: 5}, value: (u, v) => v == null ? '—' : fmt(v)}))];
    if (meta) { dados.push(xs.map(() => meta)); series.push({label: 'Meta', stroke: cssCor('--ok'), width: 2, dash: [6, 4], points: {show: false}, value: (u, v) => fmt(v)}); }
    const tinta = cssCor('--ink-2'), grade = {stroke: cssCor('--line-2'), width: 1}, fonte = '13px "D-DIN", sans-serif';
    const largura = () => Math.max(280, el.clientWidth);
    const u = new uPlot({width: largura(), height: altura, series, legend: {live: true}, cursor: {y: false, points: {size: 8}}, scales: {x: {time: true}},   // cursor: só a linha vertical do dia
      axes: [{stroke: tinta, grid: grade, ticks: grade, font: fonte, values: (u, vs) => vs.map(v => new Date(v * 1000).toLocaleDateString('pt-BR', {day: '2-digit', month: '2-digit'}))},
             {stroke: tinta, grid: grade, ticks: grade, font: fonte, size: 70, values: (u, vs) => vs.map(reais)}]}, dados, el);
    // legenda com o logo da loja no lugar do nome (loja sem logo continua pelo nome); a 1ª linha é o dia, a última a meta
    u.root.querySelectorAll('.u-legend .u-series').forEach((linha, i) => {
      const loja = g.lojas[i - 1], f = loja && arquivoLogo(loja), rotulo = linha.querySelector('.u-label');
      if (!f || !rotulo) return;
      rotulo.replaceChildren(Object.assign(document.createElement('img'),
        {src: `logos/${f}`, alt: loja, title: loja, className: `logo-leg${QUADRADOS.has(f) ? ' q' : ''}${CLAREAR_NO_ESCURO.has(f) ? ' clarear' : ''}`}));
    });
    const ro = new ResizeObserver(() => u.setSize({width: largura(), height: altura}));
    ro.observe(el);
    return () => { ro.disconnect(); u.destroy(); };
  }, [g, meta, altura, desenha, escuro, soMaisBarata]);
  if (!g.dias.length) return <Vazio>{vazio}</Vazio>;
  if (!desenha) return <Vazio>{poucos}</Vazio>;
  return <div ref={caixa} className="grafico min-h-[300px]" />;
}
export const GraficoHistorico = ({serie, alvo, altura}) => <Grafico serie={serie} meta={alvo} altura={altura} />;

// barras do placar: o menor preço de cada loja no período (logo, barra na cor da loja, preço e a distância da mais barata).
// No celular: logo e preço na mesma linha, a barra embaixo com a largura toda (dense devolve o preço à 1ª linha).
// Altura: o logo nunca passa da altura da barra (os dois com 22 px; o selo do tema escuro conta dentro dos 22).
export function Barras({lojas}) {
  const max = lojas.at(-1).min, base = lojas[0].min;
  return (
    <div className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5 text-[15px] [grid-auto-flow:dense] sm:grid-cols-[minmax(90px,max-content)_1fr_auto] sm:items-center sm:gap-x-2.5 sm:gap-y-1.5">
      {lojas.map((l, i) => <Fragment key={l.loja}>
        <span className={`truncate sm:max-w-[180px] ${i ? '' : 'font-bold'}`}><Logo loja={l.loja} className="h-[22px] max-w-[96px]" /></span>
        <span className="col-span-full mb-2 h-[22px] sm:col-span-1 sm:mb-0">
          <span className="block h-full rounded-[2px]" style={{width: `${(l.min / max * 100).toFixed(1)}%`, background: css(corDaPosicao(i))}} /></span>
        <span className={`whitespace-nowrap text-right ${i ? '' : 'font-bold'}`}>{reais(l.min)}
          {i ? <small className="ml-1 text-[13px] text-tinta-3">+{reais(l.min - base)}</small>
            : <span className="ml-1 rounded-[2px] bg-etiqueta px-1.5 py-px text-[12.5px] font-bold text-etiqueta-ink">mais barata</span>}</span>
      </Fragment>)}
    </div>
  );
}

// rosca do placar: em quantos dias do período cada loja foi a mais barata (cores = posição da loja nas barras)
export function Rosca({fatias, dias, cor}) {
  const C = 2 * Math.PI * 42; let acc = 0;
  return (
    <div className="flex flex-wrap items-center gap-[18px]">
      <svg className="h-[140px] w-[140px] flex-none" viewBox="0 0 120 120" role="img" aria-label="Loja mais barata por dia no período">
        {fatias.map(f => { const len = f.dias / dias * C, a = acc; acc += len;
          return <circle key={f.loja} cx="60" cy="60" r="42" fill="none" strokeWidth="22" style={{stroke: css(cor[f.loja] || '--ink-3')}}
            strokeDasharray={`${len.toFixed(2)} ${(C - len).toFixed(2)}`} strokeDashoffset={(-a).toFixed(2)} transform="rotate(-90 60 60)" />; })}
        <text x="60" y="58" textAnchor="middle" fontSize="22" fontWeight="700" fill="currentColor">{dias}</text>
        <text x="60" y="74" textAnchor="middle" fontSize="11" fill="currentColor">{dias === 1 ? 'dia' : 'dias'}</text>
      </svg>
      <ul className="m-0 list-none p-0 text-[15px]">
        {fatias.map(f => <li key={f.loja} className="flex items-center gap-2 py-0.5">
          <i className="h-3 w-3 flex-none rounded-[2px]" style={{background: css(cor[f.loja] || '--ink-3')}} />
          <b className="min-w-[3.2em]">{Math.round(f.dias / dias * 100)}%</b>{f.loja === 'Outras lojas' ? f.loja : <Logo loja={f.loja} className="h-[22px] max-w-[96px]" />}
        </li>)}
      </ul>
    </div>
  );
}

// uma postagem (Pelando, Promobit, Telegram): o selo do produto, o preço, a loja e o título
export function Postagem({p}) {
  return (
    <li className="break-words border-b border-linha-2 px-3 py-2.5 text-[15px] last:border-b-0">
      <Chip tipo={p.chip.classe}>{p.chip.texto}</Chip>{' '}
      {p.expirada && <><Chip>expirada</Chip>{' '}</>}
      <b>{p.preco}</b> · {p.loja}{p.cupom && <> · <CodigoCupom codigo={p.cupom} /></>}
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
