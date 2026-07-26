from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def read_workbook(path: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(path) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root]
        wb = ET.fromstring(book.read("xl/workbook.xml"))
        rel_root = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        rels = {x.attrib["Id"]: x.attrib["Target"] for x in rel_root}
        result = {}
        for sheet in wb.find("m:sheets", NS):
            name = sheet.attrib["name"]
            target = rels[sheet.attrib[f"{{{NS['r']}}}id"]]
            target = target if target.startswith("xl/") else f"xl/{target}"
            root = ET.fromstring(book.read(target))
            rows = []
            for row in root.findall(".//m:sheetData/m:row", NS):
                values = {}
                for cell in row.findall("m:c", NS):
                    value = cell.find("m:v", NS)
                    text = "" if value is None else value.text or ""
                    if cell.attrib.get("t") == "s" and text:
                        text = strings[int(text)]
                    values[cell.attrib["r"][:-len(str(row.attrib["r"]))] if False else cell.attrib["r"]] = text
                rows.append(values)
            headers = [v for k, v in sorted(rows[0].items(), key=lambda x: int(''.join(filter(str.isdigit, x[0]))))]
            records = []
            for row in rows[1:]:
                ordered = [row.get(f"{chr(65+i)}{len(records)+2}", "") for i in range(len(headers))]
                records.append(dict(zip(headers, ordered)))
            result[name] = records
        return result


def import_dossier(workbook: Path, db: Path, output_json: Path) -> dict:
    sheets = read_workbook(workbook)
    products = sheets.get("产品信息", [])
    paid = sheets.get("投流数据", [])
    organic = sheets.get("内容数据", [])
    collected_at = datetime.now(timezone.utc).isoformat()
    dossier = {
        "brand_name": "曲奇四重奏",
        "category": "香港高端烘焙／蝴蝶酥与手工曲奇／伴手礼",
        "source": {"file_name": workbook.name, "sheets": list(sheets), "collected_at": collected_at,
                   "evidence_grade": "C_user_provided_workbook", "source_note": "原工作簿未注明平台导出来源"},
        "brand_assets": {"founder_story": "谢宁港姐身份（用户提供，待品牌官方来源核验）", "founded": "2008年（用户提供，待官方来源核验）", "hong_kong_stores": "待补充门店清单", "awards": "待补充奖项名称及证书/官方来源"},
        "products": products,
        "paid_metrics": paid,
        "organic_metrics": organic,
        "data_gaps": ["香港门店与内地电商/社交/小程序/跨境渠道 URL", "历史笔记 URL、账号粉丝、评论原文", "销量、客单价、真实转化率、复购率、地域分布", "聚光账户、推广目标、投放素材、广告标识", "投流数据的正式平台来源与币种确认"],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS brand_profiles (brand_name TEXT PRIMARY KEY, category TEXT, source_file TEXT, collected_at TEXT, evidence_grade TEXT, data_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brand_products (brand_name TEXT NOT NULL, product_name TEXT NOT NULL, price TEXT, selling_points TEXT, audience TEXT, source_file TEXT, collected_at TEXT, PRIMARY KEY (brand_name, product_name));
        CREATE TABLE IF NOT EXISTS paid_metrics (brand_name TEXT NOT NULL, year INTEGER, month INTEGER, data_json TEXT NOT NULL, source_file TEXT, collected_at TEXT, PRIMARY KEY (brand_name, year, month));
        CREATE TABLE IF NOT EXISTS organic_metrics (brand_name TEXT NOT NULL, period TEXT NOT NULL, data_json TEXT NOT NULL, source_file TEXT, collected_at TEXT, PRIMARY KEY (brand_name, period));
        CREATE TABLE IF NOT EXISTS brand_data_gaps (brand_name TEXT NOT NULL, gap TEXT NOT NULL, collected_at TEXT, PRIMARY KEY (brand_name, gap));
        """)
        conn.execute("INSERT OR REPLACE INTO brand_profiles VALUES (?,?,?,?,?,?)", (dossier["brand_name"], dossier["category"], workbook.name, collected_at, dossier["source"]["evidence_grade"], json.dumps(dossier["brand_assets"], ensure_ascii=False)))
        for p in products:
            conn.execute("INSERT OR REPLACE INTO brand_products VALUES (?,?,?,?,?,?,?)", (dossier["brand_name"], p.get("产品名称", ""), p.get("价格", ""), p.get("核心卖点", ""), p.get("目标人群", ""), workbook.name, collected_at))
        for row in paid:
            conn.execute("INSERT OR REPLACE INTO paid_metrics VALUES (?,?,?,?,?,?)", (dossier["brand_name"], int(row.get("年份", "0").replace("年", "")), int(row.get("月份", "0").replace("月", "")), json.dumps(row, ensure_ascii=False), workbook.name, collected_at))
        for row in organic:
            conn.execute("INSERT OR REPLACE INTO organic_metrics VALUES (?,?,?,?,?)", (dossier["brand_name"], row.get("时间", ""), json.dumps(row, ensure_ascii=False), workbook.name, collected_at))
        for gap in dossier["data_gaps"]:
            conn.execute("INSERT OR REPLACE INTO brand_data_gaps VALUES (?,?,?)", (dossier["brand_name"], gap, collected_at))
    return {"products": len(products), "paid_months": len(paid), "organic_periods": len(organic), "data_gaps": len(dossier["data_gaps"]), "db": str(db), "json": str(output_json)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--db", type=Path, default=Path(__file__).parents[1] / "data/xhs_knowledge.db")
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "data/quartet_brand_dossier.json")
    args = parser.parse_args()
    print(json.dumps(import_dossier(args.workbook, args.db, args.output), ensure_ascii=False, indent=2))
