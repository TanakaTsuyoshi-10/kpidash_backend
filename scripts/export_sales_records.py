# -*- coding: utf-8 -*-
"""KPIダッシュボード → 販売実績データのExcel出力。

出力内容:
  A. 店舗別 月次 商品別 販売データ（販売個数・売上高） + 店舗別月次サマリ（客数・売上高・客単価）
  B. 通販 チャネル別 商品別 月次 販売データ（販売個数・売上高） + チャネル別月次サマリ（客数・売上高・客単価）

事業年度 = 9月〜翌8月。過去3年分（FY2023/FY2024/FY2025）＋進行中のFY2026を参考掲載。
売上高はKPIダッシュボードの定義に合わせ税込（sales_with_tax）。
"""
import os
from datetime import date
from collections import defaultdict

from dotenv import load_dotenv
from supabase import create_client
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, ".env"))

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

OUT_DIR = "/Users/tanakatsuyoshi/Desktop/餃子/04_経営管理/★取締役会/第18回202607/販売記録"
OUT_PATH = os.path.join(OUT_DIR, "販売実績データ_店舗別・通販別_FY2023-2026.xlsx")

# 対象期間: FY2023開始(2022-09)〜 データ最新
START = "2022-09-01"
END = "2026-08-01"


def fiscal_year(d: date) -> int:
    """9月始まり事業年度。2022-09〜2023-08 → FY2023。"""
    return d.year + 1 if d.month >= 9 else d.year


def fetch_all(table, columns, filters=None, order_key="id"):
    """ページングして全行取得。

    重要: PostgREST の .range() ページングは ORDER BY が無いと
    ページ間で行順が安定せず、行の欠落・重複が起きる。必ず主キー等で
    安定ソートしてから範囲取得する。
    """
    rows, step, start = [], 1000, 0
    while True:
        q = sb.table(table).select(columns).order(order_key).range(start, start + step - 1)
        if filters:
            for f in filters:
                q = f(q)
        res = q.execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < step:
            break
        start += step
    return rows


print("店舗マスタ取得...")
segs = {s["id"]: s["name"] for s in sb.table("segments").select("id,name,code").execute().data}
seg_code = {s["id"]: s["code"] for s in sb.table("segments").select("id,name,code").execute().data}

print("KPI定義取得...")
kdefs = sb.table("kpi_definitions").select("id,name").execute().data
kpi_id = {k["name"]: k["id"] for k in kdefs}
KID_URIAGE = kpi_id["売上高"]
KID_KYAKU = kpi_id["客数"]

# ── 店舗別 商品別 月次（product_sales。sale_dateは既に月初=月次集計済）──
print("店舗別商品別 販売データ取得...")
ps = fetch_all(
    "product_sales",
    "segment_id,sale_date,product_category_name,product_name,quantity,sales_with_tax",
    [lambda q: q.gte("sale_date", START), lambda q: q.lt("sale_date", END)],
)

# ── 店舗別 月次 客数・売上高（kpi_values）──
print("店舗別 客数・売上高(KPI)取得...")
kv = fetch_all(
    "kpi_values",
    "segment_id,kpi_id,date,value,is_target",
    [
        lambda q: q.gte("date", START),
        lambda q: q.lt("date", END),
        lambda q: q.eq("is_target", False),
        lambda q: q.in_("kpi_id", [KID_URIAGE, KID_KYAKU]),
    ],
)
store_kyaku = {}   # (segment_id, month) -> 客数
store_uriage = {}  # (segment_id, month) -> 売上高
for r in kv:
    key = (r["segment_id"], r["date"])
    if r["kpi_id"] == KID_KYAKU:
        store_kyaku[key] = r["value"]
    elif r["kpi_id"] == KID_URIAGE:
        store_uriage[key] = r["value"]

# ── 通販 チャネル別 商品別 月次（ecommerce_product_sales。channel=NULLは全チャネル合算のため除外）──
print("通販 商品別 販売データ取得...")
ep = fetch_all(
    "ecommerce_product_sales",
    "month,channel,product_name,product_category,quantity,sales",
    [lambda q: q.gte("month", START), lambda q: q.lt("month", END)],
)

