"""PRD.md 자물쇠 훅 (PreToolUse).

AI가 이 폴더 맨 위의 PRD.md 를 고치거나 새로 쓰려 하면
1) 그 동작을 막고  2) 맨 앞에 경고창을 띄우고  3) AI에게 이유를 돌려보낸다.
PRD.md 가 아닌 파일은 아무것도 하지 않고 통과시킨다.
"""
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

TITLE = "PRD 자물쇠"
MESSAGE = "PRD.md 는 잠겨 있습니다"
REASON = "PRD.md 는 잠겨 있으니 고치지 말고 바꿀 내용을 제안만 하라"

# MessageBoxW 옵션: 경고 아이콘 | 시스템 모달 | 앞으로 가져오기 | 항상 맨 앞
MB_ICONWARNING = 0x30
MB_SYSTEMMODAL = 0x1000
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000


def show_popup():
    ctypes.windll.user32.MessageBoxW(
        None, MESSAGE, TITLE,
        MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST,
    )


def launch_popup():
    """경고창을 별도 프로세스로 띄워, 확인을 누르기 전에도 훅이 바로 끝나게 한다."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), str(Path(__file__).resolve()), "--popup"],
                     creationflags=flags, close_fds=True)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except ValueError:
        return 0

    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path(__file__).resolve().parents[2])
    base = data.get("cwd") or project_dir
    target_path = os.path.normcase(os.path.abspath(os.path.join(base, target)))
    prd_path = os.path.normcase(os.path.abspath(os.path.join(project_dir, "PRD.md")))
    if target_path != prd_path:
        return 0

    try:
        launch_popup()
    except Exception:
        pass  # 경고창이 실패해도 차단은 그대로 한다

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }))
    return 0


if __name__ == "__main__":
    if "--popup" in sys.argv:
        show_popup()
    else:
        sys.exit(main())
