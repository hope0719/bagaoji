# 接入你自己的来源

bagaoji 采用**分层开源**：通用能力（引擎、下载器、数据结构、诊断器、CLI）开源，
具体来源站的接入由使用者按需补齐。

这样做有两个理由：一是避免把第三方站点的接入细节当作本项目的承诺；
二是让你能在**不 fork 本仓库**的前提下，把自己那套实现留在本地。

---

## 1. 适配器契约

一个来源 = 一个 `Adapter` 子类，放在 `~/.bagaoji/adapters/` 下即可自动加载。

```python
# ~/.bagaoji/adapters/my_source.py
from bagaoji.adapters.base import Adapter
from bagaoji.models import MediaResult, ImageItem, VideoStream


class MyAdapter(Adapter):
    name = "mysource"          # 机器可读标识（小写，唯一）
    label = "我的来源"          # 人类可读名称
    domains = ("example.com",)  # 负责的域名，含子域匹配
    login_free = True           # 是否可免登录使用
    note = "一句话说明"          # 出现在 --list 与 --diagnose 输出里

    def parse(self, url, **opts):
        res = MediaResult(
            input_url=url,
            platform=self.name,
            platform_label=self.label,
            source="mysource/api",
        )
        try:
            data = do_your_thing(url)          # 你的解析逻辑
        except Exception as e:
            res.error = "解析失败：%s" % e
            return res

        res.ok = True
        res.kind = "video"
        res.title = data.get("title")
        res.desc = data.get("desc")
        res.transcript = data.get("text")      # 有就填，没有留空
        res.stats = {"点赞": data.get("like")}
        res.video_streams = [VideoStream(url=data["video"], codec="h264",
                                         width=1080, height=1920)]
        res.image_items = [ImageItem(url=u) for u in data.get("images", [])]
        res.cover = data.get("cover")
        return res

    def probe(self, timeout=12):
        """可选。返回 {"ok": bool, "detail": str}，供 --diagnose 使用。"""
        return {"ok": True, "detail": "由我自行判断"}


ADAPTER = MyAdapter()
```

也可以一次注册多个，用 `ADAPTERS = [A(), B()]`；
只放 `Adapter` 子类（不给 `ADAPTER` 变量）也会被自动发现。

验证：

```bash
python3 -m bagaoji --list                        # 确认已加载
python3 -m bagaoji --engine mysource "<链接>"     # 指定适配器解析
python3 -m bagaoji --engine mysource --json "<链接>" | python3 -m json.tool
```

---

## 2. 目录与加载机制

| 项 | 值 |
|---|---|
| 目录 | `~/.bagaoji/adapters/` |
| 加载时机 | 每次启动（`import bagaoji.adapters` 时） |
| 文件要求 | `*.py`，`_` 开头会被跳过 |
| 失败行为 | 单个文件加载失败**不影响**其他适配器与主流程 |
| 优先级 | 私有适配器**后注册可覆盖**同名的内置适配器 |

想让引擎优先选你的适配器：把 `domains` 声明得比内置更具体，
或者直接用 `--engine` / `parse(url, engine="mysource")` 指定。

---

## 3. 登录态接入（需要登录的来源）

**十有八九，你接不进来的那个来源，卡的不是技术，而是没登录态。**
接口形态明明是完整的，参数也对，但服务端在鉴权层统一返回「未登录」。
这类来源**不要放弃**——它们通常只差一个 Cookie。

所以本仓库把凭据读取做成了公共能力，适配器只需要一行：

```python
def parse(self, url, **opts):
    cookie = self.cookie(**opts)          # ← 四种来源自动收敛成这一个入口
    if cookie is None:
        return MediaResult(input_url=url,
                           error="该来源需要登录态：请用 --cookie 传入，"
                                 "或写入 ~/.bagaoji/cookies.json（见 README）")
    # 后续请求带上 cookie ...
```

同时把两个类属性写清楚，它们会出现在 `--list` 与 `--auth` 里：

```python
login_free = False                       # 免登录是否可用；如实声明，别写 True 糊弄过去
auth_hint = "登录后额度更高，且解锁 1080P"  # 登录态的收益；写成对用户有用的信息
```

### 3.1 凭据来源与优先级

