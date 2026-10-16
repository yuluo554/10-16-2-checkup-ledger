"""`python -m checkup_ledger` 入口（与裸 `checkup-ledger` 是两条不同通路）。"""

import sys

from checkup_ledger.cli import main

if __name__ == "__main__":
    sys.exit(main())
