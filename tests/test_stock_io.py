"""stock_io 导入解析的纯逻辑单测：列名别名、行规范化、合并分组与幂等键。

不连接数据库，直接用 pandas 构造网店管家导出的表结构。
"""

import unittest
from decimal import Decimal

import pandas as pd

from v2.stock_io import (
    group_stock_lines,
    normalize_bundle_rows,
    normalize_item_rows,
    normalize_stock_rows,
    stock_io_idem_key,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class StockOutParseTests(unittest.TestCase):
    """网店管家出库明细账：出库单号/审核时间/货品编号/数量/单价/仓库/出库原因/店铺。"""

    def _out_frame(self) -> pd.DataFrame:
        return _frame([
            {"出库单号": "CK2608010001", "登记时间": "2026-08-01 09:50:11", "审核时间": "2026-08-01 09:50:11",
             "货品编号": "6956249500235", "货品名称": "60g黑芝麻汤团（简装）", "数量": 4, "单价": 14.975,
             "仓库": "昆山仓", "出库原因": "销售出库", "原始单号": "3738150743350613504", "店铺": "相城香舍点心铺"},
            {"出库单号": "CK2608010001", "登记时间": "2026-08-01 09:50:11", "审核时间": "2026-08-01 09:50:11",
             "货品编号": "6956249505810", "货品名称": "245g猪肉菌菇苏式大馄饨", "数量": 6, "单价": 8.3167,
             "仓库": "昆山仓", "出库原因": "销售出库", "原始单号": "3738150743350613505", "店铺": "相城香舍点心铺"},
        ])

    def test_outbound_columns_mapped(self):
        parsed = normalize_stock_rows(self._out_frame(), "out")
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["issues"], [])
        row = parsed["rows"][0]
        self.assertEqual(row["doc_no"], "CK2608010001")
        self.assertEqual(row["item_code"], "6956249500235")
        self.assertEqual(row["quantity"], Decimal("4"))
        self.assertEqual(row["unit_cost"], Decimal("14.975"))
        self.assertEqual(row["warehouse"], "昆山仓")
        self.assertEqual(row["reason"], "销售出库")
        self.assertIsNotNone(row["occurred_at"])

    def test_invalid_rows_become_issues(self):
        frame = _frame([
            {"出库单号": "CK1", "审核时间": "2026-08-01", "货品编号": "", "数量": 4, "仓库": "昆山仓"},
            {"出库单号": "CK2", "审核时间": "2026-08-01", "货品编号": "X1", "数量": 0, "仓库": "昆山仓"},
            {"出库单号": "CK3", "审核时间": "2026-08-01", "货品编号": "X1", "数量": 2, "仓库": ""},
        ])
        parsed = normalize_stock_rows(frame, "out")
        self.assertEqual(parsed["rows"], [])
        self.assertEqual(len(parsed["issues"]), 3)

    def test_group_merges_same_doc_item_warehouse(self):
        rows = [
            {"doc_no": "CK1", "warehouse": "昆山仓", "item_code": "A", "quantity": Decimal("4"), "unit_cost": Decimal("10"), "occurred_at": None, "item_name": None, "reason": None, "line_no": 2},
            {"doc_no": "CK1", "warehouse": "昆山仓", "item_code": "A", "quantity": Decimal("6"), "unit_cost": Decimal("20"), "occurred_at": None, "item_name": None, "reason": None, "line_no": 3},
            {"doc_no": "CK1", "warehouse": "昆山仓", "item_code": "B", "quantity": Decimal("1"), "unit_cost": Decimal("5"), "occurred_at": None, "item_name": None, "reason": None, "line_no": 4},
        ]
        grouped = group_stock_lines(rows)
        self.assertEqual(len(grouped), 2)
        merged = next(g for g in grouped if g["item_code"] == "A")
        self.assertEqual(merged["quantity"], Decimal("10"))
        self.assertEqual(merged["unit_cost"], Decimal("16"))  # (4*10+6*20)/10


