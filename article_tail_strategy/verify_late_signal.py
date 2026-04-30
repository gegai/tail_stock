"""
验证命题：
  "最后45分钟到35分钟这段时间上涨，那么最后一般会以上涨结束全天走势"

时间窗口：
  - 信号窗口：14:15 → 14:25（距收盘45分钟到35分钟，共10分钟）
  - 全天判定：开盘(9:30) → 收盘(15:00)

三种"上涨结束"定义：
  A) close > open       —— 当日收阳线
  B) close > prev_close —— 涨跌幅为正
  C) close > P14:25     —— 14:25之后继续上涨

数据源：
  Phase-1: 全部指数 1 分钟数据（D:/股票数据/指数数据/index_1min/）
  Phase-2: 股票 1 分钟数据（D:/股票数据/行情数据/stock_1min/）—— 大样本随机抽样
"""
from __future__ import annotations
import os
import time
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

INDEX_1MIN_DIR = Path("D:/股票数据/指数数据/index_1min")
STOCK_1MIN_DIR = Path("D:/股票数据/行情数据/stock_1min")

T_OPEN  = pd.Timestamp("09:30").time()
T_1415  = pd.Timestamp("14:15").time()
T_1425  = pd.Timestamp("14:25").time()
T_CLOSE = pd.Timestamp("15:00").time()


def _extract_daily_points(path: Path) -> pd.DataFrame:
    """
    从单个 1分钟 parquet 文件中提取每日 9:30 / 14:15 / 14:25 / 15:00 收盘价。
    返回 DataFrame 列：trade_date, p_open, p1415, p1425, p_close
    """
    try:
        df = pd.read_parquet(path, columns=["close"])
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df = df.reset_index()
    if "trade_time" not in df.columns or "trade_date" not in df.columns:
        return pd.DataFrame()

    times = df["trade_time"].dt.time
    df["t"] = times

    # 仅保留四个关键分钟（如缺失某分钟，取该日最接近的可用价代替）
    keep = df[df["t"].isin([T_OPEN, T_1415, T_1425, T_CLOSE])].copy()
    if keep.empty:
        return pd.DataFrame()

    # 按 (trade_date, t) 取该分钟收盘
    keep = keep.drop_duplicates(subset=["trade_date", "t"], keep="last")
    pivot = keep.pivot(index="trade_date", columns="t", values="close")
    pivot.columns = [str(c) for c in pivot.columns]

    # 对齐
    rename = {
        "09:30:00": "p_open",
        "14:15:00": "p1415",
        "14:25:00": "p1425",
        "15:00:00": "p_close",
    }
    pivot = pivot.rename(columns=rename)
    for col in ["p_open", "p1415", "p1425", "p_close"]:
        if col not in pivot.columns:
            pivot[col] = np.nan
    pivot = pivot[["p_open", "p1415", "p1425", "p_close"]].copy()

    # 取昨收
    pivot = pivot.sort_index()
    pivot["prev_close"] = pivot["p_close"].shift(1)

    # 仅保留四点齐全的交易日
    pivot = pivot.dropna(subset=["p_open", "p1415", "p1425", "p_close"])
    pivot = pivot.reset_index().rename(columns={"trade_date": "trade_date"})
    pivot["src"] = path.stem
    return pivot


def _summarize(df: pd.DataFrame, label: str) -> dict:
    """对样本统计三种解读下的条件概率。"""
    if df.empty:
        return {"label": label, "n": 0}

    df = df.dropna(subset=["p_open", "p1415", "p1425", "p_close"]).copy()
    n_total = len(df)

    # 信号
    sig = df["p1425"] > df["p1415"]
    nosig = df["p1425"] < df["p1415"]
    flat = df["p1425"] == df["p1415"]

    # 三种"上涨结束"
    up_a = df["p_close"] > df["p_open"]
    df_b = df.dropna(subset=["prev_close"])
    sig_b = df_b["p1425"] > df_b["p1415"]
    up_b = df_b["p_close"] > df_b["prev_close"]
    up_c = df["p_close"] > df["p1425"]

    def p(mask):
        return float(mask.mean()) if len(mask) else float("nan")

    res = {
        "label": label,
        "n_total": n_total,
        "n_sig": int(sig.sum()),
        "n_nosig": int(nosig.sum()),
        "n_flat": int(flat.sum()),
        "p_sig": p(sig),
        # A: close > open
        "P(A_close_gt_open)":         p(up_a),
        "P(A | sig)":                 p(up_a[sig]),
        "P(A | ~sig)":                p(up_a[nosig]),
        # B: close > prev_close
        "n_total_b":                  int(len(df_b)),
        "P(B_pct_gt_0)":              p(up_b),
        "P(B | sig)":                 p(up_b[sig_b]),
        "P(B | ~sig)":                p(up_b[df_b["p1425"] < df_b["p1415"]]),
        # C: close > p1425
        "P(C_close_gt_1425)":         p(up_c),
        "P(C | sig)":                 p(up_c[sig]),
        "P(C | ~sig)":                p(up_c[nosig]),
    }
    return res


