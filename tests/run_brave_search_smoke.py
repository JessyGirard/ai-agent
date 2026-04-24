import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.brave_search import brave_search


def main() -> int:
    query = " ".join(sys.argv[1:]).strip() or "test query"
    result = brave_search(query)

    if result.get("ok"):
        print("success: true")
    else:
        print("success: false")
    print(f"status_code: {result.get('status_code')}")
    if result.get("error"):
        print(f"error: {result['error']}")
    print("sample_output:")
    print(json.dumps(result.get("results", [])[:3], ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
