# -*- coding: utf-8 -*-
"""V2 迁移完整性对账：老 parquet 文件统计 vs PG 表统计。

在测试机上运行（需要 pandas + psycopg）：
    venv/bin/python reconcile_v2_migration.py [--legacy-base /opt/pdd_bi_v2_test/legacy_full]
"""
import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd
import psycopg

DATABASE_URL = os.getenv("V2_DATABASE_URL", "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:5432/pdd_v2_test")

PLATFORM_DIRS = {
    "pdd": "processed",
    "douyin": "processed_douyin",
    "tmall": "processed_tmall",
    "wechat": "processed_wechat",
}

# Non-pdd platforms keep order/product parquet under per-store subdirectories
# (e.g. processed_douyin/<store>/<date>_orders.parquet), so they must be scanned
# recursively. pdd uses flat processed/orders_<store>_<date>.parquet.
RECURSIVE_PLATFORMS = {"douyin", "tmall", "wechat"}
DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})$")


def file_date(p: Path) -> str | None:
    m = DATE_RE.search(p.stem)
    return m.group(1) if m else None


def scan_orders(files):
    stats = {"files": 0, "rows": 0, "orders": set(), "dates": [], "user_paid": 0.0, "item_total": 0.0}
    for f in files:
        df = pd.read_parquet(f)
        if df.empty:
            continue
        stats["files"] += 1
        stats["rows"] += len(df)
        if "order_id" in df.columns:
            stats["orders"].update(df["order_id"].astype(str))
        # pdd uses user_paid/item_total; douyin/tmall/wechat use actual_revenue/amount
        up = "user_paid" if "user_paid" in df.columns else ("actual_revenue" if "actual_revenue" in df.columns else None)
        it = "item_total" if "item_total" in df.columns else ("amount" if "amount" in df.columns else None)
        if up:
            stats["user_paid"] += float(pd.to_numeric(df[up], errors="coerce").fillna(0).sum())
        if it:
            stats["item_total"] += float(pd.to_numeric(df[it], errors="coerce").fillna(0).sum())
        d = file_date(f)
        if d:
            stats["dates"].append(d)
    return stats


def scan_promos(files):
    stats = {"files": 0, "rows": 0, "dates": [], "spend": 0.0, "gmv": 0.0}
    for f in files:
        df = pd.read_parquet(f)
        if df.empty:
            continue
        stats["files"] += 1
        stats["rows"] += len(df)
        for col, key in (("promo_spend", "spend"), ("promo_gmv", "gmv")):
            if col in df.columns:
                stats[key] += float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
        d = file_date(f)
        if d:
            stats["dates"].append(d)
    return stats


