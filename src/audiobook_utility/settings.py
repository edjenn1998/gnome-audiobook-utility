import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .files import UtilityError, staging


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "audiobook-utility/settings.json"


@dataclass
class Settings:
    downloads: str = str(Path.home() / "Audiobooks/Downloads")
    output: str = str(Path.home() / "Audiobooks")
    temporary: str = ""
    format: str = "m4b"
    mp3_bitrate: int = 128
    aac_bitrate: int = 96
    chapters: bool = True
    conflict: str = "rename"

    def validate(self):
        if self.format not in {"m4b", "mp3"} or self.conflict not in {"rename", "fail"}:
            raise UtilityError("Invalid output format or filename conflict setting.")
        if self.mp3_bitrate not in {64, 96, 128, 192, 256, 320} or self.aac_bitrate not in {64, 96, 128, 192, 256}:
            raise UtilityError("Select a supported audio bitrate.")
        for value in (self.downloads, self.output):
            if not value or not Path(value).expanduser().is_absolute():
                raise UtilityError("Choose absolute download and output directory paths.")
        if self.temporary and not Path(self.temporary).expanduser().is_absolute():
            raise UtilityError("The temporary directory must be an absolute path.")
        if type(self.chapters) is not bool:
            raise UtilityError("The chapter preference must be true or false.")
        for field in ("downloads", "output", "temporary"):
            value = getattr(self, field)
            if value:
                setattr(self, field, str(Path(value).expanduser().resolve()))

    @classmethod
    def load(cls, path: Path | None = None):
        path = path or config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            result = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            result.validate()
            return result
        except (ValueError, TypeError, AttributeError) as exc:
            raise UtilityError("Cannot read preferences. Check the settings JSON file.") from exc

    def save(self, path: Path | None = None):
        self.validate()
        with staging(path or config_path(), replace=True) as temporary:
            temporary.write_text(json.dumps(asdict(self), indent=2) + "\n")
