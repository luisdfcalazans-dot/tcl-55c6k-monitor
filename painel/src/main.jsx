import {StrictMode, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {TableCell, TableRow} from './tremor.js';
import {montaPainel} from './logica.js';
import {Chip, CodigoCupom, Fato, H2, Lista, Postagem, Sub, Tabela} from './componentes.jsx';
import Vitrine, {Pilulas} from './Vitrine.jsx';
import Tabelas from './Tabelas.jsx';
import {CRIAR_TOKEN, buscaPendente, dispara, espera, guardaToken, temToken} from './busca.js';
import './estilo.css';

const pega = (u, como) => fetch(u + '?t=' + Date.now()).then(r => r.ok ? r[como]() : null).catch(() => null);

// estado salvo nesta sessão do navegador (a aba escolhida); sem storage (aba anônima), só na memória
function useSessao(chave, inicial) {
  const [v, setV] = useState(() => { try { return sessionStorage.getItem(chave) ?? inicial; } catch { return inicial; } });
  return [v, novo => { setV(novo); try { sessionStorage.setItem(chave, novo); } catch { /* sem storage */ } }];
}

function App() {
  const [vm, setVm] = useState(undefined);   // undefined: carregando; null: sem dados
  const [abaSalva, setAba] = useSessao('aba', 'produtos');
  const aba = ABAS.some(([k]) => k === abaSalva) ? abaSalva : 'produtos';
  // dados publicados em data/: na abertura e quando a coleta disparada pelo botão de atualizar chega ao site
  const carrega = () => Promise.all([pega('data/latest_cloud.json', 'json'), pega('data/latest_pc.json', 'json'),
    pega('data/historico_cloud.csv', 'text'), pega('data/historico_pc.csv', 'text')])
    .then(([cloud, pc, csvCloud, csvPc]) => setVm(montaPainel({cloud, pc, csvCloud, csvPc})));
  useEffect(() => { carrega(); }, []);
  const rolaETroca = nome => { setAba(nome); scrollTo(0, 0); };

  // produto escolhido nas pílulas (#p= no endereço) e o cartão dele, que só abre com o clique na pílula; sem escolha
  // válida, fica o primeiro com preço
  const [prodId, setProdId] = useState(() => decodeURIComponent((location.hash.match(/^#p=(.+)$/) || [])[1] || ''));
  const [cartao, setCartao] = useState(false);
  const itens = vm ? vm.vitrine : [];
  const atual = itens.find(it => it.id === prodId) || itens.find(it => it.melhor) || itens[0];
  const escolhe = id => {
    if (id === atual?.id) setCartao(c => !c); else { setProdId(id); setCartao(true); }
    try { history.replaceState(null, '', '#p=' + encodeURIComponent(id)); } catch { /* sandbox */ }
  };
  return <>
    <header className="bg-band text-band-ink">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-end justify-between gap-x-6 gap-y-2.5 px-4 pb-3.5 pt-[18px] sm:px-6 sm:pt-[22px]">
        <h1 className="m-0 font-cond text-[clamp(40px,7vw,64px)] font-bold leading-[.95] tracking-[-.01em]">Monitor de Preços</h1>
        <div className="flex flex-wrap items-center gap-1">
          <p className="m-0 mr-1 text-[15px] text-band-ink-2">Última coleta: <b className="text-band-ink">{vm === undefined ? '—' : vm ? vm.quando : 'ainda sem dados'}</b></p>
          <BotaoAtualizar onConcluida={carrega} />
          <BotaoTema />
        </div>
      </div>
      {aba === 'produtos' && itens.length > 0 && <Pilulas itens={itens} atual={atual} cartao={cartao} onEscolhe={escolhe} />}
    </header>

    <main className="mx-auto max-w-[1180px] px-4 pb-[104px] pt-4 sm:px-6 sm:pb-[96px] sm:pt-6">
      {vm === undefined ? <p className="py-3 text-[15px] text-tinta-3">Carregando os preços…</p>
        : !vm ? <p className="py-3 text-[15px] text-tinta-3">Ainda sem dados em data/.</p>
        : <>
          {aba === 'produtos' && <>
            <Vitrine it={atual} cartao={cartao} />
            <H2>Resumo</H2>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              <Fato k="Cupons ativos" d={vm.resumo.cupons} /><Fato k="Postagens (7 dias)" d={vm.resumo.posts} />
              <Fato k="Melhor gift card PSN" d={vm.resumo.gift} /><Fato k="GTA 6 Standard com gift card" d={vm.resumo.giftStd} />
              <Fato k="GTA 6 Ultimate com gift card" d={vm.resumo.giftUlt} />
            </div>
          </>}
          {aba === 'tabelas' && <Tabelas vm={vm} />}
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

    <Barra aba={aba} onAba={rolaETroca} />
  </>;
}

// cupom: só a loja, o código (com o copiar) e a regra; sem regra (igual ao título), vale o título no lugar dela
const Cupom = ({c}) => (
  <li className="break-words border-b border-linha-2 px-3 py-2.5 text-[15px] last:border-b-0">
    <b>{c.loja}</b> <CodigoCupom codigo={c.codigo} />
    <Sub>{c.regra || c.titulo}</Sub>
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
    <button type="button" aria-pressed={escuro} aria-label="Tema escuro" title={escuro ? 'Tema claro' : 'Tema escuro'} onClick={troca} className={BOTAO_ICONE}>
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {escuro ? <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />
          : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>}
      </svg></button>
  );
}
// só o ícone, sem contorno (o foco do teclado continua visível pelo contorno amarelo global)
const BOTAO_ICONE = 'inline-flex items-center justify-center rounded-full p-1.5 text-band-ink transition-opacity duration-150 hover:opacity-80 disabled:cursor-wait';

// atualizar: pergunta antes ("Deseja buscar agora?") e, no sim, roda o robô da coleta (workflow do GitHub, src/busca.js);
// o ícone gira até a coleta nova chegar ao site, e aí o painel recarrega os dados. Sem token salvo, a janela pede um.
function BotaoAtualizar({onConcluida}) {
  const janela = useRef(null), campo = useRef(null);
  const [girando, setGirando] = useState(false), [aviso, setAviso] = useState('');
  const [pedeToken, setPedeToken] = useState(false);
  const acompanha = inicio => { setGirando(true); setAviso('');
    espera(inicio).then(onConcluida).catch(e => setAviso(e.message)).finally(() => setGirando(false)); };
  useEffect(() => { const t = buscaPendente(); if (t) acompanha(t); }, []);   // recarregou no meio de uma busca
  const abre = () => { setPedeToken(!temToken()); janela.current.showModal(); };
  const responde = sim => {
    if (sim && pedeToken) { if (!campo.current.value.trim()) return campo.current.focus(); guardaToken(campo.current.value); }
    janela.current.close();
    if (sim) { setGirando(true); setAviso(''); dispara().then(acompanha).catch(e => { setAviso(e.message); setGirando(false); }); }
  };
  return <>
    <button type="button" aria-label={girando ? 'Buscando os preços…' : 'Buscar os preços agora'} title={aviso || (girando ? 'Buscando os preços…' : 'Buscar os preços agora')}
      disabled={girando} onClick={abre} className={BOTAO_ICONE}>
      <svg className={`h-5 w-5 ${girando ? 'animate-spin' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8" /><path d="M18.5 2v3.8h-3.8M5.5 22v-3.8h3.8" /></svg>
    </button>
    {aviso && <p role="status" className="m-0 basis-full text-right text-[13px] text-etiqueta">{aviso}</p>}
    <dialog ref={janela} aria-labelledby="buscar-titulo"
      className="w-[min(360px,calc(100vw-32px))] rounded-[4px] border-2 border-linha bg-superficie p-5 text-tinta backdrop:bg-black/50">
      <p id="buscar-titulo" className="m-0 text-center text-lg font-bold">Deseja buscar agora?</p>
      {pedeToken && <label className="mt-3 block text-sm text-tinta-2">Token do GitHub (fica só neste navegador)
        <input ref={campo} type="password" autoComplete="off" spellCheck="false"
          className="mt-1 block w-full rounded-[3px] border-2 border-linha bg-superficie px-2 py-1 text-tinta" />
        <span className="mt-1 block text-[13px] text-tinta-3">Crie um token <a href={CRIAR_TOKEN} target="_blank" rel="noopener noreferrer">fine-grained</a> só
          para o repositório tcl-55c6k-monitor, com a permissão Actions: leitura e escrita.</span></label>}
      <div className="mt-4 flex justify-center gap-3">
        <button type="button" onClick={() => responde(true)} className="min-w-[96px] rounded-[3px] bg-[#1F4FA3] px-4 py-2 font-bold text-white transition-opacity duration-150 hover:opacity-90">Sim</button>
        <button type="button" onClick={() => responde(false)} className="min-w-[96px] rounded-[3px] bg-[#D7263D] px-4 py-2 font-bold text-white transition-opacity duration-150 hover:opacity-90">Não</button>
      </div>
    </dialog>
  </>;
}

// barra inferior (30/10/2026): as abas (uma parte do painel por vez); a escolha do produto fica nas pílulas do topo
const ABAS = [
  ['produtos', 'Produtos', <><rect x="3" y="3" width="7.5" height="7.5" rx="1" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1" /></>],
  ['tabelas', 'Tabelas', <><rect x="3" y="4" width="18" height="16" rx="1.5" /><path d="M3 9.5h18M3 14.5h18M9 9.5V20" /></>],
  ['cupons', 'Cupons', <><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2.5a2.5 2.5 0 0 0 0 5V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2.5a2.5 2.5 0 0 0 0-5z" /><path d="M14.5 9l-5 6M9.5 9.5h.01M14.5 14.5h.01" /></>],
  ['fontes', 'Fontes', <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />],
];
function Barra({aba, onAba}) {
  return (
    <nav aria-label="Navegação do painel" className="fixed inset-x-0 bottom-0 z-20 border-t-[3px] border-etiqueta bg-band pb-[env(safe-area-inset-bottom)] text-band-ink">
      <div className="mx-auto max-w-[1180px] px-3 py-1.5 sm:px-6 sm:py-2">
        <div className="flex justify-between gap-1 sm:justify-end">
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
