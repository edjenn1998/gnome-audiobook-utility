"""Entrypoint inside the AppImage's private native runtime."""
import locale
import os
import sys

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    os.environ["LC_ALL"] = "C.UTF-8"
    locale.setlocale(locale.LC_ALL, "C.UTF-8")

if sys.argv[1:] and sys.argv[1] == "--self-test":
    import importlib.util

    spec = importlib.util.spec_from_file_location("appimage_self_test", "/usr/share/audiobook-utility/appimage-self-test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raise SystemExit(module.main(sys.argv[2:]))

from audiobook_utility.__main__ import main

raise SystemExit(main())
