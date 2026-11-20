/** App 端共享类型。与后端 model_gateway / shared 协议保持字段一致。 */

export type Protocol = 'openai' | 'anthropic' | 'gemini';

export interface ModelProfile {
  id: string;
  label: string;
  protocol: Protocol;
  baseUrl: string;
  model: string;
  apiKey: string;          // 来自 SecureStore,内存中使用
  temperature: number;
  maxTokens: number;
}

export interface ControlConfig {
  url: string;             // ws://host:8000/ws/client
  userId: string;
}

// ---- 统一消息(与后端 types.py 对齐) ----
export interface ToolCall {
  id: string;
  name: string;
  arguments: string;       // JSON 字符串
}

export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

// ---- 统一流式事件 ----
export type StreamEvent =
  | { type: 'content'; text: string }
  | { type: 'reasoning'; text: string }
  | { type: 'tool_call'; tool_call: ToolCall }
  | { type: 'done'; usage?: Record<string, unknown> }
  | { type: 'error'; message: string };

// ---- 节点信息 ----
export interface NodeInfo {
  node_id: string;
  label: string;
  sessions: number;
  online: boolean;
  capabilities?: Record<string, unknown>;
}
