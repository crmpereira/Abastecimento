import { useEffect, useMemo, useState } from "react";
import { View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, MD3LightTheme, PaperProvider, Text } from "react-native-paper";
import { LoginScreen } from "./src/screens/LoginScreen";
import { ProcessamentoScreen } from "./src/screens/ProcessamentoScreen";
import { PostosScreen } from "./src/screens/PostosScreen";
import { AuthUser, clearUser, loadUser, saveUser } from "./src/lib/auth";

export default function App() {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [tela, setTela] = useState<"postos" | "processamento">("postos");

  const podeVerProcessamento =
    typeof user?.email === "string" && user.email.trim().toLowerCase() === "cesar.pereiram@gmail.com";

  const theme = useMemo(() => {
    return {
      ...MD3LightTheme,
      roundness: 14,
      colors: {
        ...MD3LightTheme.colors,
        primary: "#2563EB",
        secondary: "#16A34A",
        tertiary: "#F97316",
        background: "#F6F7FB",
        surface: "#FFFFFF",
        surfaceVariant: "#F1F3F8",
        outlineVariant: "#E2E8F0",
      },
    };
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const u = await loadUser();
        setUser(u);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function onLogin(email: string, password: string) {
    if (!email.trim() || !password.trim()) {
      throw new Error("Informe e-mail e senha");
    }
    const u = { email: email.trim() };
    await saveUser(u);
    setUser(u);
  }

  async function onLogout() {
    await clearUser();
    setUser(null);
    setTela("postos");
  }

  return (
    <PaperProvider theme={theme}>
      <StatusBar style="dark" />
      {loading ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            backgroundColor: theme.colors.background,
          }}
        >
          <ActivityIndicator />
          <Text style={{ marginTop: 12 }}>Carregando...</Text>
        </View>
      ) : user ? (
        tela === "processamento" ? (
          podeVerProcessamento ? (
            <ProcessamentoScreen onBack={() => setTela("postos")} onLogout={onLogout} />
          ) : (
            <PostosScreen onLogout={onLogout} />
          )
        ) : (
          <PostosScreen
            onLogout={onLogout}
            onOpenProcessamento={podeVerProcessamento ? () => setTela("processamento") : undefined}
          />
        )
      ) : (
        <LoginScreen onLogin={onLogin} />
      )}
    </PaperProvider>
  );
}
