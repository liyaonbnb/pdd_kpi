# 多平台电商 BI 看板

拼多多 / 抖音 / 天猫 / 微信小店 的推广与订单数据 BI 分析工具。

后端使用 **Python + FastAPI + pandas**，前端使用 **Vite + React + TypeScript + Tailwind CSS**，通过浏览器访问；支持多店铺、多账号权限、AI 分析结论与企业微信日报推送。

---

## 功能特性

- 📊 **多平台切换**：拼多多、抖音、天猫、微信小店独立数据与菜单，侧边栏下拉切换
- 🏪 **多店铺隔离**：每个平台下可创建多个店铺，数据分开存储、分开筛选
- 📤 **数据导入**：拖拽上传推广 Excel / 订单 CSV/Excel，支持单日文件与全数据文件自动按日期拆分；导入订单时自动刷新新出现的商家/SKU 编码到成本配置
- 📈 **核心 KPI 看板**：
  - 拼多多：推广花费、GMV、真实 ROI、退款率、点击率、商家实收、自然流量占比等
  - 抖音：消耗、成交金额、净成交金额、**实际收入**（订单应付金额 + 平台实际承担优惠金额）、ROI、点击率、转化率等
  - 天猫：成交金额、退款、ROI、点击率等
  - 微信小店：订单实际收款、退款、技术服务费、带货费用（佣金）、净成交金额等
- 🛒 **商品级 / 规格级明细**：排行、对比、趋势图、导出 CSV
- 💰 **成本管理**：按「商家编码/SKU 编码」维护商品成本/物流成本，支持刷新编码、未映射商品绑定、导入导出、待维护导出；导航栏「成本」旁实时显示未维护数量徽标
- 🤖 **AI 智能洞察**：统一 AI & 企微页面，支持 Kimi / OpenAI / 任意兼容 API，自动生成平台专属分析结论
- 📚 **运营知识助手**：内置拼多多运营课程知识库，支持来源可追溯的问答与资料检索，可选结合店铺日期范围内的真实 KPI 辅助分析
- 📲 **企业微信日报**：按店铺汇总后推送到指定机器人
- 👥 **账号权限**：主账号 + 子账号，按四大平台分组，每平台细分为总览/导入/指标/订单/成本，AI & 企微为通用权限
- 🚀 **自动部署**：GitHub Actions 推送 `main`/`master` 后自动构建前端并部署到服务器

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.12、FastAPI、Pydantic、pandas、numpy、PyJWT、bcrypt |
| 前端 | Vite、React 19、TypeScript、Tailwind CSS 3、shadcn-style 组件 |
| 数据存储 | Parquet + JSON（本地文件），按平台与店铺隔离 |
| 部署 | uvicorn + systemd + Nginx + GitHub Actions |

---

## 快速启动（本地开发）

### 1. 安装后端依赖

```bash
cd pdd_bi_dashboard
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 2. 启动后端

```bash
venv\Scripts\python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。

> 首次部署时请务必设置 `ADMIN_PASSWORD` 环境变量，否则后端启动会报错；已有 admin 用户的存量部署则不再强制要求。

---

## 线上部署

项目已配置 GitHub Actions（`.github/workflows/deploy.yml`），推送 `main`/`master` 分支后自动：

1. 读取仓库中的 `.github_deploy_key` 作为 SSH 私钥
2. 连接服务器 `122.152.201.146`（用户 `ubuntu`）执行 `git pull`
3. 安装 Python 依赖、清理 `__pycache__`
4. 前端 `npm ci && npm run build`
5. 将 `frontend/dist/` 同步到 `/var/www/pdd_kpi/`
6. 重启 `pdd_kpi.service`、重载 Nginx

生产环境建议通过 Systemd `EnvironmentFile` 注入 `JWT_SECRET_KEY` 等敏感配置，避免直接写入服务文件或仓库。

---

## 使用步骤

