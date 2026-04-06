"""
Centralized Reference Designator parsing and normalization utilities.

This module provides a unified set of functions for handling RefDes (Reference Designator)
strings across all reliability engineering tools. It consolidates functionality previously
duplicated across bom_compare_logic.py, failure_rate_logic.py, and fmea_generator_logic.py.
"""
import re
from typing import List, Optional, Set

# Pre-compiled regex patterns (compiled once at module load for performance)
TOKEN_SPLIT_REGEX = re.compile(r"[,\s;|\n]+")
BASE_REFDES_PATTERN = re.compile(r"\b([A-Z]{1,6}\d{1,5}[A-Z]?)\b", re.I)
INSTANCE_REFDES_PATTERN = re.compile(
    r"\b([A-Z0-9]+(?:-[A-Z0-9/]+)+)\b|\b([A-Z]{1,6}\d{1,5}[A-Z]?)\b", re.I
)
# Range pattern supports: hyphen-minus (-), en-dash (–), em-dash (—), and ellipsis (..)
# Using explicit Unicode escapes for reliability across different file encodings
RANGE_PATTERN = re.compile(
    r'^([A-Z]+)(\d+)\s*(?:-|\u2013|\u2014|\.\.)\s*([A-Z]+)?(\d+)$', re.I
)
PIN_PATTERN = re.compile(r'^([A-Z]+)(\d+)-(.+)$', re.I)
SUFFIX_PATTERN = re.compile(r"-[A-Z0-9/]+$")
TRAILING_LETTER_DETECT = re.compile(r"\d+[A-Z]+$")
TRAILING_LETTER_REMOVE = re.compile(r"[A-Z]+$")
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Common Unicode invisibles seen in Excel/CSV exports and pasted cells.
INVISIBLE_CHARS_PATTERN = re.compile(r"[\ufeff\u200b\u200c\u200d\u2060]")

# IEEE 315 / ANSI Y32.2 Standard Reference Designator Prefixes
# This is the authoritative whitelist used across all apps
IEEE_315_PREFIXES: Set[str] = {
    # Passive Components
    "R",      # Resistor
    "C",      # Capacitor
    "L",      # Inductor
    "FB",     # Ferrite Bead

    # Semiconductors
    "D",      # Diode (general)
    "CR",     # Diode (Crystal Rectifier - IEEE 315 standard)
    "Z",      # Zener Diode
    "Q",      # Transistor
    "U",      # Integrated Circuit
    "IC",     # Integrated Circuit (alternate)
    "LED",    # Light Emitting Diode
    "DS",     # Display / LED Indicator
    "VR",     # Voltage Regulator / Varistor

    # Connectors
    "J",      # Jack / Connector (receptacle)
    "P",      # Plug / Connector
    "CN",     # Connector
    "CONN",   # Connector
    "X",      # Socket / Receptacle
    "XPSJ",   # Cross-Point Switch Jack
    "XPSSJ",  # Cross-Point Switch Jack (double-S variant)

    # Electromechanical
    "K",      # Relay
    "RELAY",  # Relay (verbose)
    "SW",     # Switch
    "S",      # Switch (alternate)
    "F",      # Fuse
    "FUSE",   # Fuse (verbose)
    "BT",     # Battery

    # Transformers & Inductors
    "T",      # Transformer
    "XTAL",   # Crystal
    "Y",      # Crystal / Oscillator
    "OSC",    # Oscillator

    # Protection Devices
    "MOV",    # Metal Oxide Varistor
    "TVS",    # Transient Voltage Suppressor
    "BR",     # Bridge Rectifier

    # Test & Measurement
    "TP",     # Test Point
    "TEST",   # Test Point (verbose)
    "M",      # Meter
    "FID",    # Fiducial

    # Miscellaneous
    "ANT",    # Antenna
    "MP",     # Mechanical Part
    "JP",     # Jumper
    "SH",     # Shield
    "NT",     # Network
    "AR",     # Amplifier
    "SENSOR", # Sensor

    # Headers & Hardware
    "H",      # Header
    "HDR",    # Header
}

# Prefixes that use pin-style notation where the pin IS the identifier
# (e.g., J1-4 means pin 4 on connector J1 - the "-4" is part of the base)
# Used by get_base_refdes() to preserve pin suffixes
PIN_STYLE_PREFIXES: Set[str] = {"J", "P", "CN", "CONN", "X", "XPSJ", "XPSSJ"}

