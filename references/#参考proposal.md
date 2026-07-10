# **1. 目标**

`xcrawld` 是对 `xcrawl` 的服务化封装。
它的核心职责是：

- 以 HTTP 服务方式运行 `xcrawl`
- 动态管理站点定制化的ixgo爬取脚本
- 对外提供统一 fetch 接口
- 复用 `xcrawl` 现有匹配与抓取能力

---

# **2. 范围**

v1 包含：

- `xcrawld serve` 命令，在启动后，可以提供
1. `/sites` 系列管理接口，用来上传某站点抽取策略
2. 路径式 GET 抓取接口
3. Firecrawl 子集兼容接口 `POST /v2/scrape`，和我方接口功能对等
4. PostgreSQL 存储抽取策略，可依据需求热加载
5. 多种站点缓存后端

---

# **3. 运行方式**

启动命令：

```bash
xcrawld serve --config ./xcrawld.yaml
```

或：

```bash
xcrawld serve \
  --listen 127.0.0.1:8080 \
  --adminListen 127.0.0.1:8081 \
  --dsn "$XCRAWLD_DSN"
```

> **凭据管理**：数据库连接串中包含敏感凭据，**禁止**在命令行参数或配置文件中明文传递密码。
> 推荐通过环境变量注入（如 `XCRAWLD_DSN`）；生产环境也可结合 [envconsul](https://github.com/hashicorp/envconsul) 从 Vault 自动注入：
> ```bash
> envconsul -secret "secret/data/xcrawld" xcrawld serve --config ./xcrawld.yaml
> ```

---

# **4. 接口设计**

## **4.1 `/sites` 管理接口**

管理接口注册在 `adminListen` 对应的端口上。

所有管理接口请求必须携带 `Authorization` 头，使用七牛管理凭证（QiniuAdmin）进行签算验证，确保请求来自授权的管理员：

```http
Authorization: QiniuAdmin <access_key>:<sign>
```

未通过签算验证的请求返回 `401 Unauthorized`。

---

### **PUT /sites**

创建或更新一个 site。

请求：
- `Content-Type: text/plain; charset=utf-8`
- `Authorization: QiniuAdmin <access_key>:<sign>`
- body 为完整 site 代码

示例：

```txt
baseURL "https://en.wikipedia.org/"
...
```

服务内部实现一套和 site 接口相同的 hook，加载该脚本，校验是否可装载。
在加载完成后需要：
- 提取所有 `baseURL`
- 以 `baseURLs[0]` 作为该 site 的唯一标识（`id`）
- 若该 `id` 已存在，则更新 `source`、`base_urls`、`source_hash`，刷新 `updated_at`
- 若该 `id` 不存在，则创建新记录
- 写入 DB 后，同步更新本实例内存中的 site 索引（baseURL 前缀匹配表及缓存的 source）
- 完成其他杂项事务

成功响应：

```json
{
  "id": "https://en.wikipedia.org/",
  "baseURLs": [
    "https://en.wikipedia.org/"
  ],
  "createdAt": "2026-03-31T10:00:00Z",
  "updatedAt": "2026-03-31T10:00:00Z"
}
```

失败错误码：
- `SCRIPT_PARSE_FAILED` — 脚本语法解析失败
- `SCRIPT_LOAD_FAILED` — 脚本加载或校验失败
- `BASEURL_NOT_FOUND` — 脚本中未找到 baseURL 定义

---

### **POST /sites/match**

测试某个 URL 会命中哪个 site。

请求：

```json
{
  "url": "https://en.wikipedia.org/wiki/Emacs"
}
```

响应：

```json
{
  "matched": true,
  "site": {
    "id": "https://en.wikipedia.org/",
    "baseURLs": [
      "https://en.wikipedia.org/"
    ],
    "createdAt": "2026-03-31T10:00:00Z",
    "updatedAt": "2026-03-31T10:00:00Z"
  }
}
```

未命中时：

```json
{
  "matched": false
}
```

用途：
- 调试ixgo爬取脚本是否生效
- 调试 `baseURL` 提取是否正确
- 调试服务侧 site 粗匹配是否正常

---

## **4.2 路径式 GET 抓取接口**

### **GET /{scheme}/{host}/{path...}**

主抓取接口。

示例：

```http
GET /https/abc.com/path/to/doc?x=1
Authorization: Bearer sk-xxxxxxx
Accept: text/markdown
X-ReqId: req-abc-123
```

请求头说明：
| 头部 | 必选 | 说明 |
|------|------|------|
| `Authorization` | 是 | Bearer Token 认证 |
| `Accept` | 否 | 期望的响应格式，默认 `text/markdown` |
| `X-ReqId` | 否 | 请求方自定义的请求 ID，用于调试追踪 |

解释规则：
- 第一段 path 视为目标 `scheme`（`https` 或 `http`）
- 第二段 path 视为目标 `host`
- 剩余 path 视为目标 URL path
- query string 原样透传

上面请求会被解释为：

```text
https://abc.com/path/to/doc?x=1
```

### **认证**

抓取接口采用与 OpenAI API 相同的 Bearer Token 方式进行认证：

```http
Authorization: Bearer sk-xxxxxxx
```

服务端通过配置的 API Key 列表进行校验。未通过认证的请求返回 `401 Unauthorized`。

### **输出协商**

使用 `Accept` 头决定返回类型。`Accept` 头可包含多个媒体类型，服务端按以下优先级顺序进行协商：

1. `application/json` — 返回 JSON 格式
2. `text/markdown` — 返回 Markdown 格式
3. `text/html` — 返回原始 HTML（rawHtml）

协商规则：
- 客户端可通过 quality factor（`q` 值）指定偏好，例如 `Accept: text/html;q=0.9, text/markdown;q=1.0`
- 若客户端未指定 `q` 值，则按上述服务端默认优先级选择
- 若 `Accept` 为 `*/*` 或未传 `Accept` 头，默认返回 `text/markdown`
- 若请求的所有媒体类型均不支持，返回 `406 Not Acceptable`

响应头：
- `Content-Type`
- `X-ReqId`

说明：
- 这里用的是 `Accept`
- 不是 `Accept-Encoding`

---

## **4.3 Firecrawl 子集兼容接口**

### **POST /v2/scrape**

为了兼容现有 agent，保留 Firecrawl 子集兼容接口。该接口同样需要 Bearer Token 认证。

请求体：

```json
{
  "url": "https://example.com/page",
  "formats": ["rawHtml", "markdown", "json"]
}
```

请求头：

```http
Authorization: Bearer sk-xxxxxxx
```

生效字段：
- `url`
- `formats`

以下字段可接受但不生效，仅用于 API 兼容（openclaw 默认会携带这些参数）：
- `onlyMainContent: true`
- `timeout: 30000`
- `maxAge: 172800000`
- `proxy: "auto"`
- `storeInCache: true`

请求中包含上述兼容字段不会报错，服务端静默忽略。若包含其他未知字段，返回 `UNSUPPORTED_FIELD` 错误。

成功响应：

```json
{
  "success": true,
  "data": {
    "rawHtml": "<html>...</html>",
    "markdown": "# title\n...",
    "json": {},
    "metadata": {
      "title": "Example",
      "description": "...",
      "sourceURL": "https://example.com/page",
      "statusCode": 200,
      "contentType": "text/html",
      "language": "en"
    }
  }
}
```

失败响应：

```json
{
  "success": false,
  "error": {
    "code": "UNSUPPORTED_FIELD",
    "message": "field waitFor is not supported"
  }
}
```

说明：
- 内部仍走同一套 site 匹配与ixgo脚本执行链路

---

## **4.4 健康与指标接口**

### **GET /metrics**

返回 Prometheus 指标。注册在 `adminListen` 端口上。

请求：

```http
GET /metrics
Authorization: Bearer sk-xxxxxxx
```

使用 Bearer Token 认证，通过 `auth.metricsToken` 单独配置。未通过认证的请求返回 `401 Unauthorized`。

具体打点项目，参见其他相关文档。

---

# **5. fetch 工作流程**

## **5.1 内存中的 site 索引**

每个实例在内存中维护一份 site 索引，复用 `xcrawl` 现有的 `siteDispatcher` 两级匹配结构：

- 第一级：`{scheme, host}` → `[]pathDispatcher` 映射，按 scheme + host 精确查找候选 site
- 第二级：每个 `pathDispatcher` 持有 baseURL 的 path 前缀（`base`）和对应的 `site` 引用

每个 site 在内存中只保留轻量元数据（`id`、`base_urls`、`updated_at`、`lastCheckedAt`），`source` 不默认加载，首次使用时才从 DB 加载并缓存。其中 `lastCheckedAt` 记录上次向 DB 验证该 site 新鲜度的时间，用于控制检查频率（见 5.4）。

对于同步后仍未命中的 URL，将其对应的 `{scheme, host}` 在 `siteDispatcher` 中注册为默认 site（使用默认 handle 处理）。这样后续相同地址的请求会正常命中，不会重复触发即时同步。下次同步时，若该地址有了对应的 site 注册，默认 site 会被替换。

## **5.2 请求匹配**

匹配分三级，与 `xcrawl` 现有的 `siteDispatcher` + `radix.Route` 一致：

1. 按请求 URL 的 `{scheme, host}` 查找 `siteDispatcher.hosts`，得到候选 `pathDispatcher` 列表
2. 遍历候选列表，检查请求 path 是否以 baseURL 的 path 为前缀（`strings.HasPrefix`），命中则定位到 site
3. 将剩余 path（去掉 base 前缀）交给 site 内部的 radix tree（`site.mux`）进行路由匹配

若 site 的 `source` 尚未加载，此时从 DB 加载并缓存。

## **5.3 请求处理流程**

```
请求进来
  │
  └─ 匹配 siteDispatcher（见 5.2）
      │
      ├─ 命中已注册 site
      │    │
      │    └─ 新鲜度检查（见 5.4）
      │         ├─ 上次检查在 siteCheckTTL 内 ──→ 直接使用该 site 处理
      │         └─ 已过期 ──→ 查询 DB 该 site 的 updated_at
      │              ├─ 与内存一致 ──→ 刷新 lastCheckedAt，直接处理
      │              └─ 不一致 ──→ 触发增量同步（见 5.4），再处理
      │
      ├─ 命中默认 site ──→ 使用默认 handle 处理
      │
      └─ 未命中 ──→ 触发即时同步（见 5.4）
                     │
                     再次匹配
                     ├─ 命中 → 使用该 site 的 handle 处理
                     └─ 仍未命中 → 为该地址注册默认 site，使用默认 handle 处理
```

命中已注册 site 时，不直接使用内存缓存，而是按 `siteCheckTTL`（默认 `5s`）频率检查该 site 是否有更新。验证者更新 site 后最多等待 `siteCheckTTL` 即可看到变更生效。单次检查仅需一次 PK 查询（`SELECT updated_at WHERE id = $1`），开销极低。

## **5.4 增量同步机制**

每个实例维护一个 `lastSyncAt`，表示上次同步到的最大 `updated_at`。

### 两种触发方式

| 方式 | 触发时机 | 说明 |
|------|----------|------|
| **即时同步** | 请求未命中任何 site 时 | 可能有新 site 刚注册，立即拉取 |
| **新鲜度检查** | 命中已注册 site，且距上次检查超过 `siteCheckTTL` | 查询该 site 的 `updated_at`，若与内存不一致则触发增量同步 |

两者的分工：新鲜度检查保证已知 site 的变更在 `siteCheckTTL`（默认 `5s`）内被感知；即时同步保证新 site 注册后立即可用。

### 新鲜度检查

每个 site 在内存中维护 `lastCheckedAt`，记录上次向 DB 验证新鲜度的时间。请求命中 site 时：

1. 若 `now - lastCheckedAt < siteCheckTTL`，跳过检查，直接处理
2. 否则查询 `SELECT updated_at FROM sites WHERE id = $1`
   - 若与内存中的 `updated_at` 一致，更新 `lastCheckedAt`，直接处理
   - 若不一致，触发增量同步（与即时同步共享同一流程），同步完成后处理

`siteCheckTTL` 默认 `5s`。这意味着更新 site 后，验证者最多等待 5s 即可看到变更。单次检查仅需一次主键查询，开销极低。

### 同步流程

两种触发方式共享同一套增量同步流程：

1. 计算查询起点：`syncFrom = lastSyncAt - delta`（`delta` 硬编码为 `5s`，补偿多服务器间的时钟偏差和潜在的时序问题，避免遗漏变更）
2. 查询 `SELECT id, base_urls, updated_at FROM sites WHERE updated_at > $syncFrom ORDER BY updated_at`
3. 合并到内存索引（新增或更新 `siteDispatcher` 的映射关系）
4. 对 `updated_at` 变化的 site，清除已缓存的 `source`（下次使用时重新加载）
5. 新注册的 site 会自然覆盖此前为该地址注册的默认 site
6. 更新 `lastSyncAt`

### 并发控制

- 两种触发方式共享同一把互斥锁，同一时刻只有一次同步在执行
- 若某次同步触发时另一次正在执行，等待其完成后直接使用结果
- 若多个请求同时触发同步，只执行一次，其他请求等待共享结果

---

# **6. 数据库设计**

## **6.1 设计原则**

v1 数据库只有一张 `sites` 表，存储 site 脚本源码和元数据。

URL 到 site 的匹配索引在内存中维护（从 `base_urls` 派生），不单独建表。

---

## **6.2 sites 表**

```sql
CREATE TABLE sites (
  id           TEXT NOT NULL PRIMARY KEY,
  base_urls    TEXT[] NOT NULL,
  source       TEXT NOT NULL,
  source_hash  TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_sites_updated_at ON sites(updated_at);
```

字段说明：
- `id`
  - 取自 `baseURLs[0]`，作为 site 的唯一标识
- `base_urls`
  - 该 site 的所有 baseURL 列表
- `source`
  - ixgo脚本源码，唯一权威定义
- `source_hash`
  - 用于判断源码是否变化，仅内部使用
- `created_at`
  - 创建时间
- `updated_at`
  - 最后更新时间，每次写入（创建、更新）都刷新
  - 用于增量同步：实例通过 `WHERE updated_at > lastSyncAt - delta` 拉取变更（详见 5.4）

---

# **7. 配置项设计**

## **7.1 配置文件格式**

建议使用 YAML。

默认配置文件路径：

```text
./xcrawld.yaml
```

启动方式：

```bash
xcrawld serve --config ./xcrawld.yaml
```

优先级建议：
1. 命令行参数
2. 环境变量
3. YAML 配置文件
4. 内置默认值

---

## **7.2 配置文件示例**

```yaml
server:
  adminListen: "127.0.0.1:8081"
  listen: "127.0.0.1:8080"
  siteCheckTTL: "5s"

auth:
  admin:
    accessKey: "${QINIU_ACCESS_KEY}"
    secretKey: "${QINIU_SECRET_KEY}"
  apiKeys:
    - "${XCRAWLD_API_KEY}"
  metricsToken: "${XCRAWLD_METRICS_TOKEN}"

database:
  dsn: "${XCRAWLD_DSN}"

logging:
  level: "info"

headless:
  concurrency: 4
```

---

## **7.3 配置项说明**

### **server**
- `listen`
  - HTTP fetch 服务监听地址
  - 默认：`127.0.0.1:8080`

- `adminListen`
  - HTTP 管理服务监听地址
  - 默认：`127.0.0.1:8081`

- `siteCheckTTL`
  - 已命中 site 的新鲜度检查间隔；在此时间内对同一 site 的请求不再查 DB
  - 默认：`5s`

- `maxSiteScriptSize`
  - site 脚本上传的最大 body 大小
  - 默认：`1MiB`

### **auth**
- `admin.accessKey` / `admin.secretKey`
  - 用于 QiniuAdmin 签算验证管理接口请求
  - 必填；通过环境变量注入，禁止明文写入配置文件

- `apiKeys`
  - 抓取接口的 Bearer Token 列表
  - 必填；至少配置一个

- `metricsToken`
  - `/metrics` 端点的 Bearer Token
  - 必填；通过环境变量注入，禁止明文写入配置文件

### **database**
- `dsn`
  - PostgreSQL 连接串
  - 必填；通过环境变量注入，禁止明文写入配置文件

### **logging**
- `level`
  - 日志级别
  - 可选：`debug | info | warn | error`
  - 默认：`info`

### **headless**
- `concurrency`
  - headless 并发数
  - ...