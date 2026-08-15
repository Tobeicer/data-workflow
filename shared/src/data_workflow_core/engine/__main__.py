"""允许 ``python -m data_workflow_core.engine`` 直接调用引擎 CLI。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
