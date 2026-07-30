# release-ui.ps1 -- animated presenter for scripts\release.bat.
#
# Pure OBSERVER: it launches `release.bat --no-pause` unchanged and renders
# a live checklist + a continuously-moving progress bar from two signals:
#   1. The bat's own "[N/16]" step markers on stdout (step boundaries).
#   2. Time-based animation WITHIN a step, scaled by that step's duration
#      from previous runs (logs\release_timings.json -- self-calibrating,
#      exponential moving average). The in-step fraction is capped at 97%
#      so the bar never claims a step finished before the bat says so.
#      Where the log carries REAL sub-progress (pytest's "[ 45%]" markers,
#      Vitest's per-file check lines), that replaces the time estimate.
#
# The release pipeline itself is untouched -- release.bat alone still works
# exactly as before. If this script's output is redirected (or -NoAnsi is
# passed) it degrades to plain step-per-line logging.
#
# Windows Terminal bonus: OSC 9;4 paints build progress onto the taskbar
# icon (green while running, red on failure). Harmless elsewhere.
#
# NOTE: this source is deliberately pure ASCII -- Windows PowerShell 5.1
# mis-decodes BOM-less UTF-8, and a mangled em dash becomes a smart quote
# that breaks parsing. All glyphs are built from [char] code points.

[CmdletBinding()]
param(
    # Override for testing the presenter against a mock script. Defaults to
    # release.bat next to this script — resolved in the BODY, not here:
    # under `powershell -File` on PS 5.1, $PSScriptRoot is empty while
    # parameter defaults are evaluated.
    [string]$ReleaseScript,
    [switch]$NoAnsi,
    # Test hook: exercise the ANSI renderer even when output is redirected.
    [switch]$ForceAnsi
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ReleaseScript) { $ReleaseScript = Join-Path $ScriptDir 'release.bat' }

$Esc = [char]27
$Bel = [char]7
$Ansi = -not $NoAnsi -and ($ForceAnsi -or -not [Console]::IsOutputRedirected)

# Glyphs (see the ASCII note above).
$GlyphCheck = [char]0x2714   # heavy check mark
$GlyphCross = [char]0x2718   # heavy ballot X
$GlyphPending = [char]0x00B7 # middle dot
$GlyphRule = [string]([char]0x2500) * 58
$BarFill = [char]0x2588      # full block
$BarEmpty = [char]0x2591     # light shade
$VitestCheck = [char]0x2713  # check mark (Vitest per-file marker)
$SpinnerFrames = @(0x280B, 0x2819, 0x2839, 0x2838, 0x283C, 0x2834, 0x2826, 0x2827, 0x2807, 0x280F) |
    ForEach-Object { [string][char]$_ }

# ---------------------------------------------------------------- step model
# Names mirror release.bat's markers; if the bat's step count ever drifts,
# unknown indexes are ignored gracefully (bar still tracks known steps).
$StepNames = @(
    'Checking toolchain'
    'Checking version consistency'
    'Typechecking frontend'
    'Typechecking frontend tests'
    'Typechecking Rust bridge (cargo check)'
    'Running Rust bridge tests (cargo test)'
    'Running backend security audit'
    'Running backend tests'
    'Running frontend tests'
    'Building Python sidecar exe'
    'Building portable desktop exe'
    'Locating packaged executable'
    'Assembling staged desktop/sidecar pair'
    'Running packaged self-test'
    'Running packaged backend self-test'
    'Promoting verified pair to local_build'
)
# First-run duration guesses (seconds); replaced by measured EMA thereafter.
$DefaultDurations = @(2, 3, 9, 9, 20, 40, 6, 90, 45, 90, 180, 1, 2, 12, 15, 2)

$RepoRoot = Split-Path -Parent $ScriptDir
$TimingsPath = Join-Path $RepoRoot 'logs\release_timings.json'

$Timings = @{ steps = @{}; vitestFiles = 0 }
if (Test-Path $TimingsPath) {
    try {
        $raw = Get-Content $TimingsPath -Raw | ConvertFrom-Json
        foreach ($p in $raw.steps.PSObject.Properties) { $Timings.steps[$p.Name] = [double]$p.Value }
        if ($raw.vitestFiles) { $Timings.vitestFiles = [int]$raw.vitestFiles }
    } catch {}
}

