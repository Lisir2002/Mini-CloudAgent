/**
 * Agent 循环引擎 —— 把"模型"和"沙箱手"串起来。
 * 流程:
 *   1. 用户消息 -> 流式调用模型
 *   2. 若模型产出 tool_call(execute_code) -> 通过控制面在沙箱执行
 *   3. 执行结果作为 tool 消息回传模型 -> 继续流式推理
 *   4. 直到模型不再调用工具(给出最终文本),或达到最大轮数
 *
 * 通过回调把每一帧文本/工具状态实时抛给 UI。
 */
import type { Message, ModelProfile, StreamEvent, ToolCall, ToolSpec } from '../types';
import { chatStream } from './modelClient';
import type { ControlClient } from './controlClient';

export const EXEC_TOOL: ToolSpec = {
  name: 'execute_code',
  description:
    '在隔离沙箱中执行代码并返回输出。用于数据分析、计算、脚本、调试等。' +
    '代码会真实运行,输出(stdout/stderr)会返回给你。',
  parameters: {
    type: 'object',
    properties: {
      language: {
        type: 'string',
        enum: ['python', 'shell', 'node'],
        description: '编程语言,默认 python',
      },
      code: { type: 'string', description: '要执行的完整代码' },
    },
    required: ['code'],
  },
};

export interface AgentCallbacks {
  onText: (text: string) => void;          // 模型文本增量
  onReasoning?: (text: string) => void;    // 思考增量
  onToolStart: (name: string, args: string) => void;
  onToolFrame: (stream: string, text: string) => void;
  onToolEnd: (output: string) => void;
  onError: (message: string) => void;
}

export interface AgentContext {
  profile: ModelProfile;
  control: ControlClient;
  sessionId: string;
  systemPrompt?: string;
}

/** 执行一轮完整 Agent 任务,返回最终文本。 */
export async function runAgent(
  ctx: AgentContext,
  history: Message[],
  userText: string,
  cb: AgentCallbacks,
  maxRounds = 8,
): Promise<string> {
  const messages: Message[] = [...history];
  if (ctx.systemPrompt && !messages.some((m) => m.role === 'system')) {
    messages.unshift({ role: 'system', content: ctx.systemPrompt });
  }
  messages.push({ role: 'user', content: userText });

  let finalText = '';

  for (let round = 0; round < maxRounds; round++) {
    const toolCalls: ToolCall[] = [];
    let assistantText = '';
    let reasoning = '';
    let stopped = false;

    // ---- 流式收集模型输出 ----
    for await (const ev of chatStream(ctx.profile, messages, [EXEC_TOOL])) {
      switch (ev.type) {
        case 'content':
          assistantText += ev.text;
          cb.onText(ev.text);
          break;
        case 'reasoning':
          reasoning += ev.text;
          cb.onReasoning?.(ev.text);
          break;
        case 'tool_call':
          toolCalls.push(ev.tool_call);
          break;
        case 'done':
          stopped = true;
          break;
        case 'error':
          cb.onError(ev.message);
          return assistantText || finalText;
      }
    }

    // 组装 assistant 消息(含工具调用)
    const assistantMsg: Message = {
      role: 'assistant',
      content: assistantText,
      ...(reasoning ? {} : {}),
    };
    if (toolCalls.length) assistantMsg.tool_calls = toolCalls;
    messages.push(assistantMsg);
    finalText = assistantText;

    // 无工具调用 -> 本轮结束
    if (!toolCalls.length) break;

    // ---- 逐个执行工具 ----
    for (const tc of toolCalls) {
      let args: any = {};
      try { args = tc.arguments ? JSON.parse(tc.arguments) : {}; } catch {}
      const language = args.language ?? 'python';
      const code = args.code ?? '';
      cb.onToolStart(tc.name, code);

      let output: string;
      try {
        output = await ctx.control.runCode(
          ctx.sessionId, code, language, cb.onToolFrame,
        );
      } catch (e: any) {
        output = `[沙箱执行失败] ${e?.message ?? e}`;
        cb.onError(output);
      }
      cb.onToolEnd(output);

      messages.push({
        role: 'tool',
        tool_call_id: tc.id,
        name: tc.name,
        content: output || '(无输出)',
      });
    }
    // 继续下一轮,让模型基于工具结果推理
  }

  return finalText;
}
