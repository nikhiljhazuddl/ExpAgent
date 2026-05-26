"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

export function LoginForm({ users }: { users: { role: string; name: string }[] }) {
  const router = useRouter();
  const roles = useMemo(() => Array.from(new Set(users.map((u) => u.role))), [users]);
  const [role, setRole] = useState(roles[0] || "AE");
  const usersInRole = users.filter((u) => u.role === role);
  const [name, setName] = useState(usersInRole[0]?.name || "");

  function login(e: React.FormEvent) {
    e.preventDefault();
    const value = `role=${encodeURIComponent(role)}&user=${encodeURIComponent(name)}`;
    document.cookie = `session=${value}; path=/; SameSite=Lax`;
    router.push("/dashboard");
  }

  return (
    <form onSubmit={login} className="space-y-4 border border-white/10 rounded-lg p-6">
      <div>
        <label className="block text-xs uppercase text-gray-500 mb-1">Role</label>
        <select
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            const next = users.find((u) => u.role === e.target.value);
            setName(next?.name || "");
          }}
          className="w-full bg-black border border-white/20 rounded px-3 py-2"
        >
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs uppercase text-gray-500 mb-1">Person</label>
        <select
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full bg-black border border-white/20 rounded px-3 py-2"
        >
          {usersInRole.map((u) => (
            <option key={u.name} value={u.name}>
              {u.name}
            </option>
          ))}
        </select>
      </div>
      <button
        type="submit"
        className="w-full bg-white text-black rounded px-3 py-2 font-medium hover:bg-gray-200"
      >
        Sign in
      </button>
    </form>
  );
}
