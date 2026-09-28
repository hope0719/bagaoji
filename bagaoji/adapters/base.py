"""适配器基类 —— 一个来源站 = 一个适配器。

本项目公开层只内置小红书专线。其余来源可按
`docs/extending.md` 的接口形态自行实现，放到 `~/.bagaoji/adapters/` 下即可被自动加载，
不需要修改本项目代码。
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
    #: 登录态收益说明：登录后能多得到什么（留空表示登录与否无差别）
    auth_hint = ""

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
            "auth_hint": cls.auth_hint,
        }

    # ---------------------------------------------------------------- 登录态

    def cookie(self, **opts):
        """取本次调用可用的登录态 Cookie，取不到返回 `None`。

        适配器**不要**自己从环境变量或文件里读凭据 —— 统一走这里，
        这样凭据来源可审计、可脱敏，也不会散落在各个适配器里。

        优先级：`parse(..., cookie=...)` 显式传入 > 环境变量 > `~/.bagaoji/cookies.*`
        """
        if opts.get("cookie"):
            return opts["cookie"]
        from ..auth import resolve
        c, _ = resolve(self.name)
        return c

    def cookie_source(self, **opts):
        """Cookie 的**来源说明**（不含内容），用于诊断与错误提示。"""
        if opts.get("cookie"):
            return "--cookie"
        from ..auth import resolve
        _, src = resolve(self.name)
        return src or "未找到"

    # ---------------------------------------------------------------- 接口

    def parse(self, url, **opts):
        """解析一条链接，返回 `MediaResult`。子类必须实现。"""
        raise NotImplementedError

    def probe(self):
        """可用性自检。返回 `{"ok": bool, "detail": str}`，用于 `bagaoji --diagnose`。"""
        return {"ok": False, "detail": "该适配器未实现自检"}
