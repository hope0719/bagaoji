"""站点可用性自检 —— 生成/刷新公示表。

只做一件事：GET 各站的**公开首页**，记录 HTTP 状态与是否出现停机声明。
不登录、不解析、不抓内容、不绕过任何限制，因此可以安全地频繁运行。

用法：
    python3 -m bagaoji --diagnose
    python3 -m bagaoji --diagnose --json
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

__all__ = ["SITES", "check_site", "run", "print_report"]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 公示的站点清单。
# 字段说明：
#   role      —— 在本项目中的定位（主通道 / 备选 / 参考）
#   verdict   —— 最近一次人工核验的结论
#   markers   —— 页面上出现这些字样即判定为「已停用/维护中」
SITES = [
    {
        "key": "dousnap",
        "name": "抖虫 dousnap.com",
        "homepage": "https://www.dousnap.com/",
        "role": "第三方解析站（可作主通道）",
        "verdict": "可用：解析 + 转写 + 下载齐备",
        "markers": [],
    },
    {
        "key": "xiaohongshu",
        "name": "小红书（内置专线）",
        "homepage": "https://www.xiaohongshu.com/",
        "role": "内置适配器来源",
        "verdict": "可用：图文笔记正文直取，图集原图可批量下载",
        "markers": [],
    },
    {
        "key": "kaolajiexi",
        "name": "考拉解析 kaolajiexi.cn",
        "homepage": "https://bilibili.kaolajiexi.cn/",
        "role": "备选通道",
        "verdict": "可用性受限：需登录（关注公众号获取激活码）",
        "markers": ["Welcome to CentOS"],
    },
    {
        "key": "xzgtool",
        "name": "下载狗 xzgtool.com",
        "homepage": "https://www.xzgtool.com/",
        "role": "参考",
        "verdict": "可用性受限：核心接口强制登录",
        "markers": [],
    },
    {
        "key": "snapany",
        "name": "snapany snapany.com",
        "homepage": "https://snapany.com/",
        "role": "参考",
        "verdict": "可用性受限：服务端签名校验，脚本访问被拒",
        "markers": [],
    },
    {
        "key": "convry",
        "name": "convry convry.com",
        "homepage": "https://www.convry.com/",
        "role": "参考",
        "verdict": "形态不同：以上传文件为主，无链接解析入口",
        "markers": [],
    },
    {
        "key": "apowersoft",
        "name": "傲软在线视频下载 apowersoft.cn",
        "homepage": "https://www.apowersoft.cn/online-video-downloader",
        "role": "已排除",
        "verdict": "在线版已停用，页面仅为桌面客户端引流",
        "markers": ["系统维护中", "System maintenance", "请下载安装桌面端"],
    },
]


def check_site(site, timeout=15):
    """探测单个站点，返回带实测结果的新 dict。"""
    out = dict(site)
    out["http"] = None
    out["final_url"] = None
    out["stopped"] = False
    out["error"] = None
    out["detail"] = ""
    try:
        req = urllib.request.Request(site["homepage"], headers={
            "User-Agent": UA, "Accept": "text/html,*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(131072).decode("utf-8", "replace")
            out["http"] = r.status
            out["final_url"] = r.geturl()
    except urllib.error.HTTPError as e:
        out["http"] = e.code
        out["error"] = "HTTP %s" % e.code
        return out
    except Exception as e:
        out["error"] = str(e)
        return out

    hit = [m for m in site.get("markers") or [] if m.lower() in body.lower()]
    out["stopped"] = bool(hit)
    if hit:
        out["detail"] = "页面出现停机声明：%s" % "、".join(hit)
    elif out["http"] and 200 <= out["http"] < 400:
        out["detail"] = "首页可访问"
    else:
        out["detail"] = "状态码 %s" % out["http"]
    return out


def _visible_len(s):
    return len(re.sub(r"[\u4e00-\u9fff]", "  ", s or ""))


def print_report(rows, adapters=None, stream=sys.stdout):
    """打印公示表。"""
    print("bagaoji 站点可用性公示（实测时间：见各次运行输出）", file=stream)
    print("=" * 78, file=stream)
    head = "%-34s %-6s %-6s %s" % ("站点", "HTTP", "停用", "判定")
    print(head, file=stream)
    print("-" * 78, file=stream)
    for r in rows:
        http = r["http"] if r["http"] is not None else "-"
        stopped = "是" if r["stopped"] else ("-" if r["http"] else "?")
        verdict = r["detail"] or r["error"] or "-"
        name = r["name"]
        pad = max(1, 34 - _visible_len(name))
        print("%s%s %-6s %-6s %s" % (name, " " * pad, http, stopped, verdict), file=stream)
    print("-" * 78, file=stream)
    print("定位说明：", file=stream)
    for r in rows:
        print("  · %-32s %s" % (r["name"], r["role"] + "；" + r["verdict"]), file=stream)
    if adapters is not None:
        print("", file=stream)
        print("已注册适配器：", file=stream)
        for a in adapters:
            print("  · %-8s %-6s %s" % (a["name"], a["label"], a["note"]), file=stream)
    print("", file=stream)
    print("说明：本表仅记录公开可访问页面的状态，不构成对任何站点的背书或授权。", file=stream)
    print("      使用时请自行遵守各站点服务条款与平台规则。", file=stream)


def run(as_json=False, timeout=15, stream=sys.stdout):
    """执行全量探测，返回 `(ok, rows)`。"""
    from .engine import available_adapters

    rows = [check_site(s, timeout=timeout) for s in SITES]
    if as_json:
        payload = {
            "sites": [{k: v for k, v in r.items()} for r in rows],
            "adapters": available_adapters(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)
    else:
        print_report(rows, adapters=available_adapters(), stream=stream)
    return any(r["http"] for r in rows), rows
