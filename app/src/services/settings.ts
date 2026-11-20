/** 配置持久化:非敏感配置存 JSON,密钥存系统钥匙串。 */
import { SecureKV } from './secureStore';
import type { ControlConfig, ModelProfile, Protocol } from '../types';

const PROFILES_KEY = 'profiles';
const CONTROL_KEY = 'control';
const ACTIVE_KEY = 'active_id';
const SYS_PROMPT_KEY = 'sys_prompt';

export const DEFAULT_SYSTEM_PROMPT =
  '你是一个强大的 AI 助手,擅长问答、编程和数据分析。' +
  '当你需要运行代码、计算、分析数据或验证结果时,使用 execute_code 工具在沙箱中执行真实代码,' +
  '并根据输出继续回答。始终用中文回答。';

export const Settings = {
  async getControl(): Promise<ControlConfig> {
    try {
      const raw = await SecureKV.get(CONTROL_KEY);
      if (raw) return JSON.parse(raw);
    } catch {}
    return { url: 'ws://10.0.2.2:8000/ws/client', userId: 'demo-user' };
  },
  async setControl(cfg: ControlConfig) {
    await SecureKV.set(CONTROL_KEY, JSON.stringify(cfg));
  },

  async getProfiles(): Promise<ModelProfile[]> {
    try {
      const raw = await SecureKV.get(PROFILES_KEY);
      if (raw) {
        const arr = JSON.parse(raw);
        // 重新注入密钥(不落明文 JSON)
        for (const p of arr) p.apiKey = (await SecureKV.get(`key_${p.id}`)) ?? '';
        return arr;
      }
    } catch {}
    return [];
  },
  async saveProfile(p: ModelProfile) {
    const arr = await this.getProfiles();
    const idx = arr.findIndex((x) => x.id === p.id);
    if (idx >= 0) arr[idx] = p; else arr.push(p);
    await SecureKV.set(PROFILES_KEY, JSON.stringify(arr.map(({ apiKey, ...rest }) => rest)));
    await SecureKV.set(`key_${p.id}`, p.apiKey);
  },
  async deleteProfile(id: string) {
    const arr = (await this.getProfiles()).filter((p) => p.id !== id);
    await SecureKV.set(PROFILES_KEY, JSON.stringify(arr.map(({ apiKey, ...rest }) => rest)));
    await SecureKV.del(`key_${id}`);
  },

  async getActiveId(): Promise<string | null> {
    return SecureKV.get(ACTIVE_KEY);
  },
  async setActiveId(id: string) {
    await SecureKV.set(ACTIVE_KEY, id);
  },

  async getSystemPrompt(): Promise<string> {
    return (await SecureKV.get(SYS_PROMPT_KEY)) ?? DEFAULT_SYSTEM_PROMPT;
  },
  async setSystemPrompt(v: string) {
    await SecureKV.set(SYS_PROMPT_KEY, v);
  },
};

export const PROTOCOL_LABELS: Record<Protocol, string> = {
  openai: 'OpenAI 兼容(运营商MaaS/DeepSeek等)',
  anthropic: 'Anthropic Messages(Claude)',
  gemini: 'Gemini(Google)',
};
