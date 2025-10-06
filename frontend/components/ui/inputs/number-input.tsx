import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "../button";
import { Input } from "../input";
import { Minus, Plus } from "lucide-react";

interface NumberInputProps {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  unit: string;
  min?: number;
  max?: number;
  disabled?: boolean;
}

export const NumberInput = ({
  id,
  label,
  value,
  onChange,
  min = 1,
  max,
  disabled,
  unit,
}: NumberInputProps) => {
  return (
    <LabelWrapper id={id} label={label}>
      <div className="relative">
        <Input
          id="chunk-size"
          type="number"
          disabled={disabled}
          max={max}
          min={min}
          value={value}
          onChange={(e) => onChange(parseInt(e.target.value) || 0)}
          className="w-full pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        />
        <div className="absolute inset-y-0 right-0 top-0 p-[1px] py-[1.5px] flex items-center ">
          <span className="text-sm text-placeholder-foreground mr-4 pointer-events-none">
            {unit}
          </span>
          <div className="flex flex-col mt-[2px] mb-[2px]">
            <Button
              aria-label={`Increase ${label} value`}
              className="h-5 rounded-l-none rounded-br-none border-input border-t-transparent border-r-transparent border-b-[0.5px] hover:border-t-[.5px] hover:border-foreground"
              variant="outline"
              size="iconSm"
              onClick={() => onChange(value + 1)}
            >
              <Plus
                className="text-muted-foreground hover:text-foreground"
                size={8}
              />
            </Button>
            <Button
              aria-label={`Decrease ${label} value`}
              className="h-5 rounded-l-none rounded-tr-none border-input border-b-transparent border-r-transparent hover:border-b-1 hover:border-b-[.5px] hover:border-foreground"
              variant="outline"
              size="iconSm"
              onClick={() => onChange(value - 1)}
            >
              <Minus
                className="text-muted-foreground hover:text-foreground"
                size={8}
              />
            </Button>
          </div>
        </div>
      </div>
    </LabelWrapper>
  );
};
