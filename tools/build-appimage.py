"""Build a private-runtime x86_64 AppImage on Arch/CachyOS without system changes."""
import argparse
import base64
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "dist/appimage"
APPDIR = WORK / "AudiobookUtility.AppDir"
APP_ID = "io.github.edjenn1998.AudiobookUtility"
TOOL_URL = "https://github.com/probonopd/go-appimage/releases/download/continuous/appimagetool-951-x86_64.AppImage"
TOOL_SHA256 = "7c974f525d5bcde2712dd080e0b079a6c3802113a337f0ab142522dcefbf452d"
PACKAGES = [
    "python", "python-gobject", "python-cairo", "glibc", "glib2", "gtk4", "libadwaita",
    "webkitgtk-6.0", "libsoup3", "glib-networking", "gdk-pixbuf2", "glycin", "librsvg",
    "gstreamer", "gst-plugins-base", "gst-plugins-base-libs", "gst-plugins-good", "gst-plugins-bad", "gst-libav",
    "adwaita-icon-theme", "adwaita-cursors", "hicolor-icon-theme", "adwaita-fonts", "ttf-dejavu", "fontconfig",
    "xkeyboard-config", "libx11",
    "dconf", "gsettings-desktop-schemas", "gsettings-system-schemas", "shared-mime-info", "openssl", "p11-kit", "libp11-kit",
    "ca-certificates-mozilla", "tzdata", "mesa", "libglvnd", "bubblewrap", "xdg-dbus-proxy", "licenses",
]
BINARIES = {f"python{sys.version_info.major}.{sys.version_info.minor}", "python3", "python", "ffmpeg", "ffprobe", "bwrap", "xdg-dbus-proxy",
            "glib-compile-schemas", "gio-querymodules", "gdk-pixbuf-query-loaders", "gst-inspect-1.0"}
COPIED = set()
COPIED_HASHES = {}
NATIVE_PYTHON = {"pygobject": "python-gobject", "pycairo": "python-cairo", "pillow": "python-pillow",
                 "cffi": "python-cffi", "pycparser": "python-pycparser", "typing-extensions": "python-typing_extensions"}


def package_hashes(name):
    version = output("pacman", "-Q", name).strip().split(" ", 1)[1]
    path = Path("/var/lib/pacman/local") / (name + "-" + version) / "mtree"
    hashes = {}
    with gzip.open(path, "rt") as stream:
        for line in stream:
            parts = line.split()
            if not parts or not parts[0].startswith("./"):
                continue
            digest = next((field.split("=", 1)[1] for field in parts[1:] if field.startswith("sha256digest=")), None)
            if digest:
                filename = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), parts[0][1:])
                hashes[Path(filename)] = digest
    return hashes


