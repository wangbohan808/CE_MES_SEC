#!/usr/bin/env python3
"""post-commit: 为 HEAD 生成 doc/ai-changelog/*_auto-snapshot.md（不自动 commit）"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DIFF_MAX = 8000
SKIP_MSG = re.compile(
    r"(docs:\s*ai-changelog|chore\(快照\)|auto-snapshot)",
    re.IGNORECASE,
)


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def main() -> int:
    root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    msg = git("log", "-1", "--format=%s", cwd=root)

    if SKIP_MSG.search(msg):
        return 0

    names = git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", cwd=root)
    if not names:
        return 0

    short = git("rev-parse", "--short", "HEAD", cwd=root)
    stat = git("show", "--stat", "--format=", "HEAD", cwd=root)
    diff = git("show", "--format=", "HEAD", cwd=root)
    if len(diff) > DIFF_MAX:
        diff = (
            diff[:DIFF_MAX]
            + f"\n\n...（diff 已截断，完整内容见 git show {short}）"
        )

    now = datetime.now()
    ts_file = now.strftime("%Y-%m-%dT%H%M%S")
    ts_human = now.strftime("%Y-%m-%d %H:%M:%S")

    body = f"""# 自动快照

- **时间**: {ts_human}
- **类型**: Git post-commit Hook 自动生成
- **提交**: `{short}` — {msg}
- **触发**: 手动 git commit 后

## 目的

（Hook 无法推断业务语义；请结合 diff 或让 Agent 按 post-change-snapshot 技能补充说明。）

## 修改摘要

{stat}

## 行为变化

（Hook 无法推断业务语义；请结合 diff 或让 Agent 按 post-change-snapshot 技能补充说明。）

## 验证

- [ ] 按需运行 python main.py 或相关治具联调

## 给下次 AI

- 本文件为 post-commit 自动快照；业务背景见同目录下 Agent 撰写的 changelog（文件名通常含具体主题而非 auto-snapshot）。
- 对照提交: `git show {short}`
- 协议与 RV30 实现见 doc/通讯协议.png、doc/ce_mes_iteration/

## diff 摘录

{diff}
"""

    out_dir = root / "doc" / "ai-changelog"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ts_file}_auto-snapshot.md"
    out_path.write_text(body, encoding="utf-8")

    print(f"[post-commit] wrote {out_path.relative_to(root)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[post-commit] skipped: {exc}", file=sys.stderr)
        raise SystemExit(0)
