"""``pythonw -m windowtally_gui`` — the window; run from the folder that holds the package. See ``app_view``."""

import sys

from .app_view import main

if __name__ == "__main__":
    sys.exit(main())
