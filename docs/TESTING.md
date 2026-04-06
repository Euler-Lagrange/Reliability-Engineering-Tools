# Tauri Build Testing

## Frontend

```powershell
cd C:\Reliability_Eng_Tools_Dev\tauri_build
npm test
npm run typecheck
```

## Backend

```powershell
cd C:\Reliability_Eng_Tools_Dev
.\.venv\Scripts\python.exe -m pytest tauri_build\backend\tests -q
```

## Desktop

```powershell
cd C:\Reliability_Eng_Tools_Dev\tauri_build
npm run tauri:build:portable
npm run release
```

## Current Baseline

- Suite shell with active-tool navigation
- Theme switching
- Accessible select and progress semantics
- Python sidecar scaffold with `health_check` and `list_sheets`
