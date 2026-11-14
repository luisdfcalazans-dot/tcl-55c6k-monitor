import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// O build vai direto para docs/ (o GitHub Pages publica main:/docs): index.html na raiz e o JS/CSS em docs/app/.
// docs/data, docs/logos, docs/produtos e docs/fonts não são do build: no `npm run dev` o Vite os serve como
// pasta pública, e no build nada é copiado nem apagado ali (o script "build" só limpa docs/app).
export default defineConfig({
  plugins: [react()],
  base: './',
  publicDir: '../docs',
  build: {outDir: '../docs', emptyOutDir: false, assetsDir: 'app', copyPublicDir: false},
});
