import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

const options = {
  entryPoints: {
    app: 'static/js/app.js',
    'pages/dashboard': 'static/js/pages/dashboard.js',
    'pages/budget': 'static/js/pages/budget.js',
    'pages/receipts': 'static/js/pages/receipts.js',
    'pages/reports': 'static/js/pages/reports.js',
    'pages/receipt-update': 'static/js/pages/receipt-update.js',
    'pages/receipt-qr-scan': 'static/js/pages/receipt-qr-scan.js',
    'pages/loan': 'static/js/pages/loan.js',
    'pages/profile': 'static/js/pages/profile.js',
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
