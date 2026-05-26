import { redirect } from "next/navigation";
import { readSession } from "@/lib/session";

export default function Home() {
  const s = readSession();
  redirect(s.user ? "/dashboard" : "/login");
}
