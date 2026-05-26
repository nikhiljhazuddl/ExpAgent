import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        priority: {
          high: "#ec4899",
          medium: "#f59e0b",
          low: "#9ca3af",
        },
      },
    },
  },
  plugins: [],
};
export default config;
