#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「商城发布版」Skill 包。

背景
----
本仓库（开源版）包含**来源站可用性公示**与**投稿机制** —— 这在开源语境下是
透明度与社区协作的体现。但 Skill 商城的审核规则不同：任何指向外部仓库、
第三方站点或社群的话术，都会被判定为「引流」而拒稿（实测确有一次拒稿）。

因此本脚本从**同一份源码**生成一份干净的发布包：

  1. 用 tools/store-release/ 下的替代文档覆盖 README.md / SKILL.md
  2. 移除仅供开源版使用的模块与文档（诊断模块、公示文档、社群文档）
  3. 清理 pyproject.toml 中的仓库地址、清理适配器指南中的站点清单
  4. 打包为 ZIP，并对产物做一次「引流内容」自检

两版**共用同一份代码**：被移除的模块在缺失时自动降级（见 bagaoji/cli.py 中
对 diagnose 的可选导入），因此无需在源码里做条件分支。

用法
----
    python3 tools/build_store_package.py                  # 输出到 /tmp
    python3 tools/build_store_package.py -o out.zip       # 指定输出
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERRIDE_DIR = os.path.join(ROOT, "tools", "store-release")
TOP_NAME = "bagaoji"

#: 构建时整体排除（开发期产物与开源版专属目录）
IGNORE = shutil.ignore_patterns(
    ".git", ".github", "tools", "__pycache__", "*.pyc", "*.pyo",
    ".DS_Store", "*.zip", "build", "dist", "*.egg-info",
)

#: 发布包中删除的文件（开源版专属 / 商城不需要）
DROP_FILES = [
    "bagaoji/diagnose.py",     # 内含第三方站点清单 —— 商城审核红线
    "docs/sites.md",           # 来源站公示 —— 含大量第三方域名
    "docs/community.md",       # 社群分享文档 —— 含社群与投稿话术
    "CHANGELOG.md",            # 含开源协作记录，商城包不需要
]

#: 用替代版本覆盖的文件
OVERRIDE_FILES = ["README.md", "SKILL.md"]

#: 上传前自检：这些词/域名一旦出现在产物中就会被判为引流
FORBIDDEN = [
    "github.com", "githubusercontent",
    "dousnap", "kaolajiexi", "xzgtool", "snapany", "convry", "apowersoft",
    "抖虫", "考拉解析", "下载狗", "傲软", "zanqianba",
    "投稿", "欢迎投稿", "社群", "社区", "拉新", "引流",
    "issues/new", "pull request",
]

#: 允许出现的域名（被处理的目标平台与素材站，属功能必需）
ALLOWED_HOSTS = ["xiaohongshu.com", "xhslink.cn", "xhscdn.com", "xhslink.com",
                 "xhslink.cn", "python.org", "semver.org"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _prune_extending(path):
    """移除《适配器开发指南》中的「接口形态参考」章节（含第三方站点清单）。"""
    text = _read(path)
    start = text.find("## 4. 接口形态参考")
    if start == -1:
        print("  ! 未找到 §4 接口形态参考，跳过（可能已改版）")
        return
    nxt = text.find("\n## 5. ", start)
    if nxt == -1:
        print("  ! 未定位到 §5 边界，跳过")
        return
    text = text[:start] + text[nxt + 1:]

    # 顺延编号 5→4, 6→5, 7→6, 8→7（自下而上避免连锁覆盖）
    for old, new in [("## 8. ", "## 7. "), ("## 7. ", "## 6. "),
                     ("## 6. ", "## 5. "), ("## 5. ", "## 4. ")]:
        text = text.replace(old, new)
    _write(path, text)
    print("  ✓ docs/extending.md：已移除站点清单章节并重编号")


def _prune_pyproject(path):
    """移除 [project.urls] 段、并把作者署名换成商城昵称。

    开源版保留仓库地址与开发账号署名；商城版这两项都属于「导向外部」的
    潜在判定点，因此替换为中性值。
    """
    text = _read(path)
    original = text

    text = re.sub(r"\n\[project\.urls\][^\[]*", "\n", text)
    text = text.replace('authors = [{ name = "hope0719" }]',
                        'authors = [{ name = "刘同学" }]')

    if text != original:
        _write(path, text)
        print("  ✓ pyproject.toml：已清理外部仓库地址与开发账号署名")
    else:
        print("  - pyproject.toml：无需清理")


def build(out_zip):
    build_root = tempfile.mkdtemp(prefix="bagaoji-store-")
    dest = os.path.join(build_root, TOP_NAME)
    shutil.copytree(ROOT, dest, ignore=IGNORE)

    print("[1/4] 复制源码 →", dest)

    # 覆盖文档
    for name in OVERRIDE_FILES:
        src = os.path.join(OVERRIDE_DIR, name)
        if not os.path.exists(src):
            sys.exit("✗ 缺少替代文档：%s" % src)
        shutil.copy2(src, os.path.join(dest, name))
        print("  ✓ 覆盖 %s（干净版）" % name)

    # 删除开源版专属文件
    for rel in DROP_FILES:
        p = os.path.join(dest, rel)
        if os.path.exists(p):
            os.remove(p)
            print("  ✓ 移除 %s" % rel)

    # 清理
    _prune_extending(os.path.join(dest, "docs", "extending.md"))
    _prune_pyproject(os.path.join(dest, "pyproject.toml"))

    # assets 只保留 logo
    assets = os.path.join(dest, "assets")
    if os.path.isdir(assets):
        for f in os.listdir(assets):
            if f != "logo.png":
                os.remove(os.path.join(assets, f))

    # 打包
    print("[2/4] 打包 ZIP")
    if os.path.exists(out_zip):
        os.remove(out_zip)
    os.makedirs(os.path.dirname(os.path.abspath(out_zip)), exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(dest):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                full = os.path.join(base, f)
                arc = os.path.join(TOP_NAME,
                                   os.path.relpath(full, dest))
                z.write(full, arc)
    size = os.path.getsize(out_zip)

    # 自检
    print("[3/4] 上传前自检（引流内容扫描）")
    problems = []
    with zipfile.ZipFile(out_zip) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:
            if not n.lower().endswith((".md", ".py", ".toml", ".txt", ".cfg")):
                continue
            body = z.read(n).decode("utf-8", "replace")
            low = body.lower()
            for bad in FORBIDDEN:
                for m in re.finditer(re.escape(bad.lower()), low):
                    line = body[:m.start()].count("\n") + 1
                    snippet = body.splitlines()[line - 1].strip()[:90]
                    problems.append("%s:%d  [%s]  %s" % (n, line, bad, snippet))
    # 允许清单：把命中行里属于允许域名的排除
    problems = [p for p in problems
                if not any(h in p for h in ALLOWED_HOSTS)]

    if problems:
        print("  ✗ 检出 %d 处可疑内容：" % len(problems))
        for p in problems[:40]:
            print("     ", p)
    else:
        print("  ✓ 未检出引流内容")

    print("[4/4] 完成")
    print("  产物 :", out_zip)
    print("  体积 : %.1f KB" % (size / 1024))
    print("  文件 : %d 个" % len(names))
    for n in sorted(names):
        print("        ", n)

    shutil.rmtree(build_root, ignore_errors=True)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser(description="构建商城发布版 Skill 包")
    ap.add_argument("-o", "--out", default="/tmp/bagaoji-store.zip",
                    help="输出 ZIP 路径（默认 /tmp/bagaoji-store.zip）")
    args = ap.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
