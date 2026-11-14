// Regras do painel (antes no <script> do docs/index.html), sem DOM: recebe os latest_<modo>.json e os historico_<modo>.csv
// e devolve o "modelo de tela" que os componentes React só desenham. Os testes (tests/test_painel.py e cia.) importam
// este arquivo no Node e conferem o modelo, então toda regra de negócio fica aqui e nenhuma nos componentes.

export const fmt = v => v == null || isNaN(v) ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
export const reais = v => v == null || !isFinite(v) ? '—' : 'R$ ' + Math.round(v).toLocaleString('pt-BR');
export const dt = s => { if (!s) return '—'; const d = new Date(s); return isNaN(d) ? s : d.toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}); };
const pctTxt = d => `${(d * 100).toLocaleString('pt-BR', {maximumFractionDigits: 0})}%`;

// Duas TVs (26/09/2026): a 55C6K e a 65C6K. Registro sem o campo 'modelo' (latest/histórico antigos) é da 55C6K.
// Desde 03/10/2026 o campo guarda o id de qualquer produto do catálogo (PS5, GTA 6...): o catálogo vem no latest
// ('produtos', monitor/produtos.py) e o painel monta uma seção por família com ele; latest antigo, sem ele: só as TVs.
export const MODELOS = ['55C6K', '65C6K'];
const POL = {'55C6K': 55, '65C6K': 65};
export const ehTV = m => MODELOS.includes(m);
const modeloDe = (o, cat) => { const m = String(o?.modelo || '').trim().toUpperCase(); return MODELOS.includes(m) || cat[m] ? m : '55C6K'; };
// selo do modelo nas postagens e cupons: {texto, classe} (m55, m65 ou mp)
const chipModelo = (m, cat) => ehTV(m) ? {texto: `${POL[m]}"`, classe: `m${POL[m]}`} : {texto: cat[m]?.curto || m, classe: 'mp'};
// "menor já visto" de cada produto no latest: 'minimo' (55C6K, a chave de sempre), 'minimo_65C6K', 'minimo_PS5_DIGITAL'...
const chaveMin = m => m === '55C6K' ? 'minimo' : 'minimo_' + m;
const alvosDe = (f, m) => (f?.alvos && f.alvos[m])
  || (f?.produtos?.[m] ? {pix: f.produtos[m].alvo_pix, parcelado: f.produtos[m].alvo_parcelado} : null)
  || (m === '55C6K' && f ? {pix: f.alvo_pix, parcelado: f.alvo_parcelado} : null);

// Zoom/Buscapé é agregador, não loja: o preço que ele mostra para uma loja pode ficar parado por dias
// (ex.: Amazon a R$ 3.279 em 81 coletas seguidas, com a loja a R$ 4.034,50). O monitor marca extra.agregador;
// fonte/URL do Zoom cobrem os dados gravados antes disso e o "minimo" (que não traz a fonte).
// Modo sem atualizar há mais que isso: linhas marcadas como antigas. O GitHub espaça o cron da nuvem para
// cerca de 1 execução a cada 4 h (intervalos de até ~5,1 h observados), então o limite precisa ficar acima disso.
export const VELHO_H = 6, VELHO_MS = VELHO_H * 3600e3;
const normLoja = s => String(s ?? '').trim().toLowerCase();
const ehAgregador = o => o?.extra?.agregador === true || ['zoom', 'buscape'].includes(normLoja(o?.fonte))
  || /^https?:\/\/(www\.)?(zoom|buscape)\.com\.br\//i.test(o?.url || '');
const lojasDiretas = linhas => new Set(linhas.filter(o => !ehAgregador(o)).map(o => normLoja(o.loja)));
// Vendedor 1P é a própria loja na chave de deduplicação ("Magalu" no Magazine Luiza, "Amazon.com.br" na Amazon).
const VENDEDOR_1P = {'magazine luiza': ['magalu', 'magazine luiza'], 'amazon': ['amazon.com.br', 'amazon']};
const vendedorChave = o => { const v = normLoja(o.vendedor), l = normLoja(o.loja); return !v || v === l || (VENDEDOR_1P[l] || []).includes(v) ? '' : v; };
const menorPreco = r => Math.min(...[r.preco_pix, r.preco].filter(Boolean).map(Number));

