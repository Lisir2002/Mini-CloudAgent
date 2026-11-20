import React, { useEffect, useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet, Alert, ActivityIndicator,
} from 'react-native';
import { Field } from '../components/Field';
import { theme } from '../theme';
import { Settings, PROTOCOL_LABELS } from '../services/settings';
import type { ControlConfig, ModelProfile, Protocol } from '../types';
import { newId } from '../services/rpc';

export function ConfigScreen({ onSaved }: { onSaved: () => void }) {
  const [control, setControl] = useState<ControlConfig>({ url: '', userId: '' });
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editing, setEditing] = useState<ModelProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setControl(await Settings.getControl());
      setProfiles(await Settings.getProfiles());
      setActiveId(await Settings.getActiveId());
      setLoading(false);
    })();
  }, []);

  const saveControl = async () => {
    await Settings.setControl(control);
    Alert.alert('已保存', '控制面配置已保存');
  };

  const saveProfile = async () => {
    if (!editing) return;
    if (!editing.baseUrl || !editing.model) {
      Alert.alert('缺少信息', '请填写 Base URL 和模型名'); return;
    }
    await Settings.saveProfile(editing);
    await Settings.setActiveId(editing.id);
    const arr = await Settings.getProfiles();
    setProfiles(arr);
    setActiveId(editing.id);
    setEditing(null);
    onSaved();
    Alert.alert('已保存', `模型「${editing.label || editing.model}」已保存并启用`);
  };

  const newProfile = () => {
    setEditing({
      id: newId(), label: '', protocol: 'openai', baseUrl: '', model: '',
      apiKey: '', temperature: 0.7, maxTokens: 4096,
    });
  };

  if (loading) return <View style={s.center}><ActivityIndicator color={theme.primary} /></View>;

  // 编辑模式
  if (editing) {
    return (
      <ScrollView style={s.root} contentContainerStyle={s.content}>
        <Text style={s.h2}>{profiles.some(p => p.id === editing.id) ? '编辑模型' : '新增模型'}</Text>
        <Field label="显示名(可选)" value={editing.label} onChange={v => setEditing({ ...editing, label: v })} placeholder="例如:星辰-编程" />
        <Text style={s.label}>协议类型</Text>
        <View style={s.chips}>
          {(Object.keys(PROTOCOL_LABELS) as Protocol[]).map((p) => (
            <TouchableOpacity
              key={p}
              style={[s.chip, editing.protocol === p && s.chipOn]}
              onPress={() => setEditing({ ...editing, protocol: p })}
            >
              <Text style={[s.chipText, editing.protocol === p && s.chipTextOn]}>{p}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <Text style={s.hint}>{PROTOCOL_LABELS[editing.protocol]}</Text>
        <Field label="Base URL" value={editing.baseUrl} onChange={v => setEditing({ ...editing, baseUrl: v })} placeholder="https://ai.ctaigw.cn/coding/v1" keyboard="url" />
        <Field label="API Key" value={editing.apiKey} onChange={v => setEditing({ ...editing, apiKey: v })} placeholder="用户自己的密钥" secure />
        <Field label="模型名" value={editing.model} onChange={v => setEditing({ ...editing, model: v })} placeholder="例如:星辰-Pro" />
        <View style={s.row}>
          <View style={s.half}>
            <Field label="Temperature" value={String(editing.temperature)} onChange={v => setEditing({ ...editing, temperature: parseFloat(v) || 0 })} keyboard="numeric" />
          </View>
          <View style={s.half}>
            <Field label="Max Tokens" value={String(editing.maxTokens)} onChange={v => setEditing({ ...editing, maxTokens: parseInt(v) || 4096 })} keyboard="numeric" />
          </View>
        </View>
        <TouchableOpacity style={s.btn} onPress={saveProfile}><Text style={s.btnText}>保存并启用</Text></TouchableOpacity>
        <TouchableOpacity style={s.btnGhost} onPress={() => setEditing(null)}><Text style={s.btnGhostText}>取消</Text></TouchableOpacity>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={s.root} contentContainerStyle={s.content}>
      <Text style={s.h1}>连接控制面</Text>
      <Text style={s.hint}>App 通过控制面把代码任务发给你的服务器/沙箱。真机测试填电脑局域网 IP。</Text>
      <Field label="WebSocket 地址" value={control.url} onChange={v => setControl({ ...control, url: v })} placeholder="ws://192.168.1.10:8000/ws/client" keyboard="url" />
      <Field label="用户 ID" value={control.userId} onChange={v => setControl({ ...control, userId: v })} placeholder="demo-user" />
      <TouchableOpacity style={s.btn} onPress={saveControl}><Text style={s.btnText}>保存控制面</Text></TouchableOpacity>

      <Text style={[s.h1, { marginTop: 28 }]}>模型配置</Text>
      <Text style={s.hint}>配置你自己的模型 API(运营商 MaaS / OpenAI / Claude / Gemini)。密钥存在系统钥匙串。</Text>
      {profiles.map((p) => (
        <TouchableOpacity
          key={p.id}
          style={[s.card, activeId === p.id && s.cardActive]}
          onPress={() => { setActiveId(p.id); Settings.setActiveId(p.id); }}
          onLongPress={() => setEditing(p)}
        >
          <View style={s.cardRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.cardTitle}>{p.label || p.model} {activeId === p.id && '✓'}</Text>
              <Text style={s.cardSub}>{p.protocol} · {p.model}</Text>
            </View>
            <TouchableOpacity onPress={() => setEditing(p)}><Text style={s.edit}>编辑</Text></TouchableOpacity>
          </View>
        </TouchableOpacity>
      ))}
      <TouchableOpacity style={s.btnAdd} onPress={newProfile}><Text style={s.btnAddText}>+ 新增模型</Text></TouchableOpacity>
      <Text style={s.foot}>长按卡片可编辑 · 点击卡片设为启用</Text>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  content: { padding: 18, paddingBottom: 60 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: theme.bg },
  h1: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  h2: { color: theme.text, fontSize: 18, fontWeight: '700', marginBottom: 16 },
  label: { color: theme.textDim, fontSize: 13, marginBottom: 6 },
  hint: { color: theme.textDim, fontSize: 12.5, lineHeight: 18, marginBottom: 14 },
  chips: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, backgroundColor: theme.surface2, borderWidth: 1, borderColor: theme.border },
  chipOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  chipText: { color: theme.textDim, fontSize: 13 },
  chipTextOn: { color: '#fff', fontWeight: '700' },
  row: { flexDirection: 'row', gap: 12 },
  half: { flex: 1 },
  btn: { backgroundColor: theme.primary, padding: 14, borderRadius: 10, alignItems: 'center', marginTop: 6 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnGhost: { padding: 14, alignItems: 'center', marginTop: 6 },
  btnGhostText: { color: theme.textDim, fontSize: 14 },
  btnAdd: { borderWidth: 1, borderStyle: 'dashed', borderColor: theme.primary, padding: 14, borderRadius: 10, alignItems: 'center', marginTop: 12 },
  btnAddText: { color: theme.primary, fontWeight: '700', fontSize: 15 },
  card: { backgroundColor: theme.surface, borderRadius: 10, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: theme.border },
  cardActive: { borderColor: theme.primary, backgroundColor: '#1b2740' },
  cardRow: { flexDirection: 'row', alignItems: 'center' },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  cardSub: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  edit: { color: theme.primary, fontSize: 13, paddingLeft: 10 },
  foot: { color: theme.textDim, fontSize: 11, textAlign: 'center', marginTop: 16 },
});