class StockInParseTests(unittest.TestCase):
    """网店管家入库明细账：供应商/登记时间/入库单号/货品货号/数量/单价/入库原因/条码/仓库。"""

    def test_inbound_columns_mapped(self):
        frame = _frame([
            {"供应商": "零禾", "登记时间": "2026-08-01 14:12:57", "入库单号": "RK2608010002",
             "货品货号": "6956249500570（02）", "货品名称": "60g荠菜猪肉汤团（简装）", "数量": 180, "单价": 5.5,
             "入库原因": "采购入库", "条码": "6956249500570（02）", "仓库": "昆山仓"},
        ])
        parsed = normalize_stock_rows(frame, "in")
        self.assertEqual(len(parsed["rows"]), 1)
        row = parsed["rows"][0]
        self.assertEqual(row["doc_no"], "RK2608010002")
        self.assertEqual(row["item_code"], "6956249500570（02）")
        self.assertEqual(row["quantity"], Decimal("180"))
        self.assertEqual(row["unit_cost"], Decimal("5.5"))
        self.assertEqual(row["warehouse"], "昆山仓")
        self.assertEqual(row["reason"], "采购入库")


class CatalogParseTests(unittest.TestCase):
    def test_items_dedup_and_defaults(self):
        frame = _frame([
            {"单品编码": "A1", "单品名称": "汤团", "单位": "袋", "参考成本": 5.5},
            {"单品编码": "A1", "单品名称": "重复行"},
            {"单品编码": "B2", "单品名称": "云饺"},
        ])
        parsed = normalize_item_rows(frame)
        self.assertEqual([row["code"] for row in parsed["rows"]], ["A1", "B2"])
        self.assertEqual(len(parsed["issues"]), 1)
        self.assertEqual(parsed["rows"][1]["unit"], "件")
        self.assertEqual(parsed["rows"][0]["cost"], Decimal("5.5"))

    def test_bundles_group_components(self):
        frame = _frame([
            {"组合编码": "C1", "组合名称": "双拼装", "单品编码": "A1", "单品数量": 2, "预估快递费": 6},
            {"组合编码": "C1", "组合名称": "双拼装", "单品编码": "B2", "单品数量": 1},
            {"组合编码": "C2", "组合名称": "单品装", "单品编码": "A1", "单品数量": 1},
        ])
        parsed = normalize_bundle_rows(frame)
        self.assertEqual(len(parsed["rows"]), 2)
        bundle = next(b for b in parsed["rows"] if b["code"] == "C1")
        self.assertEqual(bundle["shipping"], Decimal("6"))
        self.assertEqual(bundle["components"], [{"item_code": "A1", "quantity": Decimal("2")}, {"item_code": "B2", "quantity": Decimal("1")}])

    def test_wgd_bundle_detail_sheet_with_name_map(self):
        """网店管家组合装明细 sheet：组合装编号/编号/名称(组件名)/数量，组合名由主表回填。"""
        detail = _frame([
            {"组合装编号": "C1", "编号": "A1", "名称": "组件一", "数量": 2},
            {"组合装编号": "C1", "编号": "B2", "名称": "组件二", "数量": 1},
        ])
        parsed = normalize_bundle_rows(detail, name_map={"C1": "双拼装"})
        self.assertEqual(len(parsed["rows"]), 1)
        bundle = parsed["rows"][0]
        self.assertEqual(bundle["code"], "C1")
        self.assertEqual(bundle["components"], [{"item_code": "A1", "quantity": Decimal("2")}, {"item_code": "B2", "quantity": Decimal("1")}])
        self.assertIn(bundle["name"], {"双拼装", "组件一"})  # 名称在端点层以主表为准覆盖


class IdempotencyKeyTests(unittest.TestCase):
    def test_key_format(self):
        self.assertEqual(stock_io_idem_key("in", "RK1", "KUNSHAN", "A1"), "stock_in:RK1:KUNSHAN:A1")
        self.assertEqual(stock_io_idem_key("out", "CK1", "KUNSHAN", "A1", "batch-9"), "stock_out:CK1:KUNSHAN:A1:batch-9")


if __name__ == "__main__":
    unittest.main()
