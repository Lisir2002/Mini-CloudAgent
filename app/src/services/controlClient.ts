/**
 * 控制面 WebSocket 客户端。
 * App 连 /ws/client,通过控制面把任务转发给节点Agent(手)。
 * 协议与后端 shared/protocol.py 一致(JSON-RPC 2.0)。
 */
import type { ControlConfig, NodeInfo } from '../types';
import { newId } from './rpc';

type Pending = {
  resolve: (v: any) => void;
  reject: (e: any) => void;
  onStream?: (params: any) => void;
  timer: ReturnType<typeof setTimeout>;
};

export class ControlClient {
  private ws: WebSocket | null = null;
  private pending = new Map<string, Pending>();
  private helloDone = false;
  private cfg: ControlConfig;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  onStatus?: (status: 'connecting' | 'online' | 'offline') => void;

  constructor(cfg: ControlConfig) {
    this.cfg = cfg;
  }

  get connected() {
    return this.helloDone && this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    this.intentionalClose = false;
    return new Promise((resolve, reject) => {
      let settled = false;
      try {
        const ws = new WebSocket(this.cfg.url);
        this.ws = ws;
        this.onStatus?.('connecting');

        ws.onopen = () => {
          // 首帧 hello
          this._sendRaw({
            jsonrpc: '2.0', id: 'hello', method: 'client.hello',
            params: { user_id: this.cfg.userId },
          });
        };

        ws.onmessage = (ev) => {
          let msg: any;
          try { msg = JSON.parse(ev.data); } catch { return; }
          this._handle(msg, () => { if (!settled) { settled = true; resolve(); } });
        };

        ws.onerror = () => {
          if (!settled) { settled = true; reject(new Error('WebSocket 连接错误')); }
        };

        ws.onclose = () => {
          this.helloDone = false;
          this.onStatus?.('offline');
          // 拒绝所有等待中的请求
          for (const [, p] of this.pending) {
            clearTimeout(p.timer);
            p.reject(new Error('连接已断开'));
          }
          this.pending.clear();
          if (!this.intentionalClose) this._scheduleReconnect();
        };
      } catch (e) {
        reject(e);
      }
    });
  }

  private _handle(msg: any, onHello: () => void) {
    // hello 响应
    if (msg.id === 'hello' && msg.result) {
      this.helloDone = true;
      this.onStatus?.('online');
      onHello();
      return;
    }
    // 流式通知:无 id,有 method
    if (!msg.id && msg.method) {
      const assoc = msg.params?.task_id ?? msg.params?.request_id;
      if (assoc && this.pending.has(assoc)) {
        this.pending.get(assoc)!.onStream?.(msg.params);
      }
      return;
    }
    // 请求响应
    if (msg.id && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) p.reject(new Error(msg.error.message ?? '请求失败'));
      else p.resolve(msg.result);
    }
  }

  private _sendRaw(obj: any) {
    if (this.ws?.readyState !== WebSocket.OPEN) throw new Error('未连接');
    this.ws.send(JSON.stringify(obj));
  }

  /** 发请求并等待响应;onStream 收到该请求的流式帧。 */
  request(method: string, params: Record<string, any>, opts?: {
    timeout?: number; onStream?: (p: any) => void;
  }): Promise<any> {
    if (!this.connected) return Promise.reject(new Error('控制面未连接'));
    const id = newId();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`请求超时: ${method}`));
      }, opts?.timeout ?? 120000);
      this.pending.set(id, { resolve, reject, onStream: opts?.onStream, timer });
      try {
        this._sendRaw({ jsonrpc: '2.0', id, method, params });
      } catch (e) {
        this.pending.delete(id);
        clearTimeout(timer);
        reject(e);
      }
    });
  }

  async listNodes(): Promise<NodeInfo[]> {
    const r = await this.request('node.list', {}, { timeout: 10000 });
    return r?.nodes ?? [];
  }

  async createSession(metadata?: Record<string, any>): Promise<{ session_id: string; backend: string }> {
    return this.request('session.create', { metadata }, { timeout: 15000 });
  }

  async closeSession(sessionId: string): Promise<void> {
    await this.request('session.close', { session_id: sessionId }, { timeout: 10000 });
  }

  /**
   * 执行代码。onFrame({stream,text}) 逐帧回调;resolve 在最终响应时触发。
   */
  async runCode(
    sessionId: string,
    code: string,
    language: string,
    onFrame: (stream: string, text: string) => void,
    timeout = 120,
  ): Promise<string> {
    let output = '';
    const r = await this.request('exec.run', {
      session_id: sessionId, code, language, timeout,
    }, {
      timeout: (timeout + 10) * 1000,
      onStream: (params) => {
        if (params.event === 'done') return;
        if (params.stream) {
          const text = params.text ?? '';
          output += text;
          onFrame(params.stream, text);
        }
      },
    });
    return output;
  }

  async readFile(sessionId: string, path: string): Promise<string> {
    const r = await this.request('file.read', { session_id: sessionId, path }, { timeout: 15000 });
    return r?.content ?? '';
  }

  async writeFile(sessionId: string, path: string, content: string): Promise<void> {
    await this.request('file.write', { session_id: sessionId, path, content }, { timeout: 15000 });
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(() => {});
    }, 3000);
  }

  close() {
    this.intentionalClose = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.helloDone = false;
  }
}
