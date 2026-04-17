export const OPEN_FOLDER_LABEL = "Open folder";

export function parentDirectoryForPath(path: string): string {
  const trimmed = path.trim().replace(/[\\/]+$/, "");
  const lastSeparator = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  if (lastSeparator <= 0) {
    return trimmed;
  }
  if (lastSeparator === 2 && /^[A-Za-z]:/.test(trimmed)) {
    return trimmed.slice(0, 3);
  }
  return trimmed.slice(0, lastSeparator);
}
