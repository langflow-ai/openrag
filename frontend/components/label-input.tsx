import { LabelWrapper } from "./label-wrapper";
import { Input } from "./ui/input";

export function LabelInput({
  label,
  helperText,
  id,
  required,
  ...props
}: {
  label: string;
  helperText: string;
  id: string;
  required: boolean;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <LabelWrapper
      label={label}
      helperText={helperText}
      id={id}
      required={required}
      disabled={props.disabled}
    >
      <Input id={id} {...props} />
    </LabelWrapper>
  );
}
