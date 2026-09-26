#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书专线（公用：短链 → 笔记页 → 内嵌 JSON）。

为什么单独为小红书写一条通道
----------------------------
通用解析站对小红书常常只做到「拿到图」，但拼出来的图片直链会丢掉图床的
OSS 路径前缀（如 `oss-ae/`），实测直接 404：

    别处给的：  https://sns-img-hw.xhscdn.com/notes_pre_post/1040g3v8...   -> 404
    笔记页里的： oss-ae/notes_pre_post/1040g3v8...                          -> 200

而这个前缀**因笔记而异**（实测两篇笔记一有一无），无法靠猜补全，必须从笔记页
取原始 fileId。因此小红书改走本适配器：短链 → token → 笔记页 → 内嵌 JSON。

链路
----
    xhslink.com/.cn、xhsurl.com/.cn 短链
        --302-->  带 xsec_token 的真实链接（/explore/{id} 或 /discovery/item/{id}）
        --移动端 UA-->  笔记页 HTML
        --括号平衡截取-->  window.__INITIAL_STATE__ → noteData.data.noteData
        -->  imageList（原图直链）/ video.media.stream（多清晰度）/ desc（正文）

四条踩过的坑（均为实测结论）
----------------------------
1. **`xsec_token` 是硬性必需**，不是统计参数。删掉后请求同一篇笔记只会返回空骨架页
   （不同笔记 ID 的页面字节数完全一致），`noteData` 键根本不存在。
2. **短链有 4 个域名**：`xhslink.com` / `xhslink.cn` / `xhsurl.com` / `xhsurl.cn`。
   只识别 `.com` 会让 `.cn` 静默失败——返回 200 但没有任何内容。
3. **必须用移动端 UA**。桌面 UA 拿到的 HTML 里不含笔记数据，这是最常见的翻车点。
4. **图片直链不需要签名**：fileId 直接拼图床域名即可，长期有效；页面里的
   `url` / `infoList[].url` 反而**带签名会过期**，只适合作兜底。

图片 URL 三种模式
-----------------
    jpg （默认）  {host}/{fileId}?imageView2/2/w/0/format/jpg   统一转 JPEG，兼容最好
    raw           {host}/{fileId}                              原始文件，体积最大（可能是 HEIC）
    webp          {host}/{fileId}?imageView2/2/w/0/format/webp 体积最小

实测同一张图（1242×1660）：raw 823 KB / jpg 88 KB / webp 53 KB。
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ..models import ImageItem, MediaResult, VideoStream
from .base import Adapter

__all__ = ["XhsAdapter"]

# 移动端 UA —— 桌面 UA 拿不到笔记数据，这是最关键的一步
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")

# 短链域名（4 个，缺一会导致 .cn 链接静默失败）
SHORT_HOSTS = ("xhslink.com", "xhslink.cn", "xhsurl.com", "xhsurl.cn")
# 笔记域名
NOTE_HOSTS = ("xiaohongshu.com", "rednote.com")
# 图片模式
IMG_MODES = ("jpg", "raw", "webp")
# 无签名图床（长期有效）
IMG_HOST = "sns-img-hw.xhscdn.com"

_STATE_KEY = "window.__INITIAL_STATE__"
_NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item|item)/([0-9a-fA-F]{16,32})")
# h264 兼容性最好，排前面
_CODEC_ORDER = ("h264", "h265", "h266", "av1")


# ---------------------------------------------------------------- 基础

def host_of(url):
    return (urllib.parse.urlparse(url or "").hostname or "").lower()


