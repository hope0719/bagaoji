"""引擎：把链接分发给合适的适配器。

分流规则很简单——按域名匹配。匹配不到就明确告诉你「本仓库公开层不含该来源」，
而不是抛一个看不懂的异常。
"""

from __future__ import annotations

from .adapters import all_adapters, get_adapter
from .downloader import pick_url
from .models import MediaResult

__all__ = ["available_adapters", "pick_adapter", "parse", "parse_many", "describe"]


def available_adapters():
    """列出全部已注册适配器（含私有）。"""
    return [a.info() for a in all_adapters()]


def describe():
    """人类可读的适配器清单。"""
    lines = []
    for a in all_adapters():
        flag = "免登录" if a.login_free else "需登录"
        lines.append("  %-8s %-6s %-4s  %s" % (a.name, a.label or "-", flag, a.note or ""))
    return "\n".join(lines) or "  （无）"


def pick_adapter(url, engine=None):
    """挑一个适配器。

    :param engine: 指定适配器名则强制使用（便于对照排错）；`None` 表示自动匹配。
    """
    if engine:
        return get_adapter(engine)
    for a in all_adapters():
        if a.matches(url):
            return a
    return None


def parse(url, engine=None, **opts):
    """解析一条链接（可以是纯链接，也可以是整段分享口令）。"""
    raw = (url or "").strip()
    link = pick_url(raw) or raw

    adapter = pick_adapter(link, engine=engine)
    if adapter is None:
        known = "、".join(a.label or a.name for a in all_adapters()) or "（无）"
        return MediaResult(
            input_url=link,
            error=("没有适配器能处理这个链接。本仓库公开层当前覆盖：%s。\n"
                   "其它来源的接入方式见 docs/extending.md"
                   "（把自建适配器放到 ~/.bagaoji/adapters/ 即可被自动加载）。" % known),
        )
    res = adapter.parse(link, **opts)
    if res is None:
        res = MediaResult(input_url=link, error="适配器 %s 未返回结果" % adapter.name)
    return res


def parse_many(urls, engine=None, **opts):
    """批量解析，逐条返回 `MediaResult`（不因单条失败中断）。"""
    return [parse(u, engine=engine, **opts) for u in urls]
