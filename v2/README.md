# PDD BI Dashboard V2

V2 是新系统的领域层和数据层起点，和当前线上 Parquet/JSON 版本并行演进。

本目录当前包含：

- `schema.sql`：PostgreSQL 初始数据模型
- `inventory_engine.py`：批次 FIFO、永续加权平均和订单扣库的纯 Python 引擎
- `order_engine.py`：按支付时间处理订单、展开 BOM、计算订单预计快递费并生成库存异常
- `MIGRATION.md`：旧版 Parquet/JSON 数据迁移和虚拟期初批次方案

旧版数据不会被这个目录自动修改。迁移程序会在 schema 和业务规则核对通过后单独接入。

## 已落实的业务规则

- 所有库存单品支持批次
- 批次按 FIFO 扣减；同一导入批次按支付时间升序处理
- 每仓库、每单品独立计算永续加权平均成本
- 库存金额和订单利润使用订单发生时的加权平均成本
- 库存台账保留实际批次和批次成本
- 店铺共享仓库库存
- 支付成功且未取消订单扣库存
- 库存不足时订单仍进入经营数据，但库存状态为 `exception`，不产生负库存
- 未发货取消按原批次自动冲销
- 已发货退货不自动恢复；确认后进入待检，再审核为可售/残次/报废
- 采购入库审核后才更新库存和加权平均成本
- 采购相关费用可按采购金额分摊到落地成本
- 组合商品只通过 BOM 展开扣减单品
- BOM 和单品成本都版本化
- 订单保存成本、快递费、BOM 版本和批次扣减快照
- 库存启用日由上线后的管理员配置

## 本地验证

```powershell
python -m unittest discover -s tests -p "test_inventory_engine.py"
```

当前测试覆盖：批次 FIFO、订单时点加权平均成本、库存不足原子性、待检审核、采购费用分摊、
支付时间排序、取消订单和库存启用日前订单不扣库存。

完整生命周期本地演练：

```powershell
python -m v2.local_workflow
```

该演练会串联期初批次、采购落地成本、组合 BOM、支付时间排序、订单级取消冲销、
退货待检审核和库存异常，并输出可人工核对的 JSON 结果。

一键执行后端测试、生命周期演练、编译检查和前端 lint/build：

```powershell
.\scripts\run_v2_local_checks.ps1
```

## 数据库

`schema.sql` 设计为 PostgreSQL 15+。第一阶段可用 Docker Compose 起一个独立数据库，迁移验证通过后再接入 API 和 Worker。
生产落地时，库存扣减事务必须对候选批次加行锁（`SELECT ... FOR UPDATE`），并以订单号/导入批次号作为幂等键，
避免并发导入造成重复扣库。

## 从服务器拉取本地测试样本

本机磁盘空间不足时不要拉取全量 `data/`。可以按日期拉取订单样本、成本和店铺配置：

```powershell
.\scripts\pull_legacy_sample.ps1 -Date 2026-08-31
```

脚本只读服务器业务数据，下载到 `v2/local_data/`（已加入 `.gitignore`），并自动生成
`migration_profile.json`。服务器上的临时压缩包会在脚本结束时删除。