def _match_host(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def is_xhs_url(url):
    """是否小红书链接（短链或笔记页）。"""
    h = host_of(url)
    return bool(h) and (_match_host(h, SHORT_HOSTS) or _match_host(h, NOTE_HOSTS))


def is_short_url(url):
    return _match_host(host_of(url), SHORT_HOSTS)


def note_id_of(url):
    m = _NOTE_ID_RE.search(url or "")
    return m.group(1) if m else None


def _http_get(url, timeout=30, cookie=None):
    """GET 并解 gzip，返回 `(最终地址, HTML 文本)`。

    `cookie` 可选：本专线免登录即可工作，带上登录态只是让风控场景更稳
    （区分"笔记本身不存在"与"被风控拦"时很有用）。
    """
    headers = {
        "User-Agent": UA_MOBILE,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        return r.geturl(), raw.decode("utf-8", "replace")


def expand_short(url, timeout=25, cookie=None):
    """短链跟随 302，返回带 `xsec_token` 的真实地址。

    必须带移动端 UA，否则可能被跳到 App 下载引导页。
    """
    try:
        final, _ = _http_get(url, timeout=timeout, cookie=cookie)
        return final or url
    except Exception:
        return url


# ---------------------------------------------------------------- 内嵌 JSON

def _slice_json(s, start):
    """从 `s[start]`（应为 `{`）起按大括号平衡截出 JSON 文本，跳过字符串内部。"""
    depth, in_str, quote, esc = 0, False, "", False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
            continue
        if c in ('"', "'"):
            in_str, quote = True, c
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def parse_state(html):
    """从笔记页 HTML 取 `window.__INITIAL_STATE__` 并解析为 dict。"""
    i = html.find(_STATE_KEY)
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    blob = _slice_json(html, j)
    if not blob:
        return None
    # JS 字面量修正（仅出现在字符串外；该状态是 JSON 序列化结果，风险很低）
    blob = blob.replace("undefined", "null")
    blob = re.sub(r"(?<=[:,\[])\s*NaN\s*(?=[,\]}])", "null", blob)
    try:
        return json.loads(blob)
    except Exception:
        return None


def note_from_state(state):
    """从 INITIAL_STATE 里定位笔记对象。"""
    if not isinstance(state, dict):
        return None
    node = (state.get("noteData") or {}).get("data") or {}
    note = node.get("noteData")
    return note if isinstance(note, dict) and note.get("noteId") else None


def _as_list(v):
    """字段可能是 list，也可能是 JSON 字符串。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            j = json.loads(v)
            return j if isinstance(j, list) else []
        except Exception:
            return []
    return []


def _as_int(v):
    try:
        return int(v)
    except Exception:
        return None


# ---------------------------------------------------------------- 图片 / 视频

def build_image_url(file_id, mode="jpg"):
    """由 fileId 拼长期有效的无签名直链。"""
    fid = (file_id or "").strip().lstrip("/")
    if not fid:
        return None
    base = "https://%s/%s" % (IMG_HOST, fid)
    if mode == "raw":
        return base                       # 原图：体积最大，可能是 HEIC
    fmt = "webp" if mode == "webp" else "jpg"
    return "%s?imageView2/2/w/0/format/%s" % (base, fmt)


def image_entries(note, mode="jpg"):
    """提取图片列表，返回 `[ImageItem]`。"""
    out = []
    for im in (note.get("imageList") or []):
        if not isinstance(im, dict):
            continue
        fid = im.get("fileId") or ""
        variants = {}
        for info in _as_list(im.get("infoList")):
            if isinstance(info, dict) and info.get("imageScene") and info.get("url"):
                variants[info["imageScene"]] = info["url"]
        signed = im.get("url") or variants.get("H5_DTL") or variants.get("H5_PRV")
        url = build_image_url(fid, mode) or signed
        if not url:
            continue
        live = im.get("livePhoto")
        out.append(ImageItem(
            url=url,
            file_id=fid or None,
            width=_as_int(im.get("width")),
            height=_as_int(im.get("height")),
            fallback_url=signed,
            variants=variants,
            live_photo=bool(live) and str(live).lower() not in ("false", "0", "none"),
        ))
    return out


def video_streams(note):
    """提取视频各清晰度档位，返回 `[VideoStream]`。"""
    v = note.get("video") or {}
    media = v.get("media") or {}
    stream = media.get("stream") or {}
    out = []
    for codec in _CODEC_ORDER:
        for it in _as_list(stream.get(codec)):
            if not isinstance(it, dict) or not it.get("masterUrl"):
                continue
            out.append(VideoStream(
                url=it["masterUrl"],
                codec=codec,
                quality=it.get("qualityType"),
                width=_as_int(it.get("width")),
                height=_as_int(it.get("height")),
                size=_as_int(it.get("size")),
                duration=(it.get("videoDuration") or 0) / 1000.0 or None,
                backups=[x for x in _as_list(it.get("backupUrls")) if isinstance(x, str)],
            ))
    return out


def cover_url(note):
    """封面：优先 imageList[0]，否则用视频首帧。"""
    imgs = note.get("imageList") or []
    if imgs and isinstance(imgs[0], dict):
        u = build_image_url(imgs[0].get("fileId")) or imgs[0].get("url")
        if u:
            return u
    img = (note.get("video") or {}).get("image") or {}
    fid = img.get("firstFrameFileid")
    if fid:
        return "https://%s/%s" % (IMG_HOST, fid.lstrip("/"))
    return None


# ---------------------------------------------------------------- 适配器

class XhsAdapter(Adapter):
    """小红书专线：图文笔记正文直取，图集原图批量下载，视频多清晰度可选。"""

    name = "xhs"
    label = "小红书"
    domains = SHORT_HOSTS + NOTE_HOSTS
    login_free = True
    note = ("短链 → 笔记页 → 内嵌 JSON。零额度、图片为无签名原图直链、"
            "图文笔记正文直取无需 ASR。")
    #: 本专线免登录即可取到正文与原图，Cookie 只是备用（部分风控场景下更稳）。
    auth_hint = "非必需。免登录即可取正文与原图；被风控拦截时可带上登录态 Cookie 再试。"

    # ------------------------------------------------------------ 解析

    def parse(self, url, img_mode="jpg", timeout=30, retries=2, **opts):
        res = MediaResult(
            input_url=url, platform="xhs", platform_label="小红书",
            source="xhs/note-page",
        )
        if img_mode not in IMG_MODES:
            res.error = "img_mode 只能是 %s" % "/".join(IMG_MODES)
            return res

        # 0) 登录态（可选）：免登录即可工作，带上只是让风控场景更稳
        cookie = self.cookie(**opts)

        # 1) 短链先展开
        note_url = (expand_short(url, timeout=min(timeout, 25), cookie=cookie)
                    if is_short_url(url) else url)
        nid = note_id_of(note_url)
        if not nid:
            res.error = ("短链未能跳转到笔记页（可能已失效）。请确认链接是在小红书 App 里"
                         "「分享 → 复制链接」得到的完整口令。")
            return res
        res.item_id, res.item_url = nid, note_url
        if "xsec_token=" not in note_url:
            res.error = ("该链接缺少 xsec_token。小红书笔记页必须携带该令牌才能访问，"
                         "请使用 App 分享出来的短链或完整链接（不要手动删掉问号后面的参数）。")
            return res

        # 2) 拉笔记页（瞬时失败会自愈，重试）
        html, last_err = None, None
        for attempt in range(max(1, retries)):
            try:
                _, html = _http_get(note_url, timeout=timeout, cookie=cookie)
                break
            except urllib.error.HTTPError as e:
                last_err, html = "HTTP %s" % e.code, None
            except Exception as e:
                last_err, html = str(e), None
            if attempt + 1 < max(1, retries):
                time.sleep(1.5)
        if html is None:
            res.error = "请求笔记页失败：%s" % last_err
            return res

        # 3) 解析内嵌 JSON
        state = parse_state(html)
        if state is None:
            res.error = "页面未包含笔记数据（链接可能已失效，或被平台风控）"
            return res
        note = note_from_state(state)
        if note is None:
            res.error = ("页面未返回笔记正文。通常是 xsec_token 失效，或笔记已删除/设为私密，"
                         "请重新在小红书 App 里复制分享链接。")
            return res

        # 4) 组装结果
        user = note.get("user") or {}
        inter = note.get("interactInfo") or {}
        imgs = image_entries(note, mode=img_mode)
        vids = video_streams(note)
        desc = (note.get("desc") or "").strip() or None

        stats = {}
        for key, label in (("likedCount", "点赞"), ("collectedCount", "收藏"),
                           ("commentCount", "评论"), ("shareCount", "分享")):
            v = inter.get(key)
            if v not in (None, "", "0"):
                stats[label] = v

        res.ok = True
        res.kind = "video" if note.get("type") == "video" else "note"
        res.title = (note.get("title") or "").strip() or (desc or "")[:40] or None
        res.desc = desc
        res.author = user.get("nickName") or user.get("nickname")
        res.image_items = imgs
        res.video_streams = vids
        res.cover = cover_url(note)
        res.duration = vids[0].duration if vids else None
        res.stats = stats
        res.extra = {"img_mode": img_mode}

        # 图文笔记的「文案」就是正文本身，直取、无需 ASR
        if res.kind == "note" and desc:
            res.transcript = desc
        elif res.kind == "video":
            res.extra["asr_required"] = True
        return res

    # ------------------------------------------------------------ 自检

    def probe(self, timeout=12):
        """检查笔记域名是否可达（只请求公开首页，不做任何解析）。"""
        try:
            req = urllib.request.Request("https://www.xiaohongshu.com/", headers={
                "User-Agent": UA_MOBILE, "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {"ok": 200 <= r.status < 400,
                        "detail": "HTTP %s，笔记域名可达" % r.status}
        except Exception as e:
            return {"ok": False, "detail": "不可达：%s" % e}
