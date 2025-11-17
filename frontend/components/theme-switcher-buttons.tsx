import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

export const ThemeSwitcherButtons = () => {
  const { theme, setTheme } = useTheme();
  const [selectedTheme, setSelectedTheme] = useState("dark");

  // Sync local state with theme context
  useEffect(() => {
    if (theme) {
      setSelectedTheme(theme);
    }
  }, [theme]);

  const handleThemeChange = (newTheme: string) => {
    setSelectedTheme(newTheme);
    setTheme(newTheme);
  };

  return (
    <div className="flex items-center border border-border rounded-full">
      {/* Light Theme Button */}
      <button
        type="button"
        className={`h-6 w-6 rounded-full flex items-center justify-center ${
          selectedTheme === "light"
            ? "bg-amber-400 text-primary"
            : "text-foreground hover:bg-amber-400 hover:text-background"
        }`}
        onClick={() => handleThemeChange("light")}
        data-testid="menu_light_button"
        id="menu_light_button"
      >
        <Sun className="h-4 w-4 rounded-full" />
      </button>

      {/* Dark Theme Button */}
      <button
        type="button"
        className={`h-6 w-6 rounded-full flex items-center justify-center ${
          selectedTheme === "dark"
            ? "bg-purple-500/20 text-purple-500 hover:bg-purple-500/20 hover:text-purple-500"
            : "text-foreground hover:bg-purple-500/20 hover:text-purple-500"
        }`}
        onClick={() => handleThemeChange("dark")}
        data-testid="menu_dark_button"
        id="menu_dark_button"
      >
        <Moon className="h-4 w-4" />
      </button>

      {/* System Theme Button */}
      <button
        type="button"
        className={`h-6 w-6 rounded-full flex items-center justify-center ${
          selectedTheme === "system"
            ? "bg-foreground text-background"
            : "hover:bg-foreground hover:text-background"
        }`}
        onClick={() => handleThemeChange("system")}
        data-testid="menu_system_button"
        id="menu_system_button"
      >
        <Monitor className="h-4 w-4" />
      </button>
    </div>
  );
};

export default ThemeSwitcherButtons;