$Steps = for ($i = 0; $i -lt $StepNames.Count; $i++) {
    $key = [string]($i + 1)
    $expected = if ($Timings.steps.ContainsKey($key)) { $Timings.steps[$key] } else { $DefaultDurations[$i] }
    [pscustomobject]@{
        Index    = $i + 1
        Name     = $StepNames[$i]
        Status   = 'pending'   # pending | active | done | failed
        Started  = $null
        Duration = $null
        Expected = [math]::Max(0.5, $expected)
        SubPct   = $null       # real sub-progress 0..100 when parseable
    }
}
$TotalSteps = $Steps.Count

# ------------------------------------------------------------------ helpers
function Set-TaskbarProgress([int]$State, [int]$Pct) {
    if ($Ansi) { Write-Host -NoNewline "$Esc]9;4;$State;$Pct$Bel" }
}

function Get-OverallFraction {
    $totalWeight = 0.0; $doneWeight = 0.0
    foreach ($s in $Steps) {
        $totalWeight += $s.Expected
        if ($s.Status -eq 'done') {
            $doneWeight += $s.Expected
        } elseif ($s.Status -eq 'active' -or $s.Status -eq 'failed') {
            $frac = 0.0
            if ($null -ne $s.SubPct) {
                $frac = [math]::Min($s.SubPct / 100.0, 0.99)
            } elseif ($s.Started) {
                $elapsed = ((Get-Date) - $s.Started).TotalSeconds
                $frac = [math]::Min($elapsed / $s.Expected, 0.97)
            }
            $doneWeight += $s.Expected * $frac
        }
    }
    if ($totalWeight -le 0) { return 0.0 }
    [math]::Min($doneWeight / $totalWeight, 1.0)
}

function Format-Elapsed([TimeSpan]$Span) {
    '{0:mm\:ss}' -f $Span
}

function Get-EtaSeconds {
    $remaining = 0.0
    foreach ($s in $Steps) {
        if ($s.Status -eq 'pending') { $remaining += $s.Expected }
        elseif ($s.Status -eq 'active' -and $s.Started) {
            $elapsed = ((Get-Date) - $s.Started).TotalSeconds
            $remaining += [math]::Max($s.Expected - $elapsed, $s.Expected * 0.03)
        }
    }
    $remaining
}

$script:RenderedLines = 0
$script:SpinnerTick = 0
$script:StartTime = Get-Date

function Render([switch]$Final) {
    if (-not $Ansi) { return }
    $script:SpinnerTick++
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("$Esc[1m  RELIABILITY TOOLS DESKTOP - RELEASE$Esc[0m")
    $lines.Add('')
    foreach ($s in $Steps) {
        $name = $s.Name.PadRight(40).Substring(0, 40)
        if ($s.Status -eq 'done') {
            $dur = if ($null -ne $s.Duration) { ('{0,6:0.0}s' -f $s.Duration) } else { '' }
            $lines.Add("  $Esc[32m$GlyphCheck$Esc[0m $name $Esc[2m$dur$Esc[0m")
        } elseif ($s.Status -eq 'failed') {
            $lines.Add("  $Esc[31m$GlyphCross $name$Esc[0m")
        } elseif ($s.Status -eq 'active') {
            $spin = $SpinnerFrames[$script:SpinnerTick % $SpinnerFrames.Count]
            $elapsed = if ($s.Started) { ('{0,5:0}s' -f ((Get-Date) - $s.Started).TotalSeconds) } else { '' }
            $sub = if ($null -ne $s.SubPct) { (' [{0,3:0}%]' -f $s.SubPct) } else { '' }
            $lines.Add("  $Esc[36m$spin$Esc[0m $name $Esc[2m$elapsed$Esc[0m$Esc[36m$sub$Esc[0m")
        } else {
            $lines.Add("  $Esc[2m$GlyphPending $name$Esc[0m")
        }
    }
    $lines.Add("  $GlyphRule")

    $frac = if ($Final) { 1.0 } else { Get-OverallFraction }
    $barWidth = 40
    $filled = [int][math]::Floor($frac * $barWidth)
    $bar = ([string]$BarFill * $filled) + ([string]$BarEmpty * ($barWidth - $filled))
    $pct = '{0,5:0.0}%' -f ($frac * 100)
    $elapsedTotal = Format-Elapsed ((Get-Date) - $script:StartTime)
    $etaText = ''
    if (-not $Final) {
        $eta = Get-EtaSeconds
        if ($eta -gt 1) { $etaText = ' - eta ~' + (Format-Elapsed ([TimeSpan]::FromSeconds($eta))) }
    }
    $lines.Add("  $Esc[36m[$bar]$Esc[0m $pct - elapsed $elapsedTotal$etaText")

    if ($script:RenderedLines -gt 0) {
        Write-Host -NoNewline "$Esc[$($script:RenderedLines)A"
    }
    foreach ($line in $lines) {
        Write-Host "$Esc[2K$line"
    }
    $script:RenderedLines = $lines.Count

    if (-not $Final) {
        Set-TaskbarProgress 1 ([int]($frac * 100))
    }
}

