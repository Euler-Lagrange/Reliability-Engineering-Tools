import { useId } from "react";
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
  /**
   * Short caption rendered below the trigger when the select is disabled.
   * Exposed via `aria-describedby` so assistive tech announces *why* the
   * control is inert instead of just skipping it.
   */
  disabledReason?: string;
  /**
   * Muted hint shown when `value` is empty — a blank trigger reads as
   * broken. Opt-in per call site: mapping dropdowns want "Select column…",
   * but input-card sheet pickers legitimately render empty while sheets
   * resolve and must NOT claim a selection is expected yet.
   */
  placeholder?: string;
}

export function CustomSelect({
  label,
  value,
  options,
  onChange,
  disabled = false,
  compact = false,
  disabledReason,
  placeholder,
}: CustomSelectProps) {
  // If `value` is not among `options`, show the raw value rather than silently
  // masquerading it as options[0] (which also desynced Radix's displayed value
  // from the parent's controlled value).
  const selected = options.find((option) => option.value === value);
  const reasonId = useId();
  const showReason = disabled && !!disabledReason;

  return (
    <div className="custom-select">
      <Select.Root value={value} onValueChange={onChange} disabled={disabled}>
        <Select.Trigger
          className={`custom-select__trigger${compact ? " custom-select__trigger--compact" : ""}`}
          aria-label={label}
          aria-describedby={showReason ? reasonId : undefined}
        >
          <span className="custom-select__value">
            {(selected?.label ?? value) === "" && placeholder ? (
              <span className="custom-select__placeholder">{placeholder}</span>
            ) : (
              selected?.label ?? value
            )}
          </span>
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
      {showReason ? (
        <p id={reasonId} className="custom-select__disabled-reason">
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}
