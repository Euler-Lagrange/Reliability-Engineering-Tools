# Example inputs

This folder is reserved for tool example fixtures linked from each tool's
empty-state "Load example" action. Real example workbooks are not yet
shipped — on the desktop runtime the buttons surface a truthful
"coming soon" notification, and in browser preview they reveal the staged
mock scenario instead of loading a real file.

When example fixtures land they should match these names:

| File | Used by | Notes |
|---|---|---|
| `fmea-example.xlsx` | FMEA Generator | Workbook with grouping/BOM/failure-mode sheets that exercise piece-part generation. |
| `bom-compare-a.xlsx` | BOM Compare | First BOM in a custom-mode comparison. |
| `bom-compare-b.xlsx` | BOM Compare | Second BOM aligned to the first for diff demonstration. |
| `failure-rate-example.xlsx` | Failure Rate | Parts list ready for failure-rate enrichment. |
| `refdes-example.pdf` | RefDes Extractor | Schematic PDF with reference designators on multiple pages. |

Until real fixtures exist, the desktop "Load example" button calls
`useNotificationStore.push` with an "Example files coming soon" toast so
the wiring is in place but no broken loader can ship; browser preview
reveals the mock-scenario demo content instead (no file is read either way).