// Confiança nos vendedores (monitor/confianca.py). Vendedor/anúncio reprovado (lista curada ou automático, que o
// latest traz em confianca.reprovados) some de tudo, inclusive das linhas antigas do histórico e do "minimo";
// anúncio suspeito aparece riscado no fim da tabela e nunca vira "Melhor"/"Menor já visto"; vendedor fora da lista
// de confiáveis ganha um selo com o que foi checado.
const idNorm = s => String(s ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
const nomeNorm = s => String(s ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/a classificacao do vendedor.*$/, '').replace(/politica de devolucao|^\s*vendido por\s+/g, '').replace(/[^a-z0-9]/g, '');
const RE_VID = /[?&](?:seller_id|smid|idLojista)=([^&#]+)/i, RE_ANUNCIO = /\/p\/([0-9a-z]{6,})(?:\/|$|\?|#)/i;
const pistas = o => {
  const ehMagalu = normLoja(o?.loja) === 'magazine luiza', id = String(o?.id || '');
  const vid = idNorm(o?.extra?.vendedor_id) || idNorm((RE_VID.exec(o?.url || '') || [])[1])
    || (ehMagalu && id.includes('-') ? idNorm(id.slice(id.lastIndexOf('-') + 1)) : '');
  const anuncios = new Set([o?.extra?.anuncio, o?.extra?.item_id, (RE_ANUNCIO.exec(o?.url || '') || [])[1],
    ehMagalu && id.includes('-') ? id.split('-')[0] : ''].map(idNorm).filter(Boolean));
  return {vid, nome: nomeNorm(o?.vendedor), anuncios};
};
// O anúncio de um reprovado AUTOMÁTICO só esconde linha que não diz quem vende: outro vendedor no mesmo anúncio (ex.:
// o Magalu 1P no /p/ em que o reprovado aparecia na lista de vendedores) continua. Anúncio da lista curada vale sempre.
const reprovadoPor = lista => o => { if (!o) return false; const p = pistas(o);
  return lista.some(e => normLoja(e.loja) === normLoja(o.loja) && ((p.vid && (e.ids || []).includes(p.vid))
    || (p.nome && (e.nomes || []).includes(p.nome))
    || ((e.anuncios || []).some(a => p.anuncios.has(a)) && (e.origem !== 'automatico' || (!p.vid && !p.nome))))); };
const veredito = o => o?.extra?.confianca?.veredito || '';
const suspeito = o => veredito(o) === 'suspeito';
// selo do vendedor: 'risco' (suspeito; o painel é público e a empresa pode ser vítima, então o rótulo é neutro) ou
// 'novo' (fora da lista de confiáveis, sem risco aparente). O título leva o que foi checado.
const selo = o => {
  const c = o?.extra?.confianca || {}, sinais = (c.sinais || []).join('; ');
  if (c.veredito === 'suspeito') return {tipo: 'risco', rotulo: 'sinais de risco', titulo: sinais};
  if (c.veredito === 'sem_risco_aparente') return {tipo: 'novo', rotulo: 'vendedor novo',
    titulo: `checagens: ${(c.checagens || []).join(', ') || '—'}${sinais ? ' · atenção: ' + sinais : ''}`};
  return null;
};
// Parcelamento: "12x R$ 312,49 sem juros", "10x de R$ 418,48 sem juros", "10x R$ 399,90 sem juros (cartão Casas Bahia)".
// Total = parcelas x valor; mas a loja arredonda a parcela (Amazon: 12x R$ 312,49 de um total de R$ 3.749,00), então
// quando a conta fica a menos de 1% do preço do cartão, o total cobrado é o próprio preço do cartão.
const RE_PARC = /(\d{1,2})\s*x\s*(?:de\s*)?R\$\s?(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)/i;   // aceita 'R$ 374' (dado antigo sem centavos)
export const parcela = o => {
  const txt = o?.parcelado || ''; const m = RE_PARC.exec(txt); if (!m) return null;
  const n = Number(m[1]), p = Number(m[2].replace(/\./g, '').replace(',', '.'));
  if (!(n >= 1) || !(p > 0)) return null;
  const bruto = Math.round(n * p * 100) / 100, cartao = Number(o.preco) || 0;
  const total = cartao && Math.abs(bruto - cartao) <= Math.max(n * 0.01, cartao * 0.01) ? cartao : bruto;
  return {n, valor: p, total, semJuros: /sem\s+juros/i.test(txt), comJuros: /com\s+juros/i.test(txt), condicao: (txt.match(/\(([^)]*)\)/) || [])[1] || ''};
};
const textoParc = pc => `${pc.n}x ${fmt(pc.valor)}${pc.semJuros ? ' sem juros' : pc.comJuros ? ' com juros' : ''}${pc.condicao ? ` (${pc.condicao})` : ''}`;
const quem = o => o.loja + (vendedorChave(o) ? ` (${o.vendedor})` : '');
// diferença "65\" a mais": valor e percentual (negativo quando a 65\" sai mais barata)
const fmtDif = (d, base) => d == null || isNaN(d) ? '—'
  : `${d < 0 ? '−' : '+'}${fmt(Math.abs(d))}${base ? ` (${d < 0 ? '−' : '+'}${Math.abs(d / base * 100).toLocaleString('pt-BR', {maximumFractionDigits: 0})}%)` : ''}`;

export function parseCsv(txt) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < txt.length; i++) {
    const c = txt[i];
    if (q) { if (c === '"') { if (txt[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  if (!rows.length) return [];
  const h = rows[0];
  // linha gravada antes de 26/09 num arquivo cujo cabeçalho já ganhou a coluna 'modelo' (a última): vale, e é da 55C6K
  const minimo = h[h.length - 1] === 'modelo' ? h.length - 1 : h.length;
  return rows.slice(1).filter(r => r.length >= minimo).map(r => Object.fromEntries(h.map((k, i) => [k, r[i] ?? ''])));
}

// ---- PS5 e GTA 6 (03/10/2026): o que a coleta gravou no extra (monitor/produtos.py, anota): a meta desta oferta, a
// entrega do GTA 6 (chega a tempo?), os extras do kit, o valor de face do gift card
function infoProduto(o) {
  const ex = o?.extra || {}, partes = [];
  if (ex.entrega?.texto) partes.push(ex.entrega.texto.replace(/^📦\s*/, ''));
  const det = ex.produto || {};
  if (det.extras?.length) partes.push('extras: ' + det.extras.map(e => e.nome || e.tipo).join(', '));
  if (det.valor_face && o.melhor_preco) partes.push(`vale ${fmt(det.valor_face)} (${Math.round((1 - o.melhor_preco / det.valor_face) * 100)}% de desconto)`);
  if (ex.alvo?.pix != null) partes.push(`meta ${fmt(ex.alvo.pix)}${ex.alvo.nota ? ' · ' + ex.alvo.nota : ''}`);
  return partes;
}

// Uma linha da tabela de ofertas de loja, pronta para desenhar.
function linhaLoja(o, modelo, melhor, melhorParc) {
  const pix = o.preco_pix ? fmt(o.preco_pix) : (o.preco ? fmt(o.preco) : '—');
  const cc = o.extra?.preco_melhor_cupom || o.extra?.preco_com_cupom, base = o.preco_pix || o.preco;
  const pc = parcela(o);
  return {
    classe: o === melhor ? 'best' : suspeito(o) ? 'sus' : o._velho ? 'velho' : '',
    loja: o.loja, fonte: o.fonte, agregador: ehAgregador(o), selo: selo(o),
    vendedor: o.vendedor && o.vendedor !== o.loja ? o.vendedor : null,
    oferta: o.extra?.oferta || null, info: ehTV(modelo) ? [] : infoProduto(o),
    avista: fmt(o.preco), pix, pixCupom: cc && (!base || cc < base) ? fmt(cc) : null,
    parc: pc ? {total: fmt(pc.total), texto: textoParc(pc), melhor: !!melhorParc && melhorParc.o === o} : null,
    parcTexto: pc ? null : (o.parcelado || '—'),
    cupom: o.cupom || null, visto: dt(o._visto), velho: !!o._velho, url: o.url,
  };
}

// Linhas, destaques, mínimo e série do gráfico de UM modelo (as regras são as mesmas para todos os produtos).
function painelDoModelo(modelo, ctx) {
  const {fontes, todas, reprovado, diretas, hist, vale, cat} = ctx;
  let lojas = todas.filter(o => modeloDe(o, cat) === modelo && o.ativo !== false && o.melhor_preco
    && !(ehAgregador(o) && diretas.has(normLoja(o.loja))) && (suspeito(o) || (!reprovado(o) && veredito(o) !== 'reprovado')));
  lojas.sort((a, b) => (suspeito(a) - suspeito(b)) || (a._velho - b._velho) || (a.melhor_preco - b.melhor_preco));
  const vistas = new Set();
  lojas = lojas.filter(o => { const k = normLoja(o.loja) + '|' + vendedorChave(o); if (vistas.has(k)) return false; vistas.add(k); return true; });
  const melhor = lojas.find(o => !o._velho && !suspeito(o));
  // Melhor parcelado: menor TOTAL entre as linhas recentes que informam parcelamento; no empate, sem juros e sem
  // condição (ex.: "cartão Casas Bahia") primeiro.
  const comParc = lojas.filter(o => !o._velho && !suspeito(o)).map(o => ({o, pc: parcela(o)})).filter(x => x.pc)
    .sort((a, b) => (a.pc.total - b.pc.total) || (b.pc.semJuros - a.pc.semJuros) || (!!a.pc.condicao - !!b.pc.condicao));
  const melhorParc = comParc[0] || null;
  // "Menor já visto": mínimo vindo do agregador ou de vendedor/anúncio reprovado não conta; aí recalcula o do modo
  // pelo histórico dele (só as linhas do modelo).
  const histModelo = {cloud: hist.cloud.filter(r => modeloDe(r, cat) === modelo), pc: hist.pc.filter(r => modeloDe(r, cat) === modelo)};
  const minDoModo = f => {
    const m = f[chaveMin(modelo)];
    if (!m || vale(m)) return m;
    return (histModelo[f.modo] || []).filter(vale).map(r => ({preco: menorPreco(r), loja: r.loja, quando: r.quando}))
      .sort((a, b) => a.preco - b.preco)[0] || null;
  };
  const mins = fontes.map(minDoModo).filter(Boolean).sort((a, b) => a.preco - b.preco);
  // gráfico: menor preço por loja por dia (sem o agregador nas lojas que têm fonte direta)
  const serie = {};
  [...histModelo.cloud, ...histModelo.pc].filter(vale).forEach(r => {
    const dia = r.quando.slice(0, 10); const p = menorPreco(r);
    const k = r.loja; serie[k] ??= {}; serie[k][dia] = Math.min(serie[k][dia] ?? Infinity, p);
  });
  return {lojas, melhor, melhorParc, min: mins[0] || null, serie,
    linhas: lojas.map(o => linhaLoja(o, modelo, melhor, melhorParc))};
}

// Os três cartões de destaque de uma TV: {v, s} = valor grande e a linha de baixo.
function destaques(r) {
  const {melhor, melhorParc, min} = r, tem = r.lojas.length;
  return {
    melhor: {v: melhor ? fmt(melhor.melhor_preco) : '—',
      s: melhor ? `${quem(melhor)}${melhor.preco_pix && melhor.melhor_preco === melhor.preco_pix ? ' · Pix' : ''}` : (tem ? 'sem coleta recente' : 'sem coleta')},
    parc: {v: melhorParc ? fmt(melhorParc.pc.total) : '—',
      s: melhorParc ? `${quem(melhorParc.o)} · ${textoParc(melhorParc.pc)}` : (tem ? 'nenhuma loja recente informa parcelamento' : 'sem coleta')},
    min: {v: min ? fmt(min.preco) : '—', s: min ? `${min.loja} · ${dt(min.quando)}` : '—'},
  };
}

// Comparação 55" × 65" NA MESMA LOJA: o menor à vista e o menor total parcelado de cada TV na loja, e quanto a 65"
// custa a mais. Só linhas que não são suspeitas; a coleta recente vale antes da antiga (a antiga fica marcada).
// Cada linha: {loja, celulas: [55 à vista, 65 à vista, dif à vista, 55 parcelado, 65 parcelado, dif parcelado]}; uma
// célula de preço é {v, subs, velho} ou null, a de diferença é texto.
function comparacao(res) {
  const porLoja = new Map();
  for (const m of MODELOS) {
    for (const o of res[m].lojas) {
      if (suspeito(o)) continue;
      const k = normLoja(o.loja);
      if (!porLoja.has(k)) porLoja.set(k, {loja: o.loja, m: {}});
      const e = porLoja.get(k).m[m] ??= {vista: null, parc: null};
      const melhorQue = (a, b, va, vb) => !b || (a._velho - b._velho) < 0 || ((a._velho === b._velho) && va < vb);
      if (!e.vista || melhorQue(o, e.vista.o, o.melhor_preco, e.vista.v)) e.vista = {o, v: o.melhor_preco};
      const pc = parcela(o);
      if (pc && (!e.parc || melhorQue(o, e.parc.o, pc.total, e.parc.v))) e.parc = {o, v: pc.total, pc};
    }
  }
  const linhas = [...porLoja.values()].sort((a, b) =>
    Math.min(...MODELOS.map(m => a.m[m]?.vista?.v ?? Infinity)) - Math.min(...MODELOS.map(m => b.m[m]?.vista?.v ?? Infinity)));
  const cel = x => !x ? null : {v: fmt(x.v), velho: !!x.o._velho,
    subs: [vendedorChave(x.o) ? x.o.vendedor : '', x.pc ? textoParc(x.pc) : ''].filter(Boolean)};
  const dif = (a, b) => a && b ? fmtDif(b.v - a.v, a.v) : '—';
  return linhas.map(l => { const a = l.m['55C6K'] || {}, b = l.m['65C6K'] || {};
    return {loja: l.loja, celulas: [cel(a.vista), cel(b.vista), dif(a.vista, b.vista), cel(a.parc), cel(b.parc), dif(a.parc, b.parc)]}; });
}

// ---- gift card PlayStation para pagar o GTA 6 digital (26/10/2026; latest.gift_card_psn, calculado no monitor): o
// melhor cartão de loja oficial (maior desconto) e o custo do GTA 6 digital com a melhor combinação de valores de face
// (o saldo da carteira é usado primeiro e o resto vai para o cartão de crédito). Os dois modos juntos.
function giftDosModos(fontes) {
  const blocos = fontes.map(f => f.gift_card_psn).filter(b => b && typeof b === 'object');
  if (!blocos.length) return null;
  const vistos = new Map();
  for (const b of blocos) for (const c of (b.cartoes || [])) {
    const k = [normLoja(c.loja), c.valor_face, c.preco].join('|');
    if (!vistos.has(k)) vistos.set(k, c);
  }
  const cartoes = [...vistos.values()].sort((a, b) => (b.desconto - a.desconto) || (a.preco - b.preco));
  const gta = {};
  for (const b of blocos) for (const [pid, g] of Object.entries(b.gta || {}))
    if (!gta[pid] || g.custo < gta[pid].custo) gta[pid] = g;
  const regra = blocos.find(b => b.regra)?.regra || {};
  return {melhor: cartoes[0] || null, cartoes, gta, regra};
}
const textoCartoes = g => (g.cartoes || []).map(c => `R$ ${Math.round(c.valor_face)} (${c.loja}, ${fmt(c.preco)})`).join(' + ')
  + (g.no_cartao ? ` + ${fmt(g.no_cartao)} no cartão` : '') + (g.sobra ? `; sobram ${fmt(g.sobra)} de saldo` : '');
function resumoGift(gift) {
  const m = gift?.melhor, out = {
    gift: {v: m ? fmt(m.preco) : '—', s: m ? `vale R$ ${Math.round(m.valor_face)} · ${pctTxt(m.desconto)} · ${m.loja}` : 'nenhum com desconto em loja oficial'}};
  for (const [pid, k] of [['GTA6_DIGITAL', 'giftStd'], ['GTA6_ULTIMATE', 'giftUlt']]) {
    const g = gift?.gta?.[pid];
    out[k] = {v: g ? fmt(g.custo) : '—', s: g ? `−${pctTxt(g.desconto)} · ${textoCartoes(g)}` : 'sem gift card que baixe o preço'};
  }
  return out;
}
// bloco do gift card na seção do GTA 6
function blocoGift(gift) {
  const r = gift?.regra || {}, meta = r.meta ?? 0.15, faceMin = r.face_minima ?? 100;
  const naMeta = c => c.desconto >= meta - 1e-9 && c.valor_face >= faceMin;   // cartão abaixo de R$ 100 fica sem meta (igual ao monitor)
  const regra = {prazo: r.prazo ? r.prazo.slice(8, 10) + '/' + r.prazo.slice(5, 7) : '11/11', meta: pctTxt(meta),
    excelente: pctTxt(r.excelente ?? 0.2), minimo: pctTxt(r.minimo ?? 0.15)};
  const m = gift?.melhor;
  if (!m) return {regra, melhor: null, gta: [], cartoes: []};
  const cartao = c => ({loja: c.loja, post: c.tipo === 'post', face: `R$ ${Math.round(c.valor_face)}`, preco: fmt(c.preco),
    desconto: pctTxt(c.desconto), naMeta: naMeta(c), cupom: c.cupom || null, url: c.url || null});
  const gta = Object.values(gift.gta || {}).sort((a, b) => (a.edicao || '').localeCompare(b.edicao || '')).reverse()
    .map(g => ({edicao: g.edicao || g.nome, psstore: fmt(g.preco_psstore), custo: fmt(g.custo), ok: g.custo <= g.meta,
      economia: `−${pctTxt(g.desconto)} · economia ${fmt(g.economia)}`, meta: fmt(g.meta),
      faixas: `aceitável ${fmt(g.aceitavel)} · ótimo ${fmt(g.otimo)}`, cartoes: textoCartoes(g)}));
  const outros = (gift.cartoes || []).slice(0, 6);
  return {regra, melhor: cartao(m), gta, cartoes: outros.length > 1 ? outros.map(cartao) : []};
}

// distância do preço até a meta: "R$ 49,00 acima" / "R$ 51,00 abaixo"
const distMeta = (v, meta) => v == null || !meta ? '—' : (v - meta > 0.5 ? `${fmt(v - meta)} acima` : v - meta < -0.5 ? `${fmt(meta - v)} abaixo` : 'na meta');
const ENTREGA_CLASSE = {a_tempo: 'ok', digital: 'ok', no_dia: 'warn', depois: 'bad', desconhecida: 'mute'};
const ENTREGA_ROTULO = {a_tempo: 'chega até 18/11', digital: 'digital (00:00 de 19/11)', no_dia: 'chega 19/11', depois: 'chega depois', desconhecida: 'prazo ?'};
const linhaPost = cat => p => ({chave: p.chave, chip: chipModelo(modeloDe(p, cat), cat), expirada: p.ativo === false,
  preco: fmt(p.melhor_preco), loja: p.loja, cupom: p.cupom || null, titulo: String(p.titulo || '').slice(0, 110),
  fonte: p.fonte, telegram: /^telegram/i.test(p.fonte || ''), quando: dt(p.publicado || p.primeira_vez), url: p.url});

// GTA 6 em todas as formas pelo custo final (latest.gta6_custo_final, calculado no monitor com o melhor gift card de loja
// oficial visto), nas duas edições (pedido de 03/10): a Standard (Code in Box e digital) e a Ultimate (só digital no
// Brasil), que também sai pela Standard + o upgrade de R$ 100. O mais barato primeiro, com a entrega (precisa chegar até
// 18/11 para jogar à meia-noite de 19/11). Linha de latest antigo, sem 'edicao': a edição sai do produto.
const EDICAO_GTA = {GTA6_CODE_IN_BOX: 'Standard', GTA6_DIGITAL: 'Standard', GTA6_ULTIMATE: 'Ultimate', GTA6_UPGRADE: 'Ultimate'};
function custoFinal(fontes) {
  const vistos = new Map();
  for (const f of fontes) for (const r of (f.gta6_custo_final || [])) {
    const k = [r.produto, r.via || '', normLoja(r.loja), r.url].join('|'), atual = vistos.get(k);
    if (!atual || r.custo_final < atual.custo_final) vistos.set(k, r);
  }
  let todas = [...vistos.values()].filter(r => r.custo_final != null).sort((a, b) => a.custo_final - b.custo_final);
  // os dois modos juntos: a referência pelo preço oficial (um modo que não leu a PS Store) sai quando o outro viu o
  // produto por esse preço ou menos; de cada forma da Standard + upgrade fica a mais barata
  const reais_ = todas.filter(r => r.tipo !== 'calculo');
  const vias = new Set();
  todas = todas.filter(r => {
    if (r.tipo === 'calculo' && !r.via) return !reais_.some(x => x.produto === r.produto && x.custo_final <= r.custo_final + 0.005);
    if (r.via) { if (vias.has(r.via)) return false; vias.add(r.via); }
    return true;
  });
  if (!todas.length) return null;
  const edicao = r => r.edicao || EDICAO_GTA[r.produto] || 'Standard';
  const std = todas.filter(r => edicao(r) === 'Standard').slice(0, 10), ult = todas.filter(r => edicao(r) === 'Ultimate').slice(0, 6);
  const linha = r => ({forma: r.forma, loja: r.loja || '?', tipo: r.tipo === 'post' ? 'postagem' : r.tipo === 'calculo' ? 'cálculo' : null,
    custo: fmt(r.custo_final), detalhe: r.preco && Math.abs(r.preco - r.custo_final) > 0.5 ? `preço ${fmt(r.preco)}${r.cupom ? ` · cupom ${r.cupom}` : ''}` : null,
    meta: r.meta ? fmt(r.meta) : '—', ok: !!(r.meta && r.custo_final <= r.meta),
    entrega: r.entrega ? {classe: ENTREGA_CLASSE[r.entrega] || 'mute', rotulo: ENTREGA_ROTULO[r.entrega] || r.entrega, titulo: r.entrega_texto || ''} : null,
    url: r.url || null});
  // a Ultimate mais barata: a digital × a Standard + upgrade (a melhor das linhas da comparação)
  const dig = ult.find(r => r.produto === 'GTA6_ULTIMATE'), combo = ult.find(r => r.via);
  let nota = null;
  if (dig && combo) {
    const d = Math.abs(dig.custo_final - combo.custo_final);
    nota = d < 0.005 ? `Ultimate mais barata: a digital e a Standard + upgrade empatam (${fmt(dig.custo_final)}).`
      : combo.custo_final < dig.custo_final ? `Ultimate mais barata: ${combo.forma.replace('GTA 6 Ultimate = ', '')} (${combo.loja || '?'}) por ${fmt(combo.custo_final)}, ${fmt(d)} a menos que a Ultimate digital (${fmt(dig.custo_final)}).`
      : `Ultimate mais barata: a digital por ${fmt(dig.custo_final)}, ${fmt(d)} a menos que a Standard + upgrade (${fmt(combo.custo_final)}).`;
  }
  return {std: std.map(linha), ult: ult.map(linha), nota};
}

// Uma seção por família (PS5, GTA 6): resumo por produto (meta, melhor à vista e parcelado agora, menor já visto,
// distância da meta), a tabela de preços por loja e o gráfico de cada produto, as postagens recentes e, no GTA 6, o
// gift card e todas as formas pelo custo final (com a entrega).
function secaoFamilia(sec, titulo, ctx, posts) {
  const {cat} = ctx;
  const ids = Object.keys(cat).filter(id => cat[id].secao === sec && !ehTV(id));
  if (!ids.length) return null;
  const resumo = [], produtos = [];
  for (const id of ids) {
    const p = cat[id], r = ctx.r(id);
    const meta = {pix: p.alvo_pix, parcelado: p.alvo_parcelado};
    const metaOferta = r.melhor?.extra?.alvo?.pix ?? meta.pix;
    const g = id === 'GIFT_CARD_PSN' ? ctx.gift?.melhor : null;
    if (g) {
      // gift card: o melhor é o de maior desconto (não o cartão mais barato, que é só o de menor valor de face)
      const mg = ctx.gift.regra?.meta ?? 0.15;
      resumo.push({id, nome: p.nome, sub: null, meta: {v: `${pctTxt(mg)} de desconto`, subs: ['por oferta']},
        melhor: {v: fmt(g.preco), sub: `vale R$ ${Math.round(g.valor_face)} · ${g.loja}`}, parc: {v: '—', sub: null},
        min: {v: '—', sub: null}, dist: {v: `${pctTxt(g.desconto)} de desconto`, ok: g.desconto >= mg - 1e-9}});
    } else resumo.push({id, nome: p.nome, sub: p.edicao ? `edição ${p.edicao}` : null,
      meta: {v: meta.pix != null ? fmt(meta.pix) : 'por oferta', subs: [
        meta.parcelado != null && meta.parcelado !== meta.pix ? `parc. ${fmt(meta.parcelado)}` : '',
        p.alvo_pix_tardio ? `chega depois: ${fmt(p.alvo_pix_tardio)}` : ''].filter(Boolean)},
      melhor: {v: r.melhor ? fmt(r.melhor.melhor_preco) : '—', sub: r.melhor ? quem(r.melhor) : null},
      parc: {v: r.melhorParc ? fmt(r.melhorParc.pc.total) : '—', sub: r.melhorParc ? quem(r.melhorParc.o) : null},
      min: {v: r.min ? fmt(r.min.preco) : '—', sub: r.min ? r.min.loja || '' : null},
      dist: {v: distMeta(r.melhor?.melhor_preco, metaOferta), ok: !!(r.melhor && metaOferta && r.melhor.melhor_preco <= metaOferta)}});
    if (!r.lojas.length && !Object.keys(r.serie).length) continue;
    produtos.push({id, nome: p.nome, sub: r.melhor ? `melhor ${fmt(r.melhor.melhor_preco)} · ${quem(r.melhor)}` : 'sem coleta recente',
      linhas: r.linhas, grafico: p.compara_preco === false ? null : {serie: r.serie, alvo: meta.pix}});
  }
  return {sec, titulo, resumo, produtos,
    gift: sec === 'GTA6' ? blocoGift(ctx.gift) : null,
    custoFinal: sec === 'GTA6' ? custoFinal(ctx.fontes) : null,
    posts: posts.filter(p => cat[modeloDe(p, cat)]?.secao === sec).slice(0, 10).map(linhaPost(cat))};
}

// ---- vitrine (30/10/2026): a grade com todos os produtos e o placar do produto escolhido. Usa o que painelDoModelo()
// já calcula (mesmas regras de agregador, confiança e coleta antiga).
export const menorPorDia = serie => { const m = {};
  for (const l in serie) for (const [d, v] of Object.entries(serie[l])) m[d] = Math.min(m[d] ?? Infinity, v);
  return m; };
// "R$ 439 acima da meta" / "R$ 51 abaixo da meta" / "na meta" (a mesma tolerância de R$ 0,50 do distMeta)
export const metaTxt = (v, meta) => v == null || !meta ? null
  : v - meta > 0.5 ? {txt: `${reais(v - meta)} acima da meta`, cls: 'acima'}
  : v - meta < -0.5 ? {txt: `${reais(meta - v)} abaixo da meta`, cls: 'abaixo'} : {txt: 'na meta', cls: 'abaixo'};

function vitrine(ctx, semTVs) {
  const {cat} = ctx;
  return Object.keys(cat).filter(id => cat[id].compara_preco !== false && !(semTVs && ehTV(id)))
    .map(id => { const p = cat[id], r = ctx.r(id), m = r.melhor;
      const meta = m?.extra?.alvo?.pix ?? p.alvo_pix;
      return {id, nome: p.nome, curto: p.curto || p.nome, familia: ehTV(id) ? 'TV' : p.secao, meta,
        serie: r.serie, porDia: menorPorDia(r.serie),
        melhor: m ? {preco: fmt(m.melhor_preco), loja: m.loja,
          forma: m.preco_pix && m.melhor_preco === Number(m.preco_pix) ? 'no Pix' : 'à vista',
          vendedor: vendedorChave(m) ? m.vendedor : null, visto: dt(m._visto), cupom: m.cupom || null, url: m.url,
          dist: metaTxt(m.melhor_preco, meta)} : null,
        parc: r.melhorParc ? {total: fmt(r.melhorParc.pc.total), quem: quem(r.melhorParc.o)} : null,
        min: r.min ? {preco: fmt(r.min.preco), loja: r.min.loja || '?', quando: dt(r.min.quando)} : null}; })
    .filter(it => it.melhor || Object.keys(it.serie).length);
}

// Placar no período [ini, fim] (dias 'AAAA-MM-DD'): o menor preço de cada loja (barras), em cada dia qual loja foi a
// mais barata (rosca; empate: as lojas dividem o dia) e as linhas do gráfico (as 8 mais baratas do período e a meta).
export function placar(serie, meta, ini, fim) {
  const noPeriodo = dia => dia >= ini && dia <= fim;
  const lojas = Object.entries(serie).map(([loja, s]) => {
    const vals = Object.entries(s).filter(([dia]) => noPeriodo(dia));
    return {loja, s: Object.fromEntries(vals), min: Math.min(...vals.map(([, v]) => v))};
  }).filter(l => isFinite(l.min)).sort((a, b) => a.min - b.min);
  const dias = [...new Set(lojas.flatMap(l => Object.keys(l.s)))].sort(), vitorias = {};
  for (const dia of dias) {
    const vs = lojas.filter(l => l.s[dia] != null), menor = Math.min(...vs.map(l => l.s[dia]));
    const ganhas = vs.filter(l => l.s[dia] === menor);
    for (const l of ganhas) vitorias[l.loja] = (vitorias[l.loja] || 0) + 1 / ganhas.length;
  }
  let fatias = Object.entries(vitorias).sort((a, b) => b[1] - a[1]);
  if (fatias.length > 5) fatias = [...fatias.slice(0, 4), ['Outras lojas', fatias.slice(4).reduce((s, [, n]) => s + n, 0)]];
  return {lojas, dias, fatias: fatias.map(([loja, n]) => ({loja, dias: n})),
    grafico: seriesDoGrafico(Object.fromEntries(lojas.map(l => [l.loja, l.s])))};
}

// Série {loja: {dia: preço}} no formato colunar do uPlot: os dias e, para cada uma das 8 lojas mais baratas (a mesma
// ordem das cores das barras e da rosca), o preço de cada dia ou null (o gráfico liga os pontos por cima do buraco).
export function seriesDoGrafico(serie) {
  const lojas = Object.keys(serie).sort((a, b) => Math.min(...Object.values(serie[a])) - Math.min(...Object.values(serie[b]))).slice(0, 8);
  const dias = [...new Set(lojas.flatMap(l => Object.keys(serie[l])))].sort();
  return {dias, lojas, valores: lojas.map(l => dias.map(d => serie[l][d] ?? null))};
}

// ---- o painel inteiro. dados = {cloud, pc, csvCloud, csvPc} (o que veio de docs/data; ausente = null/''),
// agora = Date.now() (os testes fixam).
export function montaPainel({cloud, pc, csvCloud = '', csvPc = ''}, agora = Date.now()) {
  const fontes = [cloud, pc].filter(Boolean);
  if (!fontes.length) return null;
  // catálogo dos produtos (os dois modos; latest antigo não tem): define as seções do PS5 e do GTA 6
  const cat = Object.assign({}, ...fontes.map(f => (f.produtos && typeof f.produtos === 'object') ? f.produtos : {}));
  const ultimo = fontes.map(f => f.atualizado).sort().pop();
  // TVs desligadas (26/10/2026: o usuário ficou com a TV): basta um modo publicar o sinal para a parte das TVs sumir
  // (tabelas, cartões, gráficos, comparação, o filtro) e as postagens e cupons de TV saírem das listas. Latest
  // antigo, sem o sinal: o painel com as TVs, como antes
  const semTVs = fontes.some(f => f.tvs_desligadas === true);
  const gift = giftDosModos(fontes);

  // ---- ofertas de loja (ativas), uma linha por loja/vendedor, menor preço primeiro, uma tabela por modelo.
  // Cada linha leva o horário do próprio modo (_visto = latest_<modo>.atualizado); modo parado há mais de
  // VELHO_MS fica marcado como antigo, vai para o fim e não disputa o "Melhor preço agora".
  const todas = fontes.flatMap(f => { const velho = !(agora - Date.parse(f.atualizado) <= VELHO_MS);
    return (f.ofertas_loja || []).map(o => ({...o, _modo: f.modo, _visto: f.atualizado, _velho: velho})); });
  // Linha do agregador some quando alguma fonte direta cobre a mesma loja (mesmo que parada ou indisponível).
  const reprovado = reprovadoPor(fontes.flatMap(f => (f.confianca && f.confianca.reprovados) || []));
  const diretas = lojasDiretas(todas.filter(o => !reprovado(o)));
  // ---- histórico (CSV de cada modo): linha do agregador não vale para loja que tem fonte direta
  const ehLinhaLoja = r => r.tipo === 'loja' && (r.preco_pix || r.preco) && !reprovado(r);
  const hist = {cloud: parseCsv(csvCloud || '').filter(ehLinhaLoja), pc: parseCsv(csvPc || '').filter(ehLinhaLoja)};
  const diretasHist = new Set([...diretas, ...lojasDiretas([...hist.cloud, ...hist.pc])]);
  const vale = o => !(ehAgregador(o) && diretasHist.has(normLoja(o.loja))) && !reprovado(o);
  const cache = {};
  const ctx = {fontes, todas, reprovado, diretas, hist, vale, gift, cat};
  ctx.r = id => (cache[id] ??= painelDoModelo(id, ctx));

  // ---- TVs
  const alvos = Object.fromEntries(MODELOS.map(m => [m, alvosDe(cloud, m) || alvosDe(pc, m) || {}]));
  const r55 = ctx.r('55C6K'), r65 = ctx.r('65C6K');
  const difPix = r55.melhor && r65.melhor ? r65.melhor.melhor_preco - r55.melhor.melhor_preco : null;
  const difParc = r55.melhorParc && r65.melhorParc ? r65.melhorParc.pc.total - r55.melhorParc.pc.total : null;
  const pct = (d, base) => `${d < 0 ? '−' : '+'}${Math.abs(d / base * 100).toLocaleString('pt-BR', {maximumFractionDigits: 0})}%`;
  const tvs = {
    alvos: Object.fromEntries(MODELOS.map(m => [m, {pix: fmt(alvos[m].pix), parcelado: fmt(alvos[m].parcelado)}])),
    modelos: Object.fromEntries(MODELOS.map(m => { const r = ctx.r(m);
      return [m, {linhas: r.linhas, destaques: destaques(r), serie: r.serie, alvo: alvos[m].pix ?? null}]; })),
    dif: {
      pix: {v: fmtDif(difPix), s: difPix == null ? 'falta preço recente de uma das TVs' : `${pct(difPix, r55.melhor.melhor_preco)} · melhor da 65" − melhor da 55"`},
      parc: {v: fmtDif(difParc), s: difParc == null ? 'falta parcelado recente de uma das TVs' : `${pct(difParc, r55.melhorParc.pc.total)} · melhor da 65" − melhor da 55"`}},
    comparar: comparacao({'55C6K': r55, '65C6K': r65}),
  };

  // ---- cupons
  const cupons = fontes.flatMap(f => f.cupons || []).filter(c => !(semTVs && c.modelo && ehTV(modeloDe(c, cat))));
  const porCodigo = new Map();
  cupons.forEach(c => { const k = c.loja + '|' + c.codigo; if (!porCodigo.has(k)) porCodigo.set(k, c); });
  const lc = [...porCodigo.values()].sort((a, b) => (a.loja + a.codigo).localeCompare(b.loja + b.codigo));

  // ---- postagens (o selo diz de qual produto é)
  let posts = fontes.flatMap(f => f.posts || []).filter(p => !(semTVs && ehTV(modeloDe(p, cat))));
  const pv = new Set();
  posts = posts.filter(p => { if (pv.has(p.chave)) return false; pv.add(p.chave); return true; });
  posts.sort((a, b) => (b.publicado || b.primeira_vez || '').localeCompare(a.publicado || a.primeira_vez || ''));
  const diasAtras = s => { if (!s) return null; const d = new Date(s); return isNaN(d) ? null : (agora - d) / 864e5; };
  const recentes = posts.filter(p => { const d = diasAtras(p.publicado || p.primeira_vez); return d != null && d <= 7; });
  const rotuloCurto = m => ehTV(m) ? `${POL[m]}"` : (cat[m]?.curto || m);

  // ---- saúde das fontes
  const saude = Object.assign({}, cloud?.saude || {}, pc?.saude || {});

  return {
    quando: dt(ultimo), semTVs,
    resumo: {
      cupons: {v: String(lc.length), s: [...new Set(lc.map(c => c.loja))].slice(0, 4).join(', ') || '—'},
      posts: {v: String(recentes.length), s: recentes[0] ? `última: ${rotuloCurto(modeloDe(recentes[0], cat))} ${recentes[0].loja} ${fmt(recentes[0].melhor_preco)}` : 'nenhuma esta semana'},
      ...resumoGift(gift)},
    tvs: semTVs ? null : tvs,
    familias: [['PS5', 'PS5'], ['GTA6', 'GTA 6']].map(([sec, titulo]) => secaoFamilia(sec, titulo, ctx, posts)).filter(Boolean),
    vitrine: vitrine(ctx, semTVs),
    cupons: lc.slice(0, 40).map(c => ({loja: c.loja, codigo: c.codigo, especifico: !!c.especifico,
      chip: c.especifico && c.modelo ? chipModelo(modeloDe(c, cat), cat) : null, titulo: c.titulo,
      regra: c.regra && c.regra !== c.titulo ? c.regra.slice(0, 140) : null, fonte: c.fonte,
      validade: c.validade ? dt(c.validade) : null, url: c.url})),
    posts: posts.slice(0, 30).map(linhaPost(cat)),
    fontes: Object.entries(saude).sort().map(([nome, s]) => { const f = s.falhas || 0;
      return {nome, classe: f === 0 ? 'ok' : f < 3 ? 'warn' : 'bad', rotulo: f === 0 ? 'OK' : `${f} falhas`,
        ultimoOk: dt(s.ultimo_ok), erro: (s.ultimo_erro || '').slice(0, 120)}; }),
  };
}