def _print_summary(res: dict):
    print(f"\n=== {res['label']} ===")
    if res.get("n_total", 0) == 0:
        print("  (无数据)")
        return
    print(f"  样本量(交易日×标的) n = {res['n_total']:,}")
    print(f"  信号成立(14:15→14:25 上涨) n_sig = {res['n_sig']:,} ({res['p_sig']:.2%})")
    print(f"  信号不成立 (下跌) n_nosig = {res['n_nosig']:,}")
    print(f"  平盘 n_flat = {res['n_flat']:,}")
    print()
    print(f"  [A] close > open  整体: {res['P(A_close_gt_open)']:.2%}")
    print(f"      P(A | 信号成立)   = {res['P(A | sig)']:.2%}")
    print(f"      P(A | 信号不成立) = {res['P(A | ~sig)']:.2%}")
    lift_a = res['P(A | sig)'] - res['P(A_close_gt_open)']
    print(f"      lift = +{lift_a*100:.2f} 个百分点")
    print()
    print(f"  [B] close > prev_close (涨跌幅>0)  整体: {res['P(B_pct_gt_0)']:.2%}")
    print(f"      P(B | 信号成立)   = {res['P(B | sig)']:.2%}")
    print(f"      P(B | 信号不成立) = {res['P(B | ~sig)']:.2%}")
    lift_b = res['P(B | sig)'] - res['P(B_pct_gt_0)']
    print(f"      lift = +{lift_b*100:.2f} 个百分点")
    print()
    print(f"  [C] close > p14:25  整体: {res['P(C_close_gt_1425)']:.2%}")
    print(f"      P(C | 信号成立)   = {res['P(C | sig)']:.2%}")
    print(f"      P(C | 信号不成立) = {res['P(C | ~sig)']:.2%}")
    lift_c = res['P(C | sig)'] - res['P(C_close_gt_1425)']
    print(f"      lift = +{lift_c*100:.2f} 个百分点")


def collect(paths: list[Path], max_workers: int = 8, log_every: int = 50) -> pd.DataFrame:
    """并行抽取多个 parquet 的关键分钟数据。"""
    rows = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_extract_daily_points, p): p for p in paths}
        done = 0
        for fu in as_completed(futures):
            try:
                rows.append(fu.result())
            except Exception as e:
                pass
            done += 1
            if done % log_every == 0:
                elapsed = time.time() - t0
                print(f"    进度 {done}/{len(paths)}  用时 {elapsed:.1f}s", flush=True)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    return out


def main():
    print("=" * 70)
    print("验证：14:15→14:25 上涨 ⇒ 当日收涨？")
    print("=" * 70)

    # ── Phase 1：全部指数 1分钟 ─────────────────────────────────────
    idx_files = sorted(INDEX_1MIN_DIR.glob("*.parquet"))
    print(f"\n[Phase 1] 指数 1分钟数据，文件数 = {len(idx_files)}")
    idx_df = collect(idx_files, max_workers=8, log_every=100)

    # 重要指数子集
    important = {
        "000001.SH": "上证综指",
        "000300.SH": "沪深300",
        "000016.SH": "上证50",
        "000905.SH": "中证500",
        "000852.SH": "中证1000",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000688.SH": "科创50",
    }
    for code, name in important.items():
        sub = idx_df[idx_df["src"] == code]
        if not sub.empty:
            _print_summary(_summarize(sub, f"{code} {name}"))

    # 全指数合并
    _print_summary(_summarize(idx_df, "全部指数（{}个文件）".format(idx_df["src"].nunique())))

    # 时间分段
    idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"])
    idx_df["year"] = idx_df["trade_date"].dt.year
    print("\n--- 全指数·按年度切片 ---")
    for year in sorted(idx_df["year"].unique()):
        sub = idx_df[idx_df["year"] == year]
        if len(sub) < 100:
            continue
        res = _summarize(sub, f"{year}年")
        print(f"  {year}: n={res['n_total']:>7,}  P(sig)={res['p_sig']:.2%}  "
              f"P(A|sig)={res['P(A | sig)']:.2%}  P(A|~sig)={res['P(A | ~sig)']:.2%}  "
              f"lift={(res['P(A | sig)']-res['P(A_close_gt_open)'])*100:+.2f}pp")

    # ── Phase 2：股票样本 1分钟 ─────────────────────────────────────
    stk_files = sorted(STOCK_1MIN_DIR.glob("*.parquet"))
    print(f"\n[Phase 2] 股票 1分钟数据，全市场 = {len(stk_files)}")

    # 为速度起见随机抽 800 只（样本量已经数百万）
    random.seed(42)
    sample = random.sample(stk_files, k=min(800, len(stk_files)))
    print(f"  随机抽样 = {len(sample)} 只")
    stk_df = collect(sample, max_workers=8, log_every=100)
    if not stk_df.empty:
        _print_summary(_summarize(stk_df, f"股票随机样本（{stk_df['src'].nunique()}只）"))

        stk_df["trade_date"] = pd.to_datetime(stk_df["trade_date"])
        stk_df["year"] = stk_df["trade_date"].dt.year
        print("\n--- 股票样本·按年度切片 ---")
        for year in sorted(stk_df["year"].unique()):
            sub = stk_df[stk_df["year"] == year]
            if len(sub) < 1000:
                continue
            res = _summarize(sub, f"{year}年")
            print(f"  {year}: n={res['n_total']:>9,}  P(sig)={res['p_sig']:.2%}  "
                  f"P(A|sig)={res['P(A | sig)']:.2%}  P(A|~sig)={res['P(A | ~sig)']:.2%}  "
                  f"lift={(res['P(A | sig)']-res['P(A_close_gt_open)'])*100:+.2f}pp")

    print("\nDONE")


if __name__ == "__main__":
    main()
