# 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
"""문화 미션 훅 (PreToolUse, Edit|Write).

data/missions.csv 를 고치거나 새로 쓴 결과에서, 아래 미션이 있으면 막고,
경고창을 띄우고, AI에게 거부 이유를 돌려보낸다.
- culture 열이 없거나 culture 칸이 비어 있는 미션
- 미션 문장(description)에 실제 나라 이름이 없는 미션 — "좋아하는 나라"처럼 아이 취향만 묻는 미션이
  여기에 걸린다. 취향을 묻는 말도 구체적인 나라와 함께면 괜찮다 ("한국어"는 나라 이름으로 치지 않는다)
근거: 솔님 경험 (다문화·세계 문화 — 나라, 전통놀이, 음식, 인사말, 의식주 등 —
미션이 서비스 차별화의 핵심인데 기본 미션만 나왔고, 나와도 "좋아하는 나라의 무엇"처럼
취향을 묻는 데 그쳤다. "베트남의 무슨 놀이, 무슨 음식"처럼 구체적으로 나와야 한다).
다른 파일, 그리고 기준에 맞는 수정은 그냥 통과시킨다.
"""
# CSV(쉼표로 칸을 나눈 표 파일)를 칸 단위로 읽는 도구를 불러온다
import csv
# 글자를 파일처럼 읽게 해 주는 도구를 불러온다
import io
# 훅이 주고받는 JSON(정해진 꼴의 데이터 글)을 다루는 도구를 불러온다
import json
# 파일 경로와 환경 변수를 다루는 도구를 불러온다
import os
# 경고창을 띄울 새 프로그램을 따로 실행하는 도구를 불러온다
import subprocess
# 입력·출력과 실행 인자를 다루는 도구를 불러온다
import sys

# 경고창 제목
TITLE = "문화 미션 지킴"
# 경고창에 보일 문구
MESSAGE = "구체적인 나라 문화가 없는 미션은 넣을 수 없어요"
# 미션 문장에 하나는 들어 있어야 하는 실제 나라 이름 (다문화 아동이 많은 나라 중심)
# 미션 문장에 하나는 있어야 하는 나라 이름 목록 시작
COUNTRIES = [
    # 나라 이름 목록 (1)
    "한국", "베트남", "중국", "일본", "필리핀", "태국", "몽골", "러시아", "우즈베키스탄",
    # 나라 이름 목록 (2)
    "카자흐스탄", "키르기스스탄", "캄보디아", "라오스", "미얀마", "네팔", "인도네시아", "인도",
    # 나라 이름 목록 (3)
    "스리랑카", "방글라데시", "파키스탄", "대만", "미국", "캐나다", "멕시코", "브라질",
    # 나라 이름 목록 (4)
    "프랑스", "독일", "영국", "이탈리아", "스페인", "튀르키예", "터키", "이집트", "케냐",
    # 나라 이름 목록 (5)
    "나이지리아", "호주",
# 목록을 닫는다
]

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


# 고치려는 파일이 검사할 파일인지 가리는 함수
def is_target(file_path, cwd):
    # 프로젝트 폴더: Claude가 알려 준 값, 없으면 이 파일 위치에서 세 칸 위
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        # 이 파일 → hooks → .claude → 프로젝트 폴더 순서로 올라간다
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 괄호를 닫는다
    )
    # 검사할 파일: data/missions.csv
    target = os.path.join(project_dir, "data", "missions.csv")
    # 고치려는 파일의 전체 경로를 만든다
    full = os.path.join(cwd or project_dir, file_path)
    # 경로를 같은 꼴로 맞추는 작은 함수 (대소문자·바로가기 차이를 없앤다)
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    # 두 경로가 같은지와, 검사할 파일 경로를 돌려준다
    return norm(full) == norm(target), target


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


# 기준에 어긋난 미션을 찾는 함수
def find_problems(text):
    # 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
    """기준에 어긋난 미션 목록."""
    # 글을 CSV 표로 읽는다 (맨 앞의 BOM 표시는 뗀다)
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    # 제목이 있는 줄만 미션으로 본다
    rows = [r for r in reader if (r.get("title") or "").strip()]
    # 미션이 있는데 culture 열 자체가 없으면
    if rows and "culture" not in (reader.fieldnames or []):
        # 그 사실 하나만 돌려준다
        return ["culture 열이 없음"]
    # 어긋난 미션을 모을 빈 목록
    bad = []
    # 미션을 하나씩 본다
    for r in rows:
        # 미션 번호와 제목 (예: M01 엄지로 답하기)
        name = f"{r.get('mission_id') or '?'} {r['title'].strip()}"
        # culture 칸 값 (앞뒤 빈칸 뗌)
        culture = (r.get("culture") or "").strip()
        # 미션 문장
        description = r.get("description") or ""
        # culture 칸이 비어 있으면
        if not culture:
            # 비어 있다고 적는다
            bad.append(f"{name}(culture 칸 비어 있음)")
        # 미션 문장에 나라 이름이 하나도 없으면 ('한국어'는 빼고 본다)
        elif not any(c in description.replace("한국어", "") for c in COUNTRIES):
            # 나라 이름이 없다고 적는다
            bad.append(f"{name}(미션 문장에 실제 나라 이름 없음)")
    # 어긋난 미션 목록을 돌려준다 (비어 있으면 문제 없음)
    return bad


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
    # 검사할 파일인지 가린다
    hit, target = is_target(file_path, data.get("cwd"))
    # 검사할 파일이 아니면
    if not hit:
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
    # 고친 뒤 내용을 알 수 없으면
    if after is None:
        # 막지 않고 끝낸다
        return
    # 고친 뒤 내용에서 어긋난 미션을 찾는다
    bad = find_problems(after)
    # 어긋난 미션이 없으면
    if not bad:
        return  # 미션마다 구체적인 나라 문화가 있으면 통과

    # 아래를 시도한다 (실패하면 except 로 간다)
    try:
        # 화면 맨 앞에 경고창을 띄운다
        launch_popup()
    # 어떤 오류가 나도 여기서 받는다
    except Exception:
        pass  # 경고창이 실패해도 막기는 그대로 한다

    # AI에게 돌려보낼 거부 이유를 만든다
    reason = (
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "구체적인 나라 문화가 없는 미션이 있어 막았다: " + ", ".join(bad) + ". "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "미션 문장에 실제 나라 이름과 그 나라의 놀이·음식·인사말 이름을 넣고(예: 베트남 쌀국수 '퍼'), "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "\"좋아하는 나라\"처럼 취향만 묻는 것으로 대신하지 말고, culture 칸도 채워 다시 써라"
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
