import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        cream: "#fffefb",
        "off-white": "#fffdf9",
        "zapier-black": "#201515",
        "zapier-orange": "#ff4f00",
        charcoal: "#36342e",
        "warm-gray": "#939084",
        sand: "#c5c0b1",
        "light-sand": "#eceae3",
        "mid-warm": "#b5b2aa",
      },
      fontFamily: {
        sans: ["Inter", "Helvetica", "Arial", "sans-serif"],
        display: ["Degular Display", "Inter", "sans-serif"],
        editorial: ["GT Alpina", "Georgia", "serif"],
      },
      borderRadius: {
        tight: "3px",
        standard: "4px",
        content: "5px",
        comfortable: "8px",
        social: "14px",
        pill: "20px",
      },
      lineHeight: {
        compressed: "0.90",
        "tight-display": "1.04",
      },
    },
  },
  plugins: [],
};

export default config;
