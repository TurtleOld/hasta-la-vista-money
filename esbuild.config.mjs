import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

const options = {
  entryPoints: {
    'app': 'frontend/js/app.js',
    'pages/dashboard': 'frontend/js/pages/dashboard.js',
    'pages/budget': 'frontend/js/pages/budget.js',
    'pages/receipts': 'frontend/js/pages/receipts.js',
    'pages/reports': 'frontend/js/pages/reports.js',
    'pages/receipt-update': 'frontend/js/pages/receipt-update.js',
    'pages/loan': 'frontend/js/pages/loan.js',
    'pages/profile': 'frontend/js/pages/profile.js',
  },
  bundle: true,
  format: 'iife',
  target: ['es2020'],
  outdir: 'static/js/dist',
  minify: !isWatch,
  sourcemap: isWatch,
  logLevel: 'info',
};

if (isWatch) {
  const context = await esbuild.context(options);
  await context.watch();
  console.log('Watching JS sources...');
} else {
  await esbuild.build(options);
}
