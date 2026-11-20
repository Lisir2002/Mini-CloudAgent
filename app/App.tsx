import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, StatusBar } from 'react-native';
import { theme } from './src/theme';
import { ChatScreen } from './src/screens/ChatScreen';
import { ConfigScreen } from './src/screens/ConfigScreen';
import { NodesScreen } from './src/screens/NodesScreen';

type Tab = 'chat' | 'nodes' | 'config';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: '对话', icon: '💬' },
  { key: 'nodes', label: '节点', icon: '🖥' },
  { key: 'config', label: '配置', icon: '⚙' },
];

export default function App() {
  const [tab, setTab] = useState<Tab>('chat');
  const [configTick, setConfigTick] = useState(0);

  return (
    <View style={s.root}>
      <StatusBar barStyle="light-content" backgroundColor={theme.bg} />
      <View style={s.body}>
        {tab === 'chat' && <ChatScreen key={configTick} />}
        {tab === 'nodes' && <NodesScreen />}
        {tab === 'config' && (
          <ConfigScreen onSaved={() => setConfigTick((x) => x + 1)} />
        )}
      </View>
      <View style={s.tabbar}>
        {TABS.map((t) => (
          <TouchableOpacity
            key={t.key}
            style={s.tab}
            onPress={() => setTab(t.key)}
          >
            <Text style={[s.tabIcon, tab === t.key && s.tabIconOn]}>{t.icon}</Text>
            <Text style={[s.tabLabel, tab === t.key && s.tabLabelOn]}>{t.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  body: { flex: 1 },
  tabbar: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: theme.border, backgroundColor: theme.surface, paddingBottom: 18, paddingTop: 8 },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 6 },
  tabIcon: { fontSize: 20, opacity: 0.5 },
  tabIconOn: { opacity: 1 },
  tabLabel: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  tabLabelOn: { color: theme.primary, fontWeight: '700' },
});
