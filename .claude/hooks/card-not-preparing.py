# 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
"""준비물 없는 미션 훅 (PreToolUse, Edit|Write).

data/missions.csv(미션 카드) 또는 app.py(화면·AI 카드 지시문)를 고치거나 새로 쓴 결과에서
"준비물" 글자가 고치기 전보다 늘어나면 막고, 경고창을 띄우고, AI에게 거부 이유를 돌려보낸다.
근거: 솔님 경험 (다른 아이템 없이 게임 규칙만으로 할 수 있는 미션이 나와야 하는데
다른 아이템이 필요한 미션이 나왔다 — 준비물 칸 자체를 두지 않는다).
다른 파일, 그리고 "준비물" 글자를 늘리지 않는 수정은 그냥 통과시킨다.
"""
# 훅이 주고받는 JSON(정해진 꼴의 데이터 글)을 다루는 도구를 불러온다
import json
# 파일 경로와 환경 변수를 다루는 도구를 불러온다
import os
# 경고창을 띄울 새 프로그램을 따로 실행하는 도구를 불러온다
import subprocess
# 입력·출력과 실행 인자를 다루는 도구를 불러온다
import sys

# 경고창 제목
TITLE = "준비물 없는 미션 지킴"
# 경고창에 보일 문구
MESSAGE = "준비물이 필요한 미션은 넣을 수 없어요"
# 세어 볼 글자
MARK = "준비물"
# 검사할 파일 두 개: data/missions.csv 와 app.py
TARGETS = [("data", "missions.csv"), ("app.py",)]

# 윈도 경고창 설정값: [확인] 버튼 하나
MB_OK = 0x0
# 윈도 경고창 설정값: 느낌표 경고 아이콘
MB_ICONWARNING = 0x30
# 윈도 경고창 설정값: 다른 창보다 먼저 응답해야 하는 창
MB_SYSTEMMODAL = 0x1000
# 윈도 경고창 설정값: 창을 앞으로 가져온다
MB_SETFOREGROUND = 0x10000
# 윈도 경고창 설정값: 항상 맨 위에 보인다
MB_TOPMOST = 0x40000


# 경고창을 실제로 띄우는 함수
def show_popup():
    # 윈도 기능을 직접 부르는 도구를 불러온다
    import ctypes
    # 아래를 시도한다 (실패하면 except 로 간다)
    try:
        # 윈도 소리 도구를 불러온다
        import winsound
        # 경고음을 한 번 낸다
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    # 어떤 오류가 나도 여기서 받는다
    except Exception:
        pass  # 소리가 실패해도 경고창은 그대로 띄운다
    # 경고창 설정값을 모두 합친다
    flags = MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST
    # 경고창을 띄운다 (누가 [확인]을 누를 때까지 열려 있다)
    ctypes.windll.user32.MessageBoxW(None, MESSAGE, TITLE, flags)


# 경고창을 띄울 새 프로그램을 따로 실행하는 함수
def launch_popup():
    # 경고창을 별도 프로세스로 띄워, 훅이 [확인] 클릭을 기다리지 않게 한다
    # 새 프로그램을 이 훅과 떼어 놓는 설정값
    DETACHED_PROCESS = 0x00000008
    # 새 프로그램을 별도 묶음으로 만드는 설정값
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    # 이 파일을 --popup 표시와 함께 새로 실행한다 (끝나기를 기다리지 않는다)
    subprocess.Popen(
        # 실행할 것: 지금 파이썬, 이 파일, --popup 표시
        [sys.executable, os.path.abspath(__file__), "--popup"],
        # 위의 두 설정값을 적용한다
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        # 훅이 열어 둔 파일을 새 프로그램에 넘기지 않는다
        close_fds=True,
    # 괄호를 닫는다
    )


# 고치려는 파일이 검사할 파일 중 하나인지 가리는 함수
def find_target(file_path, cwd):
    # 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
    """검사할 파일이면 그 경로를, 아니면 None 을 돌려준다."""
    # 프로젝트 폴더: Claude가 알려 준 값, 없으면 이 파일 위치에서 세 칸 위
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        # 이 파일 → hooks → .claude → 프로젝트 폴더 순서로 올라간다
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 괄호를 닫는다
    )
    # 고치려는 파일의 전체 경로를 만든다
    full = os.path.join(cwd or project_dir, file_path)
    # 경로를 같은 꼴로 맞추는 작은 함수 (대소문자·바로가기 차이를 없앤다)
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    # 검사할 파일을 하나씩 본다
    for parts in TARGETS:
        # 검사할 파일의 전체 경로를 만든다
        target = os.path.join(project_dir, *parts)
        # 고치려는 파일과 같으면
        if norm(full) == norm(target):
            # 그 파일 경로를 돌려준다
            return target
    # 어느 것도 아니면 None(없음)을 돌려준다
    return None


