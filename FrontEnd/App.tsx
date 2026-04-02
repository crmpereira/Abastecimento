import { useEffect, useMemo, useState } from "react";
import { View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, MD3LightTheme, PaperProvider, Text } from "react-native-paper";
import { LoginScreen } from "./src/screens/LoginScreen";
import { PostosScreen } from "./src/screens/PostosScreen";
import { AuthUser, clearUser, loadUser, saveUser } from "./src/lib/auth";

export default function App() {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);

  const theme = useMemo(() => {
    return {
      ...MD3LightTheme,
      colors: {
        ...MD3LightTheme.colors,
        primary: "#1E88E5",
        secondary: "#00A884",
        background: "#F5F7FB",
        surface: "#FFFFFF",
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
        <PostosScreen onLogout={onLogout} />
      ) : (
        <LoginScreen onLogin={onLogin} />
      )}
    </PaperProvider>
  );
}
