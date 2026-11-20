/**
 * App 端多协议模型客户端 —— 自研,与后端 model_gateway 对齐。
 * 支持 OpenAI / Anthropic / Gemini 三种协议的流式调用,
 * 统一产出 StreamEvent;上层对话引擎只认统一事件。
 *
 * 三个协议差异(请求格式、SSE 事件、工具参数累积)在这里全部抹平。
 */
import type { Message, ModelProfile, StreamEvent, ToolCall, ToolSpec } from '../types';

interface Adapter {
  build(profile: ModelProfile, messages: Message[], tools: ToolSpec[] | undefined, stream: boolean):
    { url: string; headers: Record<string, string>; body: any };
  parseLine(line: string, state: Record<string, any>, eventName: string): StreamEvent[];
}

// ---------------- OpenAI ----------------
const openaiAdapter: Adapter = {
  build(p, messages, tools, stream) {
    let base = p.baseUrl.replace(/\/+$/, '');
    const url = base.endsWith('/chat/completions') ? base : `${base}/chat/completions`;
    const msgs = messages.map((m) => {
      const d: any = { role: m.role, content: m.content };
      if (m.role === 'tool') {
        d.tool_call_id = m.tool_call_id;
        if (m.name) d.name = m.name;
      }
      if (m.tool_calls) {
        d.tool_calls = m.tool_calls.map((tc) => ({
          id: tc.id, type: 'function',
          function: { name: tc.name, arguments: tc.arguments },
        }));
      }
      return d;
    });
    const body: any = {
      model: p.model, messages: msgs, temperature: p.temperature,
      max_tokens: p.maxTokens, stream,
    };
    if (tools?.length) {
      body.tools = tools.map((t) => ({
        type: 'function',
        function: { name: t.name, description: t.description, parameters: t.parameters },
      }));
    }
    return {
      url,
      headers: { Authorization: `Bearer ${p.apiKey}`, 'Content-Type': 'application/json' },
      body,
    };
  },
  parseLine(line, state) {
    const events: StreamEvent[] = [];
    let chunk: any;
    try { chunk = JSON.parse(line); } catch { return events; }
    for (const choice of chunk.choices ?? []) {
      const delta = choice.delta ?? {};
      if (delta.content) events.push({ type: 'content', text: delta.content });
      if (delta.reasoning_content) events.push({ type: 'reasoning', text: delta.reasoning_content });
      for (const tc of delta.tool_calls ?? []) {
        const idx = tc.index ?? 0;
        const slot = state[`tc_${idx}`] ??= { id: '', name: '', arguments: '' };
        if (tc.id) slot.id = tc.id;
        const fn = tc.function ?? {};
        if (fn.name) slot.name += fn.name;
        if (fn.arguments) slot.arguments += fn.arguments;
      }
      if (choice.finish_reason === 'tool_calls') {
        for (const tc of Object.values(state) as any[]) {
          events.push({ type: 'tool_call', tool_call: { id: tc.id, name: tc.name, arguments: tc.arguments } });
        }
        for (const k of Object.keys(state)) delete state[k];
      }
    }
    if (chunk.usage) events.push({ type: 'done', usage: chunk.usage });
    return events;
  },
};