# Prefixes that use instance/terminal notation (e.g., U3-7 means instance 7 of IC U3)
# These prefixes will NOT have implicit ranges expanded (U3-7 stays as "U3-7", not "U3,U4,U5,U6,U7")
# Explicit ranges like "U1-U5" or "J1-J5" will still expand correctly
# NOTE: This set INCLUDES PIN_STYLE_PREFIXES because connectors also shouldn't expand
INSTANCE_NOTATION_PREFIXES: Set[str] = {
    # Connectors - pin notation (J1-4 = pin 4 of connector J1)
    "J", "P", "CN", "CONN", "X", "XPSJ", "XPSSJ",
    # Integrated circuits - instance notation (U3-1, U3-7 = instances of U3)
    "U", "IC",
    # Transistors - terminal notation (Q1-B = base of Q1)
    "Q",
    # Transformers - winding/terminal notation (T1-4 = terminal 4 of T1)
    "T",
    # Amplifiers - channel notation (AR1-2 = channel 2 of AR1)
    "AR",
}

# Components that should NEVER undergo pin analysis (2-terminal/simple devices)
# These are typically passives or simple semiconductors where pin differentiation
# is not meaningful for FMEA purposes
NO_PIN_ANALYSIS_PREFIXES: Set[str] = {
    # 2-terminal passives
    "R",       # Resistors
    "C",       # Capacitors
    "L",       # Inductors
    "FB",      # Ferrite Beads
    # 2-terminal semiconductors
    "D",       # Diodes (general)
    "CR",      # Crystal Rectifier diodes (IEEE 315)
    "Z",       # Zener diodes
    "LED",     # LEDs
    "DS",      # Display / LED Indicators
    "VR",      # Varistors
    "MOV",     # Metal Oxide Varistors
    "TVS",     # Transient Voltage Suppressors
    # Protection/fuses
    "F",       # Fuses
    "FUSE",    # Fuses (verbose)
    "BR",      # Bridge Rectifiers (treated as single component)
    # Test/reference points
    "TP",      # Test Points
    "TEST",    # Test Points
    "FID",     # Fiducials
    "MP",      # Mechanical Parts
    # Simple timing/power
    "Y",       # Crystals
    "XTAL",    # Crystals
    "BT",      # Batteries
}

# Components that SHOULD have pin analysis (multi-terminal devices)
# These devices have meaningful pin differentiation for FMEA purposes
PIN_ANALYSIS_PREFIXES: Set[str] = {
    # Integrated Circuits - multiple I/O pins
    "U", "IC",
    # Connectors - multiple pins by definition
    "J", "P", "CN", "CONN", "X", "XPSJ", "XPSSJ",
    # Multi-terminal discretes
    "Q",       # Transistors (B/C/E or G/D/S)
    "T",       # Transformers (multiple windings)
    # Electromechanical - multiple contacts
    "K", "RELAY",  # Relays
    "SW", "S",     # Switches
    # Multi-channel devices
    "AR",      # Amplifiers
    "OSC",     # Oscillators (may have enable/output pins)
}


def should_analyze_pins(prefix: str) -> bool:
    """
    Determine if a component type should undergo pin analysis.

    Components like resistors and capacitors are 2-terminal devices where
    pin analysis is meaningless. ICs, connectors, and transistors have
    multiple terminals with distinct functions.

    Args:
        prefix: Component prefix (e.g., "R", "U", "J")

    Returns:
        True if component type can have meaningful pin differentiation

    Examples:
        >>> should_analyze_pins("R")
        False
        >>> should_analyze_pins("U")
        True
        >>> should_analyze_pins("J")
        True
    """
    if not prefix:
        return True  # Unknown prefix - allow analysis to be safe
    p = prefix.upper()
    if p in NO_PIN_ANALYSIS_PREFIXES:
        return False
    # Allow if explicitly in PIN_ANALYSIS_PREFIXES or not in any blacklist
    return p in PIN_ANALYSIS_PREFIXES or p not in NO_PIN_ANALYSIS_PREFIXES


# Safety limit for range expansion to prevent memory issues
MAX_RANGE_EXPANSION = 5000


def get_prefix(token: str) -> Optional[str]:
    """
    Extract the alphabetic prefix from a RefDes token.

    Args:
        token: RefDes string (e.g., "CR25", "U100A")

    Returns:
        Uppercase prefix (e.g., "CR", "U") or None if invalid

    Examples:
        >>> get_prefix("CR25")
        'CR'
        >>> get_prefix("U100A")
        'U'
        >>> get_prefix("123")
        None
    """
    t = str(token).strip().upper()
    t = CONTROL_CHARS_PATTERN.sub("", t)
    match = re.match(r'^([A-Z]+)', t)
    return match.group(1) if match else None


