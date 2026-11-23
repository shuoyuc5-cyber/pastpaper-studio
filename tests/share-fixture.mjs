export const submissionCode = 'test-only-submission-code-0001';
export const moderationKey = 'test-only-moderation-key-0002';

// Text-layer fixture with a valid xref and no exam or personal material.
export function fixturePdf(text = 'Device fixture probability vector') {
  const lines = typeof text === 'string' ? [[40, 720, text]] : text;
  const stream = lines.map(([x, y, value]) => {
    if (!/^[a-zA-Z0-9 ._()[\]-]{1,120}$/.test(value)) throw new Error('Use simple ASCII fixture text.');
    const escaped = value.replace(/[()]/g, '\\$&');
    return `BT /F1 16 Tf ${x} ${y} Td (${escaped}) Tj ET\n`;
  }).join('');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}endstream`,
  ];
  let source = '%PDF-1.4\n';
  const offsets = objects.map((value, index) => {
    const offset = source.length;
    source += `${index + 1} 0 obj\n${value}\nendobj\n`;
    return offset;
  });
  const xref = source.length;
  return source + 'xref\n0 6\n0000000000 65535 f \n' + offsets.map(n => `${String(n).padStart(10,'0')} 00000 n \n`).join('') + `trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n${xref}\n%%EOF\n`;
}

export const fixtureQuestions = [
  [42, 710, '1'], [71, 710, 'Use the numbers in the table.'],
  [72, 657, '(a) Find the probability of a six.'], [530, 626, '[1]'],
  [72, 588, '(b) Work out the percentage.'], [530, 557, '[2]'],
  [72, 519, '(c) Calculate the area.'], [530, 486, '[4]'],
];

export function bindings(assets) {
  const store = new Map();
  const env = {
    SUBMISSION_CODE: submissionCode, MODERATION_KEY: moderationKey,
    SHARE_LIMIT: {limit: async () => ({success: true})}, ASSETS: {fetch: assets},
    SHARED_PAPERS: {
      async put(key, bytes, options) {
        if (options.onlyIf?.etagDoesNotMatch === '*' && store.has(key)) return null;
        const raw = new Uint8Array(bytes).slice();
        const value = {key, size: raw.length, customMetadata: options.customMetadata, arrayBuffer: async () => raw.slice().buffer};
        store.set(key, value); return value;
      },
      async get(key) {
        const value = store.get(key);
        return value ? {...value, body: await value.arrayBuffer()} : null;
      },
      async head(key) { return store.get(key) || null; },
      async delete(key) { store.delete(key); },
      async list({prefix, limit, cursor}) {
        const start = Number(cursor || 0);
        const all = [...store.values()].filter(value => value.key.startsWith(prefix));
        return {objects: all.slice(start, start + limit), truncated: start + limit < all.length, cursor: String(start + limit)};
      },
    },
  };
  return {env, store};
}
