#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自建适配器模板。

把本文件复制到 `~/.bagaoji/adapters/` 下（记得改掉 name 和 domains），
启动时会自动加载。完整说明见 docs/extending.md。

    mkdir -p ~/.bagaoji/adapters
    cp examples/custom_adapter_template.py ~/.bagaoji/adapters/my_source.py
    python3 -m bagaoji --list
"""

from bagaoji.adapters.base import Adapter
from bagaoji.models import ImageItem, MediaResult, VideoStream

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class MySourceAdapter(Adapter):
    name = "mysource"
    label = "我的来源"
    domains = ("example.com",)          # ← 记得覆盖该来源的全部域名（含短链域名）
    login_free = True                   # ← 需要登录就写 False，别写 True 糊弄过去
    note = "替换成一句话说明"
    auth_hint = ""                      # ← 需要登录时，写清"登录后能多得到什么"

    def parse(self, url, timeout=30, **opts):
        res = MediaResult(
            input_url=url,
            platform=self.name,
            platform_label=self.label,
            source="%s/api" % self.name,
        )

        # ---- 0) 登录态（可选）------------------------------------------------
        # 需要登录的来源：用这一行取凭据，不要自己读文件或环境变量。
        # 用户的 --cookie / --cookie-file / BAGAOJI_COOKIE / ~/.bagaoji/cookies.*
        # 四种传入方式会自动收敛到这里。
        cookie = self.cookie(**opts)
        if not self.login_free and cookie is None:
            res.error = ("该来源需要登录态。请用 --cookie 传入，"
                         "或写入 ~/.bagaoji/cookies.json —— 详见 README「关于 Cookie」一节。")
            return res
        # ---------------------------------------------------------------------

        # ---- 1) 你的解析逻辑 -------------------------------------------------
        # 建议：把网络请求包在 try 里，失败时写 res.error 返回，不要抛异常，
        #       否则批量处理时后续链接会被中断。
        try:
            data = self._fetch(url, timeout)         # 你要自己实现
        except Exception as e:
            res.error = "解析失败：%s" % e
            return res
        # ---------------------------------------------------------------------

        res.ok = True
        res.kind = "video"
        res.title = data.get("title")
        res.desc = data.get("desc")
        res.author = data.get("author")
        res.transcript = data.get("text")            # 没有就留空
        res.item_id = str(data.get("id") or "") or None
        res.duration = data.get("duration")
        res.stats = {"点赞": data.get("like")} if data.get("like") else {}
        res.cover = data.get("cover")

        res.video_streams = [
            VideoStream(url=u, codec="h264", width=1080, height=1920,
                        backups=list(data.get("video_backups") or []))
            for u in ([data["video"]] if data.get("video") else [])
        ]
        res.image_items = [
            ImageItem(url=u, width=None, height=None)
            for u in (data.get("images") or [])
        ]
        return res

    def _fetch(self, url, timeout):
        """占位：替换成你自己的实现。

        注意：不要在这里硬编码任何凭据；需要登录态时用 `self.cookie(**opts)` 取，
        且不要把凭据写进日志、异常信息或返回值里（展示用 `bagaoji.auth.mask()`）。
        """
        raise NotImplementedError("请实现 _fetch")

    def probe(self, timeout=12):
        """可选。只请求公开页面，用于 --diagnose。"""
        return {"ok": True, "detail": "未实现自检"}


ADAPTER = MySourceAdapter()
