const adapters = {
  ollama: {
    models: '/api/tags', run: '/api/generate',
    list: value => value.models?.filter(model => !model.remote_host && !model.remote_model).map(model => model.name),
    body: (model, prompt) => ({model, prompt, stream: false}),
    answer: value => value.response,
  },
  lmstudio: {
    models: '/v1/models', run: '/v1/chat/completions',
    list: value => value.data?.map(model => model.id),
    body: (model, prompt) => ({model, messages: [{role: 'user', content: prompt}], stream: false}),
    answer: value => value.choices?.[0]?.message?.content,
  },
};

export function runtime(provider, port, token) {
  if (!Object.hasOwn(adapters, provider) || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('请选择提供方并输入有效端口。');
  if (provider === 'lmstudio' && token && !/^[\x21-\x7e]{1,512}$/.test(token)) throw new Error('本机运行时令牌格式无效。');
  const adapter = adapters[provider], origin = `http://127.0.0.1:${port}`;
  const auth = provider === 'lmstudio' && token ? {Authorization: `Bearer ${token}`} : {};
  async function request(path, body, signal) {
    let response;
    try {
      response = await fetch(origin + path, {
        method: body ? 'POST' : 'GET', body: body && JSON.stringify(body),
        headers: body ? {...auth, 'Content-Type': 'application/json'} : auth,
        redirect: 'error', credentials: 'omit', cache: 'no-store', signal,
      });
    } catch (error) {
      if (signal?.aborted) throw new Error('请求已停止或超时。');
      throw new Error('无法连接本机运行时。请确认服务正在运行，并允许本站来源及浏览器的本地网络访问。');
    }
    if (response.status === 401 || response.status === 403) throw new Error('运行时拒绝授权。请核对本机令牌和允许的来源。');
    if (response.status === 429) throw new Error('运行时请求过多，请稍后再试。');
    if (!response.ok) throw new Error(`运行时请求失败（${response.status}）。请核对模型是否可用。`);
    const reader = response.body?.getReader();
    if (!reader) throw new Error('运行时返回空响应。');
    const decoder = new TextDecoder();
    let size = 0, text = '';
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 1024 * 1024) { await reader.cancel(); throw new Error('运行时响应过大。'); }
        text += decoder.decode(value, {stream: true});
      }
      return JSON.parse(text + decoder.decode());
    } catch { throw new Error(signal?.aborted ? '请求已停止或超时。' : '运行时返回了无效或过大的响应。'); }
    finally { reader.releaseLock(); }
  }
  return {
    origin,
    async models(signal) {
      const names = adapter.list(await request(adapter.models, undefined, signal));
      if (!Array.isArray(names)) throw new Error('无法读取模型列表。');
      return [...new Set(names.filter(name => typeof name === 'string' && name.length <= 200 && !/(?:[:@-]cloud)(?:$|[:@-])/i.test(name)))].slice(0, 100);
    },
    async generate(model, prompt, signal) {
      const text = adapter.answer(await request(adapter.run, adapter.body(model, prompt), signal));
      if (typeof text !== 'string' || !text.trim()) throw new Error('模型没有返回可显示的文字。');
      return text.slice(0, 32000);
    },
  };
}
