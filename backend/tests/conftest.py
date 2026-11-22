"""测试用临时数据目录：必须在导入 app.* 之前设置好。"""

from __future__ import annotations

import os
import tempfile

os.environ["CHOIR_DATA_DIR"] = tempfile.mkdtemp(prefix="choirparts-test-")
