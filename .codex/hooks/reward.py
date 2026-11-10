# 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
"""미션 보상 훅 (PreToolUse, Edit|Write).

data/missions.csv 를 고치거나 새로 쓴 결과에서, 미션의 difficulty(난이도)와
reward_money(보드게임 속 돈 보상)가 맞지 않으면 막고, 경고창을 띄우고,
AI에게 거부 이유를 돌려보낸다.
근거: 솔님이 정한 기준
- 쉬움 → 5천원 / 보통·적정 → 1만원·2만원·3만원 / 어려움 → 5만원
- 1만원 비율이 가장 높다 (미션이 5개 이상일 때만 검사해, 하나씩 추가하는 도중에는 막지 않는다)
- data/missions.csv 와 app.py 에 '7만원'·'10만원'처럼 글자로 쓴 금액도, 위 기준표에 없으면 막는다
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
# 글자 무늬(정규식)로 글을 찾는 도구를 불러온다
import re
# 경고창을 띄울 새 프로그램을 따로 실행하는 도구를 불러온다
import subprocess
# 입력·출력과 실행 인자를 다루는 도구를 불러온다
import sys

# 경고창 제목
TITLE = "미션 보상 지킴"
# 난이도와 보상이 안 맞을 때 경고창 문구
MESSAGE_MISMATCH = "난이도에 맞지 않는 보상이에요"
# 1만원 미션이 모자랄 때 경고창 문구
MESSAGE_RATIO = "1만원 미션이 가장 많아야 해요"
# 기준표에 없는 금액이 글자로 들어 있을 때 경고창 문구
MESSAGE_AMOUNT = "기준에 없는 보상 금액이에요"
# 7만원·10만원·5천원처럼 '숫자+만/천+원' 으로 쓴 금액을 찾는 글자 무늬
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(천|만)\s*원")
# 난이도마다 받을 수 있는 보상 표 시작
ALLOWED = {
    # 쉬움은 5천원만
    "쉬움": ["5000"],
    # 보통은 1만원·2만원·3만원 중 하나
    "보통": ["10000", "20000", "30000"],
    # 적정도 보통과 같이 1만원·2만원·3만원 중 하나
    "적정": ["10000", "20000", "30000"],
    # 어려움은 5만원만
    "어려움": ["50000"],
# 묶음을 닫는다
}
# 숫자 금액을 '5천원'처럼 읽기 쉬운 말로 바꾸는 표
WON = {"5000": "5천원", "10000": "1만원", "20000": "2만원", "30000": "3만원", "50000": "5만원"}
# 가장 많아야 하는 보상 (1만원)
MAIN_REWARD = "10000"
# 미션이 이 수 이상일 때만 1만원 비율을 검사한다
RATIO_MIN_MISSIONS = 5

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
def show_popup(message):
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
    ctypes.windll.user32.MessageBoxW(None, message, TITLE, flags)


# 경고창을 띄울 새 프로그램을 따로 실행하는 함수
def launch_popup(message):
    # 경고창을 별도 프로세스로 띄워, 훅이 [확인] 클릭을 기다리지 않게 한다
    # 새 프로그램을 이 훅과 떼어 놓는 설정값
    DETACHED_PROCESS = 0x00000008
    # 새 프로그램을 별도 묶음으로 만드는 설정값
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    # 이 파일을 --popup 표시와 함께 새로 실행한다 (끝나기를 기다리지 않는다)
    subprocess.Popen(
        # 실행할 것: 지금 파이썬, 이 파일, --popup 표시, 경고창 문구
        [sys.executable, os.path.abspath(__file__), "--popup", message],
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
    csv_path = os.path.join(project_dir, "data", "missions.csv")
    # 글자 금액만 검사할 파일: app.py
    app_path = os.path.join(project_dir, "app.py")
    # 고치려는 파일의 전체 경로를 만든다
    full = os.path.join(cwd or project_dir, file_path)
    # 경로를 같은 꼴로 맞추는 작은 함수 (대소문자·바로가기 차이를 없앤다)
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.abspath(p)))
    # 두 파일 중 하나와 같으면
    for target in (csv_path, app_path):
        if norm(full) == norm(target):
            # 맞았다는 표시, 그 파일 경로, CSV 인지를 돌려준다
            return True, target, target == csv_path
    # 둘 다 아니면 검사하지 않는다
    return False, None, False


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


# 글자로 쓴 금액 중 기준표에 없는 것을 찾는 함수
def find_stray_amounts(text):
    # 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
    """'7만원' 꼴로 쓴 금액 중 기준표(5천원·1만원·2만원·3만원·5만원)에 없는 것. 없으면 (None, [])."""
    # 빈칸을 빼고 '7만원' 꼴로 맞춘 금액을 모두 모은다
    found = [n + unit + "원" for n, unit in AMOUNT_RE.findall(text)]
    # 기준표에 없는 금액만 겹치지 않게 골라 순서대로 둔다
    stray = sorted({a for a in found if a not in WON.values()})
    # 그런 금액이 있으면
    if stray:
        # 금액 경고 문구와 그 금액들을 돌려준다
        return MESSAGE_AMOUNT, ["기준표에 없는 금액: " + ", ".join(stray)]
    # 문제가 없으면 (None, 빈 목록)을 돌려준다
    return None, []


# 기준에 어긋난 미션을 찾는 함수
def find_problems(text, is_csv=True):
    # 설명 글 (따옴표 세 개 사이는 실행되지 않는 안내문)
    """(경고창 문구, 어긋난 내용 목록). 문제가 없으면 (None, [])."""
    # app.py 처럼 CSV 가 아니면 글자 금액만 본다
    if not is_csv:
        return find_stray_amounts(text)
    # 글을 CSV 표로 읽는다 (맨 앞의 BOM 표시는 뗀다)
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    # 제목이 있는 줄만 미션으로 본다
    missions = [r for r in reader if (r.get("title") or "").strip()]
    # 어긋난 미션을 모을 빈 목록
    bad = []
    # 기준에 맞은 보상 금액을 모을 빈 목록
    rewards = []
    # 미션을 하나씩 본다
    for r in missions:
        # 미션 번호와 제목 (예: M01 엄지로 답하기)
        name = f"{r.get('mission_id') or '?'} {r['title'].strip()}"
        # 난이도 값
        difficulty = (r.get("difficulty") or "").strip()
        # 보상 금액 값 (예: 10000)
        reward = (r.get("reward_money") or "").strip()
        # 난이도가 표에 없는 값이면
        if difficulty not in ALLOWED:
            # 난이도가 잘못됐다고 적는다
            bad.append(f"{name}(난이도 '{difficulty or '없음'}' — 쉬움/보통/적정/어려움 중 하나)")
        # 난이도는 맞는데 보상이 그 난이도 금액이 아니면
        elif reward not in ALLOWED[difficulty]:
            # 그 난이도에 허용된 금액을 / 로 이어 붙인다
            allowed = "/".join(ALLOWED[difficulty])
            # 보상이 안 맞는다고 적는다
            bad.append(f"{name}({difficulty}인데 보상 '{reward or '없음'}' — {allowed} 중 하나)")
        # 둘 다 맞으면
        else:
            # 맞은 보상을 모은다
            rewards.append(reward)
    # 어긋난 미션이 하나라도 있으면
    if bad:
        # 난이도·보상 경고 문구와 어긋난 목록을 돌려준다
        return MESSAGE_MISMATCH, bad

    # 설명·제목 칸 등에 글자로 쓴 금액도 본다
    message, stray = find_stray_amounts(text)
    # 기준표에 없는 금액이 있으면
    if message:
        # 금액 경고 문구와 그 금액들을 돌려준다
        return message, stray

    # 미션이 5개 이상일 때만
    if len(missions) >= RATIO_MIN_MISSIONS:
        # 금액마다 미션이 몇 개인지 센다
        counts = {r: rewards.count(r) for r in set(rewards)}
        # 1만원 미션 수
        main = counts.get(MAIN_REWARD, 0)
        # 1만원보다 많은 다른 금액을 찾는다
        over = [f"{WON[r]} {n}개" for r, n in counts.items() if r != MAIN_REWARD and n > main]
        # 그런 금액이 있으면
        if over:
            # 1만원 비율 경고 문구와 내용을 돌려준다
            return MESSAGE_RATIO, [f"{WON[MAIN_REWARD]} {main}개보다 많은 보상: " + ", ".join(over)]
    # 문제가 없으면 (None, 빈 목록)을 돌려준다
    return None, []


# 훅이 불릴 때 실행되는 본체
def main():
    # 경고창용으로 따로 실행된 경우면
    if "--popup" in sys.argv:
        # 넘겨받은 문구로 경고창만 띄운다
        show_popup(sys.argv[-1])
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
    hit, target, is_csv = is_target(file_path, data.get("cwd"))
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
    # 고친 뒤 내용에서 경고 문구와 어긋난 내용을 받는다
    message, bad = find_problems(after, is_csv)
    # 문제가 없으면
    if not message:
        return  # 보상 기준에 맞으면 통과

    # 아래를 시도한다 (실패하면 except 로 간다)
    try:
        # 그 문구로 화면 맨 앞에 경고창을 띄운다
        launch_popup(message)
    # 어떤 오류가 나도 여기서 받는다
    except Exception:
        pass  # 경고창이 실패해도 막기는 그대로 한다

    # AI에게 돌려보낼 거부 이유를 만든다
    reason = (
        # 경고 문구와 어긋난 내용을 이어 붙인다
        message + " — 막았다: " + "; ".join(bad) + ". "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "보상 기준(쉬움 5000 / 보통·적정 10000·20000·30000 / 어려움 50000, "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "미션 5개 이상이면 10000이 가장 많게)에 맞춰 다시 써라 "
        # 거부 이유 글 이어짐 (따옴표 글은 저절로 이어 붙는다)
        "(CSV 의 reward_money 는 숫자로, 글자로 쓸 때는 5천원·1만원·2만원·3만원·5만원 중 하나로)"
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