| 优先级 | 来源 | 适用场景 |
|---|---|---|
| 1 | `--cookie "a=1; b=2"` | 临时试一下 |
| 2 | `--cookie-file PATH` | Cookie 较长；支持 JSON 与纯文本两种格式 |
| 3 | `BAGAOJI_COOKIE_<适配器名大写>` | 多来源并存时按名区分 |
| 4 | `BAGAOJI_COOKIE` | 通用兜底 |
| 5 | `~/.bagaoji/cookies.json` | 长期配置，支持 `_default` + 按名覆盖 |
| 6 | `~/.bagaoji/cookies.txt` | 同上，纯文本形式 |

`cookies.json` 示例（按适配器名区分，互不干扰）：

```json
{
  "_default": "留给没有单独配置的来源",
  "source_a": "来源 A 专用",
  "source_b": "来源 B 专用"
}
```

### 3.2 三条约束（照做，别绕）

1. **不要在适配器里自己读文件或环境变量。** 一律用 `self.cookie(**opts)` /
   `self.cookie_source(**opts)`——这样凭据来源可审计、可脱敏，也不会在十个适配器里
   散落十套读取逻辑。
2. **不要把凭据写进日志、`note`、`res.extra` 或异常信息里。** 需要展示就用
   `bagaoji.auth.mask()`，它只输出字符数与 Cookie 名。
3. **不要为了"让脚本能跑"去实现自动登录 / 扫码绕过 / 人机验证规避。**
   本仓库的定位是"用你自己的登录态"，不是"替你取得登录态"。
   遇到强制关注公众号、短信验证这类门槛，正确做法是**如实记录在公示表里**。

### 3.3 排错：先分清是"签名错"还是"没登录"

有些站点既有签名参数、又有鉴权层。这时**别急着怀疑自己的签名算法**——
构造五组请求做差分测试：正确参数 / 错误参数 / 缺参数 / 空参数 / 过期参数。

> 如果五组返回**一字不差**的同一响应，说明卡点在更前面的中间件（鉴权），
> 此时签名正确性**无法**用未登录请求验证，只能靠与前端脚本逐位比对来证明。

