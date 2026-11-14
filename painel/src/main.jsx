import {StrictMode, useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {TableCell, TableRow} from '@tremor/react';
import {montaPainel} from './logica.js';
import {Abrir, Chip, Fato, H2, Lista, Postagem, Sub, Tabela} from './componentes.jsx';
import Vitrine from './Vitrine.jsx';
import Tabelas from './Tabelas.jsx';
import './estilo.css';

const pega = (u, como) => fetch(u + '?t=' + Date.now()).then(r => r.ok ? r[como]() : null).catch(() => null);

// estado salvo nesta sessão do navegador (a aba e a família escolhidas); sem storage (aba anônima), só na memória
function useSessao(chave, inicial) {
  const [v, setV] = useState(() => { try { return sessionStorage.getItem(chave) ?? inicial; } catch { return inicial; } });
  return [v, novo => { setV(novo); try { sessionStorage.setItem(chave, novo); } catch { /* sem storage */ } }];
}

function App() {
  const [vm, setVm] = useState(undefined);   // undefined: carregando; null: sem dados
  const [abaSalva, setAba] = useSessao('aba', 'produtos');
  const aba = ABAS.some(([k]) => k === abaSalva) ? abaSalva : 'produtos';
  const [familia, setFamiliaSalva] = useSessao('familia', '');
  useEffect(() => { Promise.all([pega('data/latest_cloud.json', 'json'), pega('data/latest_pc.json', 'json'),
    pega('data/historico_cloud.csv', 'text'), pega('data/historico_pc.csv', 'text')])
    .then(([cloud, pc, csvCloud, csvPc]) => setVm(montaPainel({cloud, pc, csvCloud, csvPc}))); }, []);

  // família salva que não existe mais (TVs desligadas): volta para todos
  const fam = vm?.semTVs && familia === 'TV' ? '' : familia;
  const rolaETroca = nome => { setAba(nome); scrollTo(0, 0); };
  return <>
    <header className="bg-band text-band-ink">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-end justify-between gap-x-6 gap-y-2.5 px-4 pb-3.5 pt-[18px] sm:px-6 sm:pt-[22px]">
        <h1 className="m-0 font-cond text-[clamp(40px,7vw,64px)] font-bold leading-[.95] tracking-[-.01em]">{vm?.titulo ?? 'PS5 · GTA 6'}</h1>
        <div className="flex flex-wrap items-center gap-3.5">
          <p className="m-0 text-[15px] text-band-ink-2">Última coleta: <b className="text-band-ink">{vm === undefined ? '—' : vm ? vm.quando : 'ainda sem dados'}</b></p>
          <BotaoTema />
        </div>
      </div>
    </header>

    <main className="mx-auto max-w-[1180px] px-4 pb-[184px] pt-4 sm:px-6 sm:pb-[108px] sm:pt-6">
      {vm === undefined ? <p className="py-3 text-[15px] text-tinta-3">Carregando os preços…</p>
        : !vm ? <p className="py-3 text-[15px] text-tinta-3">Ainda sem dados em data/.</p>
        : <>
          {aba === 'produtos' && <>
            <Vitrine itens={vm.vitrine.filter(it => !fam || it.familia === fam)} />
            <H2>Resumo</H2>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              <Fato k="Cupons ativos" d={vm.resumo.cupons} /><Fato k="Postagens (7 dias)" d={vm.resumo.posts} />
              <Fato k="Melhor gift card PSN" d={vm.resumo.gift} /><Fato k="GTA 6 Standard com gift card" d={vm.resumo.giftStd} />
              <Fato k="GTA 6 Ultimate com gift card" d={vm.resumo.giftUlt} />
            </div>
          </>}
          {aba === 'tabelas' && <Tabelas vm={vm} familia={fam} />}
          {aba === 'cupons' && <div className="grid gap-6 md:grid-cols-2">
            <div><H2>Cupons ativos</H2><Lista vazio="Nenhum cupom aplicável no momento.">{vm.cupons.map(c => <Cupom key={c.loja + c.codigo} c={c} />)}</Lista></div>
            <div><H2>Últimas postagens</H2><Lista vazio="Nenhuma postagem registrada.">{vm.posts.map(p => <Postagem key={p.chave} p={p} />)}</Lista></div>
          </div>}
          {aba === 'fontes' && <><H2>Fontes</H2>
            <Tabela cab={['Fonte', 'Estado', 'Último OK', 'Último erro']}>
              {vm.fontes.map(f => <TableRow key={f.nome}><TableCell>{f.nome}</TableCell><TableCell><Chip tipo={f.classe}>{f.rotulo}</Chip></TableCell>
                <TableCell>{f.ultimoOk}</TableCell><TableCell className="whitespace-normal text-[13.5px] text-tinta-3">{f.erro}</TableCell></TableRow>)}
            </Tabela></>}
        </>}
      <footer className="mt-11 border-t-2 border-linha pt-3 text-sm text-tinta-3">Preços sem garantia; confira na loja antes de comprar. Dados em <code>data/</code> neste repositório.</footer>
    </main>

    <Barra aba={aba} onAba={rolaETroca} familia={fam} onFamilia={setFamiliaSalva} comTVs={!!vm && !vm.semTVs} />
  </>;
}

const Cupom = ({c}) => (
  <li className="break-words border-b border-linha-2 px-3 py-2.5 text-[15px] last:border-b-0">
    <b>{c.loja}</b> <code>{c.codigo}</code>{c.especifico && <> <Chip tipo="ok">produto</Chip></>}{c.chip && <> <Chip tipo={c.chip.classe}>{c.chip.texto}</Chip></>}
    <br />{c.titulo}{c.regra && <Sub>{c.regra}</Sub>}
    <Sub>{c.fonte}{c.validade && ` · até ${c.validade}`} · <Abrir url={c.url}>ver</Abrir></Sub>
  </li>
);

function BotaoTema() {
  const [escuro, setEscuro] = useState(() => document.documentElement.classList.contains('dark'));
  // sem escolha salva, acompanha o sistema
  useEffect(() => { const mq = matchMedia('(prefers-color-scheme: dark)');
    const segue = e => { let t = null; try { t = localStorage.getItem('tema'); } catch { /* sem storage */ } if (!t) aplica(e.matches); };
    mq.addEventListener?.('change', segue); return () => mq.removeEventListener?.('change', segue); }, []);
  const aplica = e => { document.documentElement.classList.toggle('dark', e); setEscuro(e); };
  const troca = () => { aplica(!escuro); try { localStorage.setItem('tema', escuro ? 'light' : 'dark'); } catch { /* sem storage */ } };
  return (
    <button type="button" aria-pressed={escuro} onClick={troca}
      className="inline-flex cursor-pointer items-center gap-[7px] rounded-full border-2 border-band-ink-2 bg-transparent py-1 pl-2 pr-3 text-sm font-bold text-band-ink transition-colors duration-150 hover:border-band-ink">
      <svg className="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {escuro ? <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />
          : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>}
      </svg>Tema escuro</button>
  );
}

