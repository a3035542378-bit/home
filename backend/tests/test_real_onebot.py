"""仅显式 pytest -m real_onebot 执行，环境变量只指定本地记录 ID。"""
import os

import pytest

from app.tools.onebot_diagnose import run


@pytest.mark.real_onebot
async def test_real_read_only_onebot():
    node_id = os.getenv('REAL_ONEBOT_NODE_ID')
    account_id = os.getenv('REAL_ONEBOT_ACCOUNT_ID')
    if not node_id or not account_id:
        pytest.skip('REAL_NAPCAT_NOT_TESTED：请配置节点和账号 ID')
    result = await run(int(node_id), int(account_id))
    # 结果只包含脱敏身份、计数与状态，失败不回显配置。
    assert result['overall'] == 'READ_ONLY_CHECKS_PASS', result
