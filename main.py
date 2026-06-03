#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import asyncio
from PySide6.QtWidgets import QApplication
import qasync

from src.core.constants import validate_config_for_main_app
from src.ui_v2.main_window import MyMainWindow

if __name__ == "__main__":
    # 验证配置完整性
    try:
        validate_config_for_main_app()
    except SystemExit:
        sys.exit(1)
        
    import logging
    # 屏蔽 paramiko 内部在连接失败时乱叫的底层错误堆栈
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = MyMainWindow()
    window.show()
    
    with loop:
        loop.run_forever()