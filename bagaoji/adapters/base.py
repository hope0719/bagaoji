"""适配器基类 —— 一个来源站 = 一个适配器。

本仓库公开层只内置小红书专线。其余来源（例如各类第三方解析站）可按
`docs/extending.md` 的接口形态自行实现，放到 `~/.bagaoji/adapters/` 下即可被自动加载，
不需要 fork 本仓库。
"""

from __future__ import annotations

import urllib.parse

from ..models import MediaResult

__all__ = ["Adapter"]


class Adapter:
    """来源站适配器。

    子类至少要覆盖：`name`、`label`、`domains`、`parse()`。
    """

    #: 机器可读标识，小写，如 `xhs`
    name = ""
    #: 人类可读名称，如「小红书」
    label = ""
    #: 负责的域名（含子域匹配），如 `("xiaohongshu.com", "xhslink.com")`
    domains = ()
    #: 是否可免登录使用
    login_free = True
    #: 一句话说明，用于 `--list` 与诊断输出
    note = ""

    # ---------------------------------------------------------------- 匹配

    @classmethod
    def host_of(cls, url):
        try:
            return (urllib.parse.urlparse(url or "").hostname or "").lower()
        except Exception:
            return ""

    @classmethod
    def matches(cls, url):
        h = cls.host_of(url)
        if not h:
            return False
        return any(h == d or h.endswith("." + d) for d in cls.domains)

    # ---------------------------------------------------------------- 能力

    @classmethod
    def info(cls):
        return {
            "name": cls.name,
            "label": cls.label,
            "domains": list(cls.domains),
            "login_free": cls.login_free,
            "note": cls.note,
        }

    # ---------------------------------------------------------------- 接口

    def parse(self, url, **opts):
        """解析一条链接，返回 `MediaResult`。子类必须实现。"""
        raise NotImplementedError

    def probe(self):
        """可用性自检。返回 `{"ok": bool, "detail": str}`，用于 `bagaoji --diagnose`。"""
        return {"ok": False, "detail": "该适配器未实现自检"}
