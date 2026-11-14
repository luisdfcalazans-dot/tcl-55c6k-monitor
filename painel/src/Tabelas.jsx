// Aba "Tabelas": as TVs (escondidas com "tvs_desligadas" no latest) e uma seção por família (PS5, GTA 6) com o resumo
// por produto, o gift card e o custo final do GTA 6, e a tabela e o gráfico de cada produto num acordeão.
import {Accordion, AccordionBody, AccordionHeader, AccordionList, TableCell, TableRow} from '@tremor/react';
import {Abrir, Chip, Fato, GraficoHistorico, H2, H3, Lista, Nota, Postagem, Sub, Tabela, TabelaLojas} from './componentes.jsx';

export default function Tabelas({vm, familia}) {
  return <>
    {vm.tvs && (!familia || familia === 'TV') && <TVs tvs={vm.tvs} />}
    {vm.familias.filter(f => !familia || f.sec === familia).map(f => <Familia key={f.sec} f={f} />)}
  </>;
}

const Grade = ({cols, children}) => <div className={`grid grid-cols-2 gap-2 ${cols}`}>{children}</div>;

function TVs({tvs}) {
  const {alvos, modelos: {'55C6K': m55, '65C6K': m65}, dif} = tvs;
  const Cel = ({c}) => !c ? '—' : <><b className="text-tinta">{c.v}</b>{c.subs.map((s, i) => <Sub key={i}>{s}</Sub>)}{c.velho && <> <Chip tipo="warn">antigo</Chip></>}</>;
  return <>
    <p className="mb-4 mt-6 max-w-[72ch] text-[15px] text-tinta-2">TVs QD-Mini LED. Alvos da 55C6K: Pix {alvos['55C6K'].pix} · parcelado {alvos['55C6K'].parcelado}.
      Alvos da 65C6K: Pix {alvos['65C6K'].pix} · parcelado {alvos['65C6K'].parcelado}.</p>
    <H3><Chip tipo="m55">55"</Chip> TCL 55C6K</H3>
    <Grade cols="md:grid-cols-3">
      <Fato k="Melhor à vista agora" d={m55.destaques.melhor} /><Fato k="Melhor parcelado agora" d={m55.destaques.parc} /><Fato k="Menor já visto" d={m55.destaques.min} />
    </Grade>
    <H3><Chip tipo="m65">65"</Chip> TCL 65C6K</H3>
    <Grade cols="md:grid-cols-5">
      <Fato k="Melhor à vista agora" d={m65.destaques.melhor} /><Fato k="Melhor parcelado agora" d={m65.destaques.parc} /><Fato k="Menor já visto" d={m65.destaques.min} />
      <Fato k='65" a mais · à vista' d={dif.pix} /><Fato k='65" a mais · parcelado' d={dif.parc} />
    </Grade>

    <H2>55" × 65" por loja</H2>
    <Tabela cab={['Loja', '55" à vista', '65" à vista', '65" a mais · à vista', '55" parcelado (total)', '65" parcelado (total)', '65" a mais · parcelado']}>
      {tvs.comparar.length ? tvs.comparar.map(l => (
        <TableRow key={l.loja}><TableCell><b className="text-tinta">{l.loja}</b></TableCell>
          {l.celulas.map((c, i) => <TableCell key={i} className={i % 3 === 2 ? 'bg-mudo font-bold text-tinta' : ''}>{i % 3 === 2 ? c : <Cel c={c} />}</TableCell>)}
        </TableRow>))
        : <TableRow><TableCell colSpan={7} className="text-tinta-3">Nenhum preço de loja ainda.</TableCell></TableRow>}
    </Tabela>
    <Nota>Menor preço de cada TV na mesma loja (Pix/à vista e total do parcelamento), entre as coletas recentes; a diferença é quanto a 65" custa a mais que a 55" ali.</Nota>

    {[['55C6K', m55], ['65C6K', m65]].map(([id, m]) => <div key={id}>
      <H2>Ofertas da {id}</H2>
      <TabelaLojas linhas={m.linhas} vazio={`Nenhum preço de loja da ${id} ainda.`} />
      <H2>Histórico da {id}</H2>
      <div className="rounded-[3px] border-2 border-linha bg-superficie p-3"><GraficoHistorico serie={m.serie} alvo={m.alvo} /></div>
    </div>)}
  </>;
}

