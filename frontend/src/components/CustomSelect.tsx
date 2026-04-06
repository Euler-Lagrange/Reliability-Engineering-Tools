import { CaretDown, Check } from "@phosphor-icons/react";
import * as Select from "@radix-ui/react-select";

export interface CustomSelectOption {
  value: string;
  label: string;
}

interface CustomSelectProps {
  label: string;
  value: string;
  options: CustomSelectOption[];
  onChange?: (value: string) => void;
  disabled?: boolean;
  compact?: boolean;
}

export function CustomSelect({
  label,
  value,
  options,
  onChange,
  disabled = false,
  compact = false,
}: CustomSelectProps) {
  const selected = options.find((option) => option.value === value) ?? options[0];

  return (
    <Select.Root value={selected?.value ?? value} onValueChange={onChange} disabled={disabled}>
      <Select.Trigger
        className={`custom-select__trigger${compact ? " custom-select__trigger--compact" : ""}`}
        aria-label={label}
      >
        <span className="custom-select__value">{selected?.label ?? value}</span>
        <Select.Icon className="custom-select__chevron">
          <CaretDown size={12} weight="bold" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="custom-select__menu" position="popper" sideOffset={6}>
          <Select.Viewport>
            {options.map((option) => (
              <Select.Item key={option.value} value={option.value} className="custom-select__option">
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="custom-select__indicator">
                  <Check size={12} weight="bold" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
