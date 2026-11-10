"""미션 횟수 훅 (PreToolUse, Edit|Write).

webapp/index.html 을 고치거나 새로 쓴 결과에서 화면 1-1 의
"미션 N회" 표시 글자가 사라지면 막고, 경고창을 띄우고,
AI에게 거부 이유를 돌려보낸다.
근거: .claude/rules/screen.md 첫째 줄
(화면 1-1 목록에는 아동 이름 옆에 "미션 N회" 참여 횟수를 함께 적는다).
다른 파일, 그리고 그 글자를 그대로 두는 수정은 그냥 통과시킨다.
"""
import json
import os
import subprocess
import sys

TITLE = "미션 횟수 지킴"
MESSAGE = "화면 1-1 '미션 N회' 표시는 지울 수 없어요"
MARK = "미션 ${missionCount[name]}회"
REASON = (
    "webapp/index.html 의 화면 1-1 \"미션 N회\" 표시(" + MARK + ")를 지우는 수정이라 막았다. "
    ".claude/rules/screen.md 에 따라 이 글자는 남겨 두고 다시 고쳐라"
)

MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_SYSTEMMODAL = 0x1000
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000


def show_popup():
    import ctypes
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass  # 소리가 실패해도 경고창은 그대로 띄운다
    flags = MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST
    ctypes.windll.user32.MessageBoxW(None, MESSAGE, TITLE, flags)


def launch_popup():
    # 경고창을 별도 프로세스로 띄워, 훅이 [확인] 클릭을 기다리지 않게 한다
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--popup"],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def is_target(file_path, cwd):
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    target = os.path.join(project_dir, "webapp", "index.html")
    full = os.path.join(cwd or project_dir, file_path)
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    return norm(full) == norm(target), target


def result_after(tool_name, tool_input, current):
    """수정이 적용된 뒤의 파일 내용을 돌려준다. 알 수 없으면 None."""
    if tool_name == "Write":
        return tool_input.get("content") or ""
    old = tool_input.get("old_string")
    new = tool_input.get("new_string") or ""
    if not old or old not in current:
        return None  # Edit 자체가 실패할 수정이라 판단하지 않는다
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def main():
    if "--popup" in sys.argv:
        show_popup()
        return

    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if tool_name not in ("Edit", "Write") or not file_path:
        return
    hit, target = is_target(file_path, data.get("cwd"))
    if not hit:
        return  # 다른 파일은 그냥 통과

    try:
        with open(target, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = ""
    if MARK not in current:
        return  # 원래 없던 글자는 지킬 것이 없으니 통과

    after = result_after(tool_name, tool_input, current)
    if after is None or MARK in after:
        return  # 글자가 그대로 남는 수정은 통과

    try:
        launch_popup()
    except Exception:
        pass  # 경고창이 실패해도 막기는 그대로 한다

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
