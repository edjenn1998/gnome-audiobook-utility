"""Bounded, shareable media errors without keys, media tags or source paths."""
import math
import re
from pathlib import Path

from .files import UtilityError


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def probe_properties(data: dict) -> dict:
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    result = {}
    for name, value in {
        "format_duration": fmt.get("duration"), "stream_duration": audio.get("duration"),
        "stream_bitrate": audio.get("bit_rate"), "format_bitrate": fmt.get("bit_rate"),
        "sample_rate": audio.get("sample_rate"), "channels": audio.get("channels"),
    }.items():
        result[name] = positive_number(value) or ("N/A" if value == "N/A" else "unavailable")
    codec = audio.get("codec_name", "")
    result["codec"] = codec if isinstance(codec, str) and re.fullmatch(r"[a-z0-9_+-]{1,32}", codec) else "unknown"
    return result


ERROR_LINES = re.compile(
    r"permission denied|operation not permitted|no such file|bad file descriptor|"
    r"unrecognized option|option not found|error (?:opening|reading|splitting|parsing|setting)|"
    r"failed to (?:set|open|read)|invalid|missing|needs to be|not on whitelist|"
    r"protocol not found|moov atom|could not find codec|error while decoding|"
    r"input buffer exhausted|channel element|number of bands|not found|"
    r"cannot open|unable to|unsupported|unknown|not allowed|not implemented|"
    r"error loading shared|version .* not found",
    re.IGNORECASE,
)


def redact_stderr(stderr, *, paths=(), options=()) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    text = stderr or ""
    text = text[:8192] + ("\n…\n" + text[-8192:] if len(text) > 8192 else "")
    for index, arg in enumerate(options):
        if arg in {"-audible_key", "-audible_iv", "-activation_bytes"} and index + 1 < len(options):
            value = options[index + 1]
            if isinstance(value, str) and value:
                text = re.sub(re.escape(value), "<redacted-secret>", text, flags=re.IGNORECASE)
    for path in sorted({str(p) for p in paths if p}, key=len, reverse=True):
        text = text.replace(path, "<media-file>")
        name = Path(path).name
        if len(name) >= 4:
            text = text.replace(name, "<media-file>")
    text = re.sub(r"/proc/(?:self|\d+)/fd/\d+", "<private-fd>", text)
    text = re.sub(r"https?://[^\s'\"<>]+", "<redacted-url>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(?:[0-9a-f]{2}[: -]){3,}[0-9a-f]{2}", "<redacted-hex>", text)
    text = re.sub(r"(?i)(?:0x)?\b[0-9a-f]{8,}\b", "<redacted-hex>", text)
    text = re.sub(r"(?i)\b(?:Bearer|Basic)\s+\S+", "<redacted-auth>", text)
    text = re.sub(r"(?i)\b(?:key|iv|token|password|cookie|authorization)\s*[:=]\s*\S+",
                  "<redacted-credential>", text)
    # Keep quoted option names, not arbitrary quoted values or embedded media text.
    def quoted(match):
        value = match.group()[1:-1]
        return match.group() if re.fullmatch(r"/?(?:audible_key|audible_iv|activation_bytes)", value) else "'<redacted>'"
    text = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", quoted, text)
    lines = [line[:400] for line in text.splitlines() if ERROR_LINES.search(line)]
    return "\n".join(lines[:12]) or "No recognized error lines (unclassified stderr omitted)."


def classify_failure(stderr: str, returncode: int | None) -> str:
    text = (stderr or "").lower()
    private = "/proc/" in text
    if "permission denied" in text or "operation not permitted" in text:
        return "private-file-permission" if private else "file-permission"
    if "bad file descriptor" in text or private and "no such file" in text:
        return "private-descriptor-unavailable"
    if private and ("error opening file" in text or "error reading the value" in text):
        return "private-file-open"
    if "unrecognized option" in text or "option not found" in text:
        return "option-syntax"
    if "needs to be 16 bytes" in text or "needs to be 4 bytes" in text:
        return "license-parameter-length"
    if "error loading shared" in text or "glibc_" in text:
        return "runtime-loader"
    if "moov atom" in text:
        return "container-header"
    if returncode is not None and returncode < 0:
        return "terminated-by-signal"
    if any(word in text for word in ("channel element", "input buffer exhausted", "number of bands", "error while decoding")):
        return "audio-bitstream"
    return "unclassified-tool-error"


class MediaFailure(UtilityError):
    def __init__(self, operation: str, *, returncode: int | None = None, stderr="",
                 paths=(), options=(), reason: str | None = None, properties: dict | None = None):
        raw = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr or ""
        cause = reason or classify_failure(raw, returncode)
        self.details = {"operation": operation, "cause": cause, "exit_status": returncode,
                        "stderr": redact_stderr(raw, paths=paths, options=options)}
        if properties is not None:
            self.details["audio_properties"] = properties
        guidance = {
            "private-file-permission": "The child could not open a private option file; this does not establish a bad voucher.",
            "private-descriptor-unavailable": "A private input descriptor was unavailable to the child process.",
            "private-file-open": "The tool could not read its private option file. Its loader may omit the OS error; run --diagnose-only to check descriptor access independently.",
            "option-syntax": "This tool rejected the option syntax. Recognizing audible_key alone does not prove file-valued option support.",
            "audio-bitstream": "The audio could not be decoded. A mismatched license or damaged media remains possible.",
            "invalid-audio-properties": "FFprobe returned unusable required audio properties; see the redacted property summary.",
            "invalid-json": "FFprobe did not return a valid media-inspection JSON document.",
            "timeout": "The media process exceeded its inspection timeout.",
            "runtime-loader": "The selected executable could not load its runtime libraries.",
        }.get(cause, "See the redacted tool error for the failing operation.")
        status = f"exit {returncode}" if returncode is not None else "no exit status"
        super().__init__(f"{operation} failed [{cause}; {status}]. {guidance}\n"
                         f"{self.details['stderr']}")
