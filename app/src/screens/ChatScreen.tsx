import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView,
  Platform, ActivityIndicator,
} from 'react-native';
import { theme } from '../theme';
import { Settings } from '../services/settings';
import { ControlClient } from '../services/controlClient';
import { runAgent } from '../services/agentEngine';
import type { ControlConfig, Message, ModelProfile } from '../types';

type ChatItem =
  | { kind: 'msg'; role: string; text: string }
  | { kind: 'tool'; status: 'start' | 'frame' | 'end'; text: string };

export function ChatScreen() {
  const [profile, setProfile] = useState<ModelProfile | null>(null);
  const [controlCfg, setControlCfg] = useState<ControlConfig | null>(null);
  const [status, setStatus] = useState<'offline' | 'connecting' | 'online'>('offline');
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sysPrompt, setSysPrompt] = useState('');
  const clientRef = useRef<ControlClient | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  const historyRef = useRef<Message[]>([]);

  const connect = async () => {
    const [profiles, activeId, cfg, sp] = await Promise.all([
      Settings.getProfiles(), Settings.getActiveId(), Settings.getControl(), Settings.getSystemPrompt(),
    ]);
    setControlCfg(cfg);
    setSysPrompt(sp);
    const p = profiles.find((x) => x.id === activeId) ?? profiles[0] ?? null;
    setProfile(p);
    if (!p) return;
    const client = new ControlClient(cfg);
    client.onStatus = setStatus;
    clientRef.current = client;
    try {
      await client.connect();
      const r = await client.createSession({ source: 'app' });
      setSessionId(r.session_id);
    } catch (e: any) {
      setItems((x) => [...x, { kind: 'msg', role: 'system', text: `连接控制面失败: ${e?.message ?? e}` }]);
    }
  };

  useEffect(() => {
    connect();
    return () => clientRef.current?.close();
  }, []);

  const scrollBottom = () => setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    if (!profile) { AlertMsg(setItems, '请先在「配置」页添加并启用模型'); return; }
    if (!clientRef.current?.connected || !sessionId) {
      AlertMsg(setItems, '控制面未连接,请检查配置页的地址,或重新启动App'); return;
    }

    setInput('');
    setBusy(true);
    setItems((x) => [...x, { kind: 'msg', role: 'user', text }]);
    // 预留一条 assistant 消息,流式追加
    setItems((x) => [...x, { kind: 'msg', role: 'assistant', text: '' }]);
    scrollBottom();

    let assistantFull = '';
    const appendText = (t: string) => {
      assistantFull += t;
      setItems((x) => {
        const copy = [...x];
        for (let i = copy.length - 1; i >= 0; i--) {
          const cur = copy[i];
          if (cur.kind === 'msg' && cur.role === 'assistant') {
            copy[i] = { kind: 'msg', role: 'assistant', text: cur.text + t };
            break;
          }
        }
        return copy;
      });
      scrollBottom();
    };

    try {
      await runAgent(
        {
          profile,
          control: clientRef.current,
          sessionId,
          systemPrompt: sysPrompt,
        },
        historyRef.current,
        text,
        {
          onText: appendText,
          onToolStart: (name, args) => {
            setItems((x) => [...x, { kind: 'tool', status: 'start', text: `${name} · ${args.slice(0, 120)}` }]);
            scrollBottom();
          },
          onToolFrame: (_stream, t) => {
            setItems((x) => {
              const copy = [...x];
              for (let i = copy.length - 1; i >= 0; i--) {
                const cur = copy[i];
                if (cur.kind === 'tool') {
                  copy[i] = { kind: 'tool', status: 'frame', text: cur.text + t };
                  break;
                }
              }
              return copy;
            });
            scrollBottom();
          },
          onToolEnd: (output) => {
            setItems((x) => [...x, { kind: 'tool', status: 'end', text: `输出: ${output.slice(0, 400)}` }]);
            scrollBottom();
          },
          onError: (m) => {
            setItems((x) => [...x, { kind: 'msg', role: 'system', text: `⚠ ${m}` }]);
          },
        },
      );
      // 记入历史(只保留文本消息)
      historyRef.current.push({ role: 'user', content: text });
      historyRef.current.push({ role: 'assistant', content: assistantFull });
      if (historyRef.current.length > 40) historyRef.current = historyRef.current.slice(-40);
    } catch (e: any) {
      AlertMsg(setItems, `执行出错: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
      scrollBottom();
    }
  };

  const statusColor = status === 'online' ? theme.green : status === 'connecting' ? theme.amber : theme.red;

  return (
    <View style={s.root}>
      <View style={s.header}>
        <View>
          <Text style={s.title}>Mini CloudAgent</Text>
          <Text style={s.sub}>{profile ? profile.label || profile.model : '未配置模型'}</Text>
        </View>
        <View style={s.statusWrap}>
          <View style={[s.dot, { backgroundColor: statusColor }]} />
          <Text style={[s.statusText, { color: statusColor }]}>
            {status === 'online' ? '沙箱已连接' : status === 'connecting' ? '连接中' : '离线'}
          </Text>
          {status !== 'online' && (
            <TouchableOpacity onPress={connect}><Text style={s.retry}>重试</Text></TouchableOpacity>
          )}
        </View>
      </View>

      <ScrollView ref={scrollRef} style={s.list} contentContainerStyle={s.listContent} onContentSizeChange={scrollBottom}>
        {items.length === 0 && (
          <View style={s.empty}>
            <Text style={s.emptyTitle}>开始对话</Text>
            <Text style={s.emptyText}>配置好模型和控制面后,试试:「帮我用 Python 计算 1 到 100 的和,并验证结果」</Text>
          </View>
        )}
        {items.map((it, i) => {
          if (it.kind === 'tool') {
            return (
              <View key={i} style={s.toolCard}>
                <Text style={s.toolTitle}>
                  {it.status === 'start' ? '⚙ 调用工具' : it.status === 'frame' ? '⚙ 执行中' : '✓ 工具完成'}
                </Text>
                <Text style={s.toolText}>{it.text}</Text>
              </View>
            );
          }
          const isUser = it.role === 'user';
          return (
            <View key={i} style={[s.bubble, isUser ? s.bubbleUser : it.role === 'system' ? s.bubbleSys : s.bubbleAi]}>
              <Text style={[s.bubbleRole, { color: isUser ? theme.primary : it.role === 'system' ? theme.red : theme.green }]}>
                {isUser ? '你' : it.role === 'system' ? '系统' : '助手'}
              </Text>
              <Text style={s.bubbleText}>{it.text || (busy ? '…' : '')}</Text>
            </View>
          );
        })}
      </ScrollView>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={s.inputRow}>
          <TextInput
            style={s.input}
            value={input}
            onChangeText={setInput}
            placeholder="输入消息…"
            placeholderTextColor={theme.textDim}
            multiline
            onSubmitEditing={send}
            editable={!busy}
          />
          <TouchableOpacity style={[s.send, busy && s.sendDisabled]} onPress={send} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.sendText}>发送</Text>}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

function AlertMsg(setter: any, text: string) {
  setter((x: any) => [...x, { kind: 'msg', role: 'system', text }]);
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 52, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: theme.border },
  title: { color: theme.text, fontSize: 17, fontWeight: '700' },
  sub: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  statusWrap: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 12 },
  retry: { color: theme.primary, fontSize: 12, marginLeft: 6 },
  list: { flex: 1 },
  listContent: { padding: 14, paddingBottom: 20 },
  empty: { padding: 24, alignItems: 'center', marginTop: 40 },
  emptyTitle: { color: theme.text, fontSize: 18, fontWeight: '700' },
  emptyText: { color: theme.textDim, fontSize: 13, lineHeight: 20, marginTop: 10, textAlign: 'center' },
  bubble: { borderRadius: 12, padding: 12, marginBottom: 12, borderWidth: 1 },
  bubbleUser: { backgroundColor: '#1c2b4a', borderColor: '#2c4a7a', alignSelf: 'flex-end', maxWidth: '88%' },
  bubbleAi: { backgroundColor: theme.surface, borderColor: theme.border, alignSelf: 'flex-start', maxWidth: '94%' },
  bubbleSys: { backgroundColor: '#3a1f22', borderColor: '#5a2b2f', alignSelf: 'center', maxWidth: '94%' },
  bubbleRole: { fontSize: 11, fontWeight: '700', marginBottom: 4 },
  bubbleText: { color: theme.text, fontSize: 14, lineHeight: 20 },
  toolCard: { backgroundColor: '#2a2140', borderColor: '#4a3a70', borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10, alignSelf: 'flex-start', maxWidth: '94%' },
  toolTitle: { color: theme.purple, fontSize: 12, fontWeight: '700', marginBottom: 4 },
  toolText: { color: '#c9c2dd', fontSize: 12, lineHeight: 17, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  inputRow: { flexDirection: 'row', padding: 12, borderTopWidth: 1, borderTopColor: theme.border, alignItems: 'flex-end', gap: 8 },
  input: { flex: 1, backgroundColor: theme.surface2, color: theme.text, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, maxHeight: 100, borderWidth: 1, borderColor: theme.border },
  send: { backgroundColor: theme.primary, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 18, justifyContent: 'center' },
  sendDisabled: { opacity: 0.6 },
  sendText: { color: '#fff', fontWeight: '700' },
});
