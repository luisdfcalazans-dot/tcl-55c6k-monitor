// Botão de atualizar: dispara o workflow da coleta (monitor.yml) pela API do GitHub e espera a primeira coleta nova
// chegar ao site (data/latest_cloud.json com 'atualizado' depois do disparo).
// - O token é do próprio usuário (fine-grained, só este repositório, Actions: leitura e escrita) e fica só no
//   localStorage deste navegador; nunca vai no código da página, que é pública.
// - Dispara o laço normal (sem 'minutos'): a coleta roda na hora e o laço continua cobrindo a hora seguinte. Uma coleta
//   única ('minutos: 0') cancelaria o laço em andamento (concurrency cancel-in-progress) e deixaria o monitor parado.
// - O início da busca fica salvo: recarregar a página no meio continua esperando (até o prazo).
const REPO = 'luisdfcalazans-dot/tcl-55c6k-monitor', WORKFLOW = 'monitor.yml';
const API = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}`;
const PRAZO_MS = 20 * 60e3, INTERVALO_MS = 20e3;
export const CRIAR_TOKEN = 'https://github.com/settings/personal-access-tokens/new';

const ler = k => { try { return localStorage.getItem(k); } catch { return null; } };
const gravar = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sem storage */ } };
export const temToken = () => !!ler('gh_token');
export const guardaToken = t => gravar('gh_token', t.trim() || null);
// busca em andamento (iniciada nesta aba ou antes de recarregar), dentro do prazo
export const buscaPendente = () => { const t = Number(ler('busca_inicio')); return t && Date.now() - t < PRAZO_MS ? t : null; };

const cabecalhos = () => ({Authorization: `Bearer ${ler('gh_token')}`, Accept: 'application/vnd.github+json'});

// dispara o workflow; devolve o horário do disparo. Token recusado: apaga e avisa.
export async function dispara() {
  const inicio = Date.now();
  const r = await fetch(`${API}/dispatches`, {method: 'POST', headers: cabecalhos(), body: JSON.stringify({ref: 'main'})});
  if (r.status === 401 || r.status === 403 || r.status === 404) { guardaToken(''); throw new Error('O GitHub recusou o token. Clique de novo e cole outro.'); }
  if (!r.ok) throw new Error(`O GitHub não aceitou o disparo (${r.status}).`);
  gravar('busca_inicio', String(inicio));
  return inicio;
}

// espera a coleta nova chegar ao site; para antes se a execução falhar ou o prazo acabar
export async function espera(inicio) {
  try {
    while (Date.now() - inicio < PRAZO_MS) {
      await new Promise(r => setTimeout(r, INTERVALO_MS));
      const latest = await fetch('data/latest_cloud.json?t=' + Date.now()).then(r => r.ok ? r.json() : null).catch(() => null);
      if (latest && Date.parse(latest.atualizado) > inicio) return;
      const execucao = await fetch(`${API}/runs?event=workflow_dispatch&per_page=1`, {headers: cabecalhos()})
        .then(r => r.ok ? r.json() : null).catch(() => null);
      const ultima = execucao?.workflow_runs?.[0];
      if (ultima && Date.parse(ultima.created_at) >= inicio - 60e3 && ultima.status === 'completed' && ultima.conclusion !== 'success')
        throw new Error(`A coleta terminou com erro (${ultima.conclusion}).`);
    }
    throw new Error('A coleta não chegou em 20 minutos. Confira a aba Actions do GitHub.');
  } finally { gravar('busca_inicio', null); }
}