1. 登录后，在左侧边栏顶部的下拉框切换平台（拼多多 / 抖音 / 天猫 / 微信小店）
2. 进入「导入」页面，选择店铺、上传推广与订单数据；若订单里出现新的商家/SKU 编码，系统会自动刷新到成本配置
3. 日期留空时，程序会自动拆分文件内的所有日期
4. 进入「总览」查看汇总 KPI 与趋势
5. 进入「指标」查看单店详情、商品明细、规格分析
6. 进入「成本」维护商家/SKU 编码对应的商品成本 / 物流成本；若存在未维护项，导航栏「成本」会显示红色数字徽标
7. 进入「AI & 企微」配置 API Key、生成分析结论、配置机器人并发送日报
8. 进入「知识助手」检索课程资料，或选择店铺和日期范围后结合真实经营数据进行分析
9. 主账号可在「用户管理」中按平台和页面为子账号授权

### 企微日报定时发送

服务器可通过以下 cron 每天北京时间 10:30 自动生成并发送昨天的拼多多全店日报：

```cron
30 10 * * * cd /home/ubuntu/pdd_kpi && ./venv/bin/python daily_wecom_job.py >> /home/ubuntu/pdd_kpi/data/wecom_daily_cron.log 2>&1
```

任务只会在发送成功后记录当天状态，同一报告日期重复执行时会自动跳过。部署或调试时可使用 `./venv/bin/python daily_wecom_job.py --dry-run` 验证生成过程而不发送企微消息。

---

## 运营知识助手

「知识助手」包含两种模式：

- **知识问答**：检索课程证据并生成带来源的分析；选择拼多多店铺和日期范围后，会附带该时段的 KPI 与高消耗商品数据
- **资料检索**：直接查找课程分块和结构化观点，可筛选课程、主题以及已验证决策

仓库内的 `knowledge/data/knowledge.db.gz` 是只读部署包。API 首次访问时会自动解压到 `data/knowledge/knowledge.db`，该运行时文件不会提交到 Git。若服务器希望使用独立维护的数据库，可设置：

```bash
PDD_KNOWLEDGE_DB=/absolute/path/to/knowledge.db
```

未配置 AI API Key 时，知识问答会自动使用检索式答案；已配置时会复用「AI & 企微」中的模型配置。所有未通过决策闸门的课程观点仅作为待验证假设，不会被表述为确定操作指令，也不会自动执行改价、建券、调预算或批量建链接。

---

## 文件格式说明

### 拼多多推广数据

支持 `.xls` / `.xlsx`，关键列：

| 关键列 | 说明 |
|---|---|
| 商品ID / 商品id | 商品唯一标识 |
| 成交花费(元) / 总花费(元) | 推广花费 |
| 交易额(元) / 成交金额(元) | 推广 GMV |
| 成交笔数 | 推广成交订单数 |
| 曝光量 | 曝光次数 |
| 点击量 | 点击次数 |

### 拼多多订单数据

支持 `.csv`，关键列：

| 关键列 | 说明 |
|---|---|
| 商品id | 商品唯一标识 |
| 样式ID | SKU/规格标识 |
| 商品规格 | 规格名称 |
| 订单状态 | 如：已收货、已取消、已发货退款成功等 |
| 售后状态 | 如：退款成功、无售后等 |
| 商品总价(元) | 订单商品总价 |
| 商家实收金额(元) | 商家实际收入 |
| 商品数量(件) | 购买数量 |

### 抖音推广数据

支持乘方推广 / 全域推广 Excel，关键列包括：

- 商品ID、商品名称、日期
- 整体消耗 / 综合成本
- 整体成交金额 / 净成交金额
- 整体成交订单数 / 净成交订单数
- 整体展示次数、整体点击次数
- 1小时内退款订单数 / 1小时内退款金额（可选）

### 抖音订单数据

支持 `.csv`，关键列：

| 关键列 | 说明 |
|---|---|
| 商品ID | 商品唯一标识 |
| 选购商品 | 商品名称 |
| 商品规格 | 规格名称 |
| 商品数量 | 购买数量 |
| 商品单价 | 单价 |
| 订单应付金额 | 买家应付金额 |
| 平台实际承担优惠金额 | 平台补贴（用于计算实际收入）|
| 商家编码 | 成本管理用（可选）|
| 订单状态 / 售后状态 | 用于退款/取消判定 |
| 订单提交时间 / 下单时间 | 用于拆分日期 |

