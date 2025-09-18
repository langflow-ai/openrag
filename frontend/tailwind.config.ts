/** @type {import('tailwindcss').Config} */
import tailwindcssForms from "@tailwindcss/forms";
import tailwindcssTypography from "@tailwindcss/typography";
import { fontFamily } from "tailwindcss/defaultTheme";
import plugin from "tailwindcss/plugin";
import tailwindcssAnimate from "tailwindcss-animate";
import tailwindcssLineClamp from "@tailwindcss/line-clamp";

const config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      screens: {
        "2xl": "1400px",
        "3xl": "1500px",
      },
    },
    extend: {
      screens: {
        xl: "1200px",
        "2xl": "1400px",
        "3xl": "1500px",
      },
      keyframes: {
        overlayShow: {
          from: { opacity: 0 },
          to: { opacity: 1 },
        },
        contentShow: {
          from: {
            opacity: 0,
            transform: "translate(-50%, -50%) scale(0.95)",
            clipPath: "inset(50% 0)",
          },
          to: {
            opacity: 1,
            transform: "translate(-50%, -50%) scale(1)",
            clipPath: "inset(0% 0)",
          },
        },
        wiggle: {
          "0%, 100%": { transform: "scale(100%)" },
          "50%": { transform: "scale(120%)" },
        },
      },
      animation: {
        overlayShow: "overlayShow 400ms cubic-bezier(0.16, 1, 0.3, 1)",
        contentShow: "contentShow 400ms cubic-bezier(0.16, 1, 0.3, 1)",
        wiggle: "wiggle 150ms ease-in-out 1",
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
          hover: "hsl(var(--primary-hover))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
          hover: "hsl(var(--secondary-hover))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        "status-blue": "var(--status-blue)",
        "status-green": "var(--status-green)",
        "status-red": "var(--status-red)",
        "status-yellow": "var(--status-yellow)",
        "component-icon": "var(--component-icon)",
        "flow-icon": "var(--flow-icon)",
        "placeholder-foreground": "hsl(var(--placeholder-foreground))",
        "datatype-blue": {
          DEFAULT: "hsl(var(--datatype-blue))",
          foreground: "hsl(var(--datatype-blue-foreground))",
        },
        "datatype-yellow": {
          DEFAULT: "hsl(var(--datatype-yellow))",
          foreground: "hsl(var(--datatype-yellow-foreground))",
        },
        "datatype-red": {
          DEFAULT: "hsl(var(--datatype-red))",
          foreground: "hsl(var(--datatype-red-foreground))",
        },
        "datatype-emerald": {
          DEFAULT: "hsl(var(--datatype-emerald))",
          foreground: "hsl(var(--datatype-emerald-foreground))",
        },
        "datatype-violet": {
          DEFAULT: "hsl(var(--datatype-violet))",
          foreground: "hsl(var(--datatype-violet-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", ...fontFamily.sans],
        mono: ["var(--font-mono)", ...fontFamily.mono],
        chivo: ["var(--font-chivo)", ...fontFamily.sans],
      },
      fontSize: {
        xxs: "11px",
        mmd: "13px",
      },
    },
  },
  plugins: [
    tailwindcssAnimate,
    tailwindcssLineClamp,
    tailwindcssForms({
      strategy: "class",
    }),
    plugin(({ addUtilities }) => {
      addUtilities({
        ".scrollbar-hide": {
          "-ms-overflow-style": "none",
          "scrollbar-width": "none",
          "&::-webkit-scrollbar": {
            display: "none",
          },
        },
        ".truncate-multiline": {
          display: "-webkit-box",
          "-webkit-line-clamp": "3",
          "-webkit-box-orient": "vertical",
          overflow: "hidden",
          "text-overflow": "ellipsis",
        },
        ".custom-scroll": {
          "&::-webkit-scrollbar": {
            width: "8px",
            height: "8px",
          },
          "&::-webkit-scrollbar-track": {
            backgroundColor: "hsl(var(--muted))",
          },
          "&::-webkit-scrollbar-thumb": {
            backgroundColor: "hsl(var(--border))",
            borderRadius: "999px",
          },
          "&::-webkit-scrollbar-thumb:hover": {
            backgroundColor: "hsl(var(--placeholder-foreground))",
          },
        },
        ".primary-input": {
          display: "block",
          width: "100%",
          borderRadius: "0.375rem",
          border: "1px solid hsl(var(--border))",
          backgroundColor: "hsl(var(--background))",
          paddingLeft: "0.75rem",
          paddingRight: "0.75rem",
          paddingTop: "0.5rem",
          paddingBottom: "0.5rem",
          fontSize: "0.875rem",
          textAlign: "left",
          textOverflow: "ellipsis",
          "&::placeholder": {
            color: "hsl(var(--muted-foreground))",
          },
          "&:hover": {
            borderColor: "hsl(var(--muted-foreground))",
          },
          "&:focus": {
            borderColor: "hsl(var(--foreground))",
            outline: "none",
            boxShadow: "none",
            "&::placeholder": {
              color: "transparent",
            },
          },
          "&:disabled": {
            pointerEvents: "none",
            cursor: "not-allowed",
            backgroundColor: "hsl(var(--muted))",
            color: "hsl(var(--muted-foreground))",
          },
        },
      });
    }),
    tailwindcssTypography,
  ],
};

export default config;