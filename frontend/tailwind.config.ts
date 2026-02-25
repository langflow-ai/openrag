/** @type {import('tailwindcss').Config} */
import tailwindcssForms from "@tailwindcss/forms";
import tailwindcssTypography from "@tailwindcss/typography";
import { fontFamily } from "tailwindcss/defaultTheme";
import plugin from "tailwindcss/plugin";
import tailwindcssAnimate from "tailwindcss-animate";

const config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
  ],
  theme: {
  	container: {
  		center: true,
  		screens: {
  			'2xl': '1400px',
  			'3xl': '1500px'
  		}
  	},
  	extend: {
  		screens: {
  			xl: '1200px',
  			'2xl': '1400px',
  			'3xl': '1500px'
  		},
  		keyframes: {
  			overlayShow: {
  				from: {
  					opacity: 0
  				},
  				to: {
  					opacity: 1
  				}
  			},
  			contentShow: {
  				from: {
  					opacity: 0,
  					transform: 'translate(-50%, -50%) scale(0.95)',
  					clipPath: 'inset(50% 0)'
  				},
  				to: {
  					opacity: 1,
  					transform: 'translate(-50%, -50%) scale(1)',
  					clipPath: 'inset(0% 0)'
  				}
  			},
  			wiggle: {
  				'0%, 100%': {
  					transform: 'scale(100%)'
  				},
  				'50%': {
  					transform: 'scale(120%)'
  				}
  			},
  			'accordion-down': {
  				from: {
  					height: '0'
  				},
  				to: {
  					height: 'var(--radix-accordion-content-height)'
  				}
  			},
  			'accordion-up': {
  				from: {
  					height: 'var(--radix-accordion-content-height)'
  				},
  				to: {
  					height: '0'
  				}
  			},
  			shimmer: {
  				'0%': {
  					backgroundPosition: '200% 0'
  				},
  				'100%': {
  					backgroundPosition: '-200% 0'
  				}
  			}
  		},
  		animation: {
  			overlayShow: 'overlayShow 400ms cubic-bezier(0.16, 1, 0.3, 1)',
  			contentShow: 'contentShow 400ms cubic-bezier(0.16, 1, 0.3, 1)',
  			wiggle: 'wiggle 150ms ease-in-out 1',
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out',
  			shimmer: 'shimmer 3s ease-in-out infinite'
  		},
  		colors: {
  			border: 'hsl(var(--border))',
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			background: 'hsl(var(--background))',
  			foreground: 'hsl(var(--foreground))',
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))',
  				hover: 'hsl(var(--primary-hover))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))',
  				hover: 'hsl(var(--secondary-hover))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			'accent-emerald': {
  				DEFAULT: 'hsl(var(--accent-emerald))',
  				foreground: 'hsl(var(--accent-emerald-foreground))'
  			},
  			'accent-pink': {
  				DEFAULT: 'hsl(var(--accent-pink))',
  				foreground: 'hsl(var(--accent-pink-foreground))'
  			},
  			'accent-amber': {
  				DEFAULT: 'hsl(var(--accent-amber))',
  				foreground: 'hsl(var(--accent-amber-foreground))'
  			},
  			'accent-purple': {
  				DEFAULT: 'hsl(var(--accent-purple))',
  				foreground: 'hsl(var(--accent-purple-foreground))'
  			},
  			'accent-indigo': {
  				DEFAULT: 'hsl(var(--accent-indigo))',
  				foreground: 'hsl(var(--accent-indigo-foreground))'
  			},
  			'accent-red': {
  				DEFAULT: 'hsl(var(--accent-red))',
  				foreground: 'hsl(var(--accent-red-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			'component-icon': 'var(--component-icon)',
  			'flow-icon': 'var(--flow-icon)',
  			'placeholder-foreground': 'hsl(var(--placeholder-foreground))',
  			warning: {
  				DEFAULT: 'hsl(var(--warning))',
  				foreground: 'hsl(var(--warning-foreground))'
  			},
  			sidebar: {
  				DEFAULT: 'hsl(var(--sidebar-background))',
  				foreground: 'hsl(var(--sidebar-foreground))',
  				primary: 'hsl(var(--sidebar-primary))',
  				'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
  				accent: 'hsl(var(--sidebar-accent))',
  				'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
  				border: 'hsl(var(--sidebar-border))',
  				ring: 'hsl(var(--sidebar-ring))'
  			}
  		},
  		borderRadius: {
  			lg: 'var(--radius)',
  			md: 'calc(var(--radius) - 2px)',
  			sm: 'calc(var(--radius) - 4px)'
  		},
  		fontFamily: {
  			sans: [
  				'var(--font-sans)',
                    ...fontFamily.sans
                ],
  			mono: [
  				'var(--font-mono)',
                    ...fontFamily.mono
                ],
  			chivo: [
  				'var(--font-chivo)',
                    ...fontFamily.sans
                ]
  		},
  		fontSize: {
  			xxs: '11px',
  			mmd: '13px'
  		}
  	}
  },
  plugins: [
    tailwindcssAnimate,
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
          height: "40px",
          borderRadius: "0.375rem",
          border: "1px solid hsl(var(--input))",
          backgroundColor: "hsl(var(--background))",
          paddingLeft: "0.75rem",
          paddingRight: "0.75rem",
          paddingTop: "0.5rem",
          paddingBottom: "0.5rem",
          fontSize: "0.875rem",
          textAlign: "left",
          textOverflow: "ellipsis",
          transitionProperty:
            "color, background-color, border-color, text-decoration-color, fill, stroke",
          transitionTimingFunction: "cubic-bezier(0.4, 0, 0.2, 1)",
          transitionDuration: "150ms",
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
