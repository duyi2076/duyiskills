#!/usr/bin/env python3
"""Use the publishing renderer and its QA gate for local previews."""
import sys
from render_wechat_html import main

if __name__ == "__main__":
    if "--standalone" not in sys.argv:
        sys.argv.append("--standalone")
    main()
