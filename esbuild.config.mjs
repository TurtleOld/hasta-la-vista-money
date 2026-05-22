import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

const options = {
  entryPoints: ['frontend/js/app.js'],
  bundle: true,
  format: 'iife',
  target: ['es2020'],
  outfile: 'static/js/dist/app.js',
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
