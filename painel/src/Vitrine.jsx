// Aba Produtos: uma pílula por produto no cabeçalho; por padrão a página mostra só os gráficos do produto escolhido
// (barras e rosca com os logos das lojas, preço por dia com filtro de período). Clicar na pílula abre o cartão dele
// (foto, etiqueta do melhor preço, onde comprar, meta); clicar de novo na mesma pílula fecha.
import {useMemo, useState} from 'react';
import {Card} from './tremor.js';
import {fmt, placar} from './logica.js';
import {Abrir, Barras, CodigoCupom, Grafico, Logo, NomeOuFoto, Rosca, corDaPosicao} from './componentes.jsx';

const diaLocal = d => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const PERIODOS = [
  [7, '7 dias'],
  [30, '30 dias'],
  [0, 'Tudo'],
];

// as pílulas na faixa azul do topo; no celular rolam de lado numa linha só
export function Pilulas({itens, atual, cartao, onEscolhe}) {
  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-3 sm:px-6" role="group" aria-label="Produtos monitorados">
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [&::-webkit-scrollbar]:hidden">
        {itens.map(it => {
          const on = it.id === atual?.id;
          return (
            <button
              key={it.id}
              type="button"
              aria-pressed={on}
              aria-expanded={on && cartao}
              onClick={() => onEscolhe(it.id)}
              className={`flex-none whitespace-nowrap rounded-full border-2 px-3.5 py-[3px] text-sm font-bold transition-colors duration-150
              ${on ? 'border-etiqueta bg-etiqueta text-etiqueta-ink' : 'border-band-ink-2 text-band-ink hover:border-band-ink'}`}
            >
              {it.curto}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function Vitrine({it, cartao}) {
  if (!it)
    return (
      <p className="py-3 text-base text-tinta-3">
        Nenhum preço coletado ainda. Os produtos aparecem aqui depois da primeira coleta.
      </p>
    );
  return <Placar key={it.id} it={it} cartao={cartao} />;
}

function Cartao({it}) {
  const m = it.melhor;
  return (
    <Card className="mb-5 rounded-[3px] px-4 py-4 ring-2 sm:px-6 sm:py-5">
      {/* título do cartão: a foto e, ao lado, a pílula da meta sobre a etiqueta do melhor preço; no celular encolhem */}
      <div className="flex items-center gap-3 sm:gap-5">
        <h2 className="flex-none font-cond text-2xl font-bold leading-tight sm:text-2xl">
          <NomeOuFoto id={it.id} nome={it.nome} className="h-14 sm:h-20" />
        </h2>
        <div className="flex min-w-0 flex-col items-start gap-1.5">
          {it.meta ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-bg px-2.5 py-0.5 text-xs font-bold text-ok">
              <i className="h-2 w-2 flex-none rounded-full bg-ok" aria-hidden="true" />
              Meta {fmt(it.meta)}
            </span>
          ) : null}
          <div className="etiqueta inline-flex min-w-0 flex-wrap items-baseline gap-x-2 bg-etiqueta pb-1.5 pl-6 pr-4 pt-1 text-etiqueta-ink">
            <span className="font-cond text-[clamp(20px,5.5vw,36px)] leading-none">
              {m ? m.preco : 'sem preço recente'}
            </span>
            {m && <span className="text-xs font-bold sm:text-base">{m.forma}</span>}
          </div>
        </div>
      </div>
      {m && (
        <p className="mt-2 max-w-[64ch]">
          Melhor lugar agora: <Logo loja={m.loja} className="h-[26px] max-w-[120px]" />
          {m.vendedor && (
            <>
              {' '}
              vendido por <b>{m.vendedor}</b>
            </>
          )}
          , coletado em {m.visto}.
          {m.cupom && (
            <>
              {' '}
              Cupom <CodigoCupom codigo={m.cupom} />.
            </>
          )}{' '}
          <Abrir url={m.url}>Abrir o anúncio</Abrir>
        </p>
      )}
      <p className="mt-2 max-w-[64ch] text-base text-tinta-2">
        {m?.dist && (
          <>
            <b className={m.dist.cls === 'acima' ? 'text-bad' : 'text-ok'}>{m.dist.txt}</b>.{' '}
          </>
        )}
        {it.parc && (
          <>
            Parcelado: {it.parc.total} em {it.parc.quem}.{' '}
          </>
        )}
        {it.min && (
          <>
            Menor já visto: {it.min.preco} em {it.min.loja}, {it.min.quando}.
          </>
        )}
      </p>
    </Card>
  );
}

function Placar({it, cartao}) {
  const [per, setPer] = useState({dias: 30, de: '', ate: ''});
  const todosDias = useMemo(() => Object.keys(it.porDia).sort(), [it]);
  const [ini, fim] =
    per.de || per.ate
      ? [per.de || '0000', per.ate || '9999']
      : !per.dias
        ? ['0000', '9999']
        : [diaLocal(new Date(Date.now() - (per.dias - 1) * 864e5)), '9999'];
  const p = useMemo(() => placar(it.serie, it.meta, ini, fim), [it, ini, fim]);
  const serieP = useMemo(() => Object.fromEntries(p.lojas.map(l => [l.loja, l.s])), [p]);
  const cor = Object.fromEntries(p.lojas.map((l, i) => [l.loja, corDaPosicao(i)]));
  const vazio = <p className="py-3 text-base text-tinta-3">Sem preços neste período. Escolha um período maior.</p>;

  return (
    <section aria-live="polite" className="mt-5">
      {cartao && <Cartao it={it} />}
      <Card className="rounded-[3px] px-4 py-4 ring-2 sm:px-6 sm:py-5">
        <div className="flex flex-wrap items-center justify-between gap-x-7 gap-y-3">
          <h2 className="font-cond text-2xl font-bold leading-tight">{it.nome}</h2>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Período dos gráficos">
            {PERIODOS.map(([dias, rotulo]) => {
              const on = !per.de && !per.ate && per.dias === dias;
              return (
                <button
                  key={dias}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setPer({dias, de: '', ate: ''})}
                  className={`rounded-[3px] border-2 px-3 py-1 text-sm font-bold transition-colors duration-150 ${on ? 'border-tinta bg-tinta text-fundo' : 'border-linha bg-superficie text-tinta'}`}
                >
                  {rotulo}
                </button>
              );
            })}
            {[
              ['de', 'De'],
              ['ate', 'até'],
            ].map(([k, rotulo]) => (
              <label key={k} className="flex items-center gap-1.5 text-sm text-tinta-2">
                {rotulo}
                <input
                  type="date"
                  value={per[k]}
                  min={todosDias[0]}
                  max={todosDias.at(-1)}
                  onChange={e => setPer({...per, [k]: e.target.value})}
                  className="rounded-[3px] border-2 border-linha bg-superficie px-1.5 py-0.5 text-sm text-tinta"
                />
              </label>
            ))}
          </div>
        </div>

        <div className="mt-5 grid gap-7 md:grid-cols-[3fr_2fr]">
          <div>
            <h3 className="mb-2.5 text-xl font-bold">Menor preço de cada loja no período</h3>
            {p.lojas.length ? <Barras lojas={p.lojas} /> : vazio}
          </div>
          <div>
            <h3 className="mb-2.5 text-xl font-bold">Loja mais barata, contando os dias</h3>
            {p.fatias.length ? <Rosca fatias={p.fatias} dias={p.dias.length} cor={cor} /> : vazio}
          </div>
        </div>

        <h3 className="mb-2.5 mt-6 text-xl font-bold">Preço por dia</h3>
        <Grafico
          serie={serieP}
          meta={it.meta}
          minDias={2}
          soMaisBarata
          vazio="Sem preços neste período. Escolha um período maior."
        />
      </Card>
    </section>
  );
}
