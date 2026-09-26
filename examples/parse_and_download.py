#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库用法示例：解析一条链接，打印文案，并把图集下到本地。

    python3 examples/parse_and_download.py "https://xhslink.cn/o/xxxxxxxx" [输出目录]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bagaoji                                                    # noqa: E402
from bagaoji.downloader import download_media, human               # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    url = argv[1]
    out = argv[2] if len(argv) > 2 else os.path.join(os.getcwd(), "bagaoji_out")

    print("可用适配器：%s" % ", ".join(a["name"] for a in bagaoji.available_adapters()))
    print("正在解析 %s ..." % url)

    res = bagaoji.parse(url)
    if not res.ok:
        print("失败：%s" % res.error)
        return 1

    print("-" * 60)
    print("标题   : %s" % res.title)
    print("作者   : %s" % res.author)
    print("类型   : %s" % ("视频" if res.kind == "video" else "图文笔记"))
    print("来源   : %s" % res.platform_label)
    if res.stats:
        print("互动   : %s" % "、".join("%s %s" % (k, v) for k, v in res.stats.items()))
    print("图片   : %d 张" % len(res.image_items))
    print("视频   : %d 路" % len(res.video_streams))
    print("文案   : %s" % ("%d 字" % len(res.transcript) if res.transcript else "无"))

    if res.transcript:
        print("-" * 60)
        print(res.transcript)

    if not res.has_media:
        print("-" * 60)
        print("没有可下载的媒体。")
        return 0

    print("-" * 60)
    print("开始下载到 %s" % out)
    saved = download_media(res, out, image_workers=4, only="image")
    ok = [d for d in saved if d.get("path")]
    print("-" * 60)
    print("完成：%d/%d" % (len(ok), len(saved)))
    for d in ok:
        print("  %-6s %8s  %s" % (d["kind"], human(d["bytes"]), d["path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
