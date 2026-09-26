#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口。

    python3 -m bagaoji <链接...> [选项]

常用：
    python3 -m bagaoji "https://xhslink.cn/o/xxxx"                  # 取文案（图文笔记直取正文）
    python3 -m bagaoji --download "短链" --out ~/Desktop/扒稿        # 顺带把原图/原片落盘
    python3 -m bagaoji --download --only image --img-mode raw "短链" # 只要最高画质原图
    python3 -m bagaoji --diagnose                                   # 刷新站点可用性公示
    python3 -m bagaoji --list                                       # 看已注册适配器
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__
from .adapters import USER_ADAPTER_DIR, all_adapters
from .downloader import human, pick_url
from .engine import available_adapters, describe, parse
from .models import MediaResult

__all__ = ["main", "build_parser", "to_markdown"]

VIDEO_EXT = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".flv")


# ---------------------------------------------------------------- 输出

def fmt_duration(sec):
    if not sec:
        return None
    try:
        sec = int(float(sec))
    except Exception:
        return None
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def to_markdown(res: MediaResult, downloads=None) -> str:
    """把一条结果写成 Markdown。"""
    L = []
    L.append("# %s" % (res.title or res.input_url))
    L.append("")
    meta = [("平台", res.platform_label or res.platform),
            ("作者", res.author),
            ("类型", "视频" if res.kind == "video" else ("图文笔记" if res.kind else None)),
            ("时长", fmt_duration(res.duration)),
            ("来源", res.source)]
    meta = [m for m in meta if m[1]]
    if meta:
        L.append("| 字段 | 值 |")
        L.append("|---|---|")
        for k, v in meta:
            L.append("| %s | %s |" % (k, v))
        L.append("")
    if res.stats:
        L.append("**互动**：" + "、".join("%s %s" % (k, v) for k, v in res.stats.items()))
        L.append("")

    if res.transcript:
        L.append("## 文案（%d 字）" % len(res.transcript))
        L.append("")
        L.append(res.transcript)

    if res.desc and res.desc != res.transcript:
        L.append("")
        L.append("## 简介")
        L.append("")
        L.append(res.desc)

    if res.video_streams:
        L.append("")
        L.append("## 视频直链（有时效，勿缓存）")
        L.append("")
        for i, s in enumerate(res.video_streams, 1):
            size = " / %s" % human(s.size) if s.size else ""
            L.append("%d. `%s`%s" % (i, s.label(), size))
            L.append("   %s" % s.url)
    if res.image_items:
        L.append("")
        L.append("## 原图 %d 张" % len(res.image_items))
        L.append("")
        for i, it in enumerate(res.image_items, 1):
            size = "%sx%s" % (it.width, it.height) if it.width else "尺寸未知"
            L.append("%d. [%s] %s" % (i, size, it.url))

    if downloads:
        L.append("")
        L.append("## 已下载文件")
        L.append("")
        for d in downloads:
            if d.get("path"):
                L.append("- `%s`（%s）" % (d["path"], human(d.get("bytes"))))
    L.append("")
    L.append("> 由 bagaoji 生成。直链有时效，请勿长期分发；商用请自行确认版权与平台规则。")
    return "\n".join(L)


def safe_name(s, limit=60):
    import re
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (s or "")).strip(" ._")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit] or "result")


# ---------------------------------------------------------------- 参数

