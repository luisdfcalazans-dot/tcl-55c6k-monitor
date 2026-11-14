// Só as peças do Tremor que o painel usa (cartões, tabelas, acordeão), importadas pelo caminho de cada componente:
// o @tremor/react não declara "sideEffects": false, então importar do índice levaria junto o Recharts (~200 kB gzip)
// que nenhum gráfico daqui usa (os gráficos são uPlot e SVG). Ao atualizar o Tremor, confira se os caminhos continuam.
export {default as Card} from '@tremor/react/dist/components/layout-elements/Card/Card.js';
export {default as Accordion} from '@tremor/react/dist/components/layout-elements/Accordion/Accordion.js';
export {default as AccordionBody} from '@tremor/react/dist/components/layout-elements/Accordion/AccordionBody.js';
export {default as AccordionHeader} from '@tremor/react/dist/components/layout-elements/Accordion/AccordionHeader.js';
export {default as AccordionList} from '@tremor/react/dist/components/layout-elements/Accordion/AccordionList.js';
export {default as Table} from '@tremor/react/dist/components/list-elements/Table/Table.js';
export {default as TableBody} from '@tremor/react/dist/components/list-elements/Table/TableBody.js';
export {default as TableCell} from '@tremor/react/dist/components/list-elements/Table/TableCell.js';
export {default as TableHead} from '@tremor/react/dist/components/list-elements/Table/TableHead.js';
export {default as TableHeaderCell} from '@tremor/react/dist/components/list-elements/Table/TableHeaderCell.js';
export {default as TableRow} from '@tremor/react/dist/components/list-elements/Table/TableRow.js';
export {default as Metric} from '@tremor/react/dist/components/text-elements/Metric/Metric.js';
export {default as Text} from '@tremor/react/dist/components/text-elements/Text/Text.js';
