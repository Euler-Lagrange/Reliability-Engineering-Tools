# Performance Baselines — 2026-07-07 (post-v0.4.8)

Measured with `scripts/perf_probe.py` (synthetic data — fake RefDes/part
numbers, no design content) on the dev machine, project venv, in-process
execute paths. Re-run after any change to the writers, styling, or the
generation loops and compare.

## 5,000 synthetic parts (≈10.6k output rows for FMEA)

| Path | Before | After | Notes |
|------|-------:|------:|-------|
| FMEA `piece_part_generate` | 55.2 s | **29.2 s** | see fixes below |
| BOM Compare group | 5.7 s | 5.2 s | already healthy |
| Failure Rate link | 4.4 s | 3.3 s | already healthy |
| FMEA cancellation latency | **never fired** | **1.1 s** | was a real bug |
| FMEA peak memory | +100 MB | +100 MB | linear with rows |

## What was found and fixed (2026-07-07 probe session)

1. **openpyxl per-cell style hashing** — `style_worksheet` assigned
   Font/Fill/Border objects per cell; every assignment re-hashes the full
   style (5.3M hash calls at 5k rows; 77% of the whole FMEA run). Now the
   first cell of each distinct (font, fill) combo is styled through the
   public descriptors and later cells are stamped with cheap `StyleArray`
   copies (`common/excel_styles.py`; copies are mandatory — openpyxl
   mutates `_style` in place, guarded by `test_style_array_stamp_is_not_shared`).
2. **Double per-row `df.iloc`** — `write_excel_report`'s row-style callback
   materialized a full Series per row on top of `style_worksheet`'s own;
   now a precomputed `row_types` list.
3. **Cancellation dead zone** — the write phase (~60-77% of a large run)
   had zero cancel coverage: generation finished ~1.4s into a 33s run and
   the Cancel button did nothing afterwards. `write_excel_report` now
   checks between phases and threads `cancel_check` into every
   `style_worksheet` call (`test_write_excel_report_honors_cancellation`).

## Known residual windows (accepted)

- `wb.save()` is an atomic ~8 s (5k rows) window with no cancel check —
  openpyxl offers no hook; the run cancels immediately before or after.
- `write_df_to_sheet` value-writing has no internal cancel check (a few
  seconds at 5k rows); bracketed by checks on both sides.
- Larger wins (lxml serializer, `write_only` workbooks) would add a
  dependency / restructure the style-after-write pattern — revisit only if
  real-board sizes make the current numbers painful.

## How to re-run

```powershell
.venv\Scripts\python.exe scripts\perf_probe.py --rows 5000
.venv\Scripts\python.exe scripts\perf_probe.py --rows 20000
```

## 20,000 synthetic parts (scaling check — all ~linear, no quadratic blowup)

| Path | 20k parts | vs 5k | Peak memory |
|------|----------:|------:|------------:|
| FMEA `piece_part_generate` | 126.9 s | 4.3× | +400 MB |
| BOM Compare group | 22.3 s | 4.3× | +36 MB |
| Failure Rate link | 12.6 s | 3.8× | +17 MB |
| FMEA cancellation latency | **0.65 s** | — | — |

Memory scales ~20 KB/part on the FMEA path — a hypothetical 100k-part
board would peak around 2 GB. If boards that size ever become real,
revisit the write path (openpyxl `write_only` mode / lxml) before then.
