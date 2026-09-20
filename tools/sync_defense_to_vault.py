# -*- coding: utf-8 -*-
"""把 docs/00-答辩实验全流程图解.md 同步成 Obsidian 版(图片内嵌可显示)。

做什么:
  1. 讲稿引用的 13 张图 → 降采样(宽≤1200, JPEG q82)拷入
     <vault>/30-Projects/15分钟生活圈比赛/assets/
  2. docs/00 → <vault>/30-Projects/15分钟生活圈比赛/14-答辩实验全流程图解.md
     图片语法改写为 Obsidian 内嵌 ![[name.png]](vault 内全局解析,与路径无关)
用法:改完 docs/00 后跑  .venv/Scripts/python.exe tools/sync_defense_to_vault.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_DIR = r"C:\Users\19066\Obsidian\30-Projects\15分钟生活圈比赛"
SRC_DOC = os.path.join(ROOT, "docs", "00-答辩实验全流程图解.md")
SRC_IMG_DIR = os.path.join(ROOT, "experiments", "results", "maps")
DST_ASSETS = os.path.join(VAULT_DIR, "assets")
DST_DOC = os.path.join(VAULT_DIR, "14-答辩实验全流程图解.md")

# 原名 → vault 资产名(ASCII,便于 wikilink)
RENAME = {
    "A.png": "map_A.png",
    "harbin.png": "map_harbin.png",
    "guilin.png": "map_guilin.png",
    "kunshan.png": "map_kunshan.png",
    "yiwu.png": "map_yiwu.png",
    "multi_threshold_harbin.png": "fig_multithreshold_harbin.png",
    "multi_threshold_kunshan.png": "fig_multithreshold_kunshan.png",
    "multi_threshold_guilin.png": "fig_multithreshold_guilin.png",
    "size_difficulty.png": "fig_size_difficulty.png",
    "nanchang_demo.png": "map_nanchang_after.png",
    "anno_yiwu_needle.png": "anno_yiwu_needle.png",
    "anno_zunyi_band.png": "anno_zunyi_band.png",
    "anno_nanchang_smallangle.png": "anno_nanchang_smallangle.png",
}


def convert_images():
    from PIL import Image
    os.makedirs(DST_ASSETS, exist_ok=True)
    for src_name, dst_name in RENAME.items():
        src = os.path.join(SRC_IMG_DIR, src_name)
        dst = os.path.join(DST_ASSETS, dst_name)
        if not os.path.exists(src):
            print("  [缺] ", src_name)
            continue
        im = Image.open(src).convert("RGB")
        if im.width > 1200:
            im = im.resize((1200, round(im.height * 1200 / im.width)),
                           Image.LANCZOS)
        im.save(dst, "JPEG", quality=82, optimize=True)
        print(f"  [图] {src_name} -> assets/{dst_name}"
              f"({im.width}x{im.height}, {os.path.getsize(dst)//1024}KB)")


def rewrite_doc():
    s = io.open(SRC_DOC, encoding="utf-8").read()
    # ![alt](../experiments/results/maps/xxx.png)  →  ![[dst.png]]
    def sub(m):
        name = os.path.basename(m.group(2))
        if name in RENAME:
            return f"![[{RENAME[name]}]]"
        return m.group(0)          # 未登记的图保持原样(提醒维护者登记)
    s2 = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", sub, s)
    left = re.findall(r"!\[\]\(\.\./[^)]+\)", s2)
    header = ("> ⚠️ 本文件由工作区 `docs/00-答辩实验全流程图解.md` 同步生成"
              f"(tools/sync_defense_to_vault.py),改内容请改工作区版再同步。\n\n")
    io.open(DST_DOC, "w", encoding="utf-8", newline="").write(header + s2)
    print(f"  [文] -> {DST_DOC}")
    if left:
        print("  [!] 未登记图片:", left)


if __name__ == "__main__":
    print("同步答辩讲稿到 Obsidian:")
    convert_images()
    rewrite_doc()
    print("完成")
