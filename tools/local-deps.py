"""Extract Ubuntu runtime packages locally for headless CI; never installs packages."""
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1] / ".deps"
root.mkdir(exist_ok=True)
plan = subprocess.check_output([
    "apt-get", "-s", "install", "--no-install-recommends",
    "ffmpeg", "gir1.2-gtk-4.0", "gir1.2-adw-1",
], text=True)
packages = [line.split()[1] for line in plan.splitlines() if line.startswith("Inst ")]
subprocess.run(["apt-get", "download", *packages], cwd=root, check=True)
for archive in root.glob("*.deb"):
    subprocess.run(["dpkg-deb", "-x", str(archive), str(root)], check=True)
