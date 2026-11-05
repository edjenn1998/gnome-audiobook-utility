"""Restrict setuptools runtime and sdist files to the reviewed public manifest."""
from pathlib import Path
import importlib.util

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import FileList, egg_info

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("package_sources", ROOT / "package_sources.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
source_files = policy.source_files


class ApprovedEggInfo(egg_info):
    def find_sources(self):
        files = source_files(ROOT)
        directory = Path(self.egg_info)
        for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"):
            path = directory / name
            if path.is_file() or name == "SOURCES.txt":
                files.append(path.relative_to(ROOT).as_posix() if path.is_absolute() else path.as_posix())
        self.filelist = FileList()
        self.filelist.files = sorted(set(files))
        (directory / "SOURCES.txt").write_text("\n".join(self.filelist.files) + "\n")


class ApprovedBuild(build_py):
    def find_package_modules(self, package, package_dir):
        approved = set(source_files(ROOT))
        return [entry for entry in super().find_package_modules(package, package_dir)
                if Path(entry[2]).resolve().relative_to(ROOT).as_posix() in approved]

    def find_data_files(self, package, src_dir):
        approved = set(source_files(ROOT))
        return [name for name in super().find_data_files(package, src_dir)
                if Path(name).resolve().relative_to(ROOT).as_posix() in approved]


setup(cmdclass={"egg_info": ApprovedEggInfo, "build_py": ApprovedBuild})
