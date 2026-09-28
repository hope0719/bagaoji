#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录态（Cookie）读取 —— 让"需要登录才完整"的来源也能用起来。

为什么需要这个模块
------------------
本项目研究的来源站里，有一类**不是技术不通，而是没登录态**：

- 接口形态完整、免登录时被统一拦在鉴权层，登录后即恢复；
- 登录后往往还会解锁更高额度、更高画质或更多平台。

这类站点的正确用法就是：**你在浏览器里正常登录一次，把 Cookie 交给本工具**。
本模块负责把这件小事变得干净、可复现，且不把凭据写进代码。

凭据来源优先级（高 → 低）
------------------------
1. `--cookie "k=v; k2=v2"`      本次命令显式传入
2. `--cookie-file <路径>`        从文件读（支持 JSON 与纯文本两种格式）
3. 环境变量 `BAGAOJI_COOKIE_<适配器名大写>`  如 `BAGAOJI_COOKIE_MYSOURCE`
4. 环境变量 `BAGAOJI_COOKIE`      通用兜底，所有来源共享
5. `~/.bagaoji/cookies.json`      `{"_default": "...", "mysource": "..."}`
6. `~/.bagaoji/cookies.txt`       纯文本，每行一个 `name<TAB>cookie` 或单行裸 Cookie

安全约定（本项目自己的约束，也建议你照做）
------------------------------------------
- 本项目**不内置任何凭据**，也不提供任何获取凭据的自动化手段。
- Cookie 只从上面这些**本地来源**读取：不上传、不写日志、不进 bug 报告。
- 用 `mask()` 做展示，避免把完整凭据打到终端或截图里。
"""

from __future__ import annotations

import json
import os

__all__ = [
    "COOKIE_DIR", "JSON_PATH", "TXT_PATH",
    "mask", "normalize", "resolve", "available_sources", "GUIDE",
]

COOKIE_DIR = os.path.expanduser("~/.bagaoji")
JSON_PATH = os.path.join(COOKIE_DIR, "cookies.json")
TXT_PATH = os.path.join(COOKIE_DIR, "cookies.txt")

ENV_PREFIX = "BAGAOJI_COOKIE_"
ENV_GENERIC = "BAGAOJI_COOKIE"


# ---------------------------------------------------------------- 基础

def normalize(cookie):
    """把各种来源的 Cookie 规整成单行字符串（换行会破坏请求头）。"""
    if not cookie:
        return None
    s = str(cookie).strip()
    if not s:
        return None
    s = " ".join(p.strip() for p in s.splitlines() if p.strip())
    return s or None


def mask(cookie):
    """用于展示的脱敏形式。绝不回显完整凭据。"""
    c = normalize(cookie)
    if not c:
        return "（未提供）"
    names = []
    for part in c.split(";"):
        k = part.strip().split("=", 1)[0].strip()
        if k:
            names.append(k)
    head = "、".join(names[:4]) + ("…" if len(names) > 4 else "")
    return "已提供（%d 字符，含 %s）" % (len(c), head or "?")


# ---------------------------------------------------------------- 各类来源

def _from_env(name):
    keys = []
    if name:
        keys.append(ENV_PREFIX + str(name).upper().replace("-", "_"))
    keys.append(ENV_GENERIC)
    for k in keys:
        v = normalize(os.environ.get(k))
        if v:
            return v, "环境变量 %s" % k
    return None, None


def _from_cookie_file(path, name):
    """从文件读 Cookie。

    支持两种格式：
      - JSON：`{"_default": "...", "<适配器名>": "..."}`
      - 纯文本：每行 `适配器名<TAB>Cookie`；若只有一行，则视为通用 Cookie
    """
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None, None

    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            return None, None
        if not isinstance(data, dict):
            return None, None
        for key in ([name] if name else []) + ["_default", "default"]:
            v = normalize(data.get(key))
            if v:
                return v, "%s → %s" % (path, key)
        return None, None

    lines = [l.strip() for l in stripped.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return None, None
    if len(lines) == 1 and "\t" not in lines[0]:
        return normalize(lines[0]), path
    for line in lines:
        if "\t" in line:
            k, _, v = line.partition("\t")
            if name and k.strip().lower() == str(name).lower():
                return normalize(v), "%s → %s" % (path, k.strip())
        elif len(lines) == 1:
            return normalize(line), path
    return None, None


def _from_default_json(name):
    return _from_cookie_file(JSON_PATH, name)


def _from_default_txt(name):
    return _from_cookie_file(TXT_PATH, name)


def available_sources():
    """列出当前**实际存在**的本地凭据来源（用于 `--auth` 展示，不回显内容）。"""
    out = []
    for k, v in sorted(os.environ.items()):
        if k == ENV_GENERIC or k.startswith(ENV_PREFIX):
            if normalize(v):
                out.append("环境变量 %s  %s" % (k, mask(v)))
    for p in (JSON_PATH, TXT_PATH):
        if os.path.isfile(p):
            maps = "（JSON 映射表）" if p.endswith(".json") else ""
            out.append("文件 %s  %s" % (p, maps))
    return out


# ---------------------------------------------------------------- 主入口

def resolve(name=None, explicit=None, cookie_file=None):
    """解析登录态 Cookie。

    :param name: 适配器名（用于按名匹配环境变量与 map 表），可为 None
    :param explicit: `--cookie` 直接传入的值
    :param cookie_file: `--cookie-file` 指定的路径
    :return: `(cookie, 来源说明)`；未找到时返回 `(None, None)`
    """
    v = normalize(explicit)
    if v:
        return v, "--cookie"
    if cookie_file:
        v, src = _from_cookie_file(cookie_file, name)
        if v:
            return v, src
    v, src = _from_env(name)
    if v:
        return v, src
    v, src = _from_default_json(name)
    if v:
        return v, src
    v, src = _from_default_txt(name)
    if v:
        return v, src
    return None, None


# ---------------------------------------------------------------- 说明文案

GUIDE = """\
关于登录态（Cookie）
====================