> 抖音实际收入 = 订单应付金额 + 平台实际承担优惠金额

### 微信小店订单数据

支持 `.xls` / `.xlsx`，关键列：

| 关键列 | 说明 |
|---|---|
| 订单号 | 订单唯一标识 |
| 商品名称 | 商品名称 |
| SKU编码(自定义) / 自定义SKU编码 | 成本管理用自定义 SKU 编码 |
| SKU编码(平台) / 平台SKU编码 | 平台 SKU 编码 |
| 商品ID / SPUID | 平台商品 ID |
| 订单下单时间 | 用于拆分日期 |
| 订单状态 | 用于判定有效/取消订单 |
| 商品数量 | 购买数量 |
| 订单实际支付金额 | 买家实际支付 |
| 订单实际收款金额 | 商家实际收款 |
| 商品已退款金额 | 退款金额 |
| 技术服务费 | 平台技术服务费 |
| 带货费用 | 带货佣金 |

> 微信小店净成交金额 = 订单实际收款金额 - 商品已退款金额 - 技术服务费 - 带货费用（佣金）

---

## AI 配置

在「AI & 企微」页面配置：

- **API Key**：Kimi / OpenAI / 兼容 API Key
- **Base URL**：
  - Kimi coding: `https://api.kimi.com/coding/v1`
  - Moonshot: `https://api.moonshot.cn/v1`
  - OpenAI: `https://api.openai.com/v1`
- **模型名称**：如 `kimi-coding`、`moonshot-v1-8k`、`gpt-4o-mini`
- **Temperature**：默认 `1.0`

配置好后点击「测试连接」验证。未配置 API Key 时，系统会使用内置规则生成简要结论。

> API Key 保存在本机 `data/config.json`，不会上传。

---

## 成本管理

成本按「商家编码 / SKU 编码」维护：

1. 导入订单时，系统会自动把订单中新出现的编码写入成本配置（对应旧版「刷新编码」按钮功能）
2. 在「待维护商家编码」中填写商品成本 / 物流成本，点击「保存」
3. 若订单中没有编码，可在「未映射编码的商品」中把 `product_id` / 规格绑定到对应编码
4. 支持导入导出 CSV，也可单独导出「待维护编码」清单
5. 导航栏「成本」旁会显示红色数字徽标，提示当前平台还有多少未维护/未映射项

成本会按 `有效订单数` 计算总成本，并结合 `有效 GMV` 计算毛利、毛利率、盈亏、盈亏率。

---

## 数据存储

数据按平台隔离保存在项目目录下：

- `data/processed/{店铺}/`：拼多多商品指标、样式指标、订单明细
- `data/processed_douyin/{店铺}/`：抖音商品指标、订单明细
- `data/processed_tmall/{店铺}/`：天猫商品指标、订单明细
- `data/processed_wechat/{店铺}/`：微信小店商品指标、订单明细
- `data/costs.json`：拼多多/抖音/天猫/微信小店成本配置
- `data/config.json`：AI 配置
- `data/stores.json`：店铺注册信息（含 platform 字段）
- `data/users.json`：用户信息、权限、JWT 数据
- `data/.jwt_secret`：JWT Secret 持久化文件（可被 `JWT_SECRET_KEY` 环境变量覆盖）
- `data/knowledge/knowledge.db`：知识库运行时数据库（由压缩部署包自动生成，不提交 Git）

---

## 项目结构