def build_parser():
    p = argparse.ArgumentParser(
        prog="bagaoji",
        description="扒稿机 —— 视频转文案，链接转原片。纯标准库，零依赖，零 API Key。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 -m bagaoji \"https://xhslink.cn/o/xxxx\"\n"
               "  python3 -m bagaoji --download \"短链\" --out ~/Desktop/扒稿\n"
               "  python3 -m bagaoji --download --only image --img-mode raw \"短链\"\n"
               "  python3 -m bagaoji --diagnose\n")
    p.add_argument("url", nargs="*", help="作品链接，或整段分享口令（自动抽链）；不支持时从 stdin 读取")
    p.add_argument("--mode", choices=["parse", "text", "both"], default="text",
                   help="text=只要文案（默认）/ parse=只要元信息与直链 / both=都要")
    p.add_argument("--download", action="store_true", help="把媒体实际下载到本地")
    p.add_argument("--only", choices=["video", "audio", "image"], help="只下载某一种媒体")
    p.add_argument("--engine", metavar="NAME", help="强制指定适配器（对照排错用）")
    p.add_argument("--img-mode", choices=["jpg", "raw", "webp"], default="jpg",
                   help="图片质量：jpg=统一JPEG（默认）/ raw=原始文件最大 / webp=最小")
    p.add_argument("--workers", type=int, default=4, help="图集并发下载线程数（默认 4）")
    p.add_argument("--all-videos", action="store_true", help="下载全部视频编码变体（默认只下第一路）")
    p.add_argument("--out", metavar="DIR", help="把每条结果保存为 Markdown 到该目录")
    p.add_argument("--media-dir", metavar="DIR", help="媒体落盘目录（默认同 --out）")
    p.add_argument("--timeout", type=int, default=120, help="单文件下载超时秒数（默认 120）")
    p.add_argument("--cookie", metavar="STR",
                   help="本次调用使用的登录态 Cookie（形如 \"a=1; b=2\"）；"
                        "部分来源登录后才完整可用，详见 --auth")
    p.add_argument("--cookie-file", metavar="PATH",
                   help="从文件读取登录态 Cookie（支持 JSON 与纯文本两种格式）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument("--auth", action="store_true",
                   help="查看登录态说明：哪些来源需要登录、怎么取 Cookie、当前已从哪些本地来源读到凭据")
    p.add_argument("--diagnose", action="store_true", help="探测各站点可用性，刷新公示表")
    p.add_argument("--list", action="store_true", help="列出已注册适配器")
    p.add_argument("-q", "--quiet", action="store_true", help="减少进度输出")
    p.add_argument("--version", action="version", version="bagaoji %s" % __version__)
    return p


def _read_stdin_urls():
    if sys.stdin.isatty():
        return []
    out = []
    for line in sys.stdin:
        u = pick_url(line.strip())
        if u or line.strip():
            out.append(u or line.strip())
    return out


# ---------------------------------------------------------------- 主流程

