"""block-lorem 훅 (PreToolUse).

AI가 .html 파일(화면 파일)에 "클릭하세요"를 쓰려 하면
1) 그 동작을 막고  2) 맨 앞에 경고창을 띄우고  3) AI에게 이유를 돌려보낸다.
.html 이 아닌 파일이나 "클릭하세요"가 없는 글자는 아무것도 하지 않고 통과시킨다.
"""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

TITLE = "block-lorem"
MESSAGE = "화면 문구에 '클릭하세요'가 들어 있습니다"
REASON = "화면 문구에 '클릭하세요'를 쓰지 말고 '누르세요'로 고쳐서 다시 써라"
BANNED = "클릭하세요"

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


def new_texts(tool_input):
    """새로 파일에 들어갈 글자만 모은다. Write 는 전체 내용, Edit·MultiEdit 는 바꿔 넣을 글자."""
    texts = [tool_input.get("content"), tool_input.get("new_string")]
    for edit in tool_input.get("edits") or []:
        texts.append(edit.get("new_string"))
    return [t for t in texts if isinstance(t, str)]


def is_hit(tool_input):
    target = tool_input.get("file_path") or ""
    if not target.lower().endswith(".html"):
        return False
    return any(BANNED in text for text in new_texts(tool_input))


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except ValueError:
        return 0

    if not is_hit(data.get("tool_input") or {}):
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