function Familia({f}) {
  return <section aria-labelledby={`sec-${f.sec}`}>
    <H2 id={`sec-${f.sec}`}>{f.titulo}</H2>
    <Tabela cab={['Produto', 'Meta à vista', 'Melhor à vista agora', 'Melhor parcelado agora', 'Menor já visto', 'Distância da meta']}>
      {f.resumo.map(r => (
        <TableRow key={r.id}>
          <TableCell className="whitespace-normal"><b className="text-tinta">{r.nome}</b><Sub>{r.sub}</Sub></TableCell>
          <TableCell>{r.meta.v}{r.meta.subs.map((s, i) => <Sub key={i}>{s}</Sub>)}</TableCell>
          <TableCell><b className="text-tinta">{r.melhor.v}</b><Sub>{r.melhor.sub}</Sub></TableCell>
          <TableCell><b className="text-tinta">{r.parc.v}</b><Sub>{r.parc.sub}</Sub></TableCell>
          <TableCell>{r.min.v}<Sub>{r.min.sub}</Sub></TableCell>
          <TableCell className={r.dist.ok ? 'text-ok' : ''}>{r.dist.v}</TableCell>
        </TableRow>))}
    </Tabela>
    <Nota>Metas aprovadas em 03/10 (Pix / total parcelado sem juros). Kit e edição especial: meta do console-base mais o valor do extra; gift card: 15% de desconto ou mais em loja oficial, em cartão de R$ 100 ou mais (10% de 01/11 a 11/11, perto do prazo da pré-venda).</Nota>
    {f.gift && <Gift g={f.gift} />}
    {f.custoFinal && <CustoFinal cf={f.custoFinal} />}
    {f.produtos.length > 0 && <AccordionList className="mt-4 rounded-[3px] ring-2">
      {f.produtos.map(p => (
        <Accordion key={p.id} id={`prod-${p.id}`}>
          <AccordionHeader className="px-3.5 py-2.5 text-left font-bold text-tinta">{p.nome}<span className="ml-2 font-normal text-tinta-3">{p.sub}</span></AccordionHeader>
          <AccordionBody className="px-2.5 pb-2.5">
            <TabelaLojas linhas={p.linhas} vazio="Nenhum preço de loja ainda." />
            {p.grafico && <div className="mt-2"><GraficoHistorico serie={p.grafico.serie} alvo={p.grafico.alvo} altura="h-64" /></div>}
          </AccordionBody>
        </Accordion>))}
    </AccordionList>}
    <H3>Últimas postagens · {f.titulo}</H3>
    <Lista vazio="Nenhuma postagem registrada.">{f.posts.map(p => <Postagem key={p.chave} p={p} />)}</Lista>
  </section>;
}

