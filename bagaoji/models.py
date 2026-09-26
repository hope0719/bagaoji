"""统一数据结构。

所有适配器的输出都收敛成 `MediaResult`，这样上层（下载器 / CLI / Markdown 导出）
不需要知道任何一个来源站的数据格式。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

__all__ = ["ImageItem", "VideoStream", "MediaResult"]


@dataclasses.dataclass
class ImageItem:
    """一张原图。"""

    url: str                                  # 首选直链（无签名、长期有效）
    file_id: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fallback_url: Optional[str] = None        # 带签名的临时地址，仅作兜底
    variants: Dict[str, str] = dataclasses.field(default_factory=dict)
    live_photo: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class VideoStream:
    """一路视频清晰度/编码。"""

    url: str
    codec: Optional[str] = None               # h264 / h265 / ...
    quality: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size: Optional[int] = None                # 字节
    duration: Optional[float] = None          # 秒
    backups: List[str] = dataclasses.field(default_factory=list)   # 备用域名直链

    def label(self) -> str:
        parts = []
        if self.codec:
            parts.append(str(self.codec))
        if self.width and self.height:
            parts.append("%sx%s" % (self.width, self.height))
        if self.quality:
            parts.append(str(self.quality))
        return " ".join(parts) or "未知规格"

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class MediaResult:
    """一条链接的解析结果。

    字段命名参考主流解析接口的通用形态，便于跨来源统一消费。
    """

    input_url: str
    ok: bool = False
    platform: str = ""                        # 机器可读标识，如 xhs
    platform_label: str = ""                  # 人类可读，如「小红书」
    source: str = ""                          # 实际生效的适配器，如 xhs/note-page
    kind: str = ""                            # video / note（图文笔记）
    title: Optional[str] = None
    desc: Optional[str] = None
    author: Optional[str] = None
    duration: Optional[float] = None          # 秒
    transcript: Optional[str] = None          # 口播文案；图文笔记即正文
    stats: Dict[str, str] = dataclasses.field(default_factory=dict)
    video_streams: List[VideoStream] = dataclasses.field(default_factory=list)
    image_items: List[ImageItem] = dataclasses.field(default_factory=list)
    cover: Optional[str] = None
    audio_url: Optional[str] = None
    item_id: Optional[str] = None             # 作品/笔记 ID
    item_url: Optional[str] = None            # 解析后的规范地址
    error: Optional[str] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # ---------------------------------------------------------------- 便捷属性

    @property
    def video_urls(self) -> List[str]:
        return [s.url for s in self.video_streams]

    @property
    def image_urls(self) -> List[str]:
        return [i.url for i in self.image_items]

    @property
    def has_media(self) -> bool:
        return bool(self.video_streams or self.image_items or self.audio_url)

    # ---------------------------------------------------------------- 序列化

    def to_dict(self, keep_streams: bool = True) -> Dict[str, Any]:
        d = {
            "input_url": self.input_url,
            "ok": self.ok,
            "platform": self.platform,
            "platform_label": self.platform_label,
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "desc": self.desc,
            "author": self.author,
            "duration": self.duration,
            "transcript": self.transcript,
            "stats": dict(self.stats),
            "video_urls": self.video_urls,
            "image_urls": self.image_urls,
            "cover": self.cover,
            "audio_url": self.audio_url,
            "item_id": self.item_id,
            "item_url": self.item_url,
            "error": self.error,
        }
        if keep_streams:
            d["video_streams"] = [s.to_dict() for s in self.video_streams]
            d["image_details"] = [i.to_dict() for i in self.image_items]
        if self.extra:
            d["extra"] = self.extra
        return d