def approved_sources():
    import importlib.util
    spec = importlib.util.spec_from_file_location("package_sources", ROOT / "package_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args):
    return subprocess.check_output([str(a) for a in args], text=True)


def copy_native(source):
    source = Path(source)
    if not source.is_file():
        return
    target = APPDIR / source.relative_to("/")
    if source in COPIED:
        return
    COPIED.add(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if source.is_symlink() and source.resolve().is_relative_to("/usr"):
        real = source.resolve()
        copy_native(real)
        target.symlink_to(os.path.relpath(APPDIR / real.relative_to("/"), target.parent))
    else:
        shutil.copy2(source, target, follow_symlinks=True)
        COPIED_HASHES[source] = hashlib.sha256(target.read_bytes()).hexdigest()


def wanted(path):
    if not path.is_relative_to("/usr") or not path.is_file():
        return False
    parts = path.parts
    if "__pycache__" in parts or path.suffix in {".pyc", ".a", ".la"}:
        return False
    if path.name.startswith("_tkinter.") or any(p in {"tkinter", "idlelib", "turtledemo"} for p in parts):
        return False  # This GTK application never loads the optional Tk GUI stack.
    if path.is_relative_to("/usr/bin"):
        return path.name in BINARIES
    if path.is_relative_to("/usr/lib"):
        return not any(p in {"pkgconfig", "cmake"} for p in parts)
    if path.is_relative_to("/usr/share"):
        return not any(p in {"doc", "man", "gtk-doc", "gir-1.0", "devhelp", "gettext"} for p in parts)
    return False


def native_packages():
    for package in PACKAGES:
        for name in output("pacman", "-Qlq", package).splitlines():
            path = Path(name)
            if wanted(path):
                copy_native(path)
    for name in ("ffmpeg", "ffprobe"):
        binary = Path(shutil.which(name) or "").resolve()
        if binary != Path("/usr/bin") / name:
            raise ValueError(f"Build requires the distribution's /usr/bin/{name}, not a PATH override")
        copy_native(binary)
    if Path("/usr/lib/locale/locale-archive").is_file():
        copy_native("/usr/lib/locale/locale-archive")
    # Load-on-demand GI libraries need their typelibs as well as ELF dependencies.
    import gi
    gi.require_version("GIRepository", "3.0")
    from gi.repository import GIRepository
    repository = GIRepository.Repository.dup_default()
    pending = [("Gtk", "4.0"), ("Adw", "1"), ("WebKit", "6.0"), ("Soup", "3.0"), ("GIRepository", "3.0")]
    seen = set()
    while pending:
        namespace, version = pending.pop()
        if namespace in seen:
            continue
        seen.add(namespace)
        repository.require(namespace, version, GIRepository.RepositoryLoadFlags(0))
        pending.extend(dependency.rsplit("-", 1) for dependency in repository.get_dependencies(namespace))
        path = repository.get_typelib_path(namespace)
        if path:
            copy_native(path)


def validate_distribution(distribution, expected=None):
    if expected is not None and distribution.version != expected:
        raise ValueError("Installed dependency version does not match requirements.lock")
    origin = distribution.read_text("direct_url.json")
    if origin:
        metadata = json.loads(origin)
        if metadata.get("dir_info", {}).get("editable"):
            raise ValueError("Unsafe editable dependency cannot be packaged")
        # Build provenance must never carry a credential-bearing URL.
        from urllib.parse import urlsplit
        parsed = urlsplit(metadata.get("url", ""))
        if parsed.username or parsed.password:
            raise ValueError("Dependency origin URL contains credentials")
    base = Path(distribution.locate_file("")).resolve()
    native = NATIVE_PYTHON.get(re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower())
    if base.is_relative_to("/usr/lib") and native:
        # Distribution packages may omit RECORD or strip extensions after wheel
        # construction. Verify against the package manager's signed-package mtree,
        # rather than trusting stale pre-strip wheel hashes or skipping integrity.
        expected_hashes = package_hashes(native)
        selected = []
        for name in output("pacman", "-Qlq", native).splitlines():
            source = Path(name)
            if not source.is_relative_to(base) or not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            if not source.resolve().is_relative_to(base):
                raise ValueError("Native Python dependency escapes its site directory")
            expected_hash = expected_hashes.get(source)
            if expected_hash is None or hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
                raise ValueError("Native Python dependency differs from its package integrity inventory")
            selected.append((source.relative_to(base), source))
        if not selected:
            raise ValueError("Native Python dependency has no runtime files")
        return selected
    if not distribution.files:
        raise ValueError("Installed dependency has no auditable file inventory")
    selected = []
    for record in distribution.files:
        relative = Path(str(record))
        if "__pycache__" in relative.parts or relative.suffix == ".pyc":
            continue
        if relative.is_absolute() or ".." in relative.parts:
            if re.fullmatch(r"(?:\.\./){1,3}(?:bin/[a-zA-Z0-9_.-]+|share/man/man[0-9]/[a-zA-Z0-9_.-]+)", str(record)):
                continue  # Declared wheel console scripts are not app runtime files.
            raise ValueError("Dependency inventory escapes its installed package directory")
        if relative.suffix in {".pth", ".egg-link"} or relative.name.startswith("__editable__"):
            raise ValueError("Unsafe editable/path-injection dependency layout")
        source = base / relative
        if not source.is_file() or not source.resolve().is_relative_to(base):
            raise ValueError("Dependency file is missing or escapes its package directory")
        if record.hash:
            if record.hash.mode not in {"sha256", "sha384", "sha512"}:
                raise ValueError("Unsupported dependency RECORD hash")
            actual = base64.urlsafe_b64encode(hashlib.new(record.hash.mode, source.read_bytes()).digest()).rstrip(b"=").decode()
            if actual != record.hash.value:
                raise ValueError("Installed dependency file does not match its RECORD hash")
        selected.append((relative, source))
    return selected


def python_packages():
    locked = {}
    for line in (ROOT / "requirements.lock").read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            locked[name] = version
    for name in ("PyGObject", "pycairo", "cffi", "pycparser"):
        locked.setdefault(name, None)  # Native ABI versions are captured in provenance.
    site = APPDIR / "usr/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name, expected in locked.items():
        distribution = importlib.metadata.distribution(name)
        versions[distribution.metadata["Name"]] = distribution.version
        for relative, source in validate_distribution(distribution, expected):
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            shutil.copy2(source, target, follow_symlinks=True)
    approved_sources().copy_sources(ROOT, site / "audiobook_utility", prefix="src/audiobook_utility")
    return versions


def elf(path):
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except OSError:
        return False


def dependency_closure():
    checked = set()
    while True:
        pending = [p for p in APPDIR.rglob("*") if p.is_file() and not p.is_symlink() and p not in checked and elf(p)]
        if not pending:
            return
        for path in pending:
            checked.add(path)
            result = subprocess.run(["ldd", str(path)], capture_output=True, text=True)
            if "=> not found" in result.stdout:
                raise RuntimeError(f"Missing native dependency for {path.relative_to(APPDIR)}: {result.stdout}")
            for library in re.findall(r"(?:=>\s+|^\s*)(/[^\s]+)", result.stdout, re.MULTILINE):
                source = Path(library)
                if source.is_relative_to(APPDIR):
                    continue
                # Arch's /lib64 is a symlink; place the loader in the private /usr/lib.
                if source.name == "ld-linux-x86-64.so.2":
                    source = source.resolve()
                copy_native(source)


def configuration():
    etc = APPDIR / "etc"
    etc.mkdir(parents=True, exist_ok=True)
    for name in ("passwd", "group", "hosts", "resolv.conf", "machine-id", "localtime"):
        (etc / name).touch()
    (etc / "nsswitch.conf").write_text("passwd: files\ngroup: files\nhosts: files dns\n")
    (etc / "os-release").write_text('NAME="Audiobook Utility runtime"\nID=appimage\n')
    for name in output("pacman", "-Qlq", "fontconfig").splitlines():
        if Path(name).is_relative_to("/etc/fonts"):
            copy_native(name)
    # Arch enables these symlinks in an installation hook; they are not listed
    # as /etc files by pacman. WebKit needs the generic-family substitution rules.
    enabled = etc / "fonts/conf.d"
    enabled.mkdir(parents=True, exist_ok=True)
    for source in Path("/usr/share/fontconfig/conf.default").glob("*.conf"):
        copy_native(source)
        target = enabled / source.name
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(os.path.relpath(APPDIR / source.relative_to("/"), enabled))
    fontconfig = etc / "fonts/fonts.conf"
    # Keep the standard alias/substitution rules, but no host system cache.
    text = fontconfig.read_text().replace("<cachedir>/var/cache/fontconfig</cachedir>", "")
    fontconfig.write_text(text)
    import certifi
    certificate = etc / "ssl/certs/ca-certificates.crt"
    certificate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(certifi.where(), certificate)
    (certificate.parent / "additional-ca.pem").touch()
    (etc / "ca-certificates/trust-source/anchors").mkdir(parents=True, exist_ok=True)
    (etc / "ssl/cert.pem").symlink_to("certs/ca-certificates.crt")
    extracted = etc / "ca-certificates/extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    for name in ("tls-ca-bundle.pem", "ca-bundle.trust.crt"):
        (extracted / name).symlink_to("../../ssl/certs/ca-certificates.crt")
    # Native binaries use the usual interpreter paths inside the namespace.
    (APPDIR / "usr/lib64").symlink_to("lib")
    for name in ("python", "python3"):
        path = APPDIR / "usr/bin" / name
        if path.exists() or path.is_symlink():
            path.unlink()
        path.symlink_to(f"python{sys.version_info.major}.{sys.version_info.minor}")
    resource = APPDIR / "usr/share/audiobook-utility"
    resource.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools/appimage/entry.py", resource / "appimage-entry.py")
    shutil.copy2(ROOT / "tools/appimage/appimage_trust.py", resource / "appimage_trust.py")
    shutil.copy2(ROOT / "tools/appimage/self_test.py", resource / "appimage-self-test.py")
    for name in ("LICENSE", "THIRD_PARTY.md", "README.md", "requirements.lock"):
        shutil.copy2(ROOT / name, resource / name)
    source = resource / "source"
    approved_sources().copy_sources(ROOT, source)
    approved_sources().write_inventory(ROOT, resource / "source-inventory.json")
    desktop = ROOT / "data" / f"{APP_ID}.desktop"
    shutil.copy2(desktop, APPDIR / desktop.name)
    applications = APPDIR / "usr/share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop, applications / desktop.name)
    icon = ROOT / "data" / f"{APP_ID}.svg"
    png = APPDIR / f"{APP_ID}.png"
    run("rsvg-convert", "--width", "256", "--height", "256", "--output", png, icon)
    (APPDIR / ".DirIcon").symlink_to(png.name)
    icons = APPDIR / "usr/share/icons/hicolor/scalable/apps"
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon, icons / icon.name)
    metadata = APPDIR / "usr/share/metainfo"
    metadata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data" / f"{APP_ID}.metainfo.xml", metadata / f"{APP_ID}.metainfo.xml")
    (metadata / f"{APP_ID}.appdata.xml").symlink_to(f"{APP_ID}.metainfo.xml")
    launcher = APPDIR / "usr/bin/audiobook-utility"
    launcher.write_text("#!/usr/bin/python3\nfrom audiobook_utility.__main__ import main\nraise SystemExit(main())\n")
    launcher.chmod(0o755)
    run("gcc", "-static", "-O2", "-s", ROOT / "tools/appimage/AppRun.c", "-o", APPDIR / "AppRun")
    run("glib-compile-schemas", "--strict", APPDIR / "usr/share/glib-2.0/schemas")
    run("gio-querymodules", APPDIR / "usr/lib/gio/modules")
    loaders = sorted((APPDIR / "usr/lib/gdk-pixbuf-2.0/2.10.0/loaders").glob("*.so"))
    cache = output("gdk-pixbuf-query-loaders", *loaders).replace(str(APPDIR), "")
    cache_file = APPDIR / "usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cache)


def notices(versions):
    owners = set(PACKAGES)
    paths = [str(p) for p in COPIED if p.exists()]
    for start in range(0, len(paths), 250):
        result = subprocess.run(["pacman", "-Qoq", *paths[start:start + 250]], capture_output=True, text=True)
        owners.update(result.stdout.splitlines())
    packages = {}
    native_hashes = {}
    licenses = APPDIR / "usr/share/licenses"
    for name in sorted(owners):
        packages[name] = output("pacman", "-Q", name).strip().split(" ", 1)[1]
        native_hashes.update(package_hashes(name))
        directory = Path("/usr/share/licenses") / name
        if directory.is_dir():
            shutil.copytree(directory, licenses / name, dirs_exist_ok=True, symlinks=False)
    for source in COPIED:
        if source.is_symlink():
            continue
        expected_hash = native_hashes.get(source)
        if expected_hash is not None:
            if COPIED_HASHES.get(source) != expected_hash:
                raise ValueError("A collected native file differs from its package integrity inventory")
    for name in ("common", "spdx"):
        directory = Path("/usr/share/licenses") / name
        if directory.is_dir():
            shutil.copytree(directory, licenses / name, dirs_exist_ok=True)
    revision = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True)
    manifest = {"architecture": "x86_64", "python": sys.version.split()[0], "python_packages": versions,
                "native_packages": packages, "builder_sha256": TOOL_SHA256,
                "native_collection_hashes": {str(path): digest for path, digest in COPIED_HASHES.items()},
                "source_head": revision.stdout.strip() if revision.returncode == 0 else "source-archive",
                "source_dirty": bool(status.stdout) if status.returncode == 0 else None,
                "source_files": approved_sources().inventory(ROOT),
                "runtime_file_hashes": {str(p.relative_to(APPDIR)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in APPDIR.rglob("*") if p.is_file() and not p.is_symlink()},
                "system_services": ["Linux kernel with unprivileged user namespaces", "desktop display server",
                                    "desktop D-Bus and Secret Service for Audible"]}
    (APPDIR / "usr/share/audiobook-utility/appimage-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (WORK / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def package():
    tool = ROOT / "dist/appimage-tools/appimagetool-951-x86_64.AppImage"
    tool.parent.mkdir(parents=True, exist_ok=True)
    if not tool.exists():
        urllib.request.urlretrieve(TOOL_URL, tool)
    if hashlib.sha256(tool.read_bytes()).hexdigest() != TOOL_SHA256:
        raise RuntimeError("AppImage build tool checksum mismatch")
    tool.chmod(0o755)
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("GITHUB_") or name in {"CI", "TRAVIS", "APPIMAGE"}:
            env.pop(name, None)
    env.update(APPIMAGE_EXTRACT_AND_RUN="1", VERSION="0.1.0", ARCH="x86_64",
               TMPDIR=str(ROOT / "dist/tmp"), HOME=str(WORK / "tool-home"),
               XDG_CACHE_HOME=str(WORK / "tool-cache"))
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    destination = ROOT / "dist/Audiobook_Utility-0.1.0-x86_64.AppImage"
    log = WORK / "appimagetool.log"
    print(f"Compressing AppImage (build log: {log})...", flush=True)
    with log.open("w") as stream:
        run(tool, "--overwrite", APPDIR, cwd=WORK, env=env, stdout=stream, stderr=subprocess.STDOUT)
    built = WORK / destination.name
    if not built.is_file():
        raise RuntimeError(f"AppImage builder did not create the expected artifact: {built}")
    os.replace(built, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".AppImage.sha256").write_text(f"{digest}  {destination.name}\n")
    print(f"AppImage: {destination}\nSHA-256: {digest}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appdir-only", action="store_true")
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    if os.uname().machine != "x86_64" or not shutil.which("pacman"):
        parser.error("Build on x86_64 Arch/CachyOS using the project virtual environment")
    WORK.mkdir(parents=True, exist_ok=True)
    (ROOT / "dist/tmp").mkdir(exist_ok=True)
    if not args.package_only:
        approved_sources().source_files(ROOT)  # Validate before touching staging.
        if APPDIR.exists():
            if not (APPDIR / ".audiobook-appdir").is_file():
                raise RuntimeError("Refusing to replace an unrecognized AppDir")
            shutil.rmtree(APPDIR)
        APPDIR.mkdir()
        (APPDIR / ".audiobook-appdir").write_text("generated by tools/build-appimage.py\n")
        print("Copying native runtime packages...", flush=True)
        native_packages()
        print("Bundling Python dependencies...", flush=True)
        versions = python_packages()
        print("Resolving the complete ELF dependency closure...", flush=True)
        dependency_closure()
        configuration()
        notices(versions)
        print("Private runtime AppDir ready.", flush=True)
    if not args.appdir_only:
        package()


if __name__ == "__main__":
    main()
