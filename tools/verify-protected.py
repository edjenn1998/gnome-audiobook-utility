"""Convert and fully decode a protected audiobook using its desktop keyring license."""
import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

from audiobook_utility.audible_service import AudibleService
from audiobook_utility.diagnostics import record_exception
from audiobook_utility.files import UtilityError, destination
from audiobook_utility.media import convert, probe
from audiobook_utility.metadata import read_tags
from audiobook_utility.receipts import digest
from audiobook_utility.protected_diagnostics import protected_report
from audiobook_utility.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing AAXC or AAX download")
    parser.add_argument("--output", type=Path, help="New M4B path; existing files are never overwritten")
    parser.add_argument("--diagnose-only", action="store_true",
                        help="Report tool, descriptor, receipt and sample-decoding evidence without creating M4B")
    parser.add_argument("--report", type=Path, help="Write the redacted diagnostic JSON to this new file")
    args = parser.parse_args()
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        if args.diagnose_only:
            report = protected_report(args.source, cancel)
            text = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
            if args.report:
                fd = os.open(args.report.expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(text)
                print("Redacted diagnostic report written. No M4B was created.")
            else:
                print(text, end="")
            return 0
        if args.report:
            parser.error("--report requires --diagnose-only")
        source = args.source.expanduser().resolve(strict=True)
        if source.suffix.lower() not in {".aaxc", ".aax"}:
            raise UtilityError("Choose an existing AAXC or AAX file.")
        settings = Settings.load()
        output = (args.output.expanduser().absolute() if args.output else
                  destination(Path(settings.output), source.stem, ".m4b", settings.conflict))
        if output.suffix.lower() != ".m4b":
            raise UtilityError("The verification output must be an M4B file.")
        before = digest(source, cancel)
        options = AudibleService().input_options(source, cancel)
        original = probe(source, options)
        print("License resolved and protected source inspected. Converting and verifying full audio…", flush=True)
        # Protected conversion decodes the complete result before publishing it.
        convert(source, output, cancel, bitrate=settings.aac_bitrate, input_options=options)
        result = probe(output)
        tags, artwork = read_tags(output)
        if digest(source, cancel) != before:
            raise UtilityError("The source changed during verification. Investigate before using the result.")
        print(f"Verified: {result.codec}, {result.duration:.2f} seconds, "
              f"{len(result.chapters)} chapters (source: {len(original.chapters)}).")
        print("Populated metadata fields: " + ", ".join(key for key, value in tags.items() if value))
        print("Cover present: " + ("yes" if artwork else "no"))
        print("Complete audio decoded without errors; original file unchanged.")
        print(f"Output: {output}")
        return 0
    except (UtilityError, OSError) as exc:
        record_exception(exc)
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        record_exception(exc)
        print("Verification failed. Check the redacted local diagnostics; no license values were printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
