"""Entry point of the packaged Bladesmith.exe."""
import os
import sys

if getattr(sys, "frozen", False):
    # Explorer copies the download's "from the internet" mark (the Zone.Identifier stream) onto every unpacked
    # file, and .NET Framework then refuses to load pythonnet's DLLs, so the window never opens
    for folder, _, files in os.walk(os.path.dirname(sys.executable)):
        for name in files:
            try:
                os.remove(os.path.join(folder, name) + ":Zone.Identifier")
            except OSError:  # no mark, or a folder we can't write to
                pass

from bladesmith.__main__ import main

sys.exit(main())
