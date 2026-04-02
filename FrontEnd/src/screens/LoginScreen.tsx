import { useMemo, useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, View, useWindowDimensions } from "react-native";
import { Button, Card, Text, TextInput } from "react-native-paper";

export type LoginScreenProps = {
  readonly onLogin: (email: string, password: string) => Promise<void>;
};

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const { width } = useWindowDimensions();
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
      style={[styles.container, { padding: pagePadding }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={[styles.inner, { maxWidth }]}>
        <Text variant="headlineLarge" style={styles.title}>
          AbasteceAqui
        </Text>
        <Text variant="bodyMedium" style={styles.lead}>
          Encontre preços e localização dos postos.
        </Text>

        <Card style={styles.card}>
          <Card.Content>
            <Text variant="titleMedium">Entrar</Text>
            <Text variant="bodyMedium" style={styles.subtitle}>
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
            />
            <TextInput
              mode="outlined"
              label="Senha"
              secureTextEntry
              value={password}
              onChangeText={setPassword}
              style={styles.field}
            />

            {erro ? (
              <Text variant="bodyMedium" style={styles.error}>
                {erro}
              </Text>
            ) : null}

            <Button
              mode="contained"
              onPress={entrar}
              disabled={!podeEntrar || loading}
              loading={loading}
              style={styles.button}
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
  container: { flex: 1, justifyContent: "center", backgroundColor: "#F5F7FB" },
  inner: { width: "100%", maxWidth: 480, alignSelf: "center" },
  title: { marginBottom: 4, textAlign: "center" },
  lead: { marginBottom: 16, textAlign: "center", opacity: 0.75 },
  card: { borderRadius: 18 },
  subtitle: { marginTop: 6, marginBottom: 12, opacity: 0.75 },
  field: { marginTop: 10 },
  error: { marginTop: 10, color: "#B00020" },
  button: { marginTop: 18 },
});
