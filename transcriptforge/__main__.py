import sys
from pathlib import Path

if "--scheduled-scan" in sys.argv:
    from .scheduler import scan_and_launch
    folder_index = sys.argv.index("--folder") + 1 if "--folder" in sys.argv else None
    folder = Path(sys.argv[folder_index]).expanduser() if folder_index is not None and folder_index < len(sys.argv) else None
    raise SystemExit(scan_and_launch(folder))
elif len(sys.argv) > 1 and sys.argv[1] in {"cli", "--cli"}:
    sys.argv.pop(1)
    from .cli import main
else:
    from .app import main

if __name__ == "__main__":
    if "--scheduled-scan" not in sys.argv:
        main()
