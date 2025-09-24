import { Eye, EyeOff } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode;
  inputClassName?: string;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, inputClassName, icon, type, placeholder, ...props }, ref) => {
    const [hasValue, setHasValue] = React.useState(
      Boolean(props.value || props.defaultValue),
    );
    const [showPassword, setShowPassword] = React.useState(false);

    const handleTogglePassword = () => {
      setShowPassword(!showPassword);
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      setHasValue(e.target.value.length > 0);
      if (props.onChange) {
        props.onChange(e);
      }
    };

    return (
      <label
        className={cn(
          "relative block h-fit w-full text-sm group",
          icon ? className : "",
        )}
      >
        {icon && (
          <div className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 transform text-muted-foreground">
            {icon}
          </div>
        )}
        <input
          autoComplete="off"
          type={type === "password" && showPassword ? "text" : type}
          placeholder={placeholder}
          className={cn(
            "primary-input !placeholder-transparent",
            icon && "pl-9",
            icon ? inputClassName : className,
          )}
          ref={ref}
          {...props}
          onChange={handleChange}
        />
        {type === "password" && (
          <button
            type="button"
            className="absolute top-1/2 opacity-0 group-hover:opacity-100 hover:text-primary transition-all right-3 transform -translate-y-1/2 text-sm text-muted-foreground"
            onClick={handleTogglePassword}
          >
            {showPassword ? (
              <Eye className="w-4" />
            ) : (
              <EyeOff className="w-4" />
            )}
          </button>
        )}
        <span
          className={cn(
            "pointer-events-none absolute top-1/2 -translate-y-1/2 pl-px text-placeholder-foreground font-mono",
            icon ? "left-9" : "left-3",
            hasValue && "hidden",
          )}
        >
          {placeholder}
        </span>
      </label>
    );
  },
);

Input.displayName = "Input";

export { Input };
