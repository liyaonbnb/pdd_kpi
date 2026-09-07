# V2 旧功能迁移计划

## 原则
- 成本：完全改用 V2 单品/组合/BOM 成本模型。
- 其他经营功能：在 V2 API 上新建 V1 兼容路由，逐步用 V2 数据模型重新实现。
- 前端保留现有 React 页面，通过 /api/* 代理到 V2 API。

## 已完成
- v2/v1_compat.py：V1 兼容路由
  - GET /api/stores
  - POST /api/stores
  - GET /api/dashboard/summary
  - GET /api/dashboard/operations-daily
  - GET /api/metrics/analysis
  - GET /api/metrics/trend
  - GET /api/orders
  - POST /api/imports/preview
  - POST /api/imports
  - GET /api/imports/batches
  - POST /api/imports/batches/{batch_id}/rollback
  - GET /api/imports/records
  - DELETE /api/imports/records/{store_name}/{day}
  - GET /api/imports/cleanup/preview
  - POST /api/imports/cleanup
- v2/test_api.py：已挂载 v1_compat.router
- v2/test_api.py：V2 单品/BOM 成本、订单成本快照、库存台账、采购、退货和异常接口
- v2/stock_io.py：库存入库、出库、商品目录和组合 BOM 导入解析
- frontend/src/pages/v2：V2 工作台已覆盖库存、成本、批次、台账、采购、订单、退货、导入、店铺和权限模块
- 用户迁移：生产 9 个账号（含 bcrypt hash、店铺/页面权限）已导入 v2_users（2026-09-04）
- 迁移对账脚本：scripts/reconcile_v2_migration.py（pdd 订单金额完全一致；promo 差异为无 product_id 行被跳过）

## 待迁移清单（按优先级）

### P0 - 核心经营看板
- [x] /api/dashboard/operations-daily
- [x] /api/metrics/analysis
- [x] /api/metrics/trend
- [x] /api/orders/*
- [x] /api/imports/*
- [x] v1_compat dashboard/summary 已改为从 V2 订单、推广和订单成本快照聚合

### P1 - 多平台等价页面
- [~] `/api/{platform}/{dashboard,orders,trend,analysis,costs,records}` 已统一接入；导入、AI、企微等写入/自动化接口仍待迁移
- [x] PDD 成本页面可通过 V2 单品/BOM 成本接口读取
- [x] 抖音/天猫/微信成本读取接口改用 V2 BOM/单品成本数据
- [ ] 四平台 parquet 数据全量迁入 PG（当前 legacy_full 只有 pdd）

### P2 - 自动化与系统
- [ ] 企业微信日报（含 daily_wecom_job 定时任务）
- [ ] AI 分析
- [ ] 用户/权限管理（/api/users 对接 v2_users）
- [ ] 知识助手
- [ ] 系统/备份

## 风险
- promo 迁移跳过无 product_id 的行（约 445 行），需在 P1 前确认口径。
- 旧版 dashboard 部分字段在 V2 中暂时使用简化假设。
- douyin/tmall/wechat 历史数据尚未从生产机拉取。
