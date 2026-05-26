import { api } from "@/lib/api";
import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const users = await api.users();
  return (
    <div className="max-w-md mx-auto mt-12">
      <h1 className="text-2xl font-bold mb-2">Sign in</h1>
      <p className="text-sm text-gray-400 mb-6">
        Fake login — pick a role and a person. (Auth lands in V1.5.)
      </p>
      <LoginForm users={users.users} />
    </div>
  );
}
