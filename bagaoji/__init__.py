"""扒稿机 / bagaoji —— 视频转文案，链接转原片。

一个纯标准库实现的短视频文案提取与素材下载工具：

    >>> import bagaoji
    >>> r = bagaoji.parse("https://xhslink.cn/o/xxxxxxxx")
    >>> print(r.title, len(r.image_items))

设计原则
--------
1. **零依赖** —— 只用 Python 标准库，系统 python3 直接跑，不需要 pip install 任何东西。
2. **零密钥** —— 不调用任何需要 API Key 的第三方转写服务，不产生费用。
3. **适配器制** —— 每个来源站是一个独立适配器；本仓库公开层只内置小红书专线，
   其余来源可按 `docs/extending.md` 的接口形态自行接入。
"""

from .models import ImageItem, MediaResult, VideoStream
from .engine import available_adapters, parse, parse_many, pick_adapter

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "MediaResult", "ImageItem", "VideoStream",
    "parse", "parse_many", "pick_adapter", "available_adapters",
]