// barra inferior (30/10/2026): abas (uma parte do painel por vez) e filtro por família, que vale para a grade e as tabelas
const ABAS = [
  ['produtos', 'Produtos', <><rect x="3" y="3" width="7.5" height="7.5" rx="1" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1" /></>],
  ['tabelas', 'Tabelas', <><rect x="3" y="4" width="18" height="16" rx="1.5" /><path d="M3 9.5h18M3 14.5h18M9 9.5V20" /></>],
  ['cupons', 'Cupons', <><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2.5a2.5 2.5 0 0 0 0 5V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2.5a2.5 2.5 0 0 0 0-5z" /><path d="M14.5 9l-5 6M9.5 9.5h.01M14.5 14.5h.01" /></>],
  ['fontes', 'Fontes', <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />],
];
function Barra({aba, onAba, familia, onFamilia, comTVs}) {
  const fams = [['', 'Todos'], ['PS5', 'PS5'], ['GTA6', 'GTA 6'], ...(comTVs ? [['TV', 'TVs']] : [])];
  return (
    <nav aria-label="Navegação do painel" className="fixed inset-x-0 bottom-0 z-20 border-t-[3px] border-etiqueta bg-band pb-[env(safe-area-inset-bottom)] text-band-ink">
      <div className="mx-auto flex max-w-[1180px] flex-col items-stretch gap-2 px-3 pb-1.5 pt-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-6 sm:py-2">
        <div className="flex flex-wrap justify-center gap-1.5" role="group" aria-label="Filtrar por família">
          {fams.map(([k, rotulo]) => <button key={k} type="button" aria-pressed={familia === k} onClick={() => onFamilia(k)}
            className={`rounded-full border-2 px-3.5 py-[3px] text-sm font-bold transition-colors duration-150 ${familia === k ? 'border-band-ink bg-band-ink text-band' : 'border-band-ink-2 bg-transparent text-band-ink'}`}>{rotulo}</button>)}
        </div>
        <div className="flex justify-between gap-1">
          {ABAS.map(([k, rotulo, icone]) => <button key={k} type="button" aria-current={aba === k ? 'page' : undefined} onClick={() => onAba(k)}
            className={`flex flex-1 flex-col items-center gap-0.5 rounded-[3px] px-0.5 py-1 text-[12.5px] font-bold transition-colors duration-150 sm:flex-none sm:flex-row sm:gap-2 sm:px-3.5 sm:py-1.5 sm:text-sm
              ${aba === k ? 'bg-etiqueta text-etiqueta-ink' : 'text-band-ink-2 hover:text-band-ink'}`}>
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icone}</svg>{rotulo}</button>)}
        </div>
      </div>
    </nav>
  );
}

createRoot(document.getElementById('raiz')).render(<StrictMode><App /></StrictMode>);
