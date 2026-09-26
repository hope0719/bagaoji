"""下载器：把 `MediaResult` 里的直链落盘。

三个从实战里换来的设计点
------------------------
1. **按响应头 `Content-Type` 反推扩展名**。有些平台（例如视频代理直链）URL 路径上
   没有扩展名，按 URL 猜会得到假的 `.mp4`（实际是 WebM）。落盘后按真实类型改名。
2. **退避重试 + 备用域名切换**。CDN 会偶发 403/5xx，而签名本身往往还有效
   （实测同一签名 URL 前一次被拒、紧接着重试即成功）。只有 403/408/429/5xx
   与网络错误才重试；404 这类确定性错误重试无意义。
3. **图集并发、视频串行**。图集常见 9~18 张，并发收益明显；视频体积大，
   串行避免互相抢带宽。视频默认只下第一路——同一分辨率常同时给 h264/h265
   两个编码变体，全下等于白拉一倍体积。
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from .models import MediaResult

__all__ = [
    "CT_EXT", "safe_name", "guess_ext", "human", "download_file",
    "download_media", "pick_url",
]

# 有些直链 URL 上没有扩展名，需要按真实 Content-Type 落盘
CT_EXT = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "video/x-flv": ".flv",
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/wav": ".wav", "audio/ogg": ".ogg",
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/heic": ".heic",
}

VIDEO_EXT = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".flv")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff（）()【】\[\]，,。、；;\"'<>]+")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def pick_url(text):
    """从一段分享文案里抽出第一个 http(s) 链接。

    用户常常直接粘贴整段分享口令，例如：
        `7.92 复制打开抖音，看看【xxx】的作品 https://v.douyin.com/xxxx/ 08/21`
    """
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;)") if m else None


def safe_name(s, limit=60):
    """把标题转成安全的文件名。"""
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (s or "")).strip(" ._")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit] or "media")


def guess_ext(url, default=".mp4"):
    """按 URL 路径猜扩展名。猜不准也没关系——落盘后会按 Content-Type 修正。"""
    path = urllib.parse.urlparse(url).path.lower()
    for e in VIDEO_EXT:
        if path.endswith(e):
            return e
    for e in IMAGE_EXT:
        if path.endswith(e):
            return e if e != ".jpeg" else ".jpg"
    if path.endswith(".mp3"):
        return ".mp3"
    return default


def human(n):
    """人类可读的体积。"""
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%dB" % int(n) if unit == "B" else "%.1f%s" % (n, unit)
        n /= 1024.0


def _unique_path(dest):
    stem, e = os.path.splitext(dest)
    k = 1
    while os.path.exists(dest):
        k += 1
        dest = "%s(%d)%s" % (stem, k, e)
    return dest


def _download_once(url, dest, referer, timeout, verbose):
    """单次流式下载，落盘后按 Content-Type 修正扩展名。"""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
    if referer:
        headers["Referer"] = referer
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            got, last_tick = 0, 0.0
            with open(tmp, "wb") as f:
                while True:
                    buf = r.read(262144)
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
                    if verbose and time.time() - last_tick > 1.5:
                        last_tick = time.time()
                        if total:
                            log("    ↓ %s / %s (%.0f%%)" % (human(got), human(total),
                                                            got * 100.0 / total))
                        else:
                            log("    ↓ %s" % human(got))
        os.replace(tmp, dest)
        real = CT_EXT.get(ctype)
        if real and os.path.splitext(dest)[1].lower() != real:
            alt = os.path.splitext(dest)[0] + real
            k = 1
            while os.path.exists(alt):
                k += 1
                alt = "%s(%d)%s" % (os.path.splitext(dest)[0], k, real)
            os.replace(dest, alt)
            dest = alt
        return True, got, None, dest
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False, 0, str(e), dest


def download_file(url, dest, referer=None, timeout=180, verbose=True, retries=3):
    """带退避重试的下载，返回 `(ok, bytes, err, final_path)`。"""
    last_err = None
    for attempt in range(max(1, retries)):
        ok, n, err, path = _download_once(url, dest, referer, timeout, verbose)
        if ok:
            return True, n, None, path
        last_err = err
        if attempt + 1 >= max(1, retries):
            break
        if err and ("HTTP 404" in err or "HTTP 41" in err):
            break                                   # 确定性错误，重试无意义
        time.sleep(1.2 * (attempt + 1))
    return False, 0, last_err, dest


def download_media(res, media_dir, timeout=180, verbose=True, image_workers=4,
                   all_videos=False, only=None):
    """把一条解析结果里的视频/音频/图片落盘，返回保存清单。

    :param res:          `MediaResult`
    :param media_dir:    落盘目录
    :param image_workers: 图集并发数（默认 4）
    :param all_videos:   True 则下载全部视频编码变体，默认只下第一路
    :param only:         `None` / `"video"` / `"audio"` / `"image"`，只下某一类
    :return: `[{"kind", "path", "bytes", "url", ...}]`
    """
    os.makedirs(media_dir, exist_ok=True)
    base = safe_name(res.title or res.input_url or "media")
    referer = res.input_url
    saved = []

    want_video = only in (None, "video")
    want_audio = only in (None, "audio")
    want_image = only in (None, "image")

    streams = list(res.video_streams or [])
    if not all_videos:
        streams = streams[:1]
    streams = streams[:4]                  # 上限，避免一次拉过多大文件
    audios = [res.audio_url] if (want_audio and res.audio_url) else []
    images = list(res.image_items or []) if want_image else []

    if not (want_video and streams or audios or images):
        if only:
            log("  ⚠️ 没有可下载的 %s（该作品可能是纯文字笔记）" % only)
        else:
            log("  ⚠️ 没有可下载的媒体直链（该作品可能是纯文字笔记 / 直播回放）")
        return saved

    # --- 视频：串行，且主域名失败时自动切备用域名
    for i, s in enumerate(streams, 1):
        cands = [s.url] + [b for b in (s.backups or []) if b]
        ext = guess_ext(s.url, ".mp4")
        name = "%s%s" % (base, ext) if i == 1 else "%s_%d%s" % (base, i, ext)
        dest = _unique_path(os.path.join(media_dir, name))
        if verbose:
            log("  ⬇ 视频(%d/%d) %s：%s" % (i, len(streams), s.label(), os.path.basename(dest)))
        ok, n, err, fp = False, 0, None, dest
        for ci, cu in enumerate(cands):
            ok, n, err, fp = download_file(cu, dest, referer=referer,
                                           timeout=timeout, verbose=verbose)
            if ok:
                if ci and verbose:
                    log("    ℹ️ 主域名失败，已用备用地址成功")
                break
            if ci + 1 < len(cands) and verbose:
                log("    ↻ 切换备用地址重试…")
        if ok:
            if verbose:
                log("    ✅ 完成 %s -> %s" % (human(n), fp))
            saved.append({"kind": "video", "path": fp, "bytes": n, "url": s.url})
        else:
            log("    ❌ 失败：%s" % err)
            saved.append({"kind": "video", "path": None, "bytes": 0,
                          "url": s.url, "error": err})

    # --- 音频：串行
    for i, u in enumerate(audios, 1):
        ext = guess_ext(u, ".mp3")
        name = "%s_音频%s" % (base, ext) if i == 1 else "%s_音频%d%s" % (base, i, ext)
        dest = _unique_path(os.path.join(media_dir, name))
        if verbose:
            log("  ⬇ 音频：%s" % os.path.basename(dest))
        ok, n, err, fp = download_file(u, dest, referer=referer, timeout=timeout, verbose=verbose)
        if ok:
            saved.append({"kind": "audio", "path": fp, "bytes": n, "url": u})
        else:
            log("    ❌ 失败：%s" % err)
            saved.append({"kind": "audio", "path": None, "bytes": 0,
                          "url": u, "error": err})

    # --- 图片：并发，按作品内顺序补零命名，便于按序查看/上传
    if images:
        width = max(2, len(str(len(images))))
        tasks = []
        for i, item in enumerate(images, 1):
            dest = _unique_path(os.path.join(
                media_dir, "%s_图%0*d%s" % (base, width, i, guess_ext(item.url, ".jpg"))))
            tasks.append((i, item.url, dest))
        if verbose:
            log("  ⬇ 图片 %d 张（%d 并发）" % (len(tasks), min(image_workers, len(tasks))))
        results = {}
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(image_workers, len(tasks)))) as ex:
            futs = {ex.submit(download_file, u, d, referer, timeout, False): (i, u, d)
                    for i, u, d in tasks}
            for fut in concurrent.futures.as_completed(futs):
                i, u, d = futs[fut]
                try:
                    ok, n, err, fp = fut.result()
                except Exception as e:
                    ok, n, err, fp = False, 0, str(e), d
                results[i] = (ok, n, err, fp, u)
        for i in sorted(results):
            ok, n, err, fp, u = results[i]
            if ok:
                if verbose:
                    log("    ✅ [%0*d] %s" % (width, i, os.path.basename(fp)))
                saved.append({"kind": "image", "index": i, "path": fp, "bytes": n, "url": u})
            else:
                log("    ❌ [%0*d] 失败：%s" % (width, i, err))
                saved.append({"kind": "image", "index": i, "path": None, "bytes": 0,
                              "url": u, "error": err})
    return saved