function Write-PlainProgress($Step, [string]$Verb) {
    if ($Ansi) { return }
    $frac = Get-OverallFraction
    Write-Host ('[{0,2}/{1}] {2,-42} {3}  (overall {4:0}%)' -f $Step.Index, $TotalSteps, $Step.Name, $Verb, ($frac * 100))
}

# --------------------------------------------------------------- log tailing
$script:LogPath = $null
$script:LogStream = $null
$script:VitestSeen = 0

function Read-NewLogText {
    if (-not $script:LogPath) { return '' }
    if (-not $script:LogStream) {
        if (-not (Test-Path $script:LogPath)) { return '' }
        try {
            $script:LogStream = [System.IO.FileStream]::new(
                $script:LogPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::ReadWrite)
        } catch { return '' }
    }
    $length = $script:LogStream.Length
    if ($length -le $script:LogStream.Position) { return '' }
    $count = [int]($length - $script:LogStream.Position)
    $buffer = [byte[]]::new($count)
    $read = $script:LogStream.Read($buffer, 0, $count)
    if ($read -le 0) { return '' }
    [System.Text.Encoding]::Default.GetString($buffer, 0, $read)
}

function Update-SubProgress($ActiveStep) {
    $chunk = Read-NewLogText
    if (-not $chunk -or -not $ActiveStep) { return }
    # pytest (backend tests) writes real "[ 45%]" markers as it progresses.
    if ($ActiveStep.Name -eq 'Running backend tests') {
        $found = [regex]::Matches($chunk, '\[\s*(\d{1,3})%\]')
        if ($found.Count -gt 0) {
            $ActiveStep.SubPct = [int]$found[$found.Count - 1].Groups[1].Value
        }
    }
    # Vitest prints one "check path (N tests)" line per completed file;
    # measure against the file count observed on the previous run.
    elseif ($ActiveStep.Name -eq 'Running frontend tests') {
        $script:VitestSeen += ([regex]::Matches($chunk, "$VitestCheck ")).Count
        if ($Timings.vitestFiles -gt 0) {
            $ActiveStep.SubPct = [math]::Min(100, 100 * $script:VitestSeen / $Timings.vitestFiles)
        }
    }
}

# ----------------------------------------------------------------- child bat
if (-not (Test-Path $ReleaseScript)) {
    Write-Error "Release script not found: $ReleaseScript"
    exit 2
}

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = 'cmd.exe'
$psi.Arguments = '/d /c ""' + $ReleaseScript + '" --no-pause"'
$psi.WorkingDirectory = $RepoRoot
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true

$proc = [System.Diagnostics.Process]::new()
$proc.StartInfo = $psi

$MarkerPattern = [regex]'^\[(\d+)/(\d+)\]\s*(.+?)\.{0,3}\s*$'
$TailBuffer = [System.Collections.Generic.List[string]]::new()
$FailureLines = [System.Collections.Generic.List[string]]::new()
$script:ActiveStep = $null

function Complete-Step($Step) {
    if (-not $Step -or $Step.Status -ne 'active') { return }
    $Step.Status = 'done'
    $Step.Duration = ((Get-Date) - $Step.Started).TotalSeconds
    $Step.SubPct = $null
    # EMA so one slow run doesn't wreck the animation for the next.
    $key = [string]$Step.Index
    $old = if ($Timings.steps.ContainsKey($key)) { $Timings.steps[$key] } else { $null }
    if ($null -ne $old) {
        $Timings.steps[$key] = [math]::Round(0.5 * $old + 0.5 * $Step.Duration, 1)
    } else {
        $Timings.steps[$key] = [math]::Round($Step.Duration, 1)
    }
    Write-PlainProgress $Step ('done in {0:0.0}s' -f $Step.Duration)
}