# ── 通販 チャネル別 月次 客数(購入者数)・売上高（ecommerce_channel_sales）──
print("通販 チャネル別 客数・売上高取得...")
ec = fetch_all(
    "ecommerce_channel_sales",
    "month,channel,sales,buyers,is_target",
    [
        lambda q: q.gte("month", START),
        lambda q: q.lt("month", END),
        lambda q: q.eq("is_target", False),
    ],
)

# =====================================================================
# Excel生成
# =====================================================================
print("Excel生成...")
wb = Workbook()

# スタイル
HDR_FILL = PatternFill("solid", fgColor="1F4E78")
HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
SUB_FILL = PatternFill("solid", fgColor="DDEBF7")
TITLE_FONT = Font(bold=True, size=14)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")


def style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def autosize(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def yen(cell):
    cell.number_format = '#,##0'


def month_str(d):
    return f"{d.year}-{d.month:02d}"


def parse(d):
    return date.fromisoformat(d)


# ---- Sheet 1: 表紙・説明 ----
ws = wb.active
ws.title = "表紙・説明"
ws["A1"] = "販売実績データ（店舗別・通販別）"
ws["A1"].font = TITLE_FONT
ws["A3"] = "出力元: KPIダッシュボード（MaruokaKPI / Supabase）"
ws["A4"] = f"出力日: {date.today().isoformat()}"
ws["A5"] = "事業年度: 9月〜翌8月（例: FY2024 = 2023年9月〜2024年8月）"
notes = [
    "",
    "★今回の修正（重要）",
    "  ・前版のM_店舗商品別シートで店舗売上高と商品別合計が乖離していた原因を修正。",
    "    原因: データ取得のページング処理に並び順指定が無く、行の重複取得・欠落が発生し",
    "          商品別売上が過大（約2倍）＋2022年12月が欠落していた。並び順を固定し全行を正しく取得。",
    "  ・修正後、商品別売上合計はDB実績と完全一致（データ収録済み月では店舗KPI売上高とも一致）。",
    "",
    "【月次マトリクス（縦=店舗/チャネル×商品、横=年月）★メイン】",
    "  ■ M_店舗商品別_売上高    : 店舗×商品を縦、月を横。各店舗末に「商品別合計/うち宅配関連/うち店頭」小計行、",
    "                             各年度末に「FYxxxx 計」列、末尾に「全期間 計」列、末尾に全店合計を追加。",
    "  ■ M_店舗商品別_販売個数  : 同上（個数ベース）。",
    "  ■ M_店舗別_客数売上客単価 : 店舗×指標(客数/売上高/客単価)を縦、月＋年度計を横。",
    "  ■ M_通販チャネル商品別_売上高 / _販売個数 : チャネル×商品を縦、月＋年度計を横。",
    "  ■ M_通販チャネル別_客数売上客単価 : チャネル×指標を縦、月＋年度計を横。",
    "",
    "【照合シート】",
    "  ■ 売上照合_店舗KPIvs商品別 : 店舗ごとに ①店舗KPI売上高 ②商品別売上合計 ③差異 を月次で対比。",
    "     差異が残るセルは赤（下記の通り2022/9〜11のPOS未収録が主因。ピンク＝差異あり）。",
    "",
    "【明細（縦持ち・ピボット元データ）】",
    "  ■ 店舗別_商品別月次 / 店舗別_月次サマリ / 通販_チャネル別商品別月次 / 通販_チャネル別月次サマリ",
    "",
    "【対象事業年度】",
    "  FY2023 (2022/9〜2023/8) … 店舗商品別POSは2022/12以降のみ収録（2022/9〜11は店舗KPI売上高のみ存在）",
    "  FY2024 (2023/9〜2024/8) … 通期 / FY2025 (2024/9〜2025/8) … 通期",
    "  FY2026 (2025/9〜2026/8) … 進行中（店舗2026/7・通販2026/6まで）",
    "",
    "【残る差異（売上照合シートの赤セル）】",
    "  ・2022年9〜11月: 16店舗で店舗KPI売上高はあるがPOS商品別データ未収録（合計約4.0億円）。",
    "  ・2026年7月: 隼人店¥930・中山店¥620（最新月データ取込タイミング差、軽微）。",
    "  ・本社: 少額の月次差（計¥9,054）。",
    "",
    "【宅配関連の定義（オレンジ）】",
    "  ・元ファイルでオレンジ塗りされていた商品行(935件)を宅配関連として踏襲（宅配ぎょうざ/たれ/送料/袋 等）。",
    "  ・各店舗の「うち宅配関連 合計」＝これらオレンジ行の合計（貴社手動集計『内宅配関連売上』と一致）。",
    "  ※参考: 宅配梱包料の『○個用箱』等158行はオレンジ未マークのため宅配関連に含めていない（要否ご確認ください）。",
    "",
    "【定義・注意】",
    "  ・売上高はKPIダッシュボード定義に合わせ税込（消費税込）。",
    "  ・客単価 = 売上高 ÷ 客数（店舗は来店客数、通販は購入者数）。客数/客単価は商品別に按分していない。",
    "  ・店舗の客数・売上高はKPI値、商品別の売上・個数はPOS商品別実績（product_sales）を集計。",
    "  ・通販チャネル: EC / 電話 / FAX / 店舗受付 / ふるさと納税。channel未設定の合算行は除外。",
]
for i, t in enumerate(notes, 7):
    ws[f"A{i}"] = t
autosize(ws, [90])

# ---- Sheet 2: 店舗別_商品別月次 ----
ws = wb.create_sheet("店舗別_商品別月次")
cols = ["事業年度", "年月", "店舗コード", "店舗名", "商品カテゴリ", "商品名", "販売個数", "売上高(税込)"]
ws.append(cols)
style_header(ws, 1, len(cols))
ws.freeze_panes = "A2"
rows = []
for r in ps:
    d = parse(r["sale_date"])
    rows.append((
        f"FY{fiscal_year(d)}", month_str(d), seg_code.get(r["segment_id"], ""),
        segs.get(r["segment_id"], r["segment_id"]),
        r.get("product_category_name") or "", r.get("product_name") or "",
        float(r.get("quantity") or 0), float(r.get("sales_with_tax") or 0),
    ))
rows.sort(key=lambda x: (x[0], x[1], x[3], x[4], x[5]))
for row in rows:
    ws.append(row)
    yen(ws.cell(row=ws.max_row, column=7))
    yen(ws.cell(row=ws.max_row, column=8))
autosize(ws, [10, 9, 10, 14, 16, 22, 12, 14])

# ---- Sheet 3: 店舗別_月次サマリ ----
ws = wb.create_sheet("店舗別_月次サマリ")
cols = ["事業年度", "年月", "店舗コード", "店舗名", "客数(人)", "売上高(税込)", "客単価(円)"]
ws.append(cols)
style_header(ws, 1, len(cols))
ws.freeze_panes = "A2"
keys = sorted(set(store_uriage) | set(store_kyaku),
              key=lambda k: (parse(k[1]), segs.get(k[0], "")))
srows = []
for (sid, mth) in keys:
    d = parse(mth)
    uri = store_uriage.get((sid, mth))
    kya = store_kyaku.get((sid, mth))
    tanka = (uri / kya) if (uri and kya) else None
    srows.append((f"FY{fiscal_year(d)}", month_str(d), seg_code.get(sid, ""),
                  segs.get(sid, sid), kya, uri, tanka))
srows.sort(key=lambda x: (x[0], x[1], x[3]))
for row in srows:
    ws.append(row)
    for c in (5, 6, 7):
        yen(ws.cell(row=ws.max_row, column=c))
autosize(ws, [10, 9, 10, 14, 10, 14, 10])

# ---- Sheet 4: 通販_チャネル別商品別月次 ----
ws = wb.create_sheet("通販_チャネル別商品別月次")
cols = ["事業年度", "年月", "チャネル", "商品カテゴリ", "商品名", "販売個数", "売上高(税込)"]
ws.append(cols)
style_header(ws, 1, len(cols))
ws.freeze_panes = "A2"
erows = []
for r in ep:
    if not r.get("channel"):
        continue  # 全チャネル合算行は除外
    d = parse(r["month"])
    erows.append((f"FY{fiscal_year(d)}", month_str(d), r["channel"],
                  r.get("product_category") or "", r.get("product_name") or "",
                  float(r.get("quantity") or 0), float(r.get("sales") or 0)))
erows.sort(key=lambda x: (x[0], x[1], x[2], x[4]))
for row in erows:
    ws.append(row)
    yen(ws.cell(row=ws.max_row, column=6))
    yen(ws.cell(row=ws.max_row, column=7))
autosize(ws, [10, 9, 12, 14, 22, 12, 14])

# ---- Sheet 5: 通販_チャネル別月次サマリ ----
ws = wb.create_sheet("通販_チャネル別月次サマリ")
cols = ["事業年度", "年月", "チャネル", "客数(購入者数)", "売上高(税込)", "客単価(円)"]
ws.append(cols)
style_header(ws, 1, len(cols))
ws.freeze_panes = "A2"
crows = []
for r in ec:
    d = parse(r["month"])
    sales = float(r["sales"]) if r.get("sales") is not None else None
    buyers = r.get("buyers")
    tanka = (sales / buyers) if (sales and buyers) else None
    crows.append((f"FY{fiscal_year(d)}", month_str(d), r["channel"], buyers, sales, tanka))
crows.sort(key=lambda x: (x[0], x[1], x[2]))
for row in crows:
    ws.append(row)
    for c in (4, 5, 6):
        yen(ws.cell(row=ws.max_row, column=c))
autosize(ws, [10, 9, 12, 14, 14, 10])

# =====================================================================
# 月次マトリクス（クロス集計）シート
#   縦: ラベル（店舗/チャネル×商品）  横: 年月 ＋ 年度計 ＋ 全期間計
# =====================================================================
import json

LABEL_FILL = PatternFill("solid", fgColor="DDEBF7")
LABEL_FONT = Font(bold=True, size=10)
TOT_FILL = PatternFill("solid", fgColor="FCE4D6")      # 年度計・全期間計 列
SUBTOT_FILL = PatternFill("solid", fgColor="FFF2CC")   # 店舗小計行
TAKUHAI_FILL = PatternFill("solid", fgColor="F8CBAD")  # 宅配関連（オレンジ）
GRAND_FILL = PatternFill("solid", fgColor="C6E0B4")    # 全店合計行
DIFF_FILL = PatternFill("solid", fgColor="FFC7CE")     # 差異あり
BOLD = Font(bold=True, size=10)

# 宅配関連の分類 = ユーザーが元ファイルでオレンジ塗りした (店舗名, カテゴリ, 商品名) 集合
with open(os.path.join(BASE, "scripts", "takuhai_orange_keys.json"), encoding="utf-8") as f:
    ORANGE = {tuple(k) for k in json.load(f)}


def months_between(mmin, mmax):
    y, m = int(mmin[:4]), int(mmin[5:7])
    ye, me = int(mmax[:4]), int(mmax[5:7])
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def col_plan(present):
    """月列に加え、各年度末に『FYxxxx 計』、末尾に『全期間 計』を挿入した列プラン。"""
    months = months_between(min(present), max(present))
    plan, prev = [], None
    for mth in months:
        fy = fiscal_year(parse(mth + "-01"))
        if prev is not None and fy != prev:
            plan.append(("fyt", prev))
        plan.append(("m", mth))
        prev = fy
    if prev is not None:
        plan.append(("fyt", prev))
    plan.append(("gt", None))
    return months, plan


def plan_headers(plan):
    fy_row, mo_row = [], []
    for kind, key in plan:
        if kind == "m":
            fy_row.append(f"FY{fiscal_year(parse(key + '-01'))}")
            mo_row.append(key)
        elif kind == "fyt":
            fy_row.append(f"FY{key}")
            mo_row.append(f"FY{key} 計")
        else:
            fy_row.append("全期間")
            mo_row.append("全期間 計")
    return fy_row, mo_row


def plan_values(cm, plan):
    """cm: dict[month->value]。プランに沿って月値・年度計・全期間計を並べる。"""
    out = []
    for kind, key in plan:
        if kind == "m":
            out.append(cm.get(key))
        elif kind == "fyt":
            s = sum(v for mm, v in cm.items() if fiscal_year(parse(mm + "-01")) == key)
            out.append(s or None)
        else:
            s = sum(cm.values())
            out.append(s or None)
    return out


def is_total_col(kind):
    return kind in ("fyt", "gt")


def build_matrix(sheet_name, label_headers, records, fmt='#,##0'):
    """縦=ラベル、横=月＋年度計＋全期間計。records: (label_tuple, month, value)。"""
    ws = wb.create_sheet(sheet_name)
    grid = defaultdict(lambda: defaultdict(float))
    present, labels = set(), set()
    for lbl, mth, val in records:
        if val is None:
            continue
        grid[lbl][mth] += val
        present.add(mth)
        labels.add(lbl)
    if not present:
        ws.append(label_headers + ["(データなし)"])
        style_header(ws, 1, len(label_headers) + 1)
        return ws, 0
    months, plan = col_plan(present)
    nlab = len(label_headers)
    fy_row, mo_row = plan_headers(plan)
    ws.append([""] * nlab + fy_row)
    ws.append(list(label_headers) + mo_row)
    ncol = nlab + len(plan)
    style_header(ws, 1, ncol)
    style_header(ws, 2, ncol)

    def sort_key(lbl):
        return tuple(str(x) for x in lbl)

    for lbl in sorted(labels, key=sort_key):
        ws.append(list(lbl) + plan_values(grid[lbl], plan))
        r = ws.max_row
        for c in range(1, nlab + 1):
            ws.cell(r, c).fill = LABEL_FILL
            ws.cell(r, c).font = LABEL_FONT
        for i, (kind, _) in enumerate(plan):
            cell = ws.cell(r, nlab + 1 + i)
            cell.number_format = fmt
            if is_total_col(kind):
                cell.fill = TOT_FILL
                cell.font = BOLD
    ws.freeze_panes = ws.cell(row=3, column=nlab + 1).coordinate
    widths = [14] * nlab
    for i, h in enumerate(label_headers):
        if "商品" in h:
            widths[i] = 22
        elif "コード" in h:
            widths[i] = 9
    widths += [12 if is_total_col(k) else 11 for k, _ in plan]
    autosize(ws, widths)
    return ws, len(labels)


def build_store_product_matrix(sheet_name, value_field, fmt='#,##0'):
    """店舗×商品の月次マトリクス。
    各店舗ごとに『商品別 合計 / うち宅配関連 / うち店頭(宅配以外)』小計行、
    末尾に全店合計、宅配関連セル(商品名)はオレンジ塗り。"""
    # data[code] -> (store, {(cat,prod): {month: val}})
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    names = {}
    present = set()
    for r in ps:
        code = seg_code.get(r["segment_id"], "")
        store = segs.get(r["segment_id"], "")
        names[code] = store
        cat = r.get("product_category_name") or ""
        prod = r.get("product_name") or ""
        mth = month_str(parse(r["sale_date"]))
        data[code][(cat, prod)][mth] += float(r.get(value_field) or 0)
        present.add(mth)
    months, plan = col_plan(present)
    nlab = 4
    fy_row, mo_row = plan_headers(plan)
    ws = wb.create_sheet(sheet_name)
    ws.append([""] * nlab + fy_row)
    ws.append(["店舗コード", "店舗名", "商品カテゴリ", "商品名"] + mo_row)
    ncol = nlab + len(plan)
    style_header(ws, 1, ncol)
    style_header(ws, 2, ncol)

    def write_row(vals4, cm, fill=None, bold=False, orange_label=False):
        ws.append(list(vals4) + plan_values(cm, plan))
        r = ws.max_row
        for c in range(1, nlab + 1):
            cell = ws.cell(r, c)
            cell.font = BOLD if bold else LABEL_FONT
            if fill:
                cell.fill = fill
            elif c <= nlab:
                cell.fill = LABEL_FILL
        if orange_label:
            ws.cell(r, 4).fill = TAKUHAI_FILL
        for i, (kind, _) in enumerate(plan):
            cell = ws.cell(r, nlab + 1 + i)
            cell.number_format = fmt
            if fill:
                cell.fill = fill
                if bold:
                    cell.font = BOLD
            elif is_total_col(kind):
                cell.fill = TOT_FILL
                cell.font = BOLD
        return r

    grand_all = defaultdict(float)
    grand_tak = defaultdict(float)
    for code in sorted(names, key=lambda c: (0, int(c)) if str(c).isdigit() else (1, str(c))):
        store = names[code]
        store_all = defaultdict(float)
        store_tak = defaultdict(float)
        for (cat, prod) in sorted(data[code], key=lambda x: (str(x[0]), str(x[1]))):
            cm = data[code][(cat, prod)]
            is_tak = (store, cat, prod) in ORANGE
            write_row((code, store, cat, prod), cm, orange_label=is_tak)
            for mth, v in cm.items():
                store_all[mth] += v
                grand_all[mth] += v
                if is_tak:
                    store_tak[mth] += v
                    grand_tak[mth] += v
        store_ten = {m: store_all[m] - store_tak.get(m, 0) for m in store_all}
        write_row((code, store, "", "◆ 商品別 合計"), store_all, fill=SUBTOT_FILL, bold=True)
        write_row((code, store, "", "　うち 宅配関連 合計"), store_tak, fill=TAKUHAI_FILL, bold=True)
        write_row((code, store, "", "　うち 店頭(宅配以外)"), store_ten, fill=SUBTOT_FILL, bold=True)
    grand_ten = {m: grand_all[m] - grand_tak.get(m, 0) for m in grand_all}
    write_row(("", "【全店】", "", "◆◆ 全店 商品別 合計"), grand_all, fill=GRAND_FILL, bold=True)
    write_row(("", "【全店】", "", "　うち 宅配関連 合計"), grand_tak, fill=GRAND_FILL, bold=True)
    write_row(("", "【全店】", "", "　うち 店頭(宅配以外)"), grand_ten, fill=GRAND_FILL, bold=True)

    ws.freeze_panes = ws.cell(row=3, column=nlab + 1).coordinate
    widths = [9, 14, 16, 24] + [12 if is_total_col(k) else 11 for k, _ in plan]
    autosize(ws, widths)
    return ws


def build_reconciliation():
    """店舗KPI売上高 と 商品別売上合計 の照合（乖離の可視化）。"""
    prod = defaultdict(lambda: defaultdict(float))   # code -> month -> Σ商品別
    kpi = defaultdict(lambda: defaultdict(float))    # code -> month -> KPI売上高
    names = {}
    present = set()
    for r in ps:
        code = seg_code.get(r["segment_id"], "")
        names[code] = segs.get(r["segment_id"], "")
        mth = month_str(parse(r["sale_date"]))
        prod[code][mth] += float(r.get("sales_with_tax") or 0)
        present.add(mth)
    for (sid, dt), v in store_uriage.items():
        code = seg_code.get(sid, "")
        names[code] = segs.get(sid, "")
        mth = dt[:7]
        kpi[code][mth] += float(v)
        present.add(mth)
    months, plan = col_plan(present)
    nlab = 3
    fy_row, mo_row = plan_headers(plan)
    ws = wb.create_sheet("売上照合_店舗KPIvs商品別")
    ws.append([""] * nlab + fy_row)
    ws.append(["店舗コード", "店舗名", "区分"] + mo_row)
    ncol = nlab + len(plan)
    style_header(ws, 1, ncol)
    style_header(ws, 2, ncol)

    def emit(code, store, kind_label, cm, diff=False):
        ws.append([code, store, kind_label] + plan_values(cm, plan))
        r = ws.max_row
        for c in range(1, nlab + 1):
            ws.cell(r, c).fill = LABEL_FILL
            ws.cell(r, c).font = LABEL_FONT
        for i, (kind, _) in enumerate(plan):
            cell = ws.cell(r, nlab + 1 + i)
            cell.number_format = '#,##0'
            if is_total_col(kind):
                cell.fill = TOT_FILL
                cell.font = BOLD
            if diff and cell.value not in (None, 0):
                cell.fill = DIFF_FILL

    for code in sorted(names, key=lambda c: (0, int(c)) if str(c).isdigit() else (1, str(c))):
        store = names[code]
        kcm = kpi[code]
        pcm = prod[code]
        dcm = {m: (kcm.get(m, 0) - pcm.get(m, 0)) for m in set(kcm) | set(pcm)}
        dcm = {m: v for m, v in dcm.items() if abs(v) >= 1}
        emit(code, store, "① 店舗KPI売上高(税込)", kcm)
        emit(code, store, "② 商品別売上 合計", pcm)
        emit(code, store, "③ 差異(①−②)", dcm, diff=True)
    ws.freeze_panes = ws.cell(row=3, column=nlab + 1).coordinate
    autosize(ws, [9, 14, 20] + [12 if is_total_col(k) else 11 for k, _ in plan])
    return ws


# ---- 店舗×商品（売上高／販売個数）: 小計・年度計・全期間計・宅配オレンジ ----
build_store_product_matrix("M_店舗商品別_売上高", "sales_with_tax")
build_store_product_matrix("M_店舗商品別_販売個数", "quantity")

# ---- 売上照合（乖離の内訳可視化）----
build_reconciliation()

# ---- 店舗サマリ（客数・売上高・客単価）マトリクス: 縦=店舗×指標 ----
rec_k, rec_u, rec_t = [], [], []
for (sid, mth) in (set(store_uriage) | set(store_kyaku)):
    lbl_base = (seg_code.get(sid, ""), segs.get(sid, ""))
    uri = store_uriage.get((sid, mth))
    kya = store_kyaku.get((sid, mth))
    mm = mth[:7]
    if kya is not None:
        rec_k.append((lbl_base + ("1_客数(人)",), mm, float(kya)))
    if uri is not None:
        rec_u.append((lbl_base + ("2_売上高(税込)",), mm, float(uri)))
    if uri and kya:
        rec_t.append((lbl_base + ("3_客単価(円)",), mm, float(uri) / float(kya)))
build_matrix("M_店舗別_客数売上客単価",
             ["店舗コード", "店舗名", "指標"], rec_k + rec_u + rec_t)

# ---- 通販 チャネル×商品 売上高／販売個数マトリクス ----
for field, sheet in [("sales", "M_通販チャネル商品別_売上高"),
                     ("quantity", "M_通販チャネル商品別_販売個数")]:
    rec = []
    for r in ep:
        if not r.get("channel"):
            continue
        d = parse(r["month"])
        lbl = (r["channel"], r.get("product_name") or "")
        rec.append((lbl, month_str(d), float(r.get(field) or 0)))
    build_matrix(sheet, ["チャネル", "商品名"], rec)

# ---- 通販 チャネルサマリ（客数・売上高・客単価）マトリクス: 縦=チャネル×指標 ----
rec = []
for r in ec:
    mm = r["month"][:7]
    sales = float(r["sales"]) if r.get("sales") is not None else None
    buyers = r.get("buyers")
    if buyers is not None:
        rec.append(((r["channel"], "1_客数(購入者数)"), mm, float(buyers)))
    if sales is not None:
        rec.append(((r["channel"], "2_売上高(税込)"), mm, sales))
    if sales and buyers:
        rec.append(((r["channel"], "3_客単価(円)"), mm, sales / buyers))
build_matrix("M_通販チャネル別_客数売上客単価", ["チャネル", "指標"], rec)

os.makedirs(OUT_DIR, exist_ok=True)
wb.save(OUT_PATH)
print("保存:", OUT_PATH)
print(f"  [明細] 店舗別商品別:{len(rows)} 店舗サマリ:{len(srows)} 通販商品別:{len(erows)} 通販サマリ:{len(crows)}")
print(f"  宅配関連(オレンジ)分類: {len(ORANGE)}件")
