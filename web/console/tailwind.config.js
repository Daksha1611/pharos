export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Control-room palette: dark, low-glare, readable at 3 AM, which is the
        // shift this screen is actually for.
        ink: { 900: "#0a0e14", 800: "#111721", 700: "#1a2130", 600: "#242d3f", 500: "#36415a" },
        signal: {
          critical: "#ff5a5f",
          high: "#ff9f43",
          medium: "#ffd166",
          low: "#4dd4ac",
          info: "#5aa9ff",
          verify: "#b388ff",
        },
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};