def fmt_dates(dates):
    return f"{min(dates)} ~ {max(dates)}" if dates else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-base", default="/opt/pdd_bi_v2_test/legacy_full")
    args = ap.parse_args()
    base = Path(args.legacy_base)

    legacy = {}
    for platform, dirname in PLATFORM_DIRS.items():
        d = base / dirname
        pat = "**/*_orders.parquet" if platform in RECURSIVE_PLATFORMS else "orders_*.parquet"
        ppat = "**/*_promo*.parquet" if platform in RECURSIVE_PLATFORMS else "promo_*.parquet"
        legacy[platform] = {
            "orders": scan_orders(sorted(d.glob(pat))) if d.is_dir() else None,
            "promos": scan_promos(sorted(d.glob(ppat))) if d.is_dir() else None,
        }

    pg = {}
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""
            select platform, count(*), count(distinct (store_name, order_id)),
                   min(payment_time at time zone 'Asia/Shanghai')::date,
                   max(payment_time at time zone 'Asia/Shanghai')::date
            from platform_orders group by platform order by platform
        """)
        pg_orders = {r[0]: r[1:] for r in cur.fetchall()}
        cur.execute("""
            select platform, count(*), sum(spend), sum(gmv), min(metric_date), max(metric_date)
            from promotion_metrics_daily group by platform order by platform
        """)
        pg_promos = {r[0]: r[1:] for r in cur.fetchall()}
        cur.execute("""
            select coalesce(sum((l.raw_payload->>'user_paid')::numeric), 0),
                   coalesce(sum((l.raw_payload->>'item_total')::numeric), 0)
            from platform_order_lines l join platform_orders o on o.id = l.order_id
            where o.platform = 'pdd'
        """)
        pg_amounts = cur.fetchone()
        cur.execute("select data_type, platform, count(*), sum(row_count) from data_import_batches group by 1, 2 order by 1, 2")
        batches = cur.fetchall()
        pg["orders"] = pg_orders
        pg["promos"] = pg_promos
        pg["pdd_amounts"] = pg_amounts
        pg["batches"] = batches

    print("=" * 78)
    print("老 parquet 文件统计（legacy_full）")
    print("=" * 78)
    for platform, data in legacy.items():
        o, p = data["orders"], data["promos"]
        print(f"\n[{platform}]")
        if o:
            print(f"  orders: {o['files']} 文件 / {o['rows']} 行 / {len(o['orders'])} 个订单号 / 日期 {fmt_dates(o['dates'])}")
            print(f"          user_paid 合计 {o['user_paid']:.2f} / item_total 合计 {o['item_total']:.2f}")
        else:
            print("  orders: 无目录或无文件")
        if p:
            print(f"  promos: {p['files']} 文件 / {p['rows']} 行 / 日期 {fmt_dates(p['dates'])}")
            print(f"          spend 合计 {p['spend']:.2f} / gmv 合计 {p['gmv']:.2f}")
        else:
            print("  promos: 无目录或无文件")

    print()
    print("=" * 78)
    print("PG 表统计（pdd_v2_test）")
    print("=" * 78)
    for platform, (cnt, distinct_cnt, dmin, dmax) in pg["orders"].items():
        print(f"\n[{platform}] platform_orders: {cnt} 行 / {distinct_cnt} 个订单号 / 支付日期 {dmin} ~ {dmax}")
    for platform, (cnt, spend, gmv, dmin, dmax) in pg["promos"].items():
        print(f"[{platform}] promotion_metrics_daily: {cnt} 行 / spend {float(spend or 0):.2f} / gmv {float(gmv or 0):.2f} / 日期 {dmin} ~ {dmax}")
    print(f"\npdd 订单行金额（raw_payload 汇总）: user_paid {float(pg['pdd_amounts'][0]):.2f} / item_total {float(pg['pdd_amounts'][1]):.2f}")
    print("\ndata_import_batches:")
    for row in pg["batches"]:
        print(f"  {row}")

    # 差异结论
    print()
    print("=" * 78)
    print("对账结论")
    print("=" * 78)
    lo = legacy["pdd"]["orders"]
    pgo = pg["orders"].get("pdd")
    if lo and pgo:
        print(f"pdd 订单号: 文件 {len(lo['orders'])} vs PG {pgo[1]} -> {'OK' if len(lo['orders']) == pgo[1] else 'DIFF'}")
        print(f"pdd user_paid: 文件 {lo['user_paid']:.2f} vs PG {float(pg['pdd_amounts'][0]):.2f} -> {'OK' if abs(lo['user_paid'] - float(pg['pdd_amounts'][0])) < 1 else 'DIFF'}")
    lp = legacy["pdd"]["promos"]
    pgp = pg["promos"].get("pdd")
    if lp and pgp:
        print(f"pdd promo 行数: 文件 {lp['rows']} vs PG {pgp[0]} -> {'OK' if lp['rows'] == pgp[0] else 'DIFF'}")
        print(f"pdd promo gmv: 文件 {lp['gmv']:.2f} vs PG {float(pgp[2] or 0):.2f} -> {'OK' if abs(lp['gmv'] - float(pgp[2] or 0)) < 1 else 'DIFF'}")
    for platform in ("douyin", "tmall", "wechat"):
        has_files = bool(legacy[platform]["orders"] or legacy[platform]["promos"])
        in_pg = platform in pg["orders"] or platform in pg["promos"]
        print(f"{platform}: 老文件 {'有' if has_files else '无'} / PG {'有' if in_pg else '无'} -> {'OK' if has_files == in_pg else 'TODO: 待迁移'}")


if __name__ == "__main__":
    main()
