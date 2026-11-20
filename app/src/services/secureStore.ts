/** 安全存储:模型 API Key、节点 token 等敏感信息存系统钥匙串,不进代码/日志。 */
import * as SecureStore from 'expo-secure-store';

const PREFIX = 'mca_';

export const SecureKV = {
  async get(key: string): Promise<string | null> {
    return SecureStore.getItemAsync(PREFIX + key);
  },
  async set(key: string, value: string): Promise<void> {
    await SecureStore.setItemAsync(PREFIX + key, value);
  },
  async del(key: string): Promise<void> {
    await SecureStore.deleteItemAsync(PREFIX + key);
  },
};
