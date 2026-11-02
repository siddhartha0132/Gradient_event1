"""Write the API schema the client generates its types from.

Run from server/:  uv run python -m scripts.dump_openapi ../client/openapi.json
"""

import json
import sys

from app.main import app

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    with open(out, "w") as f:
        json.dump(app.openapi(), f, indent=1)
    print(f"Wrote {out}")
