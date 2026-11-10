"""PRD.md 자물쇠 훅 (PreToolUse, Edit|Write|Bash|PowerShell).

맨 위 폴더의 PRD.md 를 고치거나 새로 쓰려 하면 막고, 경고창을 띄우고,
AI에게 거부 이유를 돌려보낸다. 다른 파일은 그냥 통과시킨다.
Bash/PowerShell 은 PRD.md 가 실제로 쓰기 대상일 때만 막는다
(> 로 PRD.md 에 쓰기, PRD.md 를 지우기/옮기기/덮어쓰기, 코드로 PRD.md 에 쓰기 등).
PRD.md 를 읽기만 하는 명령은 통과 (cat, 2>/dev/null, 다른 파일로 복사 등).
"""
import json
import os
import re
import subprocess
import sys

TITLE = "PRD 자물쇠"
MESSAGE = "기획서는 직접 고쳐 주세요"
REASON = "PRD.md 는 잠겨 있으니 고치지 말고 바꿀 내용을 제안만 하라"

SHELL_TOOLS = ("Bash", "PowerShell")
PRD_IN_COMMAND = re.compile(r"PRD\.md(?![\w.])", re.IGNORECASE)
# 인자 하나가 PRD.md 를 가리키는가 (경로, of=, -Path: 뒤 포함)
PRD_ARG = re.compile(r"(?:^|[/\\=:])PRD\.md$", re.IGNORECASE)
# > 또는 >> 로 PRD.md 에 쓰기 (2>/dev/null 처럼 다른 곳으로 보내는 건 해당 없음)
REDIRECT_TARGET = re.compile(r">>?\|?\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>]+)")
# 이 명령의 인자 중 PRD.md 가 있으면 PRD.md 를 바꾸는 것
CHANGE_CMDS = {
    "rm", "del", "erase", "ri", "remove-item", "unlink", "shred",
    "mv", "move", "mi", "move-item", "ren", "rename", "rni", "rename-item",
    "set-content", "sc", "add-content", "ac", "clear-content", "clc",
    "out-file", "new-item", "ni", "tee", "tee-object", "truncate",
    "ed", "ex", "vi", "vim", "nano", "patch",
}
# 복사는 PRD.md 가 받는 쪽(마지막 인자, -Destination)일 때만 바꾸는 것
COPY_CMDS = {"cp", "copy", "cpi", "copy-item", "install"}
# 코드 안에서 파일에 쓰거나 지우는 표시 (PRD.md 와 함께 있을 때만 막음)
SCRIPT_WRITE = re.compile(
    r"\.write\(|writelines|write_text|write_bytes"
    r"|\bopen\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax+]"
    r"|\bos\.(?:remove|unlink|rename|replace|truncate)\b|\.unlink\(|shutil\.move"
    r"|IO\.File\]::(?:Write|Append|Delete|Move|Replace|Create)"
    r"|WriteAll|AppendAll|AppendText|CreateText"
    r"|\bfs\.(?:write|append|unlink|rm|rename|truncate)",
    re.IGNORECASE,
)
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|\n]")
TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")

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


def is_prd(file_path, cwd):
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    target = os.path.join(project_dir, "PRD.md")
    full = os.path.join(cwd or project_dir, file_path)
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    return norm(full) == norm(target)


def command_name(token):
    name = re.split(r"[/\\]", token.strip("\"'"))[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def segment_writes_prd(segment):
    tokens = [t.strip("\"'") for t in TOKEN.findall(segment)]
    while tokens and (tokens[0] in ("&", ".", "sudo", "command") or re.match(r"^\w+=", tokens[0])):
        tokens = tokens[1:]
    if not tokens:
        return False
    name, args = command_name(tokens[0]), tokens[1:]
    prd_args = [a for a in args if PRD_ARG.search(a)]
    if not prd_args:
        return False
    if name in CHANGE_CMDS:
        return True
    if name == "sed":
        return any(re.match(r"^(?:-[a-zA-Z]*i|--in-place)", a) for a in args)
    if name == "perl":
        return any(re.match(r"^-[a-zA-Z]*i", a) for a in args)
    if name == "dd":
        return any(re.match(r"^of=", a, re.IGNORECASE) for a in prd_args)
    if name in COPY_CMDS:
        for i, a in enumerate(args[:-1]):
            if a.lower() in ("-destination", "-d") and PRD_ARG.search(args[i + 1]):
                return True
        plain = [a for i, a in enumerate(args)
                 if not a.startswith("-") and not (i and args[i - 1].lower() in ("-destination", "-d"))]
        return len(plain) >= 2 and bool(PRD_ARG.search(plain[-1]))
    if name == "git":
        return bool(args) and args[0] in ("checkout", "restore", "rm", "mv", "apply")
    return False


def writes_prd(command):
    if not PRD_IN_COMMAND.search(command):
        return False
    if any(PRD_ARG.search(t.strip("\"'")) for t in REDIRECT_TARGET.findall(command)):
        return True
    if SCRIPT_WRITE.search(command):
        return True
    return any(segment_writes_prd(s) for s in SEGMENT_SPLIT.split(command))


def main():
    if "--popup" in sys.argv:
        show_popup()
        return

    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") in SHELL_TOOLS:
        if not writes_prd(tool_input.get("command") or ""):
            return  # PRD.md 를 쓰지 않는 명령은 그냥 통과
    else:
        file_path = tool_input.get("file_path")
        if not file_path or not is_prd(file_path, data.get("cwd")):
            return  # 다른 파일은 그냥 통과

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