function Gift({g}) {
  const {regra, melhor: m} = g;
  return <>
    <H3>Gift card PlayStation · pagar o GTA 6 digital na PS Store</H3>
    {!m ? <Nota>Nenhum gift card com desconto em loja oficial agora (PS Store, Hype, Nuuvem, loja oficial PlayStation no Mercado Livre, ou vendido pela própria KaBuM, Americanas, Amazon ou Magalu). Meta: {regra.meta} de desconto ou mais; comprar e resgatar até {regra.prazo}.</Nota>
      : <>
        <p className="mb-4 max-w-[72ch] text-[15px] text-tinta-2">Melhor agora: <b className="text-tinta">{m.preco}</b> pelo cartão de <b className="text-tinta">{m.face}</b> ({m.desconto} de desconto) · {m.loja}
          {m.post && ' · postagem'}{m.cupom && <> · cupom <code>{m.cupom}</code></>}{m.url && <> · <Abrir url={m.url} /></>}{m.naMeta && <> <Chip tipo="ok">na meta</Chip></>}</p>
        {g.gta.length > 0 && <Tabela cab={['GTA 6 digital', 'PS Store', 'Pagando com gift card', `Meta (${regra.minimo})`, 'Cartões']}>
          {g.gta.map(x => <TableRow key={x.edicao}>
            <TableCell><b className="text-tinta">{x.edicao}</b></TableCell><TableCell>{x.psstore}</TableCell>
            <TableCell className={x.ok ? 'text-ok' : ''}><b>{x.custo}</b><Sub>{x.economia}</Sub></TableCell>
            <TableCell>{x.meta}<Sub>{x.faixas}</Sub></TableCell><TableCell className="whitespace-normal">{x.cartoes}</TableCell>
          </TableRow>)}
        </Tabela>}
        {g.cartoes.length > 0 && <Tabela className="mt-2" cab={['Loja', 'Valor de face', 'Preço', 'Desconto', '']}>
          {g.cartoes.map((c, i) => <TableRow key={i}>
            <TableCell><b className="text-tinta">{c.loja}</b>{c.post && <Sub>postagem</Sub>}</TableCell><TableCell>{c.face}</TableCell>
            <TableCell><b className="text-tinta">{c.preco}</b></TableCell><TableCell className={c.naMeta ? 'text-ok' : ''}>{c.desconto}</TableCell>
            <TableCell><Abrir url={c.url} /></TableCell>
          </TableRow>)}
        </Tabela>}
        <Nota>Só cartão [Exclusivo Brasil] de loja oficial. O saldo da carteira é usado primeiro e o resto vai para o cartão de crédito; a Sony tem um limite de saldo que não divulga (a conta não passa de R$ 700). Meta: {regra.meta} de desconto ou mais (🔥 a partir de {regra.excelente}). Para jogar no lançamento: comprar e resgatar o cartão e fazer a pré-venda até {regra.prazo} (pré-carregamento a partir de 12/11).</Nota>
      </>}
  </>;
}

function CustoFinal({cf}) {
  const T = ({rs}) => <Tabela cab={['Forma', 'Loja', 'Custo final', 'Meta', 'Entrega', '']}>
    {rs.map((r, i) => <TableRow key={i}>
      <TableCell className="whitespace-normal">{r.forma}</TableCell><TableCell>{r.loja}<Sub>{r.tipo}</Sub></TableCell>
      <TableCell><b className="text-tinta">{r.custo}</b><Sub>{r.detalhe}</Sub></TableCell>
      <TableCell className={r.ok ? 'text-ok' : ''}>{r.meta}</TableCell>
      <TableCell>{r.entrega ? <Chip tipo={r.entrega.classe} title={r.entrega.titulo}>{r.entrega.rotulo}</Chip> : '—'}</TableCell>
      <TableCell><Abrir url={r.url} /></TableCell>
    </TableRow>)}
  </Tabela>;
  return <>
    <H3>Todas as formas pelo custo final</H3>
    <H3>Edição Standard <span className="font-normal text-tinta-3">Code in Box e digital</span></H3>
    {cf.std.length ? <T rs={cf.std} /> : <Nota>Nenhuma oferta da Standard agora.</Nota>}
    <H3>Edição Ultimate <span className="font-normal text-tinta-3">só digital no Brasil; ou a Standard + upgrade de R$ 100 na PS Store</span></H3>
    {cf.nota && <Nota>{cf.nota}</Nota>}
    {cf.ult.length ? <T rs={cf.ult} /> : <Nota>Sem preço da Ultimate agora.</Nota>}
  </>;
}
