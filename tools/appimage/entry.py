"""Entrypoint inside the AppImage's private native runtime."""
import locale
import os
import subprocess
import sys

from appimage_trust import trust_environment


def main():
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        os.environ["LC_ALL"] = "C.UTF-8"
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    with trust_environment():
        if sys.argv[1:2] == ["--python"]:
            return subprocess.call([sys.executable, "-s", "-B", *sys.argv[2:]])
        if sys.argv[1:2] == ["--self-test"]:
            import importlib.util
            spec = importlib.util.spec_from_file_location("appimage_self_test", "/usr/share/audiobook-utility/appimage-self-test.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.main(sys.argv[2:])
        from audiobook_utility.__main__ import main as application_main
        return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