有些来源"不是技术不通，而是没登录态"：接口形态完整，免登录时被统一拦在
鉴权层；你只要在浏览器里正常登录一次，把 Cookie 交给本工具，它就能用。

  · 登录后**才可用**      —— 例如核心接口强制鉴权的解析站
  · 登录后**更好用**      —— 额度更高、画质更高、覆盖平台更多
  · 登录与否**都一样**    —— 本项目内置的小红书专线，免登录即可取正文与原图

取 Cookie 的通用步骤
--------------------
  1. 浏览器打开该来源站，按它自己的流程正常登录（扫码 / 手机号 / 激活码）；
  2. 确认页面已经是登录状态（能看到自己的账号，或不再提示登录）；
  3. 打开开发者工具的「网络」面板，刷新页面，点任意一个本站请求；
  4. 在「请求标头」里找到 Cookie 一行，整行复制（形如 `a=1; b=2`）；
     —— 也可以直接在控制台执行 `copy(document.cookie)` 复制。
  5. 交给本工具（任选其一）：
       python3 -m bagaoji --cookie "a=1; b=2" "<链接>"
       python3 -m bagaoji --cookie-file ~/my_cookie.txt "<链接>"
       export BAGAOJI_COOKIE="a=1; b=2"
       写进 ~/.bagaoji/cookies.json ： {"_default": "a=1; b=2"}

三条提醒
--------
  · **Cookie 等同于你的登录凭证**，不要提交进 git、不要贴进 issue、不要发给别人。
    本项目不会上传它，也不会把它写进日志。
  · Cookie **会过期**（几小时到几个月不等）。用到一半突然又提示未登录，
    先重新复制一份，再怀疑别的。
  · 请使用**你自己的账号**，并遵守该站点的服务条款。本项目不提供任何
    代持账号、共享账号或绕过登录限制的手段。
"""
