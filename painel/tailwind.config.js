// Tokens do Tremor ligados às variáveis CSS do encarte (src/estilo.css). As variáveis trocam com o tema (classe .dark no
// <html>), então 'tremor' e 'dark-tremor' apontam para as mesmas variáveis e o componente nunca fica com a cor errada.
// Estrutura do open-design (design-systems/dashboard): escala 12/14/16/20/24/32, grade de 8 pt, raio único e foco visível.
// as variáveis guardam os canais ("20 33 61") para o Tailwind aplicar opacidade (bg-opacity-40, /60) nos dois temas
const v = n => `rgb(var(--${n}) / <alpha-value>)`;
const tremor = {
  brand: {faint: v('accent-soft'), muted: v('accent-soft'), subtle: v('accent'), DEFAULT: v('accent'), emphasis: v('ink'), inverted: v('surface')},
  background: {muted: v('mute-bg'), subtle: v('line-2'), DEFAULT: v('surface'), emphasis: v('ink-2')},
  border: {DEFAULT: v('line')},
  ring: {DEFAULT: v('line')},
  content: {subtle: v('ink-3'), DEFAULT: v('ink-2'), emphasis: v('ink'), strong: v('ink'), inverted: v('surface')},
};

/** @type {import('tailwindcss').Config} */
export default {
  // só as pastas do Tremor que o painel importa (src/tremor.js): cartões, tabelas, acordeão e textos
  content: ['./index.html', './src/**/*.{js,jsx}', './node_modules/@tremor/react/dist/components/{layout-elements,list-elements,text-elements}/**/*.js'],
  darkMode: 'class',
  theme: {
    transparent: 'transparent',
    current: 'currentColor',
    extend: {
      colors: {
        tremor, 'dark-tremor': tremor,
        band: v('band'), 'band-ink': v('band-ink'), 'band-ink-2': v('band-ink-2'),
        fundo: v('bg'), superficie: v('surface'), tinta: v('ink'), 'tinta-2': v('ink-2'), 'tinta-3': v('ink-3'),
        linha: v('line'), 'linha-2': v('line-2'), 'linha-forte': v('line-forte'),
        etiqueta: v('tag'), 'etiqueta-ink': v('tag-ink'), destaque: v('accent'), 'destaque-suave': v('accent-soft'),
        ok: v('ok'), 'ok-bg': v('ok-bg'), warn: v('warn'), 'warn-bg': v('warn-bg'), bad: v('bad'), 'bad-bg': v('bad-bg'),
        mudo: v('mute-bg'), m55: v('m55'), 'm55-bg': v('m55-bg'), m65: v('m65'), 'm65-bg': v('m65-bg'),
      },
      fontFamily: {
        sans: ['D-DIN', '"Segoe UI"', 'system-ui', 'sans-serif'],
        cond: ['"D-DIN Condensed"', '"Arial Narrow"', 'sans-serif'],
      },
      boxShadow: {'tremor-input': 'none', 'tremor-card': 'none', 'tremor-dropdown': '0 4px 12px rgb(0 0 0 / 0.12)',
        'dark-tremor-input': 'none', 'dark-tremor-card': 'none', 'dark-tremor-dropdown': '0 4px 12px rgb(0 0 0 / 0.4)'},
      borderRadius: {'tremor-small': '3px', 'tremor-default': '4px', 'tremor-full': '9999px'},
      // escala do painel (open-design): xs 12 · sm 14 · base 16 · xl 20 · 2xl 24 · 3xl 32; fora dela, só o título do app e
      // a etiqueta de preço, que são fluidos (clamp)
      fontSize: {
        '3xl': ['2rem', {lineHeight: '2.25rem'}],
        'tremor-label': ['0.75rem', {lineHeight: '1rem'}],
        'tremor-default': ['0.875rem', {lineHeight: '1.25rem'}],
        'tremor-title': ['1.25rem', {lineHeight: '1.75rem'}],
        'tremor-metric': ['2rem', {lineHeight: '2.25rem'}],
      },
    },
  },
};