// ---------------- Anthropic ----------------
const anthropicAdapter: Adapter = {
  build(p, messages, tools, stream) {
    let base = p.baseUrl.replace(/\/+$/, '');
    const url = base.endsWith('/messages') ? base : `${base}/messages`;
    const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
    const msgs: any[] = [];
    for (const m of messages) {
      if (m.role === 'system') continue;
      if (m.role === 'tool') {
        msgs.push({ role: 'user', content: [{ type: 'tool_result', tool_use_id: m.tool_call_id, content: m.content }] });
      } else if (m.role === 'assistant' && m.tool_calls?.length) {
        const blocks: any[] = [];
        if (m.content) blocks.push({ type: 'text', text: m.content });
        for (const tc of m.tool_calls) {
          let input = {};
          try { input = tc.arguments ? JSON.parse(tc.arguments) : {}; } catch {}
          blocks.push({ type: 'tool_use', id: tc.id, name: tc.name, input });
        }
        msgs.push({ role: 'assistant', content: blocks });
      } else {
        msgs.push({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content });
      }
    }
    const body: any = {
      model: p.model, max_tokens: p.maxTokens, temperature: p.temperature,
      system, messages: msgs, stream,
    };
    if (tools?.length) {
      body.tools = tools.map((t) => ({
        name: t.name, description: t.description, input_schema: t.parameters,
      }));
    }
    return {
      url,
      headers: {
        'x-api-key': p.apiKey,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json',
      },
      body,
    };
  },
  parseLine(line, state, eventName) {
    const events: StreamEvent[] = [];
    let chunk: any;
    try { chunk = JSON.parse(line); } catch { return events; }
    const etype = eventName || chunk.type;
    if (etype === 'content_block_start') {
      const block = chunk.content_block ?? {};
      const idx = chunk.index ?? 0;
      if (block.type === 'tool_use') {
        state[`tool_${idx}`] = { id: block.id ?? '', name: block.name ?? '', arguments: '' };
      }
    } else if (etype === 'content_block_delta') {
      const delta = chunk.delta ?? {};
      if (delta.type === 'text_delta') events.push({ type: 'content', text: delta.text ?? '' });
      else if (delta.type === 'input_json_delta') {
        const idx = chunk.index ?? 0;
        const slot = state[`tool_${idx}`] ??= { id: '', name: '', arguments: '' };
        slot.arguments += delta.partial_json ?? '';
      }
    } else if (etype === 'content_block_stop') {
      const idx = chunk.index ?? 0;
      const slot = state[`tool_${idx}`];
      if (slot) {
        events.push({ type: 'tool_call', tool_call: { id: slot.id, name: slot.name, arguments: slot.arguments } });
        delete state[`tool_${idx}`];
      }
    } else if (etype === 'message_delta' && chunk.usage) {
      events.push({ type: 'done', usage: chunk.usage });
    } else if (etype === 'message_stop') {
      events.push({ type: 'done' });
    }
    return events;
  },
};

// ---------------- Gemini ----------------
const geminiAdapter: Adapter = {
  build(p, messages, tools, stream) {
    let base = p.baseUrl.replace(/\/+$/, '');
    if (!base.includes('/models/')) base = `${base}/models`;
    const model = encodeURIComponent(p.model);
    const method = stream ? 'streamGenerateContent' : 'generateContent';
    const url = `${base}/${model}:${method}?alt=sse&key=${encodeURIComponent(p.apiKey)}`;
    const contents: any[] = [];
    for (const m of messages) {
      if (m.role === 'system') continue;
      if (m.role === 'tool') {
        let resp: any = {};
        try { resp = m.content ? JSON.parse(m.content) : {}; } catch { resp = { result: m.content }; }
        contents.push({ role: 'user', parts: [{ functionResponse: { name: m.name, response: resp } }] });
      } else if (m.tool_calls?.length) {
        const parts: any[] = [];
        if (m.content) parts.push({ text: m.content });
        for (const tc of m.tool_calls) {
          let args = {};
          try { args = tc.arguments ? JSON.parse(tc.arguments) : {}; } catch {}
          parts.push({ functionCall: { name: tc.name, args } });
        }
        contents.push({ role: 'model', parts });
      } else {
        contents.push({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] });
      }
    }
    const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
    const body: any = {
      contents,
      generationConfig: { temperature: p.temperature, maxOutputTokens: p.maxTokens },
    };
    if (system) body.systemInstruction = { parts: [{ text: system }] };
    if (tools?.length) {
      body.tools = [{ functionDeclarations: tools.map((t) => ({
        name: t.name, description: t.description, parameters: t.parameters,
      })) }];
    }
    return { url, headers: { 'Content-Type': 'application/json' }, body };
  },
  parseLine(line) {
    const events: StreamEvent[] = [];
    let chunk: any;
    try { chunk = JSON.parse(line); } catch { return events; }
    for (const cand of chunk.candidates ?? []) {
      for (const part of cand.content?.parts ?? []) {
        if (part.text) events.push({ type: 'content', text: part.text });
        if (part.functionCall) {
          const fc = part.functionCall;
          events.push({
            type: 'tool_call',
            tool_call: {
              id: fc.id ?? '', name: fc.name ?? '',
              arguments: JSON.stringify(fc.args ?? {}),
            },
          });
        }
      }
    }
    if (chunk.usageMetadata) events.push({ type: 'done', usage: chunk.usageMetadata });
    return events;
  },
};

