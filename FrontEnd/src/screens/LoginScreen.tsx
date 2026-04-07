import { useMemo, useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, View, useWindowDimensions } from "react-native";
import { Button, Card, Text, TextInput, useTheme } from "react-native-paper";

export type LoginScreenProps = {
  readonly onLogin: (email: string, password: string) => Promise<void>;
};

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const { width } = useWindowDimensions();
  const theme = useTheme();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const maxWidth = width >= 960 ? 520 : 480;
  const pagePadding = width >= 720 ? 24 : 16;

  const podeEntrar = useMemo(() => {
    return email.trim().length > 0 && password.trim().length > 0;
  }, [email, password]);

  async function entrar() {
    if (!podeEntrar || loading) return;
    setErro(null);
    setLoading(true);
    try {
      await onLogin(email.trim(), password);
    } catch (e: any) {
      setErro(e?.message || "Falha ao autenticar");
    } finally {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={[styles.container, { padding: pagePadding, backgroundColor: theme.colors.background }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={[styles.inner, { maxWidth }]}>
        <Text variant="headlineLarge" style={[styles.title, { color: theme.colors.onBackground }]}>
          Abastece AQUI
        </Text>
        <Text variant="bodyMedium" style={[styles.lead, { color: theme.colors.onBackground }]}>
          Encontre preços e localização dos postos.
        </Text>

        <Card style={[styles.card, { borderColor: theme.colors.outlineVariant }]}>
          <Card.Content>
            <Text variant="titleLarge" style={{ color: theme.colors.onSurface }}>
              Entrar
            </Text>
            <Text variant="bodyMedium" style={[styles.subtitle, { color: theme.colors.onSurface }]}>
              Use seu e-mail e senha para acessar os postos.
            </Text>

            <TextInput
              mode="outlined"
              label="E-mail"
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
              style={styles.field}
              left={<TextInput.Icon icon="email-outline" />}
            />
            <TextInput
              mode="outlined"
              label="Senha"
              secureTextEntry
              value={password}
              onChangeText={setPassword}
              style={styles.field}
              left={<TextInput.Icon icon="lock-outline" />}
            />

            {erro ? (
              <Text variant="bodyMedium" style={[styles.error, { color: theme.colors.error }]}>
                {erro}
              </Text>
            ) : null}

            <Button
              mode="contained"
              onPress={entrar}
              disabled={!podeEntrar || loading}
              loading={loading}
              style={styles.button}
              contentStyle={styles.buttonContent}
              labelStyle={styles.buttonLabel}
            >
              Entrar
            </Button>
          </Card.Content>
        </Card>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center" },
  inner: { width: "100%", maxWidth: 480, alignSelf: "center" },
  title: { marginBottom: 6, textAlign: "center", fontWeight: "700", letterSpacing: 0.2 },
  lead: { marginBottom: 18, textAlign: "center", opacity: 0.75 },
  card: {
    borderRadius: 18,
    borderWidth: 1,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOpacity: 0.08,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
    elevation: 2,
  },
  subtitle: { marginTop: 6, marginBottom: 12, opacity: 0.75 },
  field: { marginTop: 10 },
  error: { marginTop: 10 },
  button: { marginTop: 18 },
  buttonContent: { height: 48 },
  buttonLabel: { fontSize: 16, fontWeight: "600" },
});
