/** 生成 JSON-RPC 请求 id。RN 无 crypto.randomUUID 时用时间戳+随机数。 */
export function newId(): string {
  const g: any = globalThis;
  if (g.crypto?.randomUUID) return g.crypto.randomUUID().replace(/-/g, '');
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}
