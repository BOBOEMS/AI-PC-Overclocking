"""Record the user's new git policy in AGENT.md.

The previous rule was "do not commit or push unless explicitly asked". The user
has replaced it with two distinct rules, which are NOT the same permission:

  commit  - part of normal work. Do it after every round of file changes, without
            waiting to be asked.
  push    - still requires explicit authorisation, every time.

Keeping them as separate rules matters: the old single sentence would now read as
"never commit", and a blanket reading of the new one would authorise pushing
without asking. The workflow also states the verification step, because
`git add -A` succeeding is not evidence that a commit was created.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")
AGENT = ROOT / "AGENT.md"

OLD_RULE = "- 不 `git commit` / `push`，除非用户明确要求。"

NEW_RULES = """- **每一轮文件改动后都要 `git commit`**，不需要等用户开口（2026-10-02 用户明确要求）。
- **`git push` 必须先取得用户当次授权。** 每次推送前单独询问；用户未明确同意就不要推。绝不用 `--force`。
  注意 `artifacts/` 已被忽略（那是刻意的），所以提交内容只含 `src/`、`config/`、`docs/` 等源码与文档。"""

NEW_SECTION = """
### 3.10 Git 工作流（2026-10-02 用户定版）

```powershell
git add -A
git commit -m "<这一轮改了什么，一句话>"
git status --porcelain    # 应为空；非空说明还有没提交的内容
git log -1 --stat         # 确认提交真的建立、且文件范围正确
```

两条规矩分开记，不要混为一谈：

| 动作 | 是否需要用户同意 |
|---|---|
| `git commit` | **不需要** —— 每轮改动后主动做 |
| `git push` | **需要，且是每一次** —— 推送前单独问 |

`git add -A` 返回成功**不等于**提交已建立，所以提交后必须核对 `git status` 与
`git log -1`。推送前至少确认：分支正确、远端正确、没有意外文件混入。
`artifacts/` 被 `.gitignore` 刻意排除，因此提交里不应出现会话证据、任务日志或
BIOS 截图；若出现，先停下查 `.gitignore` 是否被改动。
"""


def main() -> int:
    text = AGENT.read_text(encoding="utf-8")
    original = text

    if OLD_RULE in text:
        text = text.replace(OLD_RULE, NEW_RULES)
        print("replaced the old git rule with the new two-rule policy")
    elif "每一轮文件改动后都要" in text:
        print("git policy already present")
    else:
        print("WARNING: could not find the old rule; inserting into section 2 instead")
        marker = "## 3. 标准流程"
        text = text.replace(marker, NEW_RULES + "\n\n" + marker, 1)

    # Add the workflow section just before the next top-level section after 3.x.
    if "### 3.10 Git 工作流" not in text:
        marker = "## 4."
        if marker in text:
            text = text.replace(marker, NEW_SECTION.strip() + "\n\n" + marker, 1)
            print("added section 3.10 Git workflow")
        else:
            text = text.rstrip() + "\n" + NEW_SECTION
            print("appended section 3.10 Git workflow")

    # Refresh the header timestamp note.
    old_head = "最后更新：2026-10-01"
    if old_head in text:
        text = text.replace(
            old_head,
            "最后更新：2026-10-02（目录重构为 src/ + config/ + artifacts/，路径集中到 paths.py／paths.ps1；"
            "新增 git 提交规则与推送授权规则）\n\n上一版：2026-10-01",
            1)
        print("refreshed the header timestamp")

    if text != original:
        AGENT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
