import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { theme } from '../theme';
import { Settings } from '../services/settings';
import { ControlClient } from '../services/controlClient';
import type { ControlConfig, NodeInfo } from '../types';

export function NodesScreen() {
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [cfg, setCfg] = useState<ControlConfig | null>(null);
  const [status, setStatus] = useState('offline');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const refresh = async () => {
    setLoading(true); setErr('');
    try {
      const c = await Settings.getControl();
      setCfg(c);
      const client = new ControlClient(c);
      client.onStatus = setStatus;
      await client.connect();
      setNodes(await client.listNodes());
      client.close();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  return (
    <ScrollView style={s.root} contentContainerStyle={s.content}>
      <View style={s.headerRow}>
        <View>
          <Text style={s.h1}>节点状态</Text>
          <Text style={s.hint}>{cfg?.url ?? '—'}</Text>
        </View>
        <TouchableOpacity style={s.refresh} onPress={refresh}><Text style={s.refreshText}>刷新</Text></TouchableOpacity>
      </View>

      {loading && <ActivityIndicator color={theme.primary} style={{ marginTop: 30 }} />}
      {!!err && <View style={s.errCard}><Text style={s.errText}>连接失败: {err}</Text></View>}
      {!loading && !err && nodes.length === 0 && (
        <View style={s.empty}>
          <Text style={s.emptyTitle}>没有在线节点</Text>
          <Text style={s.emptyText}>在服务器上运行节点Agent,并按「配置」页的地址接入。节点上线后会出现在这里。</Text>
        </View>
      )}
      {nodes.map((n) => (
        <View key={n.node_id} style={s.card}>
          <View style={s.cardRow}>
            <View style={[s.dot, { backgroundColor: theme.green }]} />
            <Text style={s.cardTitle}>{n.label || n.node_id}</Text>
          </View>
          <Text style={s.cardSub}>ID: {n.node_id}</Text>
          <Text style={s.cardSub}>活跃会话: {n.sessions}</Text>
          {!!n.capabilities?.backend && <Text style={s.cardSub}>沙箱后端: {String(n.capabilities.backend)}</Text>}
        </View>
      ))}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  content: { padding: 18, paddingTop: 56, paddingBottom: 60 },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 },
  h1: { color: theme.text, fontSize: 20, fontWeight: '700' },
  hint: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  refresh: { backgroundColor: theme.surface2, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.border },
  refreshText: { color: theme.primary, fontSize: 13 },
  empty: { padding: 24, alignItems: 'center', marginTop: 30 },
  emptyTitle: { color: theme.text, fontSize: 16, fontWeight: '700' },
  emptyText: { color: theme.textDim, fontSize: 13, lineHeight: 20, marginTop: 10, textAlign: 'center' },
  errCard: { backgroundColor: '#3a1f22', borderRadius: 10, padding: 14, marginTop: 20 },
  errText: { color: theme.red, fontSize: 13, lineHeight: 18 },
  card: { backgroundColor: theme.surface, borderRadius: 10, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: theme.border },
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  dot: { width: 9, height: 9, borderRadius: 5 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  cardSub: { color: theme.textDim, fontSize: 12, marginTop: 4 },
});