# 수정이 끝난 뒤 파일 내용이 어떻게 될지 미리 만들어 보는 함수
def result_after(tool_name, tool_input, current):
    # 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
    """수정이 적용된 뒤의 파일 내용을 돌려준다. 알 수 없으면 None."""
    # 파일 전체를 새로 쓰는 경우면
    if tool_name == "Write":
        # 새로 쓸 내용이 곧 결과다
        return tool_input.get("content") or ""
    # 바꿀 원래 글
    old = tool_input.get("old_string")
    # 바꿔 넣을 새 글
    new = tool_input.get("new_string") or ""
    # 원래 글이 비었거나 지금 파일에 없으면
    if not old or old not in current:
        return None  # Edit 자체가 실패할 수정이라 판단하지 않는다
    # '모두 바꾸기'면
    if tool_input.get("replace_all"):
        # 파일 안의 원래 글을 전부 바꾼 결과를 돌려준다
        return current.replace(old, new)
    # 아니면 처음 한 곳만 바꾼 결과를 돌려준다
    return current.replace(old, new, 1)


# 훅이 불릴 때 실행되는 본체
def main():
    # 경고창용으로 따로 실행된 경우면
    if "--popup" in sys.argv:
        # 경고창만 띄운다
        show_popup()
        # 경고창만 띄우고 끝낸다
        return

    # Claude가 보낸 도구 사용 정보(JSON)를 읽는다
    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    # 쓰려는 도구 이름 (Edit, Write 등)
    tool_name = data.get("tool_name")
    # 도구에 넘긴 값들
    tool_input = data.get("tool_input") or {}
    # 고치려는 파일 경로
    file_path = tool_input.get("file_path")
    # Edit/Write 가 아니거나 파일 경로가 없으면
    if tool_name not in ("Edit", "Write") or not file_path:
        # 할 일 없이 끝낸다 (막지 않음)
        return
    # 검사할 파일이면 그 경로를 받는다
    target = find_target(file_path, data.get("cwd"))
    # 검사할 파일이 아니면
    if not target:
        return  # 다른 파일은 그냥 통과

    # 아래를 시도한다 (실패하면 except 로 간다)
    try:
        # 지금 파일을 연다
        with open(target, encoding="utf-8") as f:
            # 고치기 전 내용을 읽는다
            current = f.read()
    # 파일이 아직 없거나 못 열면
    except OSError:
        # 고치기 전 내용은 빈 글로 본다
        current = ""

    # 고친 뒤 내용을 미리 만들어 본다
    after = result_after(tool_name, tool_input, current)
    # 알 수 없거나, '준비물' 글자가 고치기 전보다 늘지 않았으면
    if after is None or after.count(MARK) <= current.count(MARK):
        return  # "준비물" 글자가 늘지 않는 수정은 통과

    # 아래를 시도한다 (실패하면 except 로 간다)
    try:
        # 화면 맨 앞에 경고창을 띄운다
        launch_popup()
    # 어떤 오류가 나도 여기서 받는다
    except Exception:
        pass  # 경고창이 실패해도 막기는 그대로 한다

    # AI에게 돌려보낼 거부 이유를 만든다
    reason = (
        # 어느 파일인지와 거부 이유 글을 이어 붙인다
        os.path.basename(target) + " 에 \"" + MARK + "\" 글자를 새로 넣는 수정이라 막았다. "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "미션은 다른 물건 없이 게임 규칙만으로 할 수 있어야 하니, 준비물 칸을 빼고 다시 써라"
    # 괄호를 닫는다
    )
    # Claude에게 돌려줄 '막기' 답을 만든다
    out = {
        # 훅 전용 답 칸
        "hookSpecificOutput": {
            # 도구를 쓰기 직전(PreToolUse) 훅이라는 표시
            "hookEventName": "PreToolUse",
            # 이 도구 사용을 막는다(deny)
            "permissionDecision": "deny",
            # 막은 이유 (AI가 읽고 다시 고친다)
            "permissionDecisionReason": reason,
        # 묶음을 닫는다
        }
    # 묶음을 닫는다
    }
    # 답을 JSON 글로 내보낸다 — Claude가 이것을 보고 막는다
    sys.stdout.write(json.dumps(out))


# 이 파일을 직접 실행했을 때만
if __name__ == "__main__":
    # 본체를 실행한다
    main()