const ADAPTERS: Record<string, Adapter> = {
  openai: openaiAdapter,
  anthropic: anthropicAdapter,
  gemini: geminiAdapter,
};

/** 流式对话:逐帧产出统一事件。 */
export async function* chatStream(
  profile: ModelProfile,
  messages: Message[],
  tools?: ToolSpec[],
): AsyncGenerator<StreamEvent> {
  const adapter = ADAPTERS[profile.protocol] ?? openaiAdapter;
  const { url, headers, body } = adapter.build(profile, messages, tools, true);

  let resp: Response;
  try {
    resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  } catch (e: any) {
    yield { type: 'error', message: `网络错误: ${e?.message ?? e}` };
    return;
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    yield { type: 'error', message: `HTTP ${resp.status}: ${text.slice(0, 300)}` };
    return;
  }
  if (!resp.body) {
    yield { type: 'error', message: '响应无流式 body' };
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const state: Record<string, any> = {};
  let buffer = '';
  let eventName = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE 以空行分帧
      let cut: number;
      while ((cut = buffer.indexOf('\n')) >= 0) {
        let line = buffer.slice(0, cut).replace(/\r$/, '');
        buffer = buffer.slice(cut + 1);
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
          continue;
        }
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (!data || data === '[DONE]') {
          if (data === '[DONE]') yield { type: 'done' };
          eventName = '';
          continue;
        }
        for (const ev of adapter.parseLine(data, state, eventName)) yield ev;
        eventName = '';
      }
    }
  } catch (e: any) {
    yield { type: 'error', message: `流读取失败: ${e?.message ?? e}` };
  }
}

/** 非流式对话(兜底),返回完整文本与工具调用。 */
export async function chatOnce(
  profile: ModelProfile, messages: Message[], tools?: ToolSpec[],
): Promise<{ content: string; toolCalls: ToolCall[]; error?: string }> {
  const adapter = ADAPTERS[profile.protocol] ?? openaiAdapter;
  const { url, headers, body } = adapter.build(profile, messages, tools, false);
  try {
    const resp = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      return { content: '', toolCalls: [], error: `HTTP ${resp.status}: ${text.slice(0, 300)}` };
    }
    const data: any = await resp.json();
    if (profile.protocol === 'openai') {
      const msg = data.choices?.[0]?.message ?? {};
      return {
        content: msg.content ?? '',
        toolCalls: (msg.tool_calls ?? []).map((tc: any) => ({
          id: tc.id ?? '', name: tc.function?.name ?? '', arguments: tc.function?.arguments ?? '{}',
        })),
      };
    }
    if (profile.protocol === 'anthropic') {
      const blocks = data.content ?? [];
      const text = blocks.filter((b: any) => b.type === 'text').map((b: any) => b.text).join('');
      const toolCalls = blocks.filter((b: any) => b.type === 'tool_use').map((b: any) => ({
        id: b.id ?? '', name: b.name ?? '', arguments: JSON.stringify(b.input ?? {}),
      }));
      return { content: text, toolCalls };
    }
    // gemini
    const parts = data.candidates?.[0]?.content?.parts ?? [];
    const text = parts.filter((p: any) => p.text).map((p: any) => p.text).join('');
    const toolCalls = parts.filter((p: any) => p.functionCall).map((p: any) => ({
      id: p.functionCall.id ?? '', name: p.functionCall.name ?? '',
      arguments: JSON.stringify(p.functionCall.args ?? {}),
    }));
    return { content: text, toolCalls };
  } catch (e: any) {
    return { content: '', toolCalls: [], error: e?.message ?? String(e) };
  }
}
