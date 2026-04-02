import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY_USER = "auth_user_v1";

export type AuthUser = {
  email: string;
};

export async function loadUser(): Promise<AuthUser | null> {
  const raw = await AsyncStorage.getItem(KEY_USER);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "email" in parsed &&
      typeof (parsed as any).email === "string"
    ) {
      return { email: (parsed as any).email };
    }
    return null;
  } catch {
    return null;
  }
}

export async function saveUser(user: AuthUser): Promise<void> {
  await AsyncStorage.setItem(KEY_USER, JSON.stringify(user));
}

export async function clearUser(): Promise<void> {
  await AsyncStorage.removeItem(KEY_USER);
}