def is_known_prefix(prefix: str) -> bool:
    """
    Check if a prefix is in the IEEE 315 standard whitelist.

    Args:
        prefix: The prefix to check (e.g., "CR", "R")

    Returns:
        True if prefix is a known IEEE 315 standard prefix

    Examples:
        >>> is_known_prefix("CR")
        True
        >>> is_known_prefix("XYZ")
        False
    """
    return prefix.upper() in IEEE_315_PREFIXES


def canonicalize_refdes(token: str) -> str:
    """
    Normalize a RefDes token: uppercase, strip whitespace, remove control characters.

    Args:
        token: The RefDes string to normalize

    Returns:
        Normalized uppercase RefDes string with control characters removed

    Examples:
        >>> canonicalize_refdes("  r1  ")
        'R1'
        >>> canonicalize_refdes("U100\\x00")
        'U100'
    """
    t = str(token).upper()
    # Normalize common hidden characters before trimming.
    t = CONTROL_CHARS_PATTERN.sub("", t)
    t = INVISIBLE_CHARS_PATTERN.sub("", t)
    t = t.replace("\u00A0", " ")
    t = t.strip()
    # Excel exports can include formulas/quoted cells around text values.
    if t.startswith("="):
        t = t[1:].lstrip()
    if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
        t = t[1:-1].strip()
    if not t:
        return ""
    # Drop punctuation-only tokens created by malformed formula/quote cells.
    if not any(ch.isalnum() for ch in t):
        return ""
    return t


def get_base_refdes(token: str) -> str:
    """
    Extract base RefDes by removing instance-specific suffixes.

    Removes suffixes like -1, -A, -B7 and trailing letters after digits.
    Preserves pin notation (e.g., J1-4) since the pin suffix is part of the base identifier.

    Args:
        token: The RefDes string (may include instance suffix)

    Returns:
        Base RefDes without instance suffix

    Examples:
        >>> get_base_refdes("U200-1")
        'U200'
        >>> get_base_refdes("U200-1-A")
        'U200'
        >>> get_base_refdes("R1-B7")
        'R1'
        >>> get_base_refdes("U1A")
        'U1'
        >>> get_base_refdes("C12")
        'C12'
        >>> get_base_refdes("J1-4")  # Pin notation preserved
        'J1-4'
    """
    t = canonicalize_refdes(token)

    # Preserve pin notation (e.g., J1-4, CN1-A) - the pin suffix IS part of the identifier
    if is_pin_notation(t):
        return t

    # Remove all hyphenated suffixes (e.g., -1, -A, -B7) - loop to handle multiple
    prev = None
    while prev != t:
        prev = t
        t = SUFFIX_PATTERN.sub("", t)

    # Remove trailing letters attached to digits (e.g., U1A -> U1)
    if TRAILING_LETTER_DETECT.search(t):
        t = TRAILING_LETTER_REMOVE.sub("", t)
    return t


def is_pin_notation(token: str) -> bool:
    """
    Check if a token uses connector pin-style notation.

    Pin notation is used for connectors where the format PREFIX + DIGITS + DASH + PIN
    represents a specific pin on a connector (e.g., J1-4 = pin 4 on connector J1).

    This function is used by get_base_refdes() to preserve pin suffixes because
    for connectors, the pin IS part of the unique identifier.

    Args:
        token: The RefDes string to check

    Returns:
        True if the token is connector pin notation, False otherwise

    Examples:
        >>> is_pin_notation("J1-4")
        True
        >>> is_pin_notation("CN1-A")
        True
        >>> is_pin_notation("U3-7")  # Not a connector - use is_instance_notation() instead
        False
        >>> is_pin_notation("R1-R5")
        False
    """
    m = PIN_PATTERN.match(token.upper())
    return m is not None and m.group(1) in PIN_STYLE_PREFIXES