function Save-Timings {
    try {
        if ($script:VitestSeen -gt 0) { $Timings.vitestFiles = $script:VitestSeen }
        $dir = Split-Path -Parent $TimingsPath
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
        @{ steps = $Timings.steps; vitestFiles = $Timings.vitestFiles } |
            ConvertTo-Json | Set-Content -Path $TimingsPath -Encoding UTF8
    } catch {}
}

function Invoke-OutputLine([string]$Line) {
    if ($null -eq $Line) { return }
    $m = $MarkerPattern.Match($Line)
    if ($m.Success) {
        $index = [int]$m.Groups[1].Value
        Complete-Step $script:ActiveStep
        if ($index -ge 1 -and $index -le $Steps.Count) {
            $step = $Steps[$index - 1]
            $step.Status = 'active'
            $step.Started = Get-Date
            $script:VitestSeen = 0
            $script:ActiveStep = $step
        }
        return
    }
    if ($Line -match '^\s*Output log:\s*(.+)$') {
        $script:LogPath = $Matches[1].Trim()
    }
    if ($Line -match '^\[FAILED\]' -and $FailureLines.Count -lt 12) {
        $FailureLines.Add($Line.Trim())
    } elseif ($FailureLines.Count -gt 0 -and $FailureLines.Count -lt 12 -and $Line -match '^\s{9,}\S') {
        # Indented continuation lines that follow a [FAILED] line.
        $FailureLines.Add($Line.Trim())
    }
    if ($Line.Trim() -and $Line -notmatch '^=+$') {
        $TailBuffer.Add($Line.TrimEnd())
        if ($TailBuffer.Count -gt 24) { $TailBuffer.RemoveAt(0) }
    }
}

$exitCode = 1
try {
    if ($Ansi) { Write-Host -NoNewline "$Esc[?25l" }  # hide cursor
    $proc.Start() | Out-Null

    $outTask = $proc.StandardOutput.ReadLineAsync()
    $errTask = $proc.StandardError.ReadLineAsync()
    $outDone = $false; $errDone = $false
    $lastRender = [DateTime]::MinValue

    while (-not ($outDone -and $errDone)) {
        $progressed = $false
        if (-not $outDone -and $outTask.Wait(0)) {
            $line = $outTask.Result
            if ($null -eq $line) { $outDone = $true }
            else { Invoke-OutputLine $line; $outTask = $proc.StandardOutput.ReadLineAsync() }
            $progressed = $true
        }
        if (-not $errDone -and $errTask.Wait(0)) {
            $line = $errTask.Result
            if ($null -eq $line) { $errDone = $true }
            else { Invoke-OutputLine $line; $errTask = $proc.StandardError.ReadLineAsync() }
            $progressed = $true
        }
        $now = Get-Date
        if (($now - $lastRender).TotalMilliseconds -ge 120) {
            Update-SubProgress $script:ActiveStep
            Render
            $lastRender = $now
        }
        if (-not $progressed) { Start-Sleep -Milliseconds 40 }
    }

    $proc.WaitForExit()
    $exitCode = $proc.ExitCode

    if ($exitCode -eq 0) {
        Complete-Step $script:ActiveStep
        Render -Final
        Set-TaskbarProgress 0 0
    } else {
        if ($script:ActiveStep -and $script:ActiveStep.Status -eq 'active') {
            $script:ActiveStep.Status = 'failed'
        }
        Render
        Set-TaskbarProgress 2 100
    }
} finally {
    if ($proc -and -not $proc.HasExited) {
        # Kill the whole cmd tree (npm/cargo/pytest children) on Ctrl+C.
        & taskkill /PID $proc.Id /T /F *> $null
    }
    if ($script:LogStream) { $script:LogStream.Dispose() }
    if ($Ansi) { Write-Host -NoNewline "$Esc[?25h" }  # show cursor
    Save-Timings
}

Write-Host ''
if ($exitCode -eq 0) {
    Write-Host "$Esc[32m$GlyphCheck Release succeeded in $(Format-Elapsed ((Get-Date) - $script:StartTime)).$Esc[0m"
} else {
    Write-Host "$Esc[31m$GlyphCross Release FAILED (exit $exitCode).$Esc[0m"
    foreach ($line in $FailureLines) { Write-Host "  $line" }
}
foreach ($line in ($TailBuffer | Select-Object -Last 10)) { Write-Host "  $Esc[2m$line$Esc[0m" }
exit $exitCode
