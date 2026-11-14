// Vitrine (30/10/2026): um quadro por produto; o escolhido abre o placar logo abaixo (melhor lugar agora, barras das
// lojas, rosca da loja mais barata e o gráfico por dia, com filtro de período).
import {useMemo, useRef, useState} from 'react';
import {Card} from './tremor.js';
import {fmt, placar} from './logica.js';
import {Abrir, Barras, Grafico, Logo, NomeOuFoto, Rosca, Sparkline, corDaPosicao} from './componentes.jsx';

const diaLocal = d => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const PERIODOS = [[7, '7 dias'], [30, '30 dias'], [0, 'Tudo']];

export default function Vitrine({itens}) {
  const [id, setId] = useState(() => decodeURIComponent((location.hash.match(/^#p=(.+)$/) || [])[1] || ''));
  const placarRef = useRef(null);
  // filtro por família: se o produto escolhido sumiu da grade, fica o primeiro que ficou (com preço, de preferência)
  const atual = itens.find(it => it.id === id) || itens.find(it => it.melhor) || itens[0];
  const escolhe = novo => { setId(novo);
    try { history.replaceState(null, '', '#p=' + encodeURIComponent(novo)); } catch { /* sandbox */ }
    placarRef.current?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'}); };

  if (!itens.length) return <p className="py-3 text-[15px] text-tinta-3">Nenhum preço coletado ainda. Os produtos aparecem aqui depois da primeira coleta.</p>;
  return (
    <section aria-label="Produtos monitorados">
      <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(176px,1fr))] gap-2.5">
        {itens.map(it => <Quadro key={it.id} it={it} ativo={it.id === atual.id} onClick={() => escolhe(it.id)} />)}
      </div>
      <div ref={placarRef} className="scroll-mt-4"><Placar key={atual.id} it={atual} /></div>
    </section>
  );
}

function Quadro({it, ativo, onClick}) {
  const m = it.melhor, d = m?.dist;
  return (
    <button type="button" aria-pressed={ativo} onClick={onClick}
      className={`relative flex min-w-0 flex-col gap-0.5 rounded-[3px] border-2 px-3 pb-2 pt-2.5 text-left transition-colors duration-150
        ${ativo ? 'border-etiqueta-ink bg-etiqueta text-etiqueta-ink shadow-[4px_4px_0_rgb(var(--line-forte))]' : 'border-linha bg-superficie text-tinta hover:border-linha-forte'}`}>
      {m && <span className="absolute right-2 top-2"><Logo loja={m.loja} className="h-5 max-w-16" /></span>}
      <span className="min-h-9 pr-[72px] text-[15px] font-bold leading-tight"><NomeOuFoto id={it.id} nome={it.curto} className="-my-1 h-[52px]" /></span>
      <span className={`mt-1.5 font-cond text-[32px] leading-none ${m ? '' : 'text-tinta-3'}`}>{m ? m.precoCurto : 'sem preço'}</span>
      <span className={`text-[13.5px] font-bold ${ativo ? '' : d?.cls === 'acima' ? 'text-bad' : d ? 'text-ok' : ''}`}>{d ? d.txt : m ? '' : 'nenhuma coleta recente'}</span>
      <Sparkline porDia={it.porDia} meta={it.meta} />
      <span className={`truncate text-[13px] ${ativo ? '' : 'text-tinta-3'}`}>{m ? m.visto : ''}</span>
    </button>
  );
}

function Placar({it}) {
  const [per, setPer] = useState({dias: 30, de: '', ate: ''});
  const todosDias = useMemo(() => Object.keys(it.porDia).sort(), [it]);
  const [ini, fim] = per.de || per.ate ? [per.de || '0000', per.ate || '9999']
    : !per.dias ? ['0000', '9999'] : [diaLocal(new Date(Date.now() - (per.dias - 1) * 864e5)), '9999'];
  const p = useMemo(() => placar(it.serie, it.meta, ini, fim), [it, ini, fim]);
  const serieP = useMemo(() => Object.fromEntries(p.lojas.map(l => [l.loja, l.s])), [p]);
  const cor = Object.fromEntries(p.lojas.map((l, i) => [l.loja, corDaPosicao(i)]));
  const m = it.melhor;
  const vazio = <p className="py-3 text-[15px] text-tinta-3">Sem preços neste período. Escolha um período maior.</p>;

  return (
    <Card aria-live="polite" className="mt-5 rounded-[3px] px-4 py-4 ring-2 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-x-7 gap-y-4">
        <div>
          <h2 className="mb-2.5 font-cond text-[28px] font-bold leading-tight"><NomeOuFoto id={it.id} nome={it.nome} className="h-[120px]" /></h2>
          <div className="etiqueta inline-flex items-baseline gap-2.5 bg-etiqueta pb-2 pl-[30px] pr-5 pt-1.5 text-etiqueta-ink">
            <span className="font-cond text-[clamp(44px,8vw,64px)] leading-none">{m ? m.preco : 'sem preço recente'}</span>
            {m && <span className="text-[17px] font-bold">{m.forma}</span>}
          </div>
          <p className="mt-2 max-w-[64ch]">{m ? <>Melhor lugar agora: <Logo loja={m.loja} className="h-[26px] max-w-[120px]" />
            {m.vendedor && <> vendido por <b>{m.vendedor}</b></>}, coletado em {m.visto}.
            {m.cupom && <> Cupom <code>{m.cupom}</code>.</>} <Abrir url={m.url}>Abrir o anúncio</Abrir></>
            : 'Nenhuma loja com coleta recente. O histórico abaixo mostra os preços já vistos.'}</p>
          <p className="mt-2 max-w-[64ch] text-[15px] text-tinta-2">
            {it.meta ? <>Meta {fmt(it.meta)}{m?.dist && <>: <b className={m.dist.cls === 'acima' ? 'text-bad' : 'text-ok'}>{m.dist.txt}</b></>}. </> : null}
            {it.parc && <>Parcelado: {it.parc.total} em {it.parc.quem}. </>}
            {it.min && <>Menor já visto: {it.min.preco} em {it.min.loja}, {it.min.quando}.</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Período dos gráficos">
          {PERIODOS.map(([dias, rotulo]) => {
            const on = !per.de && !per.ate && per.dias === dias;
            return <button key={dias} type="button" aria-pressed={on} onClick={() => setPer({dias, de: '', ate: ''})}
              className={`rounded-[3px] border-2 px-3 py-1 text-sm font-bold transition-colors duration-150 ${on ? 'border-tinta bg-tinta text-fundo' : 'border-linha bg-superficie text-tinta'}`}>{rotulo}</button>; })}
          {[['de', 'De'], ['ate', 'até']].map(([k, rotulo]) =>
            <label key={k} className="flex items-center gap-1.5 text-sm text-tinta-2">{rotulo}
              <input type="date" value={per[k]} min={todosDias[0]} max={todosDias.at(-1)} onChange={e => setPer({...per, [k]: e.target.value})}
                className="rounded-[3px] border-2 border-linha bg-superficie px-1.5 py-0.5 text-sm text-tinta" /></label>)}
        </div>
      </div>

      <div className="mt-6 grid gap-7 md:grid-cols-[3fr_2fr]">
        <div>
          <h3 className="mb-2.5 text-[17px] font-bold">Menor preço de cada loja no período</h3>
          {p.lojas.length ? <Barras lojas={p.lojas} /> : vazio}
        </div>
        <div>
          <h3 className="mb-2.5 text-[17px] font-bold">Loja mais barata, contando os dias</h3>
          {p.fatias.length ? <Rosca fatias={p.fatias} dias={p.dias.length} cor={cor} /> : vazio}
        </div>
      </div>

      <h3 className="mb-2.5 mt-6 text-[17px] font-bold">Preço por dia</h3>
      <Grafico serie={serieP} meta={it.meta} minDias={2} soMaisBarata
        vazio="Sem preços neste período. Escolha um período maior." />
    </Card>
  );
}
