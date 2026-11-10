import base64
import html
import json
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client

# data 폴더의 아동 명단·미션 카드 — 어느 폴더에서 실행해도 이 파일 옆 data 폴더를 찾는다
DATA_DIR = Path(__file__).parent / "data"
# .env 의 Supabase 주소와 키를 읽는다 — 이 파일 옆 .env 를 찾는다
load_dotenv(Path(__file__).parent / ".env")
# 반응 기록이 쌓이는 Supabase 표 이름
TABLE = "reactions"
# 링키 챗봇 [서비스 문의]에서 물은 말과 받은 답이 쌓이는 Supabase 표 이름
CHAT_TABLE = "chat_logs"
# AI 미션 카드를 만들 때마다 미션 종류와 문화 요소가 쌓이는 Supabase 표 이름
AI_LOG_TABLE = "ai_missions"
# 피날레 한 바퀴 릴레이(칭찬 카드 교환) 기록이 쌓이는 Supabase 표 이름
FINALE_TABLE = "finale_passes"
# 화면 2·2-1 [스킵] 칩 → reactions 표 skip_reason 값 (미션을 못 한 이유, 단순 미수행 기록)
SKIP_REASONS = {"시간초과": "timeout", "룰 미숙지": "rule_unfamiliar", "단순패스": "flow_pass"}
SKIP_LABELS = {code: label for label, code in SKIP_REASONS.items()}
# 대화창 아래 [지난 대화 목록]에 보여 줄 최근 대화 수
CHAT_HISTORY_LIMIT = 20
# 저장 시각은 세계 표준시라 한국 시각으로 바꿔 보여 준다
KST = timezone(timedelta(hours=9))
# AI 퀘스트 카드와 링키 챗봇이 쓰는 Gemini 모델 — 공식 모델 문서(ai.google.dev/gemini-api/docs/models)가 새 프로젝트에 권하는 안정판
# gemini-3.8-flash 는 요청이 몰려 47초 기다린 뒤 503 을 돌려줘서, 바로 답하는 이 모델을 쓴다
AI_MODEL = "gemini-3.5-flash-lite"
# 게임 한 판에 만들 수 있는 AI 미션 카드 수
AI_CARD_LIMIT = 5
# 멘토 한 명이 하루에 챗봇 [서비스 문의]로 물어볼 수 있는 횟수
CHAT_LIMIT = 10


def gemini():
    # 키는 .env 의 GEMINI_API_KEY 환경변수에서 알아서 읽는다
    # 하루 사용 한도에 걸리면 몇 분씩 조용히 다시 시도하느라 화면이 멈춰 보이므로, 한 번만 시도하고 바로 오류를 알린다
    return genai.Client(http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))

st.set_page_config(page_title="짝꿍 카드 미션 초안")