这个判别顺序能省掉大量无效投入。完整方法见
[sites.md §8 核验方法备忘](sites.md#8-核验方法备忘)。

---

## 4. 接口形态参考

以下是本项目调查过的来源的**接口形态**（端点、方法、字段名、鉴权方式）。

> **注意**：这里只描述"长什么样"，**不含任何加密密钥、签名算法实现或绕过方法**。
> 需要实现细节的，请先自行评估合规风险，并遵守对应站点的服务条款。

### 3.1 抖虫 dousnap.com

- 基址：`https://www.dousnap.com/prod-api`
- 解析：`POST /link/parse`，请求体字段名 **`text`**
- 转写：`POST /transcript/doTask` + `GET /transcript/queryTask?taskId=`
- 请求体与响应体**整体加密**（对称加密，密钥硬编码在前端 bundle，本仓库不提供）
- GET 的普通查询参数不加密

**接入建议**：解析与下载不受免登录额度限制（额度只作用于转写），
所以"只取原片"这条路径是最容易先跑通的。

### 3.2 考拉解析 kaolajiexi.cn

- 解析：`POST /parse/apply`（form-urlencoded），需签名参数
- 账号：`GET /user/info`（字段名首字母大写）
- 激活：`POST /user/auth`
- 下载代理：`GET /xzbs/video_<ts>.mp4?s=<base64>`
- **鉴权中间件先于签名校验**，未登录时任何签名都返回同一个 403

**接入建议**：除非你已有可用登录态（例如从自己浏览器取 Cookie），
否则不建议投入。状态语义表见 [sites.md §3.5](sites.md#35-状态语义排错用)。

### 3.3 下载狗 xzgtool.com

- 核心端点均已还原（文本提取提交、短链解析、签名下载、媒体代理）
- 未登录时统一返回 401 + 业务码 1001

**接入建议**：卡点是账号不是技术。有账号态时可作平替。

### 3.4 snapany snapany.com

- 网关：`api.snapany.com`（`GET /health` → `200 ok`）
- 契约端点：`POST /v1/extract/post`，请求体 `{"link": url}`
- 另需三个请求头（时间戳 / 页脚签名 / 会话标识），由前端产出

**接入建议**：服务端校验依赖浏览器环境产出的动态凭证，
纯脚本补齐请求头解决不了。要么走浏览器自动化，要么放弃。

### 3.5 convry / 傲软

形态不匹配（上传式）或后端已停用，不建议投入。原因见
[sites.md §6](sites.md#6-convry-convrycom-形态不同) 与
[sites.md §7](sites.md#7-傲软-apowersoftcn在线版已停用)。

---

## 5. 数据模型速查

`MediaResult` 的字段（完整定义见 `bagaoji/models.py`）：

| 字段 | 说明 |
|---|---|
| `ok` | 是否成功。失败时填 `error`，不要抛异常给上层 |
| `platform` / `platform_label` | 机器可读 / 人类可读的来源名 |
| `source` | 实际生效的通道，如 `xhs/note-page` |
| `kind` | `video` 或 `note` |
| `title` / `desc` / `author` / `duration` | 基本元信息 |
| `transcript` | 口播文案；图文笔记即正文 |
| `stats` | 互动数据，如 `{"点赞": "1352"}` |
| `video_streams` | `[VideoStream]`，含 `codec`/`width`/`height`/`size`/`backups` |
| `image_items` | `[ImageItem]`，含 `url`/`width`/`height`/`fallback_url` |
| `cover` / `audio_url` | 封面 / 音频直链 |
| `item_id` / `item_url` | 作品 ID / 解析后的规范地址 |
| `extra` | 放你认为有用的补充信息（不会污染通用字段） |

`download_media()` 只认这些字段，所以你只要填对，下载、Markdown 导出、
JSON 输出、批量处理全都自动可用。

---

## 6. 检查清单

写完之后对着过一遍：

- [ ] `python3 -m bagaoji --list` 能看到你的适配器
- [ ] `--engine <name> --json` 输出结构完整，`ok` 为 `true`
- [ ] 失败路径返回 `res.error` 而不是抛异常（引擎要能继续处理下一条）
- [ ] `domains` 覆盖了该来源的**全部**短链域名（漏一个会静默失败）
- [ ] 下载后校验过文件真实类型（不要只看 URL 扩展名）
- [ ] 媒体直链的**有效期**已在 `note` 或文档里说明
- [ ] `probe()` 只请求公开页面，不做登录、不解析内容
- [ ] **需要登录态时**：`login_free = False` 已如实声明，且 `auth_hint` 写明了登录后的收益
- [ ] **需要登录态时**：凭据通过 `self.cookie(**opts)` 读取，而不是自己读文件/环境变量
- [ ] **需要登录态时**：缺凭据的报错文案**明确告诉用户怎么补**（`--cookie` / `~/.bagaoji/cookies.json`）
- [ ] 任何输出（日志、`note`、`extra`、异常）都**不含凭据原文**，展示用 `mask()`
- [ ] 未在代码里硬编码任何凭据，也未实现任何自动登录 / 验证码规避逻辑

---

## 7. 排错

| 现象 | 处理 |
|---|---|
| 适配器没被加载 | 检查文件名不以 `_` 开头、目录拼写、模块顶层有没有抛异常 |
| 报 `没有适配器能处理这个链接` | `domains` 没匹配上；用 `--engine` 强制指定验证逻辑本身 |
| 下载文件打不开 | 直链已过期 → 重新解析；同时检查是否被误加扩展名 |
| 昨天还能用，今天提示未登录 | **先怀疑 Cookie 过期**，重新复制一份；确认无误再查其它 |
| 分不清是签名错还是没登录 | 做差分测试（正确/错误/缺失/空/过期五组）。返回一字不差 → 卡在鉴权层 |
| 大批量解析被限流 | 加请求间隔；区分"限流的接口"与"不限流的接口"（例如解析 vs 转写） |
| 线上突然全部失效 | 站点改了协议 → 按 [sites.md §8](sites.md#8-核验方法备忘) 重新走一遍核验流程 |

---

## 8. 关于"只描述形态、不提供实现"

本仓库公开层不包含任何来源站的具体加密密钥、签名实现或绕过付费与登录限制的方法。

如果你的场景是**自己研究、自己使用**，按本文档实现即可，风险自担；
如果你打算**分发**这些实现，请先确认：
第三方站点的服务条款是否允许、是否会被认定为不正当竞争、
是否会给你自己带来投诉或法律风险。

技术可行性不等于合规可行性——这两件事本项目分开表述，也希望使用者分开判断。
