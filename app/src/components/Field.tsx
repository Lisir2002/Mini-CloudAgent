import React from 'react';
import { View, Text, TextInput, StyleSheet } from 'react-native';
import { theme } from '../theme';

export function Field({
  label, value, onChange, placeholder, secure, multiline, keyboard,
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; secure?: boolean; multiline?: boolean; keyboard?: 'default' | 'url' | 'numeric';
}) {
  return (
    <View style={s.wrap}>
      <Text style={s.label}>{label}</Text>
      <TextInput
        style={[s.input, multiline && s.multiline]}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={theme.textDim}
        secureTextEntry={secure}
        multiline={multiline}
        keyboardType={keyboard ?? 'default'}
        autoCapitalize="none"
        autoCorrect={false}
      />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { marginBottom: 14 },
  label: { color: theme.textDim, fontSize: 13, marginBottom: 6 },
  input: {
    backgroundColor: theme.surface2, color: theme.text, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 11, fontSize: 15, borderWidth: 1, borderColor: theme.border,
  },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
});
