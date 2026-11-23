export function validEmail(input: string): boolean {
  const email = input.trim();
  if (email.length > 254) return false;
  const [local, domain, extra] = email.split('@');
  if (extra !== undefined || !domain || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$/i.test(local)
    || local.startsWith('.') || local.endsWith('.') || local.includes('..')) return false;
  const labels = domain.split('.');
  return labels.length > 1 && labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))
    && /^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/i.test(labels.at(-1) || '');
}