```
pdd_bi_dashboard/
├── api.py                      # FastAPI 主入口
├── api_client.py               # LLM API 调用客户端
├── app.py / dashboard.py       # 旧版 Streamlit 入口（保留兼容）
├── auth.py                     # JWT 认证、权限中间件、密码策略
├── data_loader.py              # 拼多多文件读取
├── data_processor.py           # 拼多多推广与订单匹配
├── metrics.py                  # 拼多多 KPI 计算
├── cost_manager.py             # 拼多多成本管理
├── storage.py                  # 拼多多数据持久化
├── ai_analyzer.py              # 拼多多 AI 提示词
├── knowledge_service.py        # 运营知识库检索、问答与只读运行时管理
├── report_builder.py / wecom.py # 拼多多企微日报
├── store_manager.py            # 店铺注册与权限
├── services.py                 # 拼多多业务服务层
├── generic_report_builder.py   # 抖音/天猫/微信通用日报生成器
├── routers/                    # FastAPI 路由
│   ├── auth.py / users.py / stores.py / system.py
│   ├── knowledge.py            # 运营知识助手 API
│   ├── imports.py / orders.py / metrics.py / costs.py
│   ├── ai.py / wecom.py / exports.py / dashboard.py
│   ├── douyin.py / douyin_costs.py / douyin_ai.py / douyin_wecom.py
│   ├── tmall.py / tmall_costs.py / tmall_ai.py / tmall_wecom.py
│   └── wechat.py / wechat_costs.py / wechat_ai.py / wechat_wecom.py
├── douyin_loader.py            # 抖音文件读取
├── douyin_metrics.py           # 抖音 KPI 计算
├── douyin_cost_manager.py      # 抖音成本管理
├── douyin_services.py          # 抖音业务服务层
├── douyin_storage.py           # 抖音数据持久化
├── douyin_ai_analyzer.py       # 抖音 AI 提示词
├── douyin_report_builder.py    # 抖音企微日报
├── tmall_loader.py             # 天猫文件读取
├── tmall_metrics.py            # 天猫 KPI 计算
├── tmall_cost_manager.py       # 天猫成本管理
├── tmall_services.py           # 天猫业务服务层
├── tmall_storage.py            # 天猫数据持久化
├── tmall_ai_analyzer.py        # 天猫 AI 提示词
├── wechat_loader.py            # 微信小店文件读取
├── wechat_metrics.py           # 微信小店 KPI 计算
├── wechat_cost_manager.py      # 微信小店成本管理
├── wechat_services.py          # 微信小店业务服务层
├── wechat_storage.py           # 微信小店数据持久化
├── wechat_ai_analyzer.py       # 微信小店 AI 提示词
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── App.tsx             # 路由、侧边栏、平台切换、权限守卫
│   │   ├── pages/              # 拼多多 / 抖音 / 天猫 / 微信各页面
│   │   ├── components/
│   │   └── api/client.ts
│   └── package.json
├── knowledge/data/knowledge.db.gz # 只读知识库部署包
├── scripts/build_knowledge_bundle.py # 知识库部署包构建脚本
├── requirements.txt
├── start.bat / start.ps1       # 本地旧版 Streamlit 启动脚本
├── .github/workflows/deploy.yml # 自动部署
└── README.md
```

---

## 注意事项

- 首次运行会创建 `venv/` 和 `data/` 目录
- 新部署必须设置 `ADMIN_PASSWORD` 环境变量；存量部署若已存在 `admin` 用户则不受此限制
- `JWT_SECRET_KEY` 优先从环境变量读取，否则持久化到 `data/.jwt_secret`；生产环境建议通过 Systemd `EnvironmentFile` 外部注入
- 上传文件默认限制 50MB，统一走上传 helper 处理
- 生产环境异常信息不再直接返回客户端，可通过 `DEBUG=true` 开启详细错误
- 店铺写操作、AI/企微配置写操作、全局成本写操作均限制为主账号
- 拼多多真实 ROI = 有效商家实收 / 推广花费，「有效」指剔除退款和取消订单
- 抖音实际收入 = 订单应付金额 + 平台实际承担优惠金额
- 微信小店净成交金额 = 订单实际收款金额 - 商品已退款金额 - 技术服务费 - 带货费用（佣金）
- 推广数据中的「总计/汇总/全部」行会自动过滤
- 多店铺数据按「店铺名称」分别存储；店铺注册时选择所属平台
- 子账号权限在「用户管理」中配置，需勾选对应平台页面与允许店铺