def is_instance_notation(token: str) -> bool:
    """
    Check if a token uses instance/terminal notation that should NOT be range-expanded.

    Instance notation is used for components where the format PREFIX + DIGITS + DASH + SUFFIX
    represents a specific instance, terminal, or bank of a component:
    - J1-4 = pin 4 on connector J1
    - U3-7 = instance/bank 7 of IC U3
    - Q1-B = base terminal of transistor Q1
    - T1-4 = terminal 4 of transformer T1

    This function is used by expand_refdes_range() to prevent incorrect range expansion.
    "U3-7" should stay as "U3-7", NOT expand to ["U3", "U4", "U5", "U6", "U7"].

    This function distinguishes between:
    - Instance notation: "U3-7" → suffix is numeric or single letter → NOT a range
    - Range notation: "U1-U5" → suffix has same prefix → IS a range (should expand)

    Args:
        token: The RefDes string to check

    Returns:
        True if the token is instance notation (should NOT expand), False otherwise

    Examples:
        >>> is_instance_notation("J1-4")
        True
        >>> is_instance_notation("CN1-A")
        True
        >>> is_instance_notation("U3-7")
        True
        >>> is_instance_notation("U1-U5")  # Explicit range - should expand
        False
        >>> is_instance_notation("R1-R5")  # R not in INSTANCE_NOTATION_PREFIXES
        False
    """
    m = PIN_PATTERN.match(token.upper())
    if m is None:
        return False

    prefix = m.group(1)
    suffix = m.group(3)

    # Must be a prefix that uses instance notation
    if prefix not in INSTANCE_NOTATION_PREFIXES:
        return False

    # If suffix starts with the same prefix (like "U5" in "U1-U5"), it's a range, not instance notation
    # This allows explicit ranges like "U1-U5" to still expand correctly
    if suffix and len(suffix) > 1 and suffix.upper().startswith(prefix):
        return False

    return True


def get_usage_base_refdes(token: str) -> str:
    """
    Extract usage-level base RefDes for part quantity/usage aggregation.

    Unlike get_base_refdes() which preserves pin notation for comparison,
    this function strips ALL suffixes including pins because for usage counting,
    U300-1, U300-2, J1-4, and J1-5 all represent parts of ONE physical component.

    For usage validation, we need to group all instances/pins of a component
    together to validate that their usage values sum correctly (or individually
    equal 1/count).

    Args:
        token: The RefDes string (may include instance suffix or pin)

    Returns:
        Base RefDes without ANY suffix (instance or pin)

    Examples:
        >>> get_usage_base_refdes("U300-1")
        'U300'
        >>> get_usage_base_refdes("U300-AB17")
        'U300'
        >>> get_usage_base_refdes("J1-4")  # Pin stripped for usage counting
        'J1'
        >>> get_usage_base_refdes("CN1-A")
        'CN1'
        >>> get_usage_base_refdes("U1A")  # Trailing letter stripped
        'U1'
        >>> get_usage_base_refdes("C12")
        'C12'
        >>> get_usage_base_refdes("U200-1-A")  # Multiple suffixes all stripped
        'U200'
    """
    t = canonicalize_refdes(token)

    # Strip ALL hyphenated suffixes (including pin notation)
    # Loop handles multiple suffixes: U200-1-A → U200
    prev = None
    while prev != t:
        prev = t
        t = SUFFIX_PATTERN.sub("", t)

    # Strip trailing letters after digits: U1A → U1
    if TRAILING_LETTER_DETECT.search(t):
        t = TRAILING_LETTER_REMOVE.sub("", t)

    return t


def expand_refdes_range(
    token: str,
    max_expansion: int = MAX_RANGE_EXPANSION,
    expand: bool = False,
) -> List[str]:
    """
    Optionally expand a RefDes range into individual RefDes values.

    By default (expand=False) every token is returned as-is.  This is the safe
    default because in FMEA / BOM workflows every ``PREFIX-NUMBER`` is a
    component instance or connector pin, not a range.  Callers that genuinely
    need range expansion (e.g., a BOM that lists "R1-R5" meaning five
    resistors) can pass ``expand=True``.

    When expansion is enabled the function handles ranges like R1-R5 for
    passive components and preserves instance notation for ICs, connectors,
    transistors, and transformers (U3-7 stays as-is, not expanded).

    Args:
        token: The RefDes token (may be a range or single value)
        max_expansion: Maximum number of items to expand (safety limit)
        expand: Enable range expansion.  When False (default) the token is
                returned as a single-element list after canonicalization only.

    Returns:
        List of individual RefDes values. If not a valid range, returns [token].

    Examples:
        >>> expand_refdes_range("XPSSJ1-50")          # Default: preserved
        ['XPSSJ1-50']
        >>> expand_refdes_range("R1-R5", expand=True)  # Opt-in: expands
        ['R1', 'R2', 'R3', 'R4', 'R5']
        >>> expand_refdes_range("U3-7", expand=True)   # Instance notation still preserved
        ['U3-7']
        >>> expand_refdes_range("J1-4", expand=True)   # Connector pin still preserved
        ['J1-4']
        >>> expand_refdes_range("C100")                # Single value
        ['C100']
    """
    t = canonicalize_refdes(token)

    # Safe default: return the token as-is (no range expansion)
    if not expand:
        return [t]

    # --- Range expansion logic (opt-in only) ---

    # Preserve instance/pin notation (ICs, connectors, transistors, transformers, amplifiers)
    if is_instance_notation(t):
        return [t]

    # Try to match range pattern
    m = RANGE_PATTERN.match(t)
    if not m:
        return [t]

    p1, n1, p2, n2 = m.groups()
    p2 = p1 if not p2 else p2.upper()

    # Prefixes must match for a valid range
    if p1 != p2:
        return [t]

    try:
        a, b = int(n1), int(n2)
        # Validate range
        if a > b:
            return [t]
        if (b - a + 1) > max_expansion:
            return [t]  # Safety limit exceeded
        # Preserve leading zero padding from original input
        pad_width = len(n1)
        return [f"{p1}{k:0{pad_width}d}" for k in range(a, b + 1)]
    except ValueError:
        return [t]