# 이번 MVP는 모바일용 — 컴퓨터 브라우저에서 열어도 휴대폰 세로 화면 폭으로 보이게 한다 (웹용 화면은 추후 따로 제작)
st.markdown(
    """
    <style>
    .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 420px;
        padding-left: 16px;
        padding-right: 16px;
    }
    /* 한 줄에 다 안 들어가는 글은 단어 중간이 아니라 띄어쓰기에서 줄을 바꾼다 */
    body, [data-testid="stMarkdownContainer"] {
        word-break: keep-all;
    }
    /* 화면 2·2-1 제목 줄 — 휴대폰 폭에서도 [스킵] 버튼이 제목 오른쪽 위에 붙어 있게 칸을 쌓지 않는다 */
    .st-key-mission_header [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
    }
    .st-key-mission_header [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    /* 상담 챗봇 링키 아이콘 — 스크롤해도 화면 오른쪽 아래에 떠 있는 동그란 버튼 (링키 그림은 아래에서 따로 깐다) */
    .st-key-chatbot {
        position: fixed;
        right: 20px;
        bottom: 20px;
        width: auto;
        z-index: 1000;
    }
    /* 아이콘 버튼만 꾸민다 — 대화창 안의 버튼은 그대로 둔다 */
    .st-key-chatbot [data-testid="stPopoverButton"] {
        width: 60px;
        height: 60px;
        border-radius: 50%;
        border: none;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    /* 아이콘 옆의 펼침 화살표는 숨긴다 */
    .st-key-chatbot [data-testid="stPopoverButton"] svg {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 챗봇 링키 그림 — 오른쪽 아래 아이콘 버튼의 배경과 대화창의 링키 얼굴에 쓴다
LINKY_ICON = Path(__file__).parent / "assets" / "linky.png"
linky_b64 = base64.b64encode(LINKY_ICON.read_bytes()).decode()
st.markdown(
    "<style>.st-key-chatbot [data-testid='stPopoverButton'] {"
    f"background: url(data:image/png;base64,{linky_b64}) center / cover no-repeat !important;"
    # 버튼 글자('링키')는 화면 읽기 도구용으로만 두고 보이지 않게 한다
    "color: transparent !important;}</style>",
    unsafe_allow_html=True,
)


@st.cache_data
def load_data():
    # 빈 칸은 NaN이 아니라 빈 글자("")로 읽는다
    def read(name):
        return pd.read_csv(DATA_DIR / name, encoding="utf-8", dtype=str, keep_default_na=False)

    children = read("children.csv")
    missions = read("missions.csv")
    # 성향별 코칭 문구 — 화면 2-1 행동 지침 02(망설일 때)·03(끝난 뒤 살펴볼 것)에 쓴다
    tips = read("coaching_tips.csv")
    return children, missions, tips


children_df, missions_df, tips_df = load_data()
# 성향 → {"hesitate": 망설일 때 문구, "observe": 끝난 뒤 살펴볼 것} — 성향이 비어 있는 아이는 "(성향 없음)" 줄을 쓴다
COACHING_TIPS = {row["trait"]: row for row in tips_df.to_dict("records")}
NO_TRAIT = "(성향 없음)"


@st.cache_resource
def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
        st.stop()
    return create_client(url, key)


client = get_client()

# 아동 이름 ↔ child_id — Supabase에는 실명 대신 child_id만 저장한다
NAME_TO_ID = dict(zip(children_df["name"], children_df["child_id"]))
MISSION_TITLE = dict(zip(missions_df["mission_id"], missions_df["title"]))

# 아동 이름 → 성향 / 기피 특성 (성향이 비어 있는 아동은 "성향 데이터 없음")
CHILD_INFO = {
    row["name"]: {
        "traits": [t for t in row["traits"].split("|") if t],
        "avoid": row["avoid"],
    }
    for _, row in children_df.iterrows()
}

# 성향 데이터가 없는 아동에게 주는 보편적 아이스브레이킹 미션
ICEBREAK = missions_df[missions_df["mission_id"] == "M00"].iloc[0].to_dict()
MISSIONS = [m for m in missions_df.to_dict("records") if m["mission_id"] != "M00"]

# 지금 보고 있는 화면: "s1"(화면 1), "s1_1"(화면 1-1), "s2"(화면 2), "s2_1"(화면 2-1), "s3"(화면 3)
if "screen" not in st.session_state:
    st.session_state.screen = "s1"
# 화면 위에 떠 있는 팝업: None, "p1"(팝업 1 — 이름 확인), "p2"(팝업 2 — 또래관계 체크 안내)
if "popup" not in st.session_state:
    st.session_state.popup = None
# 아동 명단 — children.csv에서 시작한다. 아래 기록은 모두 브라우저 메모리에만 있다 (새로고침하면 초기화)
# 반응 기록만 Supabase reactions 표에 저장되어 새로고침해도 남는다
if "children" not in st.session_state:
    st.session_state.children = list(children_df["name"])
# [+ 이름 추가]로 넣은 아동의 임시 child_id — N01, N02 … (children.csv에 없는 아동)
if "new_ids" not in st.session_state:
    st.session_state.new_ids = {}
# 이번 게임의 미션 횟수 — 화면 1-1의 "미션 N회"이자 매칭 기준. 0회에서 시작하고 [게임 끝내기]를 누르면 다시 0회
if "mission_count" not in st.session_state:
    st.session_state.mission_count = {}
# 아동 프로필의 누적 미션 횟수 — children.csv에서 시작해 [게임 끝내기] 때마다 이번 게임 횟수를 더한다 (화면에는 보이지 않음)
if "profile_count" not in st.session_state:
    st.session_state.profile_count = {
        row["name"]: int(row["mission_count"] or 0) for _, row in children_df.iterrows()
    }
# 이번 게임에서 이미 한 미션 번호 — 같은 미션이 되풀이되지 않게 한다. [게임 끝내기]를 누르면 비운다
# 몇 번째 게임(회차)인지 — Supabase에 저장된 가장 큰 회차의 다음 번호에서 시작하고,
# [게임 끝내기]를 누를 때마다 1 늘어난다
if "game_no" not in st.session_state:
    try:
        last = client.table(TABLE).select("game_no").order("game_no", desc=True).limit(1).execute().data
        st.session_state.game_no = int(last[0]["game_no"] or 0) + 1 if last else 1
    except Exception:
        st.session_state.game_no = 1
if "used_missions" not in st.session_state:
    st.session_state.used_missions = set()
# 오늘 게임 판(game_no)별 AI 미션 카드를 만든 횟수 — 한 판에 AI_CARD_LIMIT번까지 (토큰 비용이 큰 Gemini 호출을 줄인다)
# [게임 끝내기]로 다음 판이 되거나 날짜가 바뀌면 다시 센다. 브라우저 메모리에만 있어 새로고침하면 초기화
if "ai_card_count" not in st.session_state:
    st.session_state.ai_card_count = {}
# 횟수를 센 날짜 — ai_card_count 와 따로 만들어, 앱을 켠 채 코드가 바뀌어도 빠지지 않게 한다
if "ai_card_day" not in st.session_state:
    st.session_state.ai_card_day = None
# 오늘 챗봇 [서비스 문의]에 물어본 횟수 — 멘토 한 명당 하루 CHAT_LIMIT번까지 (토큰 비용을 줄인다)
# 날짜가 바뀌면 다시 센다. 로그인이 없어 이 브라우저를 쓰는 멘토 한 명으로 보고, 새로고침하면 초기화
if "chat_count" not in st.session_state:
    st.session_state.chat_count = {"day": None, "count": 0}

# 다른 화면으로 갔다 와도 체크 상태와 나라·기타 칸이 유지되도록 값을 붙잡아 둔다
for key in list(st.session_state.keys()):
    if key.startswith(("s1_pick_", "s1_1_pick_", "ai_pick_", "ai_extra", "ai_country")):
        st.session_state[key] = st.session_state[key]


def go(screen):
    st.session_state.screen = screen
    st.session_state.popup = None


def open_popup(popup):
    st.session_state.popup = popup


def clear_picks(prefix):
    # [전체 해제] — 이 화면의 이름 체크를 한꺼번에 모두 푼다
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state[key] = False


def picked(prefix, names):
    return [n for n in names if st.session_state.get(f"{prefix}{n}")]


def traits_of(name):
    return CHILD_INFO.get(name, {}).get("traits", [])


def count_of(name):
    return st.session_state.mission_count.get(name, 0)


def id_of(name):
    # children.csv의 child_id — 없으면 [+ 이름 추가]로 넣은 아동이라 임시 번호를 붙인다
    if name in NAME_TO_ID:
        return NAME_TO_ID[name]
    new_ids = st.session_state.new_ids
    if name not in new_ids:
        new_ids[name] = f"N{len(new_ids) + 1:02d}"
    return new_ids[name]


def name_of(child_id):
    # 내려받는 기록 파일에서 child_id를 이름으로 바꿔 보여 준다 (모르는 번호는 번호 그대로)
    names = {v: k for k, v in NAME_TO_ID.items()}
    names.update({v: k for k, v in st.session_state.new_ids.items()})
    return names.get(child_id, child_id)


# ---------- 매칭 ----------

# 팀으로 도착했을 때 개인 미션이 나올 확률 (나머지는 팀 미션)
SOLO_RATE_FOR_TEAM = 0.1

def weighted_sample(pool, k):
    # 미션 횟수가 적은 아동일수록 잘 뽑히게 한다 (이 기준은 멘토 화면에 안내하지 않는다)
    pool = list(pool)
    chosen = []
    for _ in range(k):
        weights = [1 / (count_of(n) + 1) for n in pool]
        pick = random.choices(pool, weights=weights)[0]
        chosen.append(pick)
        pool.remove(pick)
    return chosen


def fits(mission, k, pool_size):
    # 도착 아동 k명 + 합류·상대로 뽑을 수 있는 아동 pool_size명으로 이 미션을 꾸릴 수 있으면
    # 상대·합류 인원 수를 돌려주고, 못 꾸리면 None
    kind, ratio = mission["mission_type"], mission["ratio"]
    if kind == "개인":
        return 0 if ratio == "1" else None
    if kind == "합동(도착 팀)":
        if not ratio.isdigit():
            return None
        n = int(ratio)
        return 0 if (n == 0 and k >= 2) or n == k else None
    if kind == "합동(합류)":
        if not ratio.isdigit():
            return None
        need = int(ratio) - k
        return need if 1 <= need <= pool_size else None
    if kind == "경쟁":
        # 도착 팀은 한 편으로만 묶는다 — 도착 팀이 a편이든 b편이든 상대 편 인원만 뽑는다
        m = re.fullmatch(r"([1-3]):([1-3])", ratio)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        for mine, other in ((a, b), (b, a)):
            if mine == k and other <= pool_size:
                return other
    return None


def make_matchup(arrived, today, exclude=(), prefer_easy=False):
    # exclude — 방금 스킵한 미션처럼 이번에는 빼고 고를 미션 번호
    # prefer_easy — [룰 미숙지]로 스킵했을 때 쉬움 미션을 먼저 고른다
    pool = [n for n in today if n not in arrived]

    # 성향 데이터가 없는 아동이 있으면 보편적 아이스브레이킹 미션
    no_trait = [n for n in arrived if not traits_of(n)]
    if no_trait:
        return {"mission": ICEBREAK, "team_a": [no_trait[0]], "team_b": [], "label": "1"}

    candidates = [(m, need) for m in MISSIONS if (need := fits(m, len(arrived), len(pool))) is not None]
    # 팀으로 도착하면 팀 미션(합동·경쟁)을 우선 — 개인 미션은 가끔(SOLO_RATE_FOR_TEAM)만 나온다
    if len(arrived) >= 2:
        team_cands = [c for c in candidates if c[0]["mission_type"] != "개인"]
        solo_cands = [c for c in candidates if c[0]["mission_type"] == "개인"]
        if team_cands and (not solo_cands or random.random() >= SOLO_RATE_FOR_TEAM):
            candidates = team_cands
        else:
            candidates = solo_cands
    # 이번 게임에서 이미 한 미션은 빼고 고른다 — 남은 미션이 없을 때만 다시 나온다
    used = st.session_state.used_missions
    candidates = [c for c in candidates if c[0]["mission_id"] not in used] or candidates
    candidates = [c for c in candidates if c[0]["mission_id"] not in exclude] or candidates
    if prefer_easy:
        candidates = [c for c in candidates if c[0]["difficulty"] == "쉬움"] or candidates
    arrived_traits = {t for n in arrived for t in traits_of(n)}
    matched = [(m, need) for m, need in candidates if m["target_trait"] in arrived_traits]
    mission, need = random.choice(matched or candidates)

    if mission["mission_type"] == "개인":
        # 도착 아동 중 한 명만 참여 — 미션 성향과 맞는 아동 중 미션 횟수가 가장 적은 아동을 지정한다
        fit = [n for n in arrived if mission["target_trait"] in traits_of(n)] or list(arrived)
        fewest = min(count_of(n) for n in fit)
        team_a = [random.choice([n for n in fit if count_of(n) == fewest])]
    else:
        team_a = list(arrived)
    team_b = weighted_sample(pool, need)

    if mission["mission_type"] == "경쟁":
        label = f"{len(team_a)}:{len(team_b)}"
    elif team_b:
        label = f"{len(team_a)}+{len(team_b)}"
    else:
        label = str(len(team_a))
    return {"mission": mission, "team_a": team_a, "team_b": team_b, "label": label}


def start_mission(arrived, today):
    st.session_state.arrived = arrived
    # 오늘 참여 아동 — [스킵] 뒤 같은 아이들에게 다른 미션을 다시 고를 때 쓴다
    st.session_state.today = today
    # 새 미션이 정해지면 지난 미션의 AI 미션 카드도 함께 사라진다 (AI 카드는 matchup 안에 들어 있다)
    set_mission(make_matchup(arrived, today))
    go("s2")


def set_mission(matchup):
    # 미션 카드를 화면에 띄운다 — 띄운 시각을 적어 두고, [스킵]까지 걸린 초(response_latency)를 센다
    st.session_state.matchup = matchup
    st.session_state.mission_started_at = time.time()


st.caption("반응 기록은 Supabase에 저장됩니다.")

st.title("짝꿍 미션 카드")

# 왼쪽 사이드바 — 이 서비스가 무엇을 해 주는지 한 줄 소개 (PRD 한 줄 정의·목표 참고)
st.sidebar.write("아이 성향에 맞는 짝꿍 미션과 코칭 가이드를 바로 보여 주고, 미션 직후 1초 피드백으로 다음 미션에 반영해 주는 멘토용 서비스입니다.")


def screen_1():
    # 화면 1 — 참여 아동 전체 선택
    st.subheader("참여 아동 전체 선택")
    st.caption("1 / 2")

    # 넣는 자리
    st.write("오늘 같이 게임하는 아동을 모두 선택하세요.  \n(다중 선택)")
    children = st.session_state.children
    any_checked = bool(picked("s1_pick_", children))
    st.button("전체 해제", disabled=not any_checked, on_click=clear_picks, args=("s1_pick_",))
    cols = st.columns(2)
    for i, name in enumerate(children):
        cols[i % 2].checkbox(name, key=f"s1_pick_{name}")
    selected = picked("s1_pick_", children)

    # 새로운 아동 이름 추가 — 마지막 아동 옆 칸의 [+ 이름 추가]를 누르면 입력칸이 열리고,
    # 추가한 이름은 목록에 체크박스로 나타나 바로 선택할 수 있다 (성향 데이터가 없는 아동으로 취급)
    add_cell = cols[len(children) % 2]
    if not st.session_state.get("adding_child"):
        if add_cell.button("+ 이름 추가", use_container_width=True):
            st.session_state.adding_child = True
            st.rerun()
    else:
        with add_cell.form("add_child", border=False):
            new_name = st.text_input(
                "새로운 아동 이름", placeholder="이름을 입력하세요", label_visibility="collapsed"
            )
            ok_col, cancel_col = st.columns(2)
            added = ok_col.form_submit_button("추가", type="primary", use_container_width=True)
            canceled = cancel_col.form_submit_button("취소", use_container_width=True)
            if canceled:
                st.session_state.adding_child = False
                st.rerun()
            if added:
                new_name = new_name.strip()
                if not new_name:
                    st.error("이름을 입력해 주세요.")
                elif new_name in children:
                    st.error(f"'{new_name}'은(는) 이미 목록에 있습니다.")
                else:
                    children.append(new_name)
                    st.session_state.mission_count[new_name] = 0
                    st.session_state.adding_child = False
                    st.rerun()

    st.write(f"**{len(selected)}명 선택됨**")

    # 버튼 (1명 이하 선택 시 비활성)
    st.button(
        "다음", type="primary", use_container_width=True, disabled=len(selected) <= 1,
        on_click=go, args=("s1_card",),
    )


def screen_1_card():
    # 화면 1 → 화면 1-1 사이 — 피날레 때 나눠 줄 칭찬 카드를 미리 쓰게 하는 안내
    st.button("← 뒤로", on_click=go, args=("s1",), key="card_back")
    st.subheader("친구에게 줄 칭찬 카드")
    with st.container(border=True):
        st.markdown(by_sentence(
            "유코마블의 무지 카드에 친구를 위한 그림과 칭찬 한 줄을 작성해요. "
            "게임 마지막 라운드에 나눠 줄 거예요."
        ))
        st.caption("모든 카드의 게임 내 보상은 유코 화폐 1만원으로 통일합니다.")
    st.button("다음", type="primary", use_container_width=True, on_click=go, args=("s1_1",), key="card_next")


def start_finale():
    # [게임 끝내기] 뒤 피날레 — 오늘 참여한 아이들을 무작위로 한 줄로 세워, 앞 아이가 다음 아이에게
    # (마지막 아이는 첫 아이에게) 칭찬 카드를 주는 한 바퀴 릴레이를 만든다. 누구나 1장 주고 1장 받는다
    # 순서는 모두 같은 확률로 나오고, 릴레이가 뜬 때부터 [전원 릴레이 교환 완료]까지 초를 잰다
    order = list(st.session_state.get("today") or picked("s1_pick_", st.session_state.children))
    random.shuffle(order)
    st.session_state.finale = {
        "game_no": st.session_state.game_no,
        "order": order,
        "started_at": time.time(),
    }
    st.session_state.finale_memo_open = False
    st.session_state.finale_error = None


def finish_finale(save=True):
    # [전원 릴레이 교환 완료] — Supabase finale_passes 표에 한 줄 남기고 화면 1로 간다
    # 머뭇거린 아이는 [멘토 메모]에서 체크한 아이만 (아무도 없으면 빈 목록). 실명 대신 아동 번호로 저장한다
    fin = st.session_state.finale
    if save:
        hesitant = [n for n in fin["order"] if st.session_state.get(f"fin_hes_{n}")]
        row = {
            "game_no": fin["game_no"],
            "child_count": len(fin["order"]),
            "relay_order": [id_of(n) for n in fin["order"]],
            "hesitant_ids": [id_of(n) for n in hesitant],
            "exchange_latency": round(time.time() - fin["started_at"], 1),
        }
        try:
            client.table(FINALE_TABLE).insert(row).execute()
        except Exception as e:
            if "PGRST205" in str(e) or FINALE_TABLE in str(e):
                # 표가 아직 없으면 기다려도 안 되니, 표를 만들라고 알려 준다
                st.session_state.finale_error = "Supabase 에 피날레 기록 표가 아직 없어요.  \n표를 만든 뒤 다시 눌러 주세요."
            else:
                st.session_state.finale_error = "피날레 기록을 저장하지 못했어요.  \n잠시 뒤 다시 눌러 주세요."
            return
    for n in fin["order"]:
        st.session_state.pop(f"fin_hes_{n}", None)
    st.session_state.finale = None
    st.session_state.finale_error = None
    go("s1")


def toggle_finale_memo():
    st.session_state.finale_memo_open = not st.session_state.get("finale_memo_open", False)


def screen_finale():
    # 피날레 화면 — 다른 화면과 같은 모양에 릴레이 순서만 크게, 완료 버튼을 가장 크게
    # 머뭇거림 체크는 아이들이 화면을 볼 수 있어 처음에는 접어 두고 [멘토 메모]를 눌렀을 때만 펼친다
    fin = st.session_state.finale
    order = fin["order"]
    pic_col, text_col = st.columns([1, 4], vertical_alignment="center")
    pic_col.image(str(LINKY_ICON), width=56)
    text_col.subheader("오늘의 피날레 방향은?")
    st.caption("친구에게 칭찬 카드를 건네며 카드에 적은 칭찬을 말해 줘요.")
    with st.container(border=True):
        for giver, receiver in zip(order, order[1:] + order[:1]):
            st.markdown(
                f"<div style='font-size:1.35rem;font-weight:700;padding:2px 0'>{html.escape(giver)} → {html.escape(receiver)}</div>",
                unsafe_allow_html=True,
            )
    if st.session_state.get("finale_error"):
        st.error(st.session_state.finale_error)
        st.button("기록 없이 처음 화면으로", use_container_width=True, on_click=finish_finale, args=(False,))
    st.button("전원 릴레이 교환 완료", type="primary", use_container_width=True, on_click=finish_finale)
    st.button("멘토 메모", type="tertiary", on_click=toggle_finale_memo, key="finale_memo")
    if st.session_state.get("finale_memo_open"):
        st.caption("머뭇거리거나 건네기 어려워한 아동만 체크하세요 (여러 명 가능).")
        for col, n in zip(st.columns(3) * len(order), order):
            col.checkbox(n, key=f"fin_hes_{n}")


def screen_1_1():
    # 화면 1-1 — 미션칸 도착 아동 선택 (화면 1에서 고른 아동만 보인다)
    st.button("← 뒤로", on_click=go, args=("s1",))
    st.subheader("미션칸 도착 아동 선택")
    st.caption("2 / 2")

    # 넣는 자리
    st.write("미션 칸에 도착한 아동을 선택하세요.  \n팀으로 도착했다면 여러 명을 함께 선택합니다.  \n(다중 선택)")
    today = picked("s1_pick_", st.session_state.children)
    any_checked = bool(picked("s1_1_pick_", today))
    st.button("전체 해제", key="s1_1_clear", disabled=not any_checked, on_click=clear_picks, args=("s1_1_pick_",))
    for name in today:
        name_col, count_col = st.columns([4, 1])
        name_col.checkbox(name, key=f"s1_1_pick_{name}")
        count_col.caption(f"미션 {count_of(name)}회")
    selected = picked("s1_1_pick_", today)

    kind = "개인 도착" if len(selected) == 1 else "팀 도착"
    st.write(f"**{len(selected)}명 선택됨 · {kind}**" if selected else "**0명 선택됨**")
    st.caption("화면 1에서 선택한 아동만 목록에 표시됩니다.")

    # 버튼 (아무도 고르지 않으면 비활성) — 누르는 순간 미션 구성을 한 번 정해 둔다
    st.button(
        "다음", type="primary", use_container_width=True, disabled=not selected,
        on_click=start_mission, args=(selected, today),
    )


def mission_tabs(current):
    # 화면 2와 2-1이 함께 쓰는 [미션 카드] / [코칭 가이드] 탭 — 지금 화면의 탭이 진하게 보인다
    card_col, guide_col = st.columns(2)
    card_col.button(
        "미션 카드", use_container_width=True,
        type="primary" if current == "s2" else "secondary", on_click=go, args=("s2",),
    )
    guide_col.button(
        "코칭 가이드", use_container_width=True,
        type="primary" if current == "s2_1" else "secondary", on_click=go, args=("s2_1",),
    )


def back_next_buttons():
    # 화면 2·2-1 아래 버튼 — [이전으로]는 팝업 1, [다음으로]는 화면 3
    back_col, next_col = st.columns(2)
    back_col.button("이전으로", use_container_width=True, on_click=open_popup, args=("p1",))
    next_col.button("다음으로", type="primary", use_container_width=True, on_click=go, args=("s3",))


def waiting_children():
    # 팀으로 도착했는데 개인 미션이 나온 경우, 이번 미션을 하지 않는 도착 아동
    mu = st.session_state.matchup
    return [n for n in st.session_state.arrived if n not in mu["team_a"]]


def mission_subtitle():
    mu = st.session_state.matchup
    who = f"{mu['team_a'][0]} 차례" if waiting_children() else ", ".join(st.session_state.arrived)
    return f"{who} · {mu['label']} {mu['mission']['mission_type']} 미션"


ICEBREAK_NOTE = "성향 데이터가 아직 없는 아동이 있어 보편적 아이스브레이킹 미션을 보여 줍니다."


def child_tip(name, mission, kind):
    # 아이 한 명에게 맞는 코칭 문구 — 미션 대상 성향을 가진 아이면 그 성향을 먼저, 아니면 아이의 첫 성향
    # 성향이 비어 있거나 문구가 없는 성향이면 "(성향 없음)" 초기 관찰용 문구
    traits = traits_of(name)
    order = ([mission.get("target_trait")] if mission.get("target_trait") in traits else []) + traits
    trait = next((t for t in order if t in COACHING_TIPS), NO_TRAIT)
    label = trait if traits else "성향 데이터 없음"
    return f"{name}({label}) — {COACHING_TIPS[trait][kind]}"


def guide_lines():
    # 화면 2-1의 행동 지침 세 칸 (와이어프레임 01·02·03)
    # 01 먼저 할 말·행동 — 미션 카드의 coaching_guide (팀 도착에 개인 미션이면 응원 역할 안내를 덧붙인다)
    # 02 아이가 망설일 때 · 03 미션이 끝난 뒤 살펴볼 것 — 이번 미션 아이마다 성향에 맞춘 한 줄 (data/coaching_tips.csv)
    mu = st.session_state.matchup
    mission = mu["mission"]
    first = mission["coaching_guide"] or "이 미션의 코칭 가이드 문구가 아직 없습니다."
    waiting = waiting_children()
    if waiting:
        first += (
            f" 화면에 {mu['team_a'][0]} 차례로 나왔다고 함께 보여 주고, "
            f"{', '.join(waiting)}에게는 \"다음 미션은 같이 하자\"며 응원 역할을 맡겨 주세요."
        )
    players = mu["team_a"] + mu["team_b"]
    return [
        ("먼저 할 말·행동", first),
        ("아이가 망설일 때", "  \n".join(child_tip(n, mission, "hesitate") for n in players)),
        ("미션이 끝난 뒤 살펴볼 것", "  \n".join(child_tip(n, mission, "observe") for n in players)),
    ]


def caution_lines():
    mu = st.session_state.matchup
    return [
        f"{n}: {CHILD_INFO[n]['avoid']}"
        for n in mu["team_a"] + mu["team_b"]
        if CHILD_INFO.get(n, {}).get("avoid")
    ]


# AI 고정 지시문 — app.py 옆 ai_rules.md 에서 "## 이름" 덩어리별로 읽는다
# 화면이 다시 그려질 때마다 새로 읽으니, 파일을 고쳐 저장하면 다음 동작부터 바로 쓰인다
AI_RULES_FILE = Path(__file__).parent / "ai_rules.md"
AI_RULE_NAMES = [
    "SAFE_RULE", "AI_CARD_RULE", "COUNTRY_CHECK_RULE",
    "CHAT_FORMAT_RULE", "CHAT_FORMAT_REMINDER", "CHATBOT_RULE", "CHAT_TONES",
]


def load_ai_rules():
    # "## 이름" 줄부터 다음 "## " 줄 전까지가 한 덩어리 — 첫 "## " 앞의 설명은 AI에게 보내지 않는다
    try:
        text = AI_RULES_FILE.read_text(encoding="utf-8")
    except OSError:
        st.error(f"AI 지시문 파일 {AI_RULES_FILE.name} 을 찾지 못했어요.")
        st.stop()
    rules = {}
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        name, _, body = block.partition("\n")
        rules[name.strip()] = body.strip()
    missing = [n for n in AI_RULE_NAMES if not rules.get(n)]
    if missing:
        st.error(f"{AI_RULES_FILE.name} 에 이 지시문이 없거나 비어 있어요: {', '.join(missing)}")
        st.stop()
    return rules


AI_RULES = load_ai_rules()

# 챗봇 답과 AI 미션 카드 모두에 붙이는 전체 이용가 규칙
SAFE_RULE = AI_RULES["SAFE_RULE"] + "\n"
# AI 답에 이런 말이 있으면 쓰지 않는다 — 규칙을 어긴 답을 한 번 더 거른다
UNSAFE_RE = re.compile(r"파트너|야한|야동|19금|성인용|섹시|섹스|\bAV\b|씨발|시발|병신|개새|존나")
# 미션 카드에만 쓰는 폭력 낱말 — 챗봇 조언에는 "때리지 말고"처럼 하지 말라는 말로 나올 수 있어 거르지 않는다
VIOLENT_RE = re.compile(r"싸움|때리|주먹")


def is_safe(text, card=False):
    return not UNSAFE_RE.search(text) and not (card and VIOLENT_RE.search(text))


def by_sentence(text):
    # 온점(.) 뒤에 띄어쓰기가 오면 줄을 바꿔, 휴대폰 화면에서 한 줄에 한 문장씩 보이게 한다
    # (마크다운 줄바꿈 "  \n" — 1.5처럼 띄어쓰기 없는 점은 그대로 둔다)
    return re.sub(r"\.[ \t]+(?=\S)", ".  \n", text)


# AI 미션 카드 지시문 — 전체 이용가 규칙 뒤에 붙인다 (내용은 ai_rules.md)
AI_CARD_RULE = SAFE_RULE + AI_RULES["AI_CARD_RULE"]

# AI 미션 카드에 넣을 의식주·문화 요소를 고르는 체크 칸 (나라는 직접 적는다)
AI_ELEMENTS = ["전통놀이", "음식", "인사말", "옷", "집", "명절"]

# 멘토가 적은 나라 이름이 실제로 있는 나라인지 Gemini에 묻는 규칙 — 다른 언어·띄어쓰기·오타도 알아보면 한국어 이름으로 바꾼다
# (되묻지 않는다 — 알아보면 그 나라로 바로 만들고, 없는 나라면 만들지 않는다)
COUNTRY_CHECK_RULE = AI_RULES["COUNTRY_CHECK_RULE"]
# AI 답의 줄 이름 → 미션 카드 칸
AI_CARD_FIELDS = {
    "퀘스트 이름": "title",
    "할 일": "description",
    "보상": "reward_text",
    "응원 한마디": "cheer",
    "코칭 가이드": "coaching_guide",
}


# AI 카드 검사 — 실제 나라 이름이 하나는 있어야 보여 준다. 취향을 묻는 말은 구체적인 나라와 함께면 괜찮다
# (.claude/hooks/card-content.py 와 같은 기준. "한국어"는 나라 이름으로 치지 않는다)
CULTURE_COUNTRIES = [
    "한국", "베트남", "중국", "일본", "필리핀", "태국", "몽골", "러시아", "우즈베키스탄",
    "카자흐스탄", "키르기스스탄", "캄보디아", "라오스", "미얀마", "네팔", "인도네시아", "인도",
    "스리랑카", "방글라데시", "파키스탄", "대만", "미국", "캐나다", "멕시코", "브라질",
    "프랑스", "독일", "영국", "이탈리아", "스페인", "튀르키예", "터키", "이집트", "케냐",
    "나이지리아", "호주",
]


def concrete_culture(card, countries=()):
    # 멘토가 적어 확인을 마친 나라(목록에 없는 나라도)도 나라 이름으로 친다
    return any(c in card.replace("한국어", "") for c in [*CULTURE_COUNTRIES, *countries])


def split_countries(raw):
    # 나라 이름 안의 띄어쓰기는 그대로 두고, 쉼표·슬래시로 여러 나라를 나눈다
    return [n.strip() for n in re.split(r"[,，、/]", raw) if n.strip()]


def check_countries(names):
    # 나라마다 한국어 나라 이름을, 있는 나라가 아니면 None 을 돌려준다
    # 한국어 이름이 목록에 있으면(띄어쓰기는 무시) Gemini에 묻지 않는다
    known = [n.replace(" ", "") if n.replace(" ", "") in CULTURE_COUNTRIES else None for n in names]
    ask = [n for n, k in zip(names, known) if k is None]
    if not ask:
        return known
    ai = gemini()
    with st.spinner("나라 이름을 확인하는 중..."):
        interaction = ai.interactions.create(
            model=AI_MODEL,
            system_instruction=COUNTRY_CHECK_RULE,
            input="\n".join(ask),
        )
    lines = [line.strip() for line in interaction.output_text.splitlines() if line.strip()]
    if len(lines) != len(ask):
        raise ValueError("나라 이름 확인 답이 적은 나라 수와 맞지 않아요. 다시 눌러 주세요.")
    answers = iter(None if line == "없음" else line for line in lines)
    return [k if k is not None else next(answers) for k in known]


def parse_ai_card(text):
    # "퀘스트 이름: …" 같은 줄을 미션 카드 칸으로 나눈다 — 이름과 할 일이 없으면 None
    card = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        key = key.strip().strip("*").strip()
        if sep and key in AI_CARD_FIELDS:
            card[AI_CARD_FIELDS[key]] = value.strip().strip("*").strip()
    return card if card.get("title") and card.get("description") else None


def apply_ai_card(card, culture):
    # AI 카드를 이번 미션으로 바꿔 끼운다 — 화면 2 카드, 화면 2-1 코칭 가이드, Supabase 기록에 그대로 쓰인다
    # 인원 구성(팀·상대)과 미션 종류는 원래 미션 그대로 둔다
    mu = st.session_state.matchup
    base = mu.setdefault("base_mission", mu["mission"])
    mu["mission"] = {
        **base,
        "mission_id": "AI",
        "title": card["title"],
        "description": card["description"],
        "culture": culture,
        "coaching_guide": card.get("coaching_guide") or base["coaching_guide"],
        "difficulty": card.get("reward_text", "").split("·")[0].strip() or base["difficulty"],
        "reward_text": card.get("reward_text", ""),
        "cheer": card.get("cheer", ""),
    }
    # 새 카드가 뜬 셈이라 [스킵]까지 걸린 초를 다시 센다
    st.session_state.mission_started_at = time.time()


def ai_card_counts():
    # 오늘 게임 판별로 AI 미션 카드를 만든 횟수 — 날짜가 바뀌면 0번부터 다시 센다
    today = datetime.now(KST).date().isoformat()
    if st.session_state.ai_card_day != today:
        st.session_state.ai_card_day = today
        st.session_state.ai_card_count = {}
    return st.session_state.ai_card_count


def ai_cards_left():
    # 이번 판에 AI 미션 카드를 더 만들 수 있는 횟수
    return AI_CARD_LIMIT - ai_card_counts().get(st.session_state.game_no, 0)


def ai_card_request(culture):
    # Gemini에 보낼 이번 미션 정보 — 멘토가 고른 문화 요소와, 실명 대신 성향·기피 특성과 인원 구성만 보낸다
    # AI 카드로 바꾼 뒤 다시 만들어도 참고 미션은 missions.csv에서 고른 원래 미션
    mu = st.session_state.matchup
    mission = mu.get("base_mission", mu["mission"])

    def describe(names):
        return [
            f"성향 {', '.join(traits_of(n)) or '데이터 없음'} / 기피 {CHILD_INFO.get(n, {}).get('avoid') or '없음'}"
            for n in names
        ]

    lines = [
        f"멘토가 고른 나라와 의식주·문화 요소: {culture}",
        f"미션 종류: {mission['mission_type']} ({mu['label']})",
        f"참고할 미션: {mission['title']} — {mission['description']}",
        "이번 미션을 하는 아이:",
        *[f"- {d}" for d in describe(mu["team_a"])],
    ]
    if mu["team_b"]:
        lines.append("상대 편 아이:" if mission["mission_type"] == "경쟁" else "합류하는 아이:")
        lines += [f"- {d}" for d in describe(mu["team_b"])]
    return "\n".join(lines)


def reward_ok(reward_text):
    # AI 카드 보상이 기준표에 맞는지 — 쉬움 5천원 / 보통 1·2·3만원 / 어려움 5만원 (missions.csv 의 보상 hook 과 같은 기준)
    allowed = {"쉬움": {"5천원"}, "보통": {"1만원", "2만원", "3만원"}, "어려움": {"5만원"}}
    level, _, money = (part.strip() for part in reward_text.partition("·"))
    return money.replace(" ", "") in allowed.get(level, set())


def friendly_ai_error(error, what):
    # AI 오류를 멘토가 알아들을 말로 — 영어 오류 글은 화면에 보이지 않게 한다
    msg = str(error)
    if "429" in msg or "quota" in msg or "Rate limit" in msg:
        return f"{what}.  \n오늘 AI 사용량을 다 써서 잠시 쉬어야 해요. 잠시 뒤 다시 눌러 주세요."
    if "503" in msg or "high demand" in msg:
        return f"{what}.  \n지금 AI가 붐벼요. 잠시 뒤 다시 눌러 주세요."
    return f"{what}.  \n잠시 뒤 다시 눌러 주세요."


def log_ai_card(culture):
    # 화면에 쓴 AI 카드를 Supabase ai_missions 표에 남긴다 — 나중에 이 표를 보고 고증이 틀린 카드를 고친다
    # 카드 내용 칸(title 등)을 아직 안 만들었으면 미션 종류·문화 요소만 남긴다. 실패해도 카드는 그대로 쓴다
    mission = st.session_state.matchup["mission"]
    short = {"mission_type": mission["mission_type"], "culture": culture}
    full = {
        **short,
        "title": mission["title"],
        "description": mission["description"],
        "coaching_guide": mission["coaching_guide"],
        "reward_text": mission["reward_text"],
        "cheer": mission["cheer"],
    }
    for row in (full, short):
        try:
            client.table(AI_LOG_TABLE).insert(row).execute()
            return
        except Exception:
            continue
    st.caption("이 카드를 기록하지 못했어요.  \n카드는 그대로 쓸 수 있어요.")


def make_ai_card(countries, elements, extra):
    # Gemini에 미션 카드를 받아 이번 미션으로 바꿔 끼운다 (helper.py와 같은 방식)
    culture = " / ".join(
        f"{label}: {value}"
        for label, value in [("나라", ", ".join(countries)), ("요소", ", ".join(elements)), ("기타", extra)]
        if value
    )
    try:
        ai = gemini()
        with st.spinner("AI가 미션 카드를 만드는 중..."):
            interaction = ai.interactions.create(
                model=AI_MODEL,
                system_instruction=AI_CARD_RULE,
                input=ai_card_request(culture),
            )
    except Exception as e:
        st.warning(friendly_ai_error(e, "미션 카드를 만들지 못했어요"))
        return
    # 카드를 받은 경우에만 센다 — 오류로 못 받은 것은 횟수에 넣지 않는다
    # (검사에 걸려 쓰지 않는 카드도 Gemini 비용은 들었으니 센다)
    count = ai_card_counts()
    count[st.session_state.game_no] = count.get(st.session_state.game_no, 0) + 1
    text = interaction.output_text
    card = parse_ai_card(text)
    if not is_safe(text, card=True):
        st.warning("AI 카드에 전체 이용가에 맞지 않는 말이 있어 쓰지 않았어요.  \n다시 만들어 주세요.")
    elif not concrete_culture(text, countries):
        st.warning("AI 카드에 구체적인 나라 문화(예: 베트남 놀이·음식 이름)가 없어 쓰지 않았어요.  \n다시 만들어 주세요.")
    elif not card:
        st.warning("AI 카드 형식이 맞지 않아 쓰지 않았어요.  \n다시 만들어 주세요.")
    elif not reward_ok(card.get("reward_text", "")):
        st.warning("AI 카드의 보상이 기준표(쉬움 5천원 / 보통 1·2·3만원 / 어려움 5만원)와 달라 쓰지 않았어요.  \n다시 만들어 주세요.")
    else:
        # 챗봇이 화면보다 먼저 그려지므로, 이어서 그리는 화면 2에 새 카드가 바로 나온다
        apply_ai_card(card, culture)
        log_ai_card(culture)
        st.session_state.chat.append(
            ("assistant", f"미션 카드를 만들었어요! 화면의 미션 카드가 **{card['title']}**(으)로 바뀌었어요.")
        )
        st.success(f"화면의 미션 카드가 **{card['title']}**(으)로 바뀌었어요.")


def chat_card_maker():
    # 챗봇의 [미션 카드 만들기] — 나라를 적고 의식주·문화 요소를 체크하고(기타는 직접 적고) 버튼을 누르면,
    # AI가 만든 미션 카드가 화면 2의 미션 카드를 바꾼다. 게임 한 판에 AI_CARD_LIMIT번까지
    if st.session_state.screen not in ("s2", "s2_1"):
        st.info("미션칸 도착 아동을 고른 뒤, 화면 2(미션 카드)에서 만들 수 있어요.")
        return
    used_up = ai_cards_left() <= 0

    st.write("AI 미션 카드에 넣고 싶은 요소를 적거나 체크하세요.")
    country_raw = st.text_input(
        "나라", placeholder="예: 베트남, Mongolia, 中国 (여러 나라는 쉼표로)", key="ai_country"
    ).strip()
    st.caption("의식주·문화 요소")
    elements = [e for col, e in zip(st.columns(3) * 2, AI_ELEMENTS) if col.checkbox(e, key=f"ai_pick_{e}")]
    extra = st.text_input("기타", placeholder="예: 베트남 모자 '논라', 설날 세배", key="ai_extra").strip()

    if st.button("AI 미션 카드 만들기", use_container_width=True, disabled=used_up):
        names = split_countries(country_raw)
        if not (names or elements or extra):
            st.write("넣고 싶은 요소를 하나 이상 적거나 체크해 주세요.")
        else:
            try:
                countries = check_countries(names)
            except Exception as e:
                st.warning(friendly_ai_error(e, "나라 이름을 확인하지 못했어요"))
                countries = None
            # 알아본 나라(오타·다른 언어 포함)는 되묻지 않고 바로 만들고, 없는 나라가 있으면 만들지 않는다
            wrong = [n for n, c in zip(names, countries or []) if c is None]
            if wrong:
                st.warning(f"{', '.join(wrong)}은(는) 있는 나라 이름으로 알아보지 못했어요.  \n나라 이름을 다시 적어 주세요.")
            elif countries is not None:
                make_ai_card(countries, elements, extra)

    left = ai_cards_left()
    if left <= 0:
        st.caption(f"이번 판에는 AI 미션 카드를 {AI_CARD_LIMIT}번 모두 만들었어요.")
    else:
        st.caption(f"AI 미션 카드는 게임 한 판에 {AI_CARD_LIMIT}번까지 — 이번 판은 {left}번 남았어요.")


def reward_text(mission):
    # 미션 카드의 보상 — AI 카드는 AI가 쓴 그대로, missions.csv 미션은 난이도와 reward_money (예: 쉬움 · 5천원)
    if mission.get("reward_text"):
        return mission["reward_text"]
    money = int(mission["reward_money"] or 0)
    won = f"{money // 10000}만원" if money % 10000 == 0 else f"{money // 1000}천원"
    return f"{mission['difficulty'] or '미정'} · {won}" if money else "미정"


def toggle_skip():
    st.session_state.skip_open = not st.session_state.get("skip_open", False)


def skip_header(title):
    # 화면 2·2-1 제목 줄 — 오른쪽 위 작은 [스킵] 글자 버튼, 누르면 바로 밑에 이유 칩 세 개가 펼쳐진다 (팝업 X)
    with st.container(key="mission_header"):
        title_col, skip_col = st.columns([5, 1], vertical_alignment="center")
        title_col.subheader(title)
        skip_col.button("스킵", key="skip_toggle", type="tertiary", on_click=toggle_skip,
                        help="시간 초과·룰 미숙지·단순 패스로 미션을 못 했을 때 누르세요")
    if st.session_state.get("skip_open"):
        st.pills("스킵 이유", list(SKIP_REASONS), key="skip_pick", on_change=do_skip, label_visibility="collapsed")
    if st.session_state.get("skip_error"):
        st.error(st.session_state.pop("skip_error"))
    if st.session_state.get("skip_notice"):
        st.info(st.session_state.pop("skip_notice"))


def do_skip():
    # 칩을 누르면 — reactions 표에 스킵 한 줄(단순 미수행 기록)을 남기고, 이유에 따라 바로 이어 간다
    # 시간초과 → 다음 아동 선택(화면 1-1) / 룰 미숙지 → 같은 아이들에게 더 쉬운 미션 / 단순패스 → 다른 미션
    # 스킵한 미션은 "미션 N회"를 늘리지 않는다
    label = st.session_state.get("skip_pick")
    st.session_state.skip_pick = None
    st.session_state.skip_open = False
    if not label:
        return
    mu = st.session_state.matchup
    mission = mu["mission"]
    started = st.session_state.get("mission_started_at", time.time())
    record = {
        "game_no": st.session_state.game_no,
        "mission_id": mission["mission_id"],
        "mission_title": mission["title"],
        "child_ids": [id_of(n) for n in mu["team_a"] + mu["team_b"]],
        "reaction": None,
        "memo": None,
        "feedback_type": "skip",
        "skip_reason": SKIP_REASONS[label],
        "response_latency": round(time.time() - started, 1),
    }
    try:
        client.table(TABLE).insert(record).execute()
    except Exception as e:
        msg = str(e)
        if any(col in msg for col in ("feedback_type", "skip_reason", "response_latency")):
            st.session_state.skip_error = "Supabase reactions 표에 스킵 기록 칸이 아직 없어요.  \n칸을 만든 뒤 다시 눌러 주세요."
        elif "not-null" in msg or "null value" in msg:
            st.session_state.skip_error = "Supabase reactions 표의 reaction 칸이 비어 있으면 저장되지 않게 되어 있어요."
        else:
            st.session_state.skip_error = "스킵을 저장하지 못했어요.  \n잠시 뒤 다시 눌러 주세요."
        return
    saved_reactions.clear()
    st.session_state.used_missions.add(mission["mission_id"])

    code = SKIP_REASONS[label]
    if code == "timeout":
        clear_picks("s1_1_pick_")
        go("s1_1")
        return
    arrived = st.session_state.arrived
    skipped = {mission["mission_id"], mu.get("base_mission", mission)["mission_id"]}
    new = make_matchup(arrived, st.session_state.get("today", arrived), exclude=skipped,
                       prefer_easy=code == "rule_unfamiliar")
    set_mission(new)
    if new["mission"]["mission_id"] in skipped:
        st.session_state.skip_notice = "이 아이들에게 맞는 다른 미션이 없어 같은 미션이 다시 나왔어요."
    elif code == "rule_unfamiliar":
        st.session_state.skip_notice = "더 쉬운 미션으로 바꿨어요."
    else:
        st.session_state.skip_notice = (
            "다른 미션으로 바꿨어요.  \n"
            "링키와 함께 새 미션 카드를 만들 수도 있어요 (오른쪽 아래 링키 → [미션 카드 만들기])."
        )
    go("s2")


def screen_2():
    # 화면 2 — OO님의 미션 (missions.csv에서 고른 짝꿍 미션 카드 1장)
    mu = st.session_state.matchup
    mission = mu["mission"]
    skip_header(f"{', '.join(st.session_state.arrived)}님의 미션")
    mission_tabs("s2")

    st.caption(f"`{mu['label']}` {mission['mission_type']} · 난이도 {mission['difficulty'] or '미정'}")
    # 팀 도착인데 개인 미션이면 누가 할지 앱이 지정한다 — 아이들끼리 서로 하겠다고 다투지 않게
    waiting = waiting_children()
    if waiting:
        st.info(f"이번 미션은 **{mu['team_a'][0]}** 차례입니다.  \n{', '.join(waiting)}은(는) 옆에서 응원해 주세요.")
    with st.container(border=True):
        if mu["team_b"]:
            left, mid, right = st.columns([2, 1, 2], vertical_alignment="center")
            sign = "VS" if mission["mission_type"] == "경쟁" else "+"
            mid.markdown(f"<div style='text-align:center'>{sign}</div>", unsafe_allow_html=True)
            for n in mu["team_a"]:
                left.button(n, disabled=True, use_container_width=True, key=f"a_{n}")
            for n in mu["team_b"]:
                right.button(n, disabled=True, use_container_width=True, key=f"b_{n}")
        else:
            for col, n in zip(st.columns(len(mu["team_a"])), mu["team_a"]):
                col.button(n, disabled=True, use_container_width=True, key=f"a_{n}")
        st.divider()
        st.markdown(f"**{mission['title']}**")
        st.markdown(by_sentence(mission["description"]))
        # 보상은 모든 미션 카드에 보여 준다 — AI 카드면 응원 한마디와 안내도 함께
        lines = [f"보상: {reward_text(mission)}"]
        if mission["mission_id"] == "AI":
            if mission["cheer"]:
                lines.append(f"응원 한마디: {mission['cheer']}")
            lines.append("AI가 만든 미션 카드예요. 코칭 가이드와 반응 기록에도 이 카드가 쓰입니다.")
        st.caption(by_sentence("  \n".join(lines)))
    if mission["mission_id"] == ICEBREAK["mission_id"]:
        st.caption(ICEBREAK_NOTE)

    back_next_buttons()


def screen_2_1():
    # 화면 2-1 — 코칭 가이드 (01은 missions.csv의 coaching_guide, 02·03은 아이 성향별 data/coaching_tips.csv)
    mu = st.session_state.matchup
    mission = mu["mission"]
    skip_header("코칭 가이드")
    st.caption(f"{mission_subtitle()} · 멘토용")
    mission_tabs("s2_1")

    st.write("행동 지침")
    for i, (title, text) in enumerate(guide_lines(), start=1):
        with st.container(border=True):
            st.markdown(f"**{i:02d} {title}**  \n{by_sentence(text)}")

    # 주의 문구 영역 — 이번 미션 참여 아동의 기피 특성 (children.csv의 avoid)
    cautions = caution_lines()
    if cautions:
        st.caption("주의 — 기피 특성  \n" + "  \n".join(cautions))

    back_next_buttons()


def pick_reaction(reaction):
    st.session_state.reaction = reaction


def current_record():
    # 지금 화면 3에서 체크한 미션 한 건 — Supabase reactions 표의 한 줄이 된다
    # child_ids에는 실제로 미션한 아동만 담는다 (팀 도착에 개인 미션이면 차례인 아동 한 명, 응원한 아동은 빠진다)
    # memo는 멘토가 고르는 선택 칸이지만 적은 것은 꼭 저장한다 (나중에 레포트에 쓴다), 안 적으면 빈 칸
    mu = st.session_state.matchup
    return {
        "game_no": st.session_state.game_no,
        "mission_id": mu["mission"]["mission_id"],
        # Supabase 표에서 M08 같은 번호만 보고도 어떤 미션인지 알 수 있게 — missions.csv의 짧은 미션 제목
        # (나중에 missions.csv를 고쳐도 기록에는 그때 한 미션 제목이 남는다)
        "mission_title": mu["mission"]["title"],
        "child_ids": [id_of(n) for n in mu["team_a"] + mu["team_b"]],
        "reaction": st.session_state.reaction,
        "memo": memo_with_ids(st.session_state.get("memo", "").strip()) or None,
    }


def memo_with_ids(memo):
    # 메모 속 아동 이름을 child_id로 바꿔 저장한다 — Supabase에는 실명 대신 child_id만 남긴다
    # 긴 이름부터 바꿔, 한 이름이 다른 이름 안에 들어 있어도 잘못 바뀌지 않게 한다
    for name in sorted(st.session_state.children, key=len, reverse=True):
        memo = memo.replace(name, id_of(name))
    return memo


@st.cache_data(ttl=60, show_spinner=False)
def saved_reactions():
    # Supabase에 저장된 반응 기록 전체 — 최신 것이 맨 위에 오게
    return (
        client.table(TABLE)
        # 모든 칸 — 스킵 기록 칸(feedback_type 등)을 Supabase에 만들기 전에도 그대로 읽힌다
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
    )


def child_list(child_ids):
    # Supabase 표의 child_ids 열이 글 종류라 '["C01","C02"]' 같은 글로 돌아온다 — 번호 목록으로 바꾼다
    if isinstance(child_ids, str):
        try:
            return json.loads(child_ids)
        except ValueError:
            return [child_ids]
    return child_ids or []


def records_csv(rows):
    # Supabase에 저장된 기록을 엑셀에서 바로 열리는 표 파일로 만든다
    # (utf-8-sig — 엑셀에서 열어도 한글이 깨지지 않는다)
    table = [
        {
            "회차": r["game_no"],
            "기록 시각": datetime.fromisoformat(r["created_at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            "미션 번호": r["mission_id"],
            "미션 제목": r["mission_title"] or MISSION_TITLE.get(r["mission_id"], ""),
            "미션한 아동": ", ".join(name_of(c) for c in child_list(r["child_ids"])),
            # 스킵 기록은 반응 대신 스킵 이유와 스킵까지 걸린 초가 남는다
            "구분": "스킵" if r.get("feedback_type") == "skip" else "반응",
            "반응": r.get("reaction") or "",
            "스킵 이유": SKIP_LABELS.get(r.get("skip_reason"), ""),
            "걸린 시간(초)": r.get("response_latency") if r.get("response_latency") is not None else "",
            "메모": r.get("memo") or "",
        }
        for r in rows
    ]
    return pd.DataFrame(table).to_csv(index=False).encode("utf-8-sig")


def leave(screen):
    # 반응을 Supabase에 저장하고 참여한 아동의 미션 횟수를 1 늘린 뒤 다음 화면으로 간다
    # 저장에 실패하면 화면 3에 그대로 남아 다시 누를 수 있게 한다
    mu = st.session_state.matchup
    players = mu["team_a"] + mu["team_b"]
    try:
        client.table(TABLE).insert(current_record()).execute()
    except Exception as e:
        if "mission_title" in str(e):
            st.session_state.save_error = "Supabase 표에 mission_title 열이 없어요.  \n열을 만든 뒤 다시 눌러 주세요."
        elif "row-level security" in str(e):
            st.session_state.save_error = "Supabase 표에 저장을 허용하는 정책이 없어요."
        else:
            st.session_state.save_error = "인터넷 연결을 확인하고 잠시 뒤 다시 눌러 주세요."
        return
    st.session_state.save_error = None
    saved_reactions.clear()
    st.session_state.used_missions.add(mu["mission"]["mission_id"])
    for n in players:
        st.session_state.mission_count[n] = count_of(n) + 1
    if screen == "s1":
        # [게임 끝내기] — 이번 게임 횟수를 아동 프로필에 더하고, 다음 게임은 0회부터 시작한다
        profile = st.session_state.profile_count
        for n, c in st.session_state.mission_count.items():
            profile[n] = profile.get(n, 0) + c
        # 피날레 릴레이는 끝난 판의 회차로 기록한다 — 회차를 올리기 전에 만든다
        start_finale()
        st.session_state.mission_count = {}
        st.session_state.game_no += 1
        st.session_state.used_missions = set()
        # 화면 1로 가기 전에 피날레 화면을 먼저 보여 준다
        screen = "s_finale"
    st.session_state.reaction = None
    st.session_state.memo = ""
    clear_picks("s1_1_pick_")
    go(screen)


def screen_3():
    # 화면 3 — 미션 직후 또래관계 체크
    st.subheader("미션 직후 또래관계 체크")
    st.caption(mission_subtitle())

    with st.container(border=True):
        st.markdown("아동 개인의 기분이 아니라, **이번 짝·팀과 잘 어울렸는지**를 멘토가 판단해 한 가지를 선택하세요.")

    # 넣는 자리 — 고른 반응이 진하게 보인다
    reaction = st.session_state.get("reaction")
    for label in ["좋음", "보통", "기피"]:
        st.button(
            label, use_container_width=True,
            type="primary" if reaction == label else "secondary",
            on_click=pick_reaction, args=(label,),
        )
    st.text_input("메모", key="memo", placeholder="메모 입력(선택) — 한 줄", label_visibility="collapsed")

    # 버튼 — 반응을 하나 골라야 누를 수 있다
    next_col, end_col = st.columns(2)
    next_col.button(
        "다음 아동 선택", type="primary", use_container_width=True,
        disabled=reaction is None, on_click=leave, args=("s1_1",),
    )
    end_col.button(
        "게임 끝내기", use_container_width=True,
        disabled=reaction is None, on_click=leave, args=("s1",),
    )
    if st.session_state.get("save_error"):
        st.error(f"Supabase에 저장하지 못했어요.  \n{st.session_state.save_error}")

    # 기록한 반응은 화면에 표로 보여 주지 않고, 이 단추로 Supabase에 저장된 기록만 파일에 담아 내려받는다
    try:
        rows = saved_reactions()
    except Exception as e:
        st.error("저장된 기록을 불러오지 못했어요.  \n잠시 뒤 다시 열어 주세요.")
        rows = []
    st.download_button(
        "기록 CSV 파일로 내려받기", use_container_width=True, disabled=not rows,
        data=records_csv(rows) if rows else b"",
        file_name=f"미션기록_{date.today():%Y%m%d}.csv", mime="text/csv",
    )
    if not rows:
        st.caption("아직 Supabase에 저장된 기록이 없습니다.")


@st.dialog("이름 확인", dismissible=False)
def popup_1():
    # 팝업 1 — 화면 2·2-1에서 [이전으로]를 누르면 뜬다
    st.markdown("#### 이름을 잘못 선택하셨나요?")
    yes_col, no_col = st.columns(2)
    if yes_col.button("맞음", type="primary", use_container_width=True):
        go("s1_1")
        st.rerun()
    if no_col.button("아님", use_container_width=True):
        open_popup("p2")
        st.rerun()


@st.dialog("또래관계 체크 안내", dismissible=False)
def popup_2():
    # 팝업 2 — 팝업 1에서 [아님]을 누르면 뜨고, [확인]을 누르면 직전 화면(화면 2 또는 2-1)으로 돌아간다
    st.markdown("**또래관계 체크를 아직 안 하셨습니다.**\n\n**'다음으로'를 눌러주세요.**")
    if st.button("확인", type="primary", use_container_width=True):
        open_popup(None)
        st.rerun()


# ---------- 상담 챗봇 ----------

# 답의 모양을 고정하는 지시문 — 챗봇 규칙에 함께 넣어, 어떤 질문을 받아도 이 형식을 지키게 한다
CHAT_FORMAT_RULE = AI_RULES["CHAT_FORMAT_RULE"] + "\n"
# 멘토 질문 뒤에 붙이는 짧은 형식 알림 — 긴 PRD 문서 뒤에서도 세 문장 형식을 잊지 않게 한다 (화면에는 보이지 않는다)
CHAT_FORMAT_REMINDER = "\n\n" + AI_RULES["CHAT_FORMAT_REMINDER"]
# 멘토가 모르는 개발 용어 → 멘토가 화면에서 보는 말 (AI에게 알려 주고, 답에 남으면 한 번 더 바꾼다)
MENTOR_WORDS = {
    "PRD 문서": "서비스 안내", "PRD": "서비스 안내",
    "Supabase reactions 표": "온라인 반응 기록", "Supabase": "온라인 기록", "reactions 표": "반응 기록",
    "child_id": "아동 번호",
    "화면 1-1": "'미션칸 도착 아동 선택' 화면", "화면 2-1": "[코칭 가이드] 탭",
    "화면 1": "'참여 아동 전체 선택' 화면", "화면 2": "미션 카드 화면", "화면 3": "'미션 직후 또래관계 체크' 화면",
    "팝업 1": "이름 확인 알림 창", "팝업 2": "또래관계 체크 안내 창",
    "MVP": "첫 버전", "비목표": "이번에 만들지 않는 것", "수용 기준": "완성 기준",
}


def mentor_words(text):
    # 답에 남은 개발 용어를 멘토가 아는 말로 바꾼다 — 긴 말부터 바꿔 '화면 1-1'이 '화면 1'로 잘못 바뀌지 않게 한다
    # 바뀐 말의 끝 글자에 맞게 바로 뒤 조사도 고친다 (예: '화면 2-1로' → '[코칭 가이드] 탭으로')
    for word in sorted(MENTOR_WORDS, key=len, reverse=True):
        new = MENTOR_WORDS[word]
        text = re.sub(
            re.escape(word) + r"(?:(으로|로|은|는|이|가|을|를|과|와)(?![가-힣]))?",
            lambda m, new=new: new + fit_particle(new, m.group(1) or ""),
            text,
        )
    return text


def fit_particle(word, particle):
    # 받침 있는 말 뒤에는 은·이·을·과·으로, 없는 말 뒤에는 는·가·를·와·로 (ㄹ 받침 뒤는 '로')
    if not particle:
        return ""
    code = ord(word[-1]) - 0xAC00
    final = code % 28 if 0 <= code < 11172 else 0
    pairs = {"으로": "로", "은": "는", "이": "가", "을": "를", "과": "와"}
    with_final = {v: k for k, v in pairs.items()} | {k: k for k in pairs}
    without_final = pairs | {v: v for v in pairs.values()}
    if particle in ("로", "으로"):
        return "으로" if final not in (0, 8) else "로"
    return with_final[particle] if final else without_final[particle]

# 링키 챗봇 지시문 — 전체 이용가 규칙 + 답 형식 + 챗봇 규칙, 이 뒤에 PRD.md 가 붙는다 (내용은 ai_rules.md)
CHATBOT_RULE = SAFE_RULE + CHAT_FORMAT_RULE + AI_RULES["CHATBOT_RULE"] + "\n\n"
# 링키 대화창 [말투] 칸의 말투 목록 — ai_rules.md 의 CHAT_TONES 에서 "말투 이름: 쓰는 법" 한 줄씩 읽는다 (맨 위가 처음 골라진 말투)
CHAT_TONES = dict(
    (name.strip(), how.strip())
    for name, sep, how in (line.partition(":") for line in AI_RULES["CHAT_TONES"].splitlines())
    if sep and name.strip()
)


@st.cache_data
def prd_text():
    # 챗봇이 읽는 PRD.md — 이 파일 옆에 있는 것을 읽는다
    return (Path(__file__).parent / "PRD.md").read_text(encoding="utf-8")


def chat_children_note():
    # 지금 미션을 하는 아이들의 성향·기피 — 링키가 지금 아이들에게 맞춘 조언을 하게 질문 뒤에 붙인다 (화면에는 보이지 않는다)
    # 실명은 보내지 않는다. 미션 화면(화면 2·2-1·3)에 있을 때만 붙이고, children.csv가 바뀌면 바뀐 성향이 그대로 쓰인다
    if st.session_state.screen not in ("s2", "s2_1", "s3") or "matchup" not in st.session_state:
        return (
            "\n\n(참고 — 지금 미션 아이 정보 없음. 아이를 대하는 방법을 묻는 질문일 때만 쓴다: 신체 접촉은 먼저 권하지 말고, "
            "말할 때는 '아이가 편해하면'이라는 조건을 꼭 붙인다. 그 밖의 질문에는 신체 접촉 이야기를 꺼내지 않는다)"
        )
    mu = st.session_state.matchup
    lines = [
        f"- 아이 {i}: 성향 {', '.join(traits_of(n)) or '데이터 없음'} / 기피 {CHILD_INFO.get(n, {}).get('avoid') or '없음'}"
        for i, n in enumerate(mu["team_a"] + mu["team_b"], start=1)
    ]
    return (
        "\n\n(참고 — 지금 미션 아이들. 아이를 대하는 방법을 묻는 질문일 때만 쓰고, 그 밖의 질문에는 이 정보와 신체 접촉 이야기를 꺼내지 않는다)\n"
        + "\n".join(lines)
    )


def save_chat(question, answer):
    # 물은 말과 받은 답을 Supabase chat_logs 표에 한 줄로 남긴다 — 아동 이름은 반응 메모처럼 child_id로 바꿔 저장한다
    # (표의 열: id, created_at 은 Supabase가 채우고, question·answer 만 보낸다)
    client.table(CHAT_TABLE).insert({
        "question": memo_with_ids(question),
        "answer": memo_with_ids(answer),
    }).execute()
    saved_chats.clear()


@st.cache_data(ttl=60, show_spinner=False)
def saved_chats():
    # Supabase에 남은 대화 중 최근 것부터 CHAT_HISTORY_LIMIT개
    return (
        client.table(CHAT_TABLE)
        .select("created_at, question, answer")
        .order("created_at", desc=True)
        .limit(CHAT_HISTORY_LIMIT)
        .execute()
        .data
    )


def ids_to_names(text):
    # 저장된 child_id(C01, N01 …)를 화면에 보여 줄 때만 이름으로 되돌린다 (모르는 번호는 번호 그대로)
    return re.sub(r"(?<![A-Za-z0-9])([CN]\d{2})(?!\d)", lambda m: name_of(m.group(1)), text)


def chat_history():
    # 대화창 아래 [지난 대화 목록] — Supabase에 남은 대화를 최근 것부터 보여 준다
    with st.expander("지난 대화 목록"):
        try:
            rows = saved_chats()
        except Exception as e:
            if CHAT_TABLE in str(e):
                st.caption(f"Supabase에 {CHAT_TABLE} 표가 아직 없어요.  \n표를 만든 뒤 다시 열어 주세요.")
            else:
                st.caption("지난 대화를 불러오지 못했어요.  \n잠시 뒤 다시 열어 주세요.")
            return
        if not rows:
            st.caption("아직 남은 대화가 없어요.")
            return
        for r in rows:
            when = datetime.fromisoformat(r["created_at"]).astimezone(KST).strftime("%m-%d %H:%M")
            st.caption(when)
            st.markdown(f"**물은 말** {ids_to_names(r['question'])}")
            st.markdown(by_sentence(ids_to_names(r["answer"]).replace("\n", "  \n")))
            st.divider()


def show_chat(box, role, text, ai_written=False):
    # 대화 한 줄 — AI가 쓴 답이면 답 바로 위에 초안이라는 표시와 [복사] 버튼을 나란히 붙인다
    with box.chat_message(role, avatar=str(LINKY_ICON) if role == "assistant" else None):
        if ai_written:
            st.html(copy_bar(text), unsafe_allow_javascript=True)
        # 마크다운은 줄바꿈 한 번을 무시하므로, 문장마다 바꾼 줄이 화면에서도 보이게 줄 끝에 빈칸 두 개를 붙인다
        st.markdown(by_sentence(text.replace("\n", "  \n")))


def copy_bar(text):
    # "AI가 쓴 초안입니다" 표시 + 답 전체를 한 번에 복사하는 버튼
    # 답 글은 HTML로 해석되지 않게 바꿔(escape) data-text 칸에만 담고, 버튼은 그 칸의 글만 클립보드에 넣는다
    return (
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "font-size:0.875rem;color:rgba(49,51,63,0.6)'>"
        "<span>AI가 쓴 초안입니다</span>"
        f"<button data-text=\"{html.escape(text, quote=True)}\" "
        "onclick=\"navigator.clipboard.writeText(this.dataset.text).then(() => {"
        "this.textContent = '복사됨 ✓'; setTimeout(() => this.textContent = '복사', 1500);})\" "
        "style='border:1px solid rgba(49,51,63,0.2);border-radius:6px;background:white;"
        "padding:2px 10px;font-size:0.8rem;cursor:pointer'>복사</button>"
        "</div>"
    )


def chatbot():
    # 오른쪽 아래 링키 아이콘 — 누르면 대화창이 열린다 (helper.py와 같은 방식으로 Gemini를 부른다)
    if "chat" not in st.session_state:
        st.session_state.chat = [("assistant", "안녕하세요! 지구별에서 온 요원 링키예요. 짝꿍 미션 카드에 대해 궁금한 점을 물어보세요.")]
        # 앞 대화의 번호 — 다음 질문에 넘겨 앞에서 한 이야기를 이어서 답하게 한다
        st.session_state.chat_last_id = None

    with st.container(key="chatbot"):
        with st.popover("링키", help="링키에게 물어보기"):
            st.markdown("**지구별 링키 상담 챗봇**")
            # 무엇을 할지 고르는 메뉴 — 서비스 문의는 대화, 미션 카드 만들기는 화면 2 미션 카드를 AI 카드로 바꾼다
            mode = st.segmented_control(
                "메뉴", ["서비스 문의", "미션 카드 만들기"], default="서비스 문의",
                key="chat_mode", label_visibility="collapsed",
            )
            if mode == "미션 카드 만들기":
                chat_card_maker()
                return

            # 링키가 답할 말투 — 고른 말투의 쓰는 법이 질문 뒤에 붙는다 (앞서 한 답은 그대로 둔다)
            tone = st.selectbox("말투", list(CHAT_TONES), key="chat_tone")

            messages = st.container(height=320)
            # 대화 한 줄은 (누가, 글, AI가 쓴 답인지) — 예전에 쌓인 두 칸짜리 줄은 AI 답이 아닌 것으로 본다
            for role, text, *ai_written in st.session_state.chat:
                show_chat(messages, role, text, bool(ai_written and ai_written[0]))

            # 오늘 물어본 횟수 — 날짜가 바뀌면 0번부터 다시 센다
            today = datetime.now(KST).date().isoformat()
            used = st.session_state.chat_count
            if used["day"] != today:
                used.update(day=today, count=0)
            left = CHAT_LIMIT - used["count"]

            question = st.chat_input(
                "서비스에 대해 물어보세요" if left > 0 else "오늘 물어볼 수 있는 횟수를 다 썼어요",
                key="chat_question", disabled=left <= 0,
            )
            st.caption(f"서비스 문의는 하루 {CHAT_LIMIT}번까지 — 오늘 {max(left - bool(question), 0)}번 남았어요.")
            if question:
                # 물어본 순간 센다 — 답을 못 받아도 Gemini에 보낸 것은 비용이 들 수 있다
                used["count"] += 1
                st.session_state.chat.append(("user", question))
                show_chat(messages, "user", question)
                ai_written = False
                try:
                    ai = gemini()
                    with messages, st.spinner("답을 생각하는 중..."):
                        interaction = ai.interactions.create(
                            model=AI_MODEL,
                            system_instruction=CHATBOT_RULE + prd_text(),
                            input=question + chat_children_note()
                            + f"\n\n(말투: {tone} — {CHAT_TONES.get(tone, '')})" + CHAT_FORMAT_REMINDER,
                            previous_interaction_id=st.session_state.chat_last_id,
                        )
                    answer = mentor_words((interaction.output_text or "").strip())
                    ai_written = bool(answer) and is_safe(answer)
                    if not answer:
                        # 가끔 빈 답이 온다 — 다음 질문이 이 질문에 이어 답하지 않게 대화 번호도 넘기지 않는다
                        answer = "답을 받지 못했어요. 한 번 더 물어봐 주세요."
                    elif not ai_written:
                        answer = "그 내용은 답할 수 없어요. 짝꿍 미션 카드 서비스에 대해 물어봐 주세요."
                    if answer and ai_written:
                        st.session_state.chat_last_id = interaction.id
                    # Gemini가 답을 준 경우만 남긴다 (오류로 못 받은 것은 남기지 않는다)
                    got_answer = True
                except Exception as e:
                    got_answer = False
                    if "429" in str(e) or "Rate limit" in str(e):
                        answer = "오늘 AI 사용 한도를 다 썼어요. 내일 다시 물어봐 주세요."
                    else:
                        answer = "지금 링키가 바빠서 답을 받지 못했어요.  \n잠시 뒤 다시 물어봐 주세요."
                st.session_state.chat.append(("assistant", answer, ai_written))
                show_chat(messages, "assistant", answer, ai_written)
                if got_answer:
                    # 저장에 실패해도 대화는 그대로 이어 간다
                    try:
                        save_chat(question, answer)
                    except Exception as e:
                        if CHAT_TABLE in str(e):
                            st.caption(f"Supabase에 {CHAT_TABLE} 표가 없어 이 대화를 남기지 못했어요.")
                        elif "row-level security" in str(e):
                            st.caption(f"Supabase {CHAT_TABLE} 표에 저장을 허용하는 정책이 없어요.")
                        else:
                            st.caption("이 대화를 남기지 못했어요.  \n대화는 그대로 이어 갈 수 있어요.")

            chat_history()


# 챗봇을 화면보다 먼저 그린다 — 챗봇에서 만든 AI 미션 카드가 같은 실행에서 화면 2에 바로 나오게 (아이콘은 CSS로 오른쪽 아래에 떠 있다)
chatbot()

{
    "s1": screen_1,
    "s1_card": screen_1_card,
    "s1_1": screen_1_1,
    "s_finale": screen_finale,
    "s2": screen_2,
    "s2_1": screen_2_1,
    "s3": screen_3,
}[st.session_state.screen]()

if st.session_state.popup == "p1":
    popup_1()
elif st.session_state.popup == "p2":
    popup_2()
