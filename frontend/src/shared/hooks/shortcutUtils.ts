function detectedPlatform(): string {
  if (typeof navigator === "undefined") {
    return "";
  }
  const navWithUAData = navigator as Navigator & {
    userAgentData?: {
      platform?: string;
    };
  };
  if (typeof navWithUAData.userAgentData?.platform === "string") {
    return navWithUAData.userAgentData.platform;
  }
  return navigator.platform ?? "";
}

export function isApplePlatform(platform = detectedPlatform()): boolean {
  return /mac|iphone|ipad|ipod/i.test(platform);
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  if (target.isContentEditable) {
    return true;
  }
  const role = target.getAttribute("role");
  return role === "textbox" || role === "searchbox" || role === "combobox";
}

export function hasPrimaryModifier(
  event: Pick<KeyboardEvent, "ctrlKey" | "metaKey">,
  platform = detectedPlatform(),
): boolean {
  return isApplePlatform(platform) ? event.metaKey : event.ctrlKey;
}

export function matchesPrimaryShortcut(
  event: Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "shiftKey" | "altKey" | "key">,
  key: string,
  options?: {
    platform?: string;
    allowShift?: boolean;
  },
): boolean {
  if (!hasPrimaryModifier(event, options?.platform)) {
    return false;
  }
  if (!options?.allowShift && event.shiftKey) {
    return false;
  }
  if (event.altKey) {
    return false;
  }
  return event.key.toLowerCase() === key.toLowerCase();
}

/**
 * Alt-only chord (⌥L / Alt+D). Deliberately rejects Ctrl/Cmd so it can
 * never collide with AltGr (= Ctrl+Alt on many international layouts)
 * or a primary-modifier shortcut.
 */
export function matchesAltShortcut(
  event: Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "shiftKey" | "altKey" | "key">,
  key: string,
): boolean {
  if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
    return false;
  }
  return event.key.toLowerCase() === key.toLowerCase();
}

export function primaryShortcutLabel(key: string, platform = detectedPlatform()): string {
  const modifier = isApplePlatform(platform) ? "Cmd" : "Ctrl";
  return `${modifier}+${key}`;
}