def split_refdes_list(text: str, expand_ranges: bool = False) -> List[str]:
    """
    Split a RefDes string into individual tokens.

    Handles various separators (comma, semicolon, space, newline, pipe).
    Slash "/" is NOT a separator and is preserved within RefDes values
    (e.g., T300-24/22 for bonded pins).

    Range expansion (e.g., R1-R5 → five tokens) is disabled by default.
    Pass ``expand_ranges=True`` to opt in.

    Args:
        text: String containing one or more RefDes values
        expand_ranges: When True, expand range notation like R1-R5 into
                       individual tokens.  Default False preserves every
                       token as-is.

    Returns:
        List of individual RefDes values (normalized to uppercase)

    Examples:
        >>> split_refdes_list("R1, R2, R3")
        ['R1', 'R2', 'R3']
        >>> split_refdes_list("XPSSJ1-50, R1")
        ['XPSSJ1-50', 'R1']
        >>> split_refdes_list("R1-R5, C1", expand_ranges=True)
        ['R1', 'R2', 'R3', 'R4', 'R5', 'C1']
        >>> split_refdes_list("")
        []
    """
    # Handle None/NaN/empty
    try:
        if text != text:
            return []
    except Exception:
        pass
    if not text:
        return []
    if hasattr(text, '__class__') and 'NAType' in text.__class__.__name__:
        return []

    text_str = str(text).strip()
    if not text_str:
        return []

    tokens = [t for t in TOKEN_SPLIT_REGEX.split(text_str) if t]
    result = []
    for tok in tokens:
        result.extend(expand_refdes_range(tok, expand=expand_ranges))
    return result


def extract_base_refdes(text: str) -> Optional[str]:
    """
    Search text for a base RefDes pattern and return the first match.

    Useful for extracting RefDes from free-text fields like failure cause descriptions.

    Args:
        text: Text that may contain a RefDes

    Returns:
        The first matching base RefDes (uppercase), or None if not found

    Examples:
        >>> extract_base_refdes("Failure in U200 caused by...")
        'U200'
        >>> extract_base_refdes("No refdes here")
        None
    """
    match = BASE_REFDES_PATTERN.search(str(text))
    return match.group(1).upper() if match else None


def extract_instance_refdes(text: str) -> Optional[str]:
    """
    Search text for an instance RefDes (hyphenated) or base RefDes.

    Prefers hyphenated instance format (U200-1) over base format (U200).

    Args:
        text: Text that may contain a RefDes

    Returns:
        The first matching RefDes (uppercase), or None if not found

    Examples:
        >>> extract_instance_refdes("Issue with U200-1")
        'U200-1'
        >>> extract_instance_refdes("Issue with U200")
        'U200'
    """
    match = INSTANCE_REFDES_PATTERN.search(str(text))
    if match:
        return (match.group(1) or match.group(2)).upper()
    return None


def is_valid_refdes(token: str) -> bool:
    """
    Check if a token matches the standard RefDes format.

    Valid format: 1-6 letters followed by 1-5 digits, optionally followed by 1 letter.

    Args:
        token: The string to validate

    Returns:
        True if valid RefDes format, False otherwise

    Examples:
        >>> is_valid_refdes("R1")
        True
        >>> is_valid_refdes("U200")
        True
        >>> is_valid_refdes("CN1A")
        True
        >>> is_valid_refdes("ABCDEFG1")  # Too many letters (7)
        False
        >>> is_valid_refdes("123")  # No letters
        False
    """
    normalized = canonicalize_refdes(token)
    return BASE_REFDES_PATTERN.fullmatch(normalized) is not None