def _emit(res, args, downloads=None):
    if args.json:
        d = res.to_dict()
        if downloads:
            d["downloads"] = downloads
        return json.dumps(d, ensure_ascii=False, indent=2)

    L = []
    if not res.ok:
        L.append("❌ %s" % res.error)
        return "\n".join(L)

    L.append("标题：%s" % (res.title or "（无）"))
    bits = [res.platform_label or res.platform]
    if res.author:
        bits.append("作者 " + res.author)
    if res.kind:
        bits.append("视频" if res.kind == "video" else "图文笔记")
    if res.duration:
        bits.append(fmt_duration(res.duration))
    L.append("信息：%s" % " | ".join(bits))
    if res.stats:
        L.append("互动：%s" % "、".join("%s %s" % (k, v) for k, v in res.stats.items()))

    if args.mode in ("text", "both"):
        if res.transcript:
            L.append("")
            L.append("—— 文案（%d 字）——" % len(res.transcript))
            L.append(res.transcript)
        elif res.kind == "video":
            L.append("")
            L.append("ℹ️ 这是一条视频笔记。本仓库公开层不含语音转写适配器，"
                     "因此不产出逐字稿（原片可直接下载后自行转写）。")
        else:
            L.append("")
            L.append("ℹ️ 该笔记没有正文文本。")

    if args.mode in ("parse", "both"):
        if res.video_streams:
            L.append("")
            L.append("—— 视频直链（%d 路，有时效勿缓存）——" % len(res.video_streams))
            for i, s in enumerate(res.video_streams, 1):
                size = " / %s" % human(s.size) if s.size else ""
                L.append("  [%d] %s%s" % (i, s.label(), size))
                L.append("      %s" % s.url)
        if res.image_items:
            L.append("")
            L.append("—— 原图 %d 张 ——" % len(res.image_items))
            for i, it in enumerate(res.image_items, 1):
                size = "%sx%s" % (it.width, it.height) if it.width else "尺寸未知"
                L.append("  [%02d] %-10s %s" % (i, size, it.url))
        if res.cover:
            L.append("")
            L.append("封面：%s" % res.cover)

    if downloads:
        okd = [d for d in downloads if d.get("path")]
        L.append("")
        L.append("—— 已落盘 %d 个文件 ——" % len(okd))
        for d in okd:
            L.append("  %-6s %s" % (d.get("kind", ""), d["path"]))
    return "\n".join(L)


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list:
        print("已注册适配器：")
        print(describe())
        print()
        print("私有适配器目录：%s" % USER_ADAPTER_DIR)
        print("（放进去的 *.py 会在启动时自动加载，无需 fork 本仓库；")
        print("  接口形态见 docs/extending.md）")
        print()
        print("登录态：python3 -m bagaoji --auth")
        return 0

    if args.auth:
        from .auth import GUIDE, available_sources, mask, resolve
        print(GUIDE)
        print("当前检测到的本地凭据来源")
        print("-" * 40)
        found = available_sources()
        print("\n".join("  · %s" % f for f in found) if found
              else "  （无。当前所有来源都将在免登录状态下工作）")
        print()
        print("按来源查看：")
        for a in all_adapters():
            c, src = resolve(a.name, explicit=args.cookie, cookie_file=args.cookie_file)
            flag = "免登录" if a.login_free else "需登录"
            hint = getattr(a, "auth_hint", "") or "登录与否无差别"
            print("  · %-8s %-6s %s" % (a.name, flag, hint))
            print("    %-8s 当前凭据：%s%s" % ("", mask(c),
                                              ("（来源：%s）" % src) if src else ""))
        return 0

    if args.diagnose:
        from .diagnose import run as diag_run
        ok, _ = diag_run(as_json=args.json)
        return 0 if ok else 1

    urls = list(args.url) or _read_stdin_urls()
    if not urls:
        build_parser().print_help()
        print("\n⚠️ 请至少给一条链接，或用 --diagnose / --list。", file=sys.stderr)
        return 2

    out_dir = os.path.expanduser(args.out) if args.out else None
    media_dir = os.path.expanduser(args.media_dir) if args.media_dir else out_dir
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if args.download and not media_dir:
        media_dir = os.path.abspath(".")
    verbose = not args.quiet

    batch, all_ok = [], True

    # 登录态：命令行 > 环境变量 > ~/.bagaoji/cookies.*（未提供则为 None，不影响免登录来源）
    from .auth import resolve
    cookie, cookie_src = resolve(explicit=args.cookie, cookie_file=args.cookie_file)
    if cookie and verbose:
        print("🔑 已读取登录态（来源：%s），部分来源会因此解锁更高额度或权限。"
              % cookie_src, file=sys.stderr)

    for idx, u in enumerate(urls, 1):
        if verbose and len(urls) > 1:
            print("—" * 60, file=sys.stderr)
            print("[%d/%d] %s" % (idx, len(urls), u), file=sys.stderr)
        res = parse(u, engine=args.engine, img_mode=args.img_mode, cookie=cookie)
        downloads = None
        if res.ok and args.download:
            from .downloader import download_media
            downloads = download_media(res, media_dir, timeout=args.timeout,
                                       verbose=verbose, image_workers=max(1, args.workers),
                                       all_videos=args.all_videos, only=args.only)
        if out_dir and res.ok:
            stem = safe_name(res.title or res.item_id or ("result_%d" % idx))
            path = os.path.join(out_dir, stem + ".md")
            k = 1
            while os.path.exists(path) and len(urls) > 1:
                k += 1
                path = os.path.join(out_dir, "%s(%d).md" % (stem, k))
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_markdown(res, downloads))
            if verbose:
                print("  📄 已保存 %s" % path, file=sys.stderr)
        if not res.ok:
            all_ok = False
        text = _emit(res, args, downloads)
        print(text)
        batch.append({"ok": res.ok, "result": res.to_dict(keep_streams=False)})
        if len(urls) > 1:
            print()

    if len(urls) > 1 and verbose:
        ok_n = sum(1 for b in batch if b["ok"])
        print("—" * 60, file=sys.stderr)
        print("完成：%d/%d 条成功" % (ok_n, len(urls)), file=sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
