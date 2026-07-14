import { useEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import { useEscapeLayer } from "../../shared/hooks/useEscapeLayer";

/**
 * In-app User Guide — a full-screen, theme-aware help overlay launched from
 * Settings. Successor to the legacy Flet app's stylized HTML help page: a
 * sticky section nav on the left "hops around" the document on the right.
 *
 * Content is adapted from docs/USER_GUIDE.md (the canonical manual — keep
 * the two in sync when tool behavior changes). Everything renders from the
 * design-system tokens, so all 11 themes style it automatically, and the
 * overlay participates in the shared Escape dismiss-stack.
 */

interface HelpGuideProps {
  open: boolean;
  onClose: () => void;
}

interface HelpTableProps {
  head: string[];
  rows: ReactNode[][];
}

function HelpTable({ head, rows }: HelpTableProps) {
  return (
    <div className="help-guide__table-wrap">
      <table className="help-guide__table">
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, rowIndex) => (
            <tr key={rowIndex}>
              {cells.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Callout({ children }: { children: ReactNode }) {
  return <p className="help-guide__callout">{children}</p>;
}

interface GuideSection {
  id: string;
  navLabel: string;
  title: string;
  body: ReactNode;
}

const SECTIONS: GuideSection[] = [
  {
    id: "getting-started",
    navLabel: "Getting started",
    title: "Getting started",
    body: (
      <>
        <p>
          Reliability Tools Desktop bundles five tools behind one window. Pick a
          tool in the left sidebar (or <kbd>Ctrl+1</kbd>–<kbd>Ctrl+5</kbd>,{" "}
          <kbd>Ctrl+[</kbd> / <kbd>Ctrl+]</kbd>, or the command palette{" "}
          <kbd>Ctrl+K</kbd>). Each tool loads Excel/PDF inputs, validates them,
          runs the offline Python engine, and writes a styled <code>.xlsx</code>{" "}
          report.
        </p>
        <HelpTable
          head={["Tool", "What it does", "Inputs"]}
          rows={[
            [<strong key="t">FMEA Generator</strong>, "Builds or merges a piece-part FMEA workbook", "Grouping / BOM / Failure Modes / Functional or existing FMEA / HDA"],
            [<strong key="t">BOM Comparison Tool</strong>, "Diffs grouping-vs-BOM, two BOMs, or two extraction outputs", "Two workbooks"],
            [<strong key="t">Failure Rate Integration</strong>, "Links predicted failure rates onto FMEA failure modes", "Prediction workbook + FMEA workbook"],
            [<strong key="t">RefDes Extractor</strong>, "Pulls reference designators out of an annotated schematic PDF", "Schematic PDF (+ optional BOM / pinlist)"],
            [<strong key="t">Settings</strong>, "Themes, logs, backend health, RefDes prefix editor, this guide", "—"],
          ]}
        />
        <h3>Concepts you will see in every tool</h3>
        <ul>
          <li>
            <strong>Workflow cards.</strong> The first card offers the mode
            choices. The rest of the screen — which inputs appear, which options
            apply — changes with your pick.
          </li>
          <li>
            <strong>Input cards with Required chips.</strong> Each input is a
            card with a Browse button and (for Excel) a sheet dropdown. An
            unloaded card shows a <em>Required</em> chip when the current
            workflow needs it. Empty required cards block the run — the app
            never runs against a fake or example path.
          </li>
          <li>
            <strong>Column mapping.</strong> A mapping table pairs each field
            the tool needs with a dropdown of the actual headers read from your
            file. Required rows carry a red <code>*</code>. Every dropdown
            includes <em>— Do Not Map —</em>; choosing it on a required field
            blocks the run rather than silently guessing. Optional rows may be
            left unmapped and are auto-detected.
          </li>
          <li>
            <strong>Review / Run panel.</strong> The right-side panel toggles
            between Preview (sample rows + validation messages) and Run (live
            progress and the result). <kbd>Ctrl+R</kbd> opens the review
            drawer.
          </li>
          <li>
            <strong>Output folder.</strong> Defaults to the folder of your
            first loaded input. An unusable chosen folder never fails the run —
            it falls back to the default with a warning.
          </li>
          <li>
            <strong>One run at a time.</strong> Starting a second run anywhere
            in the app while one is live shows{" "}
            <em>&ldquo;Another run is active&rdquo;</em> and blocks safely.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "fmea",
    navLabel: "FMEA Generator",
    title: "FMEA Generator",
    body: (
      <>
        <p>
          Builds a piece-part FMEA from your design data, or merges new
          piece-part rows into an existing FMEA. Start button:{" "}
          <strong>Generate FMEA</strong>.
        </p>
        <h3>Modes — pick the card that matches your source data</h3>
        <HelpTable
          head={["Mode", "When to pick it", "Required inputs"]}
          rows={[
            [<strong key="m">Merge Functional FMEA</strong>, "Expand a functional-level FMEA to piece-part rows", "Functional FMEA, BOM, Failure Modes"],
            [<strong key="m">Merge Piece-Part FMEA</strong>, "Fill gaps / union components into an existing piece-part FMEA", "Existing FMEA, BOM, Failure Modes"],
            [<strong key="m">Piece-Part from Grouping File</strong>, "Fresh build with the richest inputs", "Grouping, BOM, Failure Modes"],
            [<strong key="m">Piece-Part from BOM Only</strong>, "Minimal build under one CCA identifier", "BOM, Failure Modes, CCA Identifier"],
          ]}
        />
        <ul>
          <li>
            <strong>Failure Modes Standard</strong> (FMD-91 / FMD-2016) drives
            the commodity-type labels in mapping and failure-mode lookups.
            Switching keeps your manual commodity mappings.
          </li>
          <li>
            <strong>HDA source</strong>: Inline in BOM (default) or a Separate
            HDA file. Choosing Separate without attaching a file blocks the run.
          </li>
          <li>
            <strong>CCA Identifier</strong> (BOM-Only, required): prefix for
            generated FMEA-IDs — <code>PSU</code> produces{" "}
            <code>PSU-C200-A</code>. 1–8 uppercase letters, digits, or hyphens.
          </li>
          <li>
            <strong>Output strategy</strong>: New Workbook (fresh, simplest to
            review) or Existing Workbook / Preserve Formatting (rows merged into
            a copy of your FMEA; formatting kept, new columns appended at the
            far right).
          </li>
          <li>
            <strong>Part Usage</strong>: leave unmapped to auto-count instances.
            If you map it and it disagrees with the computed count, the row is
            flagged and listed on the Part Usage Diagnostics sheet.
          </li>
        </ul>
        <h3>Reading the output</h3>
        <p>
          The main <strong>FMEA</strong> sheet shades rows by type: grey Circuit
          Block headers, plain Piece-Part rows, <strong>yellow</strong> rows
          carrying an FMR / Part-Usage flag, <strong>red</strong> rows that
          matched no failure mode. Diagnostic sheets appear only when they have
          content, and each opens with a banner explaining itself:
        </p>
        <HelpTable
          head={["Sheet", "Meaning"]}
          rows={[
            [<code key="s">No_Matches</code>, "RefDes with no failure-mode match (with the reason)."],
            [<code key="s">Validation_Warnings</code>, "FMR-sum and Part-Usage issues, each with a plain-language Reason Code."],
            [<code key="s">FMEA Gen New RefDes</code>, "Variants found in the source but not the BOM, with inherited data — a paste-back list for your BOM."],
            [<code key="s">Part Usage Diagnostics</code>, "Mapped vs computed instance counts (Diff = Computed − Mapped)."],
            [<code key="s">Template_Merge_Summary</code>, "Preserve-mode merge counts + a legend for the two Diagnostic flags: NOT IN BOM - Review and NEW - Added by generator."],
          ]}
        />
        <h3>Limitations to know</h3>
        <ul>
          <li>
            Preserve-Formatting appends any new generator columns at the far
            right of your sheet — it never reorders your existing columns.
          </li>
          <li>
            Cell-level rich-text runs are flattened to plain cell text when the
            copied workbook is loaded and saved.
          </li>
          <li>
            Template analysis caps the target workbook at 50&nbsp;MB to protect
            memory.
          </li>
          <li>
            Merge modes require the <strong>Failure Mode Causes</strong> mapping
            — group membership is parsed from that column&rsquo;s
            comma-separated RefDes lists.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "bom-compare",
    navLabel: "BOM Comparison",
    title: "BOM Comparison Tool",
    body: (
      <>
        <p>Three comparison styles, selected in the Run Setup card:</p>
        <HelpTable
          head={["Workflow", "Compares", "Notes"]}
          rows={[
            [<strong key="w">Group vs BOM</strong>, "A grouping sheet against a BOM — coverage in both directions", "All options apply"],
            [<strong key="w">Custom Compare</strong>, "Any two BOMs by RefDes key", "Adds per-column value diffs (auto-paired matching headers, Text / Text exact / Numeric rules)"],
            [<strong key="w">Extraction Compare</strong>, "Two RefDes-extraction outputs (rev A vs rev B)", "Fixed schema — no mappings or options; reports Appeared / Disappeared / Moved Groups"],
          ]}
        />
        <h3>Options</h3>
        <ul>
          <li>
            <strong>Ignore DNP rows</strong> (on) — skip Do-Not-Populate rows.{" "}
            <strong>Check Part Usage</strong> (on) — emit Part Usage warnings.{" "}
            <strong>Check Failure Mode Ratios</strong> — add a
            Failure-Mode-Ratio check sheet.
          </li>
          <li>
            <strong>Loose prefix base match</strong> — base-RefDes matching is
            always on; this adds fuzzy prefix coverage (no effect with exact
            match). <strong>Exact match</strong> — compare tokens verbatim.
          </li>
          <li>
            <strong>Treat PROV as covered</strong> — Group vs BOM only; treats
            PROV groups as covered.
          </li>
          <li>
            FMEA-aware checks (Scope Warnings sheet, composite duplicate
            identity) turn on when a file is recognized as an FMEA — by
            filename <em>or</em> by a validated FMEA Level column in its
            content, so a renamed FMEA export is still recognized.
          </li>
        </ul>
        <h3>Limitations to know</h3>
        <ul>
          <li>
            <strong>Hyphens are pins, never ranges.</strong>{" "}
            <code>U200-1</code> means pin 1 of U200; tokens reduce to their base
            for matching. The tool never expands <code>R200-R205</code> into a
            range.
          </li>
          <li>
            Extraction Compare needs real RefDes-extraction outputs — a
            non-extraction sheet blocks with a message naming the missing
            column. Verified/Unverified suffix changes never read as churn.
          </li>
          <li>
            An empty or wrong sheet blocks up front (e.g.{" "}
            <em>&ldquo;File 1: the selected sheet has no data rows&rdquo;</em>)
            — pick the sheet that actually holds the parts.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "failure-rate",
    navLabel: "Failure Rate",
    title: "Failure Rate Integration",
    body: (
      <>
        <p>
          Links predicted component failure rates onto FMEA failure modes and
          allocates a per-mode rate. Start button: <strong>Link Rates</strong>.
          Requires a Prediction workbook (RefDes + rate) and an FMEA workbook;
          five mappings are required, and the optional{" "}
          <strong>Function column</strong> enables circuit-block roll-ups.
        </p>
        <ul>
          <li>
            <strong>Failure rate unit</strong> — Per hour / Per million hours /
            Per billion hours (converted to per-hour before the math).
          </li>
          <li>
            Output adds <code>Mode_FR</code> (part rate × FMR × usage),{" "}
            <code>Function_FR</code> (roll-up when a Function column is mapped),
            and a <code>Validation_Notes</code> column.
          </li>
        </ul>
        <h3>Reading Validation_Notes</h3>
        <HelpTable
          head={["Note", "Meaning"]}
          rows={[
            [<code key="n">RefDes not in Prediction</code>, "No prediction row matched — Mode_FR is 0."],
            [<code key="n">Part Usage missing — Mode_FR left blank; verify</code>, "A genuine usage gap on a real-rate row. Mode_FR is intentionally blank, never overstated as ×1.0. Fill the usage and re-run."],
            [<code key="n">Circuit-block roll-up of N piece-part row(s)</code>, "Informational, not a warning: the block's rate is the sum of its children. “may be understated” means blank-usage children were skipped."],
            [<code key="n">Failure Mode Ratio Sum … does not equal 1.0</code>, "The part's ratios don't total 1.0 (with the Validate FMR option)."],
          ]}
        />
        <h3>Limitations to know</h3>
        <ul>
          <li>
            The join key is the RefDes in <strong>Failure Mode Causes</strong> —
            multi-RefDes cells roll up by their listed components.
          </li>
          <li>
            Your original FMEA text ships verbatim — only the tool&rsquo;s own
            notes column carries generated wording.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "refdes",
    navLabel: "RefDes Extractor",
    title: "RefDes Extractor",
    body: (
      <>
        <p>
          Pulls reference designators out of an annotated schematic PDF and
          optionally cross-checks them against a BOM. Only the PDF is required;
          adding a BOM enables verification and the coverage sheets.
        </p>
        <ul>
          <li>
            <strong>Extraction mode</strong> — Functional groups components by
            annotation boxes; Piece-Part additionally qualifies individual pins
            (with the optional pinlist).
          </li>
          <li>
            <strong>Backend</strong> — Auto (recommended) runs the NextGen
            engine with Legacy fallback.
          </li>
          <li>
            <strong>Geometry analysis</strong> + adaptive page gating qualify
            pins by vector geometry; the Advanced section tunes batch size,
            distances, and thresholds — every field has a tooltip, all 16
            options are range-checked before the run, and defaults are safe.
          </li>
        </ul>
        <h3>Reading the output</h3>
        <ul>
          <li>
            With a BOM, each group emits <strong>two rows</strong>:{" "}
            <code>X (Verified)</code> (components found in the BOM) and{" "}
            <code>X (Unverified)</code>. Without a BOM everything is
            Unverified.
          </li>
          <li>
            <strong>Component Detail</strong> lists per-component provenance
            with a legend: Source = geometry / parent-refdes / box-text /
            pinlist-cluster / unqualified; Confidence is a 0–1 score.
          </li>
          <li>
            <strong>Orphan Pins</strong> records every pin dropped before
            output with a disposition and detail.
          </li>
          <li>
            BOM coverage sheets show which BOM parts were never grouped
            (Not Extracted / Extracted-Ungrouped / Extracted-Provisional) and
            which extracted RefDes are not in the BOM.
          </li>
        </ul>
        <h3>Limitations to know</h3>
        <ul>
          <li>
            The PDF must be a vector schematic with annotation group boxes —
            scanned images will not extract.
          </li>
          <li>
            A hyphenated token is a <strong>pin</strong> (<code>U92-2</code> =
            pin 2 of U92), never a range.
          </li>
          <li>
            Custom RefDes prefixes (Settings) apply <strong>after an app
            restart</strong>.
          </li>
          <li>
            If the BOM fails to load, the run still completes but the title
            says <em>BOM cross-check FAILED</em> and everything is marked NOT
            IN BOM — fix the BOM input and re-run.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "settings",
    navLabel: "Settings",
    title: "Settings",
    body: (
      <>
        <HelpTable
          head={["Card", "What it holds"]}
          rows={[
            [<strong key="c">Theme</strong>, "11 themes; selection is immediate and remembered."],
            [<strong key="c">Logs</strong>, <>The sidecar log directory with Copy path / Open folder. Default <code>~/.reliability_tools/logs/</code>.</>],
            [<strong key="c">Backend Diagnostics</strong>, "Run health check — backend name, protocol version, ping latency."],
            [<strong key="c">RefDes Prefixes</strong>, "Custom prefixes (1–5 letters) extending the IEEE-315 defaults the extractor recognizes. Changes apply after restart. A corrupt config file shows a warning instead of silently resetting."],
            [<strong key="c">User Guide</strong>, "This page."],
          ]}
        />
      </>
    ),
  },
  {
    id: "troubleshooting",
    navLabel: "Troubleshooting",
    title: "Troubleshooting",
    body: (
      <>
        <h3>Run blocked</h3>
        <p>
          The Start button turns the validation result into a toast and
          highlighted cards — the sentence names exactly what to fix:
        </p>
        <HelpTable
          head={["Message", "Meaning"]}
          rows={[
            [<code key="m">Select required files: …</code>, "A required input card is empty."],
            [<code key="m">Load current files and sheets for: …</code>, "A file is picked but its sheet isn't resolved yet."],
            [<code key="m">Missing required mappings: …</code>, "A required column is unmapped."],
            [<code key="m">Required mappings cannot use 'Do Not Map': …</code>, "A required column is set to — Do Not Map —. Pick a real column."],
            [<code key="m">Another run is active</code>, "A run is live somewhere in the app; wait or cancel it from that tool."],
          ]}
        />
        <h3>Backend disconnected</h3>
        <p>
          The Python engine heartbeats every 5 seconds; if it stops, the app
          reports the disconnect and auto-reconnects with backoff. A live run
          does not survive a full disconnect — re-run once reconnected. Confirm
          health under Settings → Backend Diagnostics.
        </p>
        <h3>Crash dumps</h3>
        <p>
          Unhandled errors write a timestamped file under{" "}
          <code>~/.reliability_tools/logs/crashes/</code>. Every dump opens
          with a review-before-sharing banner because a crash can echo BOM /
          part values — read it before sending it on. Only the newest 20 are
          kept.
        </p>
        <Callout>
          &ldquo;N warning(s) captured in the output workbook&rdquo; on a
          success toast is not a failure — the workbook was written; open its
          diagnostic sheets to review the flagged rows.
        </Callout>
      </>
    ),
  },
  {
    id: "faq",
    navLabel: "FAQ",
    title: "FAQ",
    body: (
      <>
        <h3>Why is Mode_FR blank for some rows?</h3>
        <p>
          Part Usage was a genuine gap on a row with a real predicted rate. The
          tool leaves it blank and flags it rather than overstating it as
          ×1.0. Fill in the usage and re-run.
        </p>
        <h3>Why did my RefDes group come out (Unverified)?</h3>
        <p>
          Groups split Verified/Unverified by whether each component was found
          in the loaded BOM. No BOM → everything Unverified. &ldquo;BOM
          cross-check FAILED&rdquo; in the title → the BOM didn&rsquo;t load;
          fix that input.
        </p>
        <h3>Why did a hyphenated designator become a pin, not a range?</h3>
        <p>
          By design: <code>U92-2</code> means component U92, pin 2. Neither the
          extractor nor BOM Compare ever expands hyphens into ranges.
        </p>
        <h3>Where do my outputs go?</h3>
        <p>
          To the Output Folder you set, or the folder of your first loaded
          input by default. An unwritable folder falls back to that default
          with a warning.
        </p>
        <h3>Do settings changes apply immediately?</h3>
        <p>
          Themes, yes. RefDes prefix changes require an app restart (the
          recognition patterns compile at startup).
        </p>
      </>
    ),
  },
];

export function HelpGuide({ open, onClose }: HelpGuideProps) {
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});

  useEscapeLayer(open, onClose);

  useEffect(() => {
    if (open) {
      headingRef.current?.focus();
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const jumpTo = (id: string) => {
    // jsdom has no scrollIntoView; guard so tests can exercise the nav.
    sectionRefs.current[id]?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="help-guide" role="dialog" aria-modal="true" aria-label="User guide">
      <header className="help-guide__header">
        <div>
          <p className="eyebrow">Help</p>
          <h1 tabIndex={-1} ref={headingRef}>
            User Guide
          </h1>
        </div>
        <button
          type="button"
          className="ghost-button"
          onClick={onClose}
          aria-label="Close user guide"
        >
          <X size={16} weight="regular" /> Close
        </button>
      </header>
      <div className="help-guide__body">
        <nav className="help-guide__nav" aria-label="Guide sections">
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              type="button"
              className="help-guide__nav-link"
              onClick={() => jumpTo(section.id)}
            >
              {section.navLabel}
            </button>
          ))}
        </nav>
        <main className="help-guide__content">
          {SECTIONS.map((section) => (
            <section
              key={section.id}
              id={`help-${section.id}`}
              ref={(node) => {
                sectionRefs.current[section.id] = node;
              }}
              className="help-guide__section"
            >
              <h2>{section.title}</h2>
              {section.body}
            </section>
          ))}
          <p className="help-guide__footer">
            The full manual also ships as <code>docs/USER_GUIDE.md</code> in the
            repository.
          </p>
        </main>
      </div>
    </div>
  );
}
