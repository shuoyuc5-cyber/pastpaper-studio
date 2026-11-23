import {copyFile, cp, mkdir} from 'node:fs/promises';

const base = new URL('../', import.meta.url);
const destination = new URL('public/device/pdf-engine/', base);
await mkdir(destination, {recursive: true});
for (const name of ['pdf.min.mjs', 'pdf.worker.min.mjs']) {
  await copyFile(new URL(`node_modules/pdfjs-dist/legacy/build/${name}`, base), new URL(name, destination));
}
await copyFile(new URL('node_modules/pdfjs-dist/LICENSE', base), new URL('LICENSE.txt', destination));
await cp(new URL('node_modules/pdfjs-dist/standard_fonts/', base), new URL('standard-fonts/', destination), {recursive: true});
