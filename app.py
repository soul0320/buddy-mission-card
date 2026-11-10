import base64
import html
import json
import os
import random
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import io

import altair as alt
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 화면 없이 그림 파일로만 그린다 (서버용)
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import statsmodels.formula.api as smf
from scipy.stats import chi2_contingency
import streamlit as st
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import MaxNLocator
from dotenv import load_dotenv
# 멘토링 보고서 PDF — 한글 글꼴을 넣은 PDF를 만들고, 막대 그래프도 직접 그린다
from fpdf import FPDF
from fpdf.enums import XPos, YPos
# 멘토링 보고서 Word(.docx) — 내려받아 Word 에서 고칠 수 있게
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
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
        /* 넓은 화면에서 사이드바를 펼쳐도 본문이 오른쪽으로 쏠리지 않고 가운데에 오게 */
        margin-left: auto !important;
        margin-right: auto !important;
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

    /* ===== 유코마블 공통 디자인 — 색은 .streamlit/config.toml 테마와 같은 남색·하늘색·노랑·크림 ===== */
    /* 바탕: 위쪽만 살짝 짙은 하늘색으로 번지게 */
    .stApp {
        background: linear-gradient(180deg, #E4F1FD 0px, #F6FAFF 260px) fixed;
    }
    /* 로고 글씨 — 흰 글자에 두꺼운 먹색 외곽선, 오른쪽 아래로 떨어지는 그림자 (시작 화면 제목과 같은 꼴) */
    .yuco-logo {
        font-family: "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif;
        font-weight: 900;
        color: #FFFFFF;
        -webkit-text-stroke: 6px #14182B;
        paint-order: stroke fill;
        text-shadow: 2px 4px 0 #14182B;
        letter-spacing: .01em;
        line-height: 1.15;
    }
    /* 화면 1~3 맨 위 머리 줄 — 작은 로고 + 서비스 이름 */
    .yuco-head {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 4px 0 6px;
    }
    /* 작은 로고는 외곽선·그림자를 줄여야 글자 속 빈칸이 뭉개지지 않는다 */
    .yuco-head .yuco-logo {
        font-size: 26px;
        -webkit-text-stroke: 4px #14182B;
        text-shadow: 1.5px 3px 0 #14182B;
    }
    .yuco-head .yuco-tag {
        background: #1E2A5A;
        color: #FFD84D;
        border-radius: 999px;
        padding: 3px 11px;
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
    }
    /* 화면 제목(소제목) — 남색 굵은 글씨 */
    [data-testid="stMainBlockContainer"] h3 {
        color: #1E2A5A;
        letter-spacing: -.01em;
    }
    /* 주 버튼 — 남색 바탕에 노란 글자, 살짝 뜬 그림자 */
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"],
    [data-testid="stDialog"] [data-testid="stBaseButton-primary"] {
        box-shadow: 0 6px 14px rgba(30, 42, 90, .22);
        border: none;
    }
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"] p,
    [data-testid="stDialog"] [data-testid="stBaseButton-primary"] p {
        color: #FFD84D;
        font-weight: 800;
    }
    /* 아직 누를 수 없는 주 버튼 — 노란 글자는 회색 바탕에서 안 읽히므로 흐린 남색으로, 그림자도 뺀다 */
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"]:disabled {
        box-shadow: none;
        background: #E3ECF7;
    }
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"]:disabled p {
        color: rgba(27, 34, 64, .4);
    }
    /* 보조 버튼 — 흰 바탕, 남색 글자 */
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] {
        background: #FFFFFF;
    }
    [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] p {
        color: #1E2A5A;
        font-weight: 700;
    }

    /* ===== 사이드바 — 쨍한 남색 대신 옅은 안개빛 바탕에 흰 카드, 강조는 남색 글자 + 노란 형광펜 ===== */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #F5F8FC 0%, #EDF2F8 100%);
        border-right: 1px solid #E1E8F1;
    }
    .yuco-side-brand { text-align: center; padding: 6px 0 2px; }
    .yuco-side-brand .yuco-logo { font-size: 32px; }
    .yuco-side-brand .yuco-side-en {
        color: #8A97B8;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .38em;
        margin-top: 6px;
    }
    .yuco-side-card {
        background: #FFFFFF;
        border: 1px solid #E1E8F1;
        border-radius: 16px;
        padding: 14px 14px 12px;
        margin-top: 14px;
        font-size: 14px;
        line-height: 1.6;
        color: #3A4670;
        box-shadow: 0 2px 10px rgba(30, 42, 90, .05);
    }
    .yuco-side-card b {
        color: #1E2A5A;
        background: linear-gradient(transparent 62%, #FFE9A8 62%);
    }
    .yuco-side-title {
        color: #7584AA;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: .12em;
        margin-bottom: 6px;
    }
    .yuco-side-title.side-report { margin: 18px 0 8px 2px; }
    .yuco-side-steps { margin: 0; padding-left: 18px; }
    .yuco-side-steps li { margin: 2px 0; }
    /* 보고서 기간 띠 — 언제부터 언제까지인지 제목 바로 아래에 크게 */
    .yuco-period { display: inline-flex; align-items: center; gap: 10px; flex-wrap: wrap;
        background: #FFFFFF; border: 1px solid #DCE5F0; border-left: 4px solid #1E2A5A;
        border-radius: 12px; padding: 8px 14px; margin: 2px 0 6px;
        color: #1E2A5A; font-weight: 700; font-size: 15px; box-shadow: 0 2px 8px rgba(30, 42, 90, .04); }
    .yuco-period-k { background: #FFE9A8; color: #1E2A5A; border-radius: 999px; padding: 1px 10px;
        font-size: 12px; font-weight: 800; }
    /* 보고서 숫자 칸 — 한 줄에 4칸, 옅은 하늘색 바탕에 남색 숫자 */
    .yuco-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 4px 0 14px; }
    .yuco-kpi { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 14px;
        padding: 10px 6px 9px; text-align: center; box-shadow: 0 2px 8px rgba(30, 42, 90, .04); }
    .yuco-kpi-l { font-size: 12px; color: #6B7BA6; font-weight: 700; }
    .yuco-kpi-v { font-size: 19px; color: #1E2A5A; font-weight: 800; margin-top: 2px; }
    /* 보고서 필터 카드 — 소개 카드와 같은 흰 카드 */
    [data-testid="stSidebar"] .st-key-report_box {
        background: #FFFFFF;
        border-radius: 16px;
        box-shadow: 0 2px 10px rgba(30, 42, 90, .05);
    }
    /* 사이드바 주 버튼 — 본문과 같은 남색 바탕에 노란 글자 */
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {
        color: #FFD84D;
        font-weight: 800;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:disabled {
        background: #E3ECF7;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:disabled p {
        color: rgba(27, 34, 64, .4);
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

# 지금 보고 있는 화면: "s_start"(시작 화면), "s1"(화면 1), "s1_1"(화면 1-1), "s2"(화면 2), "s2_1"(화면 2-1), "s3"(화면 3)
# 앱을 열면 유코마블 표지(시작 화면)부터 나온다
if "screen" not in st.session_state:
    st.session_state.screen = "s_start"
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


def child_sort_key(name):
    # "아동 A"~"아동 Z"는 알파벳 순서로 먼저, 그 밖의 이름은 가나다순으로 뒤에
    m = re.fullmatch(r"아동 ([A-Z])", name)
    return (0, m.group(1)) if m else (1, name)


def next_child_name(children):
    # [+ 이름 추가] 칸에 미리 넣을 이름 — 쓰지 않은 가장 앞 알파벳 (A~H가 있으면 "아동 I"), 다 쓰면 빈칸
    used = {m.group(1) for n in children if (m := re.fullmatch(r"아동 ([A-Z])", n))}
    return next((f"아동 {c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in used), "")


def count_of(name):
    return st.session_state.mission_count.get(name, 0)


def register_child(name):
    # [+ 이름 추가]로 넣은 아동을 children.csv 에 이어 적는다 — 명단 번호 다음 번호(C08 다음이면 C09)를 준다
    # 그래서 Supabase 에도 C09 처럼 명단과 같은 순서의 번호가 남고, 보고서에서도 실명으로 되돌릴 수 있다
    # (성향·기피는 비워 둔다 — 성향 데이터가 없는 아동으로 보고 아이스브레이킹 카드가 나온다)
    if name in NAME_TO_ID:
        return NAME_TO_ID[name]
    nums = [int(m.group(1)) for cid in NAME_TO_ID.values() if (m := re.fullmatch(r"C(\d+)", cid))]
    child_id = f"C{max(nums, default=0) + 1:02d}"
    path = DATA_DIR / "children.csv"
    text = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8", newline="") as f:
        if text and not text.endswith("\n"):
            f.write("\n")
        f.write(f"{child_id},{name.replace(',', ' ')},,,0\n")
    NAME_TO_ID[name] = child_id
    load_data.clear()  # 다음 실행부터 새 명단을 읽는다
    return child_id


def id_of(name):
    # children.csv의 child_id — 명단에 없으면(예전 방식으로 넣은 아동) 임시 번호를 붙인다
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


# 시작 화면은 표지만 크게 보여 주고, 나머지 화면 위에만 안내 한 줄과 제목을 단다
if st.session_state.screen != "s_start":
    # 머리 줄 — 작은 유코마블 로고 + 서비스 이름 (시작 화면 표지와 같은 로고 꼴)
    st.markdown(
        '<div class="yuco-head"><span class="yuco-logo">유코마블</span>'
        '<span class="yuco-tag">짝꿍 미션 카드</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("반응 기록은 Supabase에 저장됩니다.")

# 왼쪽 사이드바 — 로고, 이 서비스가 무엇을 해 주는지 한 줄 소개(PRD 한 줄 정의·목표 참고), 쓰는 순서
st.sidebar.markdown(
    '<div class="yuco-side-brand"><div class="yuco-logo">유코마블</div>'
    '<div class="yuco-side-en">YUCO MARBLE</div></div>'
    '<div class="yuco-side-card"><div class="yuco-side-title">짝꿍 미션 카드</div>'
    '아이 성향에 맞는 <b>짝꿍 미션</b>과 <b>코칭 가이드</b>를 바로 보여 주고, '
    '미션 직후 <b>1초 피드백</b>으로 다음 미션에 반영해 주는 멘토용 서비스입니다.</div>'
    '<div class="yuco-side-card"><div class="yuco-side-title">쓰는 순서</div>'
    '<ol class="yuco-side-steps"><li>참여 아동 전체 선택</li><li>칭찬 카드 쓰기</li>'
    '<li>미션칸 도착 아동 선택</li><li>짝꿍 미션 · 코칭 가이드</li><li>또래관계 체크</li></ol></div>',
    unsafe_allow_html=True,
)


# 시작 화면 — 유코마블 사용설명서 표지 느낌: 하늘색 배경, 보드판 칸 테두리(START·FOOD·GAME·FINISH), 가운데 큰 제목
# 칸 그림은 나라별 음식·놀이 이모지. 위 줄은 음식, 오른쪽은 건물·물건, 아래 줄은 놀이, 왼쪽은 화살표와 전통 물건
COVER_TOP = ["START", "🍛", "🥐", "🍢", "🥘", "🍵", "FOOD"]
COVER_RIGHT = ["🏛️", "🗝️", "⛺", "🐚", "🎲"]
COVER_BOTTOM = ["GAME", "🪁", "🥁", "🧩", "🎐", "🪀", "FINISH"]
COVER_LEFT = ["⬇️", "🪆", "🏮", "🪭", "⚖️"]
COVER_CSS = """
<style>
.yuco { border-radius: 26px; overflow: hidden; padding: 16px 12px 18px;
  background: linear-gradient(180deg, #4F9DE6 0%, #7DBDF3 55%, #A9D6FA 100%);
  box-shadow: 0 18px 40px rgba(30, 42, 90, .28); }
.yuco-band { text-align: center; color: #fff; font-weight: 800; font-size: 11px;
  letter-spacing: .38em; opacity: .92; margin: 2px 0 12px; }
.yuco-band.bottom { margin: 12px 0 0; letter-spacing: .12em; font-weight: 700; opacity: .85; }
.yuco-board { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px;
  background: rgba(30, 42, 90, .55); border: 1.5px solid #1E2A5A; border-radius: 8px; overflow: hidden; }
.yt { aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
  background: #FFF5E1; font-size: 21px; }
.yt.corner { background: #FFD84D; color: #1E2A5A; font-weight: 900; font-size: 10.5px; letter-spacing: .02em; }
.yuco-center { grid-column: 2 / 7; grid-row: 2 / 7; position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
  background: radial-gradient(circle at 50% 42%, #F4FBFF 0%, #D6EEFF 58%, #BCE1FA 100%); }
.yuco-pill { background: #14182B; color: #fff; border-radius: 999px; padding: 4px 14px;
  font-size: 12px; font-weight: 800; letter-spacing: .1em; }
/* 제목 로고 — 흰 글자 + 두꺼운 먹색 외곽선(글자 뒤에 깔림) + 오른쪽 아래로 떨어지는 먹색 그림자 */
.yuco-title { font-size: 50px; -webkit-text-stroke: 10px #14182B;
  text-shadow: 3px 6px 0 #14182B, 0 14px 20px rgba(30, 42, 90, .25); }
.yuco-sub { background: #1E2A5A; color: #FFD84D; border-radius: 999px; padding: 5px 14px;
  font-size: 12px; font-weight: 800; white-space: nowrap; }
.yuco-float { position: absolute; font-size: 30px; filter: drop-shadow(0 5px 6px rgba(30, 42, 90, .25));
  animation: yuco-float 3.4s ease-in-out infinite; }
.yuco-float.tiger { right: 8px; bottom: 6px; font-size: 38px; }
.yuco-float.globe { left: 8px; top: 8px; font-size: 24px; animation-delay: -1.7s; }
@keyframes yuco-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
@media (prefers-reduced-motion: reduce) { .yuco-float { animation: none; } }
/* [유코마블 시작] 버튼 — 표지 제목과 같은 남색 바탕에 노란 글자 */
.st-key-start_btn button { background: #1E2A5A !important; border: none !important; border-radius: 999px;
  min-height: 56px; box-shadow: 0 10px 20px rgba(30, 42, 90, .3); }
.st-key-start_btn button p { color: #FFD84D; font-size: 18px; font-weight: 800; letter-spacing: .04em; }
.st-key-start_btn button:hover { background: #26356F !important; }
</style>
"""


def cover_html():
    # 7×7 보드판: 맨 위 줄 7칸, 맨 아래 줄 7칸, 양옆 5칸씩. 가운데 5×5 칸은 제목 자리
    def tile(t):
        return f'<div class="yt corner">{t}</div>' if t.isascii() else f'<div class="yt">{t}</div>'

    cells = [tile(t) for t in COVER_TOP]
    for row, (left, right) in enumerate(zip(COVER_LEFT, COVER_RIGHT), start=2):
        cells.append(f'<div class="yt" style="grid-row:{row};grid-column:1">{left}</div>')
        cells.append(f'<div class="yt" style="grid-row:{row};grid-column:7">{right}</div>')
    cells.append(
        '<div class="yuco-center">'
        '<span class="yuco-float globe">🌏</span>'
        '<span class="yuco-pill">다문화 보드게임</span>'
        '<div class="yuco-logo yuco-title">유코마블</div>'
        '<span class="yuco-sub">for. 다문화 감수성 강화 놀이</span>'
        '<span class="yuco-float tiger">🐯</span>'
        '</div>'
    )
    cells += [tile(t) for t in COVER_BOTTOM]
    # 줄 앞 공백이 있으면 마크다운이 코드 블록으로 읽으므로 한 줄로 이어 붙인다
    return (
        '<div class="yuco"><div class="yuco-band">YUCO MARBLE</div>'
        f'<div class="yuco-board">{"".join(cells)}</div>'
        '<div class="yuco-band bottom">짝꿍 미션 카드</div></div>'
    )


def screen_start():
    # 시작 화면 — 표지를 보여 주고 [유코마블 시작]을 누르면 화면 1(참여 아동 전체 선택)로 간다
    st.markdown(COVER_CSS, unsafe_allow_html=True)
    st.markdown(cover_html(), unsafe_allow_html=True)
    st.write("")
    st.button("유코마블 시작", type="primary", use_container_width=True,
              on_click=go, args=("s1",), key="start_btn")


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
            # 이름 칸에는 다음 알파벳 이름(아동 H 다음이면 "아동 I")이 미리 들어 있다 — 그대로 [추가]하거나 고쳐 쓴다
            new_name = st.text_input(
                "새로운 아동 이름", value=next_child_name(children),
                placeholder="이름을 입력하세요", label_visibility="collapsed",
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
                    st.error(f"'{new_name}'{josa(new_name, '은')} 이미 목록에 있습니다.")
                else:
                    # 명단 파일에 다음 번호로 저장 — 새로고침하거나 다른 날 보고서를 만들어도 이름이 남는다
                    register_child(new_name)
                    children.append(new_name)
                    # 목록은 늘 ABCD(가나다) 순서로 — 새 아동도 맨 끝이 아니라 제자리에 들어간다
                    children.sort(key=child_sort_key)
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
    "CHAT_FORMAT_RULE", "CHAT_FORMAT_REMINDER", "CHATBOT_RULE", "CHAT_TONES", "REPORT_RULE",
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
# 멘토링 보고서의 핵심 요약·지도 코칭·보고서 초안 지시문 (내용은 ai_rules.md)
REPORT_RULE = SAFE_RULE + AI_RULES["REPORT_RULE"]

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
            ("assistant", f"미션 카드를 만들었어요! 화면의 미션 카드가 **{card['title']}**{josa(card['title'], '로')} 바뀌었어요.")
        )
        st.success(f"화면의 미션 카드가 **{card['title']}**{josa(card['title'], '로')} 바뀌었어요.")


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
                st.warning(f"{', '.join(wrong)}{josa(wrong[-1], '은')} 있는 나라 이름으로 알아보지 못했어요.  \n나라 이름을 다시 적어 주세요.")
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
        st.info(f"이번 미션은 **{mu['team_a'][0]}** 차례입니다.  \n{', '.join(waiting)}{josa(waiting[-1], '은')} 옆에서 응원해 주세요.")
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


# ---------- 멘토링 보고서 (사이드바 → 보고서 화면) ----------
# 게임 중인 화면 — 여기서는 [게임 끝내기]를 누르기 전까지 [멘토링 보고서 제작]이 잠긴다
IN_GAME_SCREENS = {"s1_card", "s1_1", "s2", "s2_1", "s3"}
REACTION_ORDER = ["좋음", "보통", "기피"]
# 막대 색 — 유코마블 색으로, 좋음이 가장 진하게 (남색 · 하늘색 · 주황)
REACTION_COLORS = ["#1E2A5A", "#7DBDF3", "#F2A65A"]
REACTION_RGB = {"좋음": (30, 42, 90), "보통": (125, 189, 243), "기피": (242, 166, 90)}
# 정량 분석용 반응 점수 — 좋음 2 · 보통 1 · 기피 0
REACTION_SCORE = {"좋음": 2, "보통": 1, "기피": 0}
# 미션 번호 → 미션 종류·난이도 (기록에는 미션 번호만 있어 missions.csv 에서 찾는다)
MISSION_INFO = missions_df.set_index("mission_id")[["mission_type", "difficulty"]].to_dict("index")
# 아동 번호 → 성향 목록 (children.csv) — 이름을 모르는 추가 아동은 성향도 없다
TRAITS_BY_ID = {
    row["child_id"]: [t for t in str(row["traits"]).split("|") if t and t != "nan"]
    for _, row in children_df.iterrows()
}
# PDF 한글 글꼴 — 앞에서부터 먼저 있는 파일을 쓴다 (static/ 에 글꼴 파일을 넣으면 그것부터 쓴다)
PDF_FONTS = [
    (Path(__file__).parent / "static" / "report-regular.ttf", Path(__file__).parent / "static" / "report-bold.ttf"),
    (Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")),
]


@st.cache_data(ttl=60, show_spinner=False)
def saved_finales():
    # 피날레 칭찬 카드 릴레이 기록 — 표가 없거나 못 읽으면 빈 목록 (보고서는 반응 기록만으로도 만든다)
    try:
        return client.table(FINALE_TABLE).select("*").execute().data
    except Exception:
        return []


def ended_records():
    # 끝난 회차의 기록만 — 진행 중인 회차(지금 game_no)는 [게임 끝내기]를 누르기 전까지 보고서에 넣지 않는다
    return [r for r in saved_reactions() if (r.get("game_no") or 0) < st.session_state.game_no]


def record_day(r):
    return datetime.fromisoformat(r["created_at"]).astimezone(KST).date()


def range_label(mode, rng):
    a, b = rng
    if mode == "회기별":
        return f"{a}차" if a == b else f"{a}차~{b}차"
    return f"{a:%Y.%m.%d}" if a == b else f"{a:%Y.%m.%d}~{b:%Y.%m.%d}"


WEEKDAYS = "월화수목금토일"


def report_period(rows, rounds):
    # "1차~6차 · 2026.10.14(화) ~ 2026.11.10(화) · 활동일 4일" — 회차와 날짜를 한 줄로 (기록이 없으면 회차만)
    days = sorted({record_day(r) for r in rows})
    round_txt = (f"{rounds[0]}차" if rounds[0] == rounds[-1] else f"{rounds[0]}차~{rounds[-1]}차") if rounds else "회차 없음"
    if not days:
        return round_txt

    def d(x):
        return f"{x:%Y.%m.%d}({WEEKDAYS[x.weekday()]})"

    day_txt = d(days[0]) if days[0] == days[-1] else f"{d(days[0])} ~ {d(days[-1])}"
    return f"{round_txt}  ·  {day_txt}  ·  활동일 {len(days)}일"


def report_kind(kids):
    # 아동 선택 수에 따라 보고서 종류 — 0명: 전체, 1명: 개인, 2명 이상: 관계
    return "전체" if not kids else "개인" if len(kids) == 1 else "관계"


def open_report(mode, rng, kids):
    # [멘토링 보고서 제작] — 고른 범위·아동을 적어 두고 본문을 보고서 화면으로 바꾼다
    label = range_label(mode, rng)
    kind = report_kind(kids)
    st.session_state.report = {
        "mode": mode, "range": rng, "label": label, "kids": list(kids), "kind": kind,
        "key": f"{mode}|{label}|{','.join(kids)}",
    }
    if st.session_state.screen != "s_report":
        st.session_state.report_back = st.session_state.screen
    go("s_report")


# ---- 사이드바 범위 칸 맞추기 — 슬라이더·달력과 직접 입력 칸이 서로 같은 값을 보이게 한다 ----
def sync_rounds_from_slider():
    st.session_state.rep_r_from, st.session_state.rep_r_to = st.session_state.rep_r


def sync_rounds_from_inputs():
    a, b = sorted((st.session_state.rep_r_from, st.session_state.rep_r_to))
    st.session_state.rep_r_from, st.session_state.rep_r_to = a, b
    st.session_state.rep_r = (a, b)


def sync_days_from_calendar():
    picked = st.session_state.rep_d
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        st.session_state.rep_d_txt = f"{picked[0]:%Y/%m/%d}~{picked[1]:%Y/%m/%d}"
        st.session_state.rep_d_err = None


def sync_days_from_text(lo, hi):
    # "2026/11/01~2026/11/10" (점·빗금·붙임표 모두 허용) 을 읽어 달력 칸에 넣는다 — 기록이 있는 날짜 범위로 맞춘다
    m = re.fullmatch(
        r"\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*[~\-–]\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*",
        st.session_state.rep_d_txt,
    )
    try:
        a, b = sorted((date(*map(int, m.group(1, 2, 3))), date(*map(int, m.group(4, 5, 6)))))
    except (AttributeError, ValueError):
        st.session_state.rep_d_err = "날짜를 2026/11/01~2026/11/10 처럼 적어 주세요."
        return
    a, b = max(a, lo), min(b, hi)
    if a > b:
        st.session_state.rep_d_err = f"기록이 있는 날짜는 {lo:%Y/%m/%d}~{hi:%Y/%m/%d} 이에요."
        return
    st.session_state.rep_d = (a, b)
    st.session_state.rep_d_txt = f"{a:%Y/%m/%d}~{b:%Y/%m/%d}"
    st.session_state.rep_d_err = None


def round_controls(rounds):
    # [회기별] — 슬라이더로 끌어서 고르거나, 아래 두 칸에 n회~nn회를 직접 적는다
    ss = st.session_state
    lo, hi = rounds[0], rounds[-1]
    # 끝난 회차가 늘거나 줄었으면 저장된 값을 새 범위 안으로 맞춘다 (위젯을 그리기 전에만 바꿀 수 있다)
    a, b = ss.get("rep_r", (lo, hi))
    a, b = min(max(a, lo), hi), min(max(b, lo), hi)
    if ss.get("rep_r") != (a, b):
        ss.rep_r = (a, b)
        ss.rep_r_from, ss.rep_r_to = a, b
    ss.setdefault("rep_r_from", a)
    ss.setdefault("rep_r_to", b)
    st.slider("회차", lo, hi, key="rep_r", format="%d차", on_change=sync_rounds_from_slider)
    c1, c2 = st.columns(2)
    c1.number_input("시작 회차", lo, hi, step=1, key="rep_r_from", on_change=sync_rounds_from_inputs)
    c2.number_input("끝 회차", lo, hi, step=1, key="rep_r_to", on_change=sync_rounds_from_inputs)
    return ss.rep_r


def day_controls(days):
    # [기간별] — 달력에서 고르거나, 아래 칸에 nnnn/nn/nn~nnnn/nn/nn 을 직접 적는다
    ss = st.session_state
    lo, hi = days[0], days[-1]
    cur = ss.get("rep_d")
    if not (isinstance(cur, (tuple, list)) and len(cur) == 2 and lo <= cur[0] <= cur[1] <= hi):
        if not (isinstance(cur, (tuple, list)) and len(cur) == 1):  # 끝 날짜를 고르는 중이면 그대로 둔다
            ss.rep_d = (lo, hi)
            ss.rep_d_txt = f"{lo:%Y/%m/%d}~{hi:%Y/%m/%d}"
    ss.setdefault("rep_d_txt", f"{lo:%Y/%m/%d}~{hi:%Y/%m/%d}")
    st.date_input("기간", min_value=lo, max_value=hi, format="YYYY/MM/DD", key="rep_d",
                  on_change=sync_days_from_calendar)
    st.text_input("직접 입력", key="rep_d_txt", placeholder="2026/11/01~2026/11/10",
                  on_change=sync_days_from_text, args=(lo, hi))
    if ss.get("rep_d_err"):
        st.caption(ss.rep_d_err)
    picked = ss.rep_d
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        return tuple(picked)
    st.caption("끝 날짜도 골라 주세요.")
    return None


def report_sidebar():
    # 사이드바 — [회기별](회차 범위) / [기간별](날짜) 필터, 아동 선택(검색·여러 명), [멘토링 보고서 제작] 버튼
    with st.sidebar:
        st.markdown('<div class="yuco-side-title side-report">멘토링 보고서</div>', unsafe_allow_html=True)
        with st.container(border=True, key="report_box"):
            try:
                rows = ended_records()
            except Exception:
                rows = []
                st.caption("기록을 불러오지 못했어요.  \n인터넷 연결을 확인해 주세요.")
            mode = st.segmented_control(
                "범위", ["회기별", "기간별"], default="회기별", key="rep_mode", width="stretch"
            ) or "회기별"
            rng = None
            if not rows:
                st.caption("아직 끝난 회차 기록이 없어요.")
            elif mode == "회기별":
                rounds = sorted({r["game_no"] for r in rows})
                if len(rounds) == 1:
                    st.caption(f"고를 수 있는 회차 : {rounds[0]}차")
                    rng = (rounds[0], rounds[0])
                else:
                    rng = round_controls(rounds)
            else:
                rng = day_controls(sorted({record_day(r) for r in rows}))

            # 아동 선택 — 비우면 전체, 1명이면 개인 리포트, 여러 명(AB, ABC …)이면 관계 리포트
            ids = sorted({c for r in rows for c in child_list(r["child_ids"])})
            by_name = {report_name(c): c for c in ids}
            picked = st.multiselect(
                "아동 선택", child_order(by_name), key="rep_kids",
                placeholder="이름 검색 · 비우면 전체 보고서",
            )
            kind = report_kind(picked)
            st.caption({"전체": "아동을 고르지 않으면 전체 보고서를 만들어요.",
                        "개인": "개인 리포트 + 개인 맞춤 지도 코칭을 만들어요.",
                        "관계": "고른 아동끼리의 상호 관계 리포트 + 관계 맞춤 지도 코칭을 만들어요."}[kind])
            in_game = st.session_state.screen in IN_GAME_SCREENS
            st.button(
                "멘토링 보고서 제작", type="primary", use_container_width=True, key="report_btn",
                disabled=in_game or rng is None, on_click=open_report,
                args=(mode, rng, [by_name[n] for n in picked]),
            )
            if in_game:
                st.caption("게임 진행 중이에요.  \n[게임 끝내기]를 누른 뒤 만들 수 있어요.")


def report_name(child_id):
    # 다른 날 [+ 이름 추가]로 넣은 아동은 이름을 알 수 없어 번호만 남는다 — "추가 아동 N01"로 보여 준다
    name = name_of(child_id)
    return f"추가 아동 {child_id}" if name == child_id else name


def child_order(names):
    # 명단 아동을 먼저(이름순), 이름을 모르는 추가 아동은 맨 뒤에
    return sorted(names, key=lambda n: (n.startswith("추가 아동"), n))


def report_data(rep):
    # 고른 범위의 기록 — 반응(아동 한 명당 한 줄로 펼침), 스킵, 피날레, 회차 목록
    a, b = rep["range"]
    if rep["mode"] == "회기별":
        rows = [r for r in ended_records() if a <= r["game_no"] <= b]
    else:
        rows = [r for r in ended_records() if a <= record_day(r) <= b]
    rounds = sorted({r["game_no"] for r in rows})
    finales = [f for f in saved_finales() if f.get("game_no") in rounds]
    # 아동 한 명당 한 줄 — 정량 분석에 쓸 변수(미션 종류·난이도·인원·함께한 아동)도 함께 담는다
    long = []
    for i, r in enumerate(rows):
        if r.get("feedback_type") == "skip" or r.get("reaction") not in REACTION_ORDER:
            continue
        kids = child_list(r["child_ids"])
        info = MISSION_INFO.get(r.get("mission_id"), {})
        for c in kids:
            long.append({
                "child_id": c, "아동": report_name(c), "회차": r["game_no"], "반응": r["reaction"],
                "점수": REACTION_SCORE[r["reaction"]],
                # AI 미션 카드는 missions.csv 에 없어 종류·난이도를 모른다
                "미션종류": info.get("mission_type") or "AI 미션 카드",
                "난이도": info.get("difficulty") or "미정",
                "인원": len(kids),
                "기록": i,
                "함께한": ",".join(k for k in kids if k != c),
            })
    df = pd.DataFrame(long, columns=["child_id", "아동", "회차", "반응", "점수", "미션종류", "난이도", "인원", "기록", "함께한"])
    skips = [r for r in rows if r.get("feedback_type") == "skip"]
    return rows, df, skips, finales, rounds


def report_ai_input(rep, rows, df, skips, finales, rounds):
    # Gemini에 보내는 기록 — 아동은 번호(child_id)로만 보낸다 (메모도 저장할 때 이미 번호로 바뀌어 있다)
    out = [f"범위: {rep['mode']} {rep['label']}", "회차: " + ", ".join(f"{n}차" for n in rounds), "", "[아동별 회차별 반응]"]
    for cid, g in df.groupby("child_id"):
        parts = []
        for n, gg in g.groupby("회차"):
            c = gg["반응"].value_counts()
            parts.append(f"{n}차 " + " ".join(f"{k}{c.get(k, 0)}" for k in REACTION_ORDER))
        out.append(f"{cid}: " + " / ".join(parts))
    skip_count = Counter(SKIP_LABELS.get(r.get("skip_reason"), "기타") for r in skips)
    out += ["", "[스킵 이유]"] + ([f"{k} {v}번" for k, v in skip_count.items()] or ["없음"])
    memos = [f"{r['game_no']}차: {r['memo']}" for r in rows if r.get("memo")][:30]
    out += ["", "[멘토 메모]"] + (memos or ["없음"])
    hes = [f"{f['game_no']}차: {', '.join(child_list(f.get('hesitant_ids'))) or '없음'}" for f in finales]
    out += ["", "[피날레에서 머뭇거린 아동]"] + (hes or ["기록 없음"])
    return "\n".join(out)


def parse_report(text):
    # "[요약]" 아래 '-' 세 줄, "[코칭]" 아래 '-' 줄들, "[초안]" 아래 문단으로 나눈다
    def bullets(block):
        # 줄 앞의 목록 표시(-, •, ·, "1." "2)")만 뗀다 — "1차부터"의 1 같은 글 속 숫자는 그대로 둔다
        lines = [re.sub(r"^\s*(?:[-•·*]|\d+[.)])\s*", "", line).strip() for line in block.splitlines()]
        return [line for line in lines if line]

    head, _, draft = text.partition("[초안]")
    summ, _, rest = head.partition("[코칭]")
    coach, _, report_coach = rest.partition("[보고서 코칭]")
    return (bullets(summ.replace("[요약]", ""))[:3], bullets(coach)[:4],
            bullets(report_coach)[:4], draft.strip())


def names_to_ids(lines, df):
    # 정량 분석 문장의 아동 이름을 번호로 — Gemini 에는 실명을 보내지 않는다 (긴 이름부터 바꾼다)
    pairs = dict(zip(df["아동"], df["child_id"]))
    out = []
    for line in lines:
        for name in sorted(pairs, key=len, reverse=True):
            line = line.replace(name, pairs[name])
        out.append(line)
    return out


def make_report_text(rep, rows, df, skips, finales, rounds, stats_lines=(), focus_lines=()):
    # 핵심 요약 · 지도 코칭 · 보고서 초안 — 실패하거나 규칙에 어긋나면 (None, 이유)
    kind, kids = rep.get("kind", "전체"), rep.get("kids", [])
    focus = f"[보고서 종류] {kind}" + (f" — 대상: {', '.join(kids)}" if kids else " — 고른 범위의 아동 전체")
    try:
        ai = gemini()
        with st.spinner("AI가 요약 · 지도 코칭 · 보고서 초안을 쓰는 중..."):
            interaction = ai.interactions.create(
                model=AI_MODEL,
                system_instruction=REPORT_RULE,
                input=report_ai_input(rep, rows, df, skips, finales, rounds)
                + "\n\n[정량 분석 결과]\n" + "\n".join(stats_lines)
                + "\n\n" + focus + ("\n[대상 지표]\n" + "\n".join(focus_lines) if focus_lines else ""),
            )
        out = (interaction.output_text or "").strip()
    except Exception as e:
        return None, friendly_ai_error(e, "AI 요약을 만들지 못해 기본 요약을 보여 드려요")
    summary, coaching, report_coaching, draft = parse_report(out)
    if len(summary) < 3 or len(coaching) < 2 or len(report_coaching) < 2 or not draft or not is_safe(out):
        return None, "AI 답이 형식에 맞지 않아 기본 요약을 보여 드려요."
    # coaching = 화면 [지도 코칭] 탭(멘토용 말투), report_coaching = 보고서에 들어가는 보고서 문체
    return {"summary": summary, "coaching": coaching, "report_coaching": report_coaching, "draft": draft, "ai": True}, None


def fallback_report(rep, df, skips, finales, n_missions, c, focus_lines=(), coaching=(), report_coaching=()):
    # AI를 못 쓸 때의 기본 요약·코칭·초안 — 기록 숫자만으로 만든다 (c = 미션 건수로 센 좋음·보통·기피)
    kids = df["child_id"].nunique()
    good = df[df["반응"] == "좋음"]["child_id"].value_counts()
    top = f"{good.index[0]}({good.iloc[0]}번)" if len(good) else "아직 없습니다"
    skip_count = Counter(SKIP_LABELS.get(r.get("skip_reason"), "기타") for r in skips)
    skip_text = f" ({', '.join(f'{k} {v}번' for k, v in skip_count.items())})" if skip_count else ""
    hes = {cid for f in finales for cid in child_list(f.get("hesitant_ids"))}
    reactions = f"좋음 {c.get('좋음', 0)}건 · 보통 {c.get('보통', 0)}건 · 기피 {c.get('기피', 0)}건"
    if focus_lines:
        summary = list(focus_lines[:3])
    else:
        summary = [
            f"{rep['label']} 동안 아동 {kids}명이 짝꿍 미션 {n_missions}건에 참여했고, 반응은 {reactions}이었습니다.",
            f"'좋음'이 가장 많았던 아동은 {top}.",
            f"스킵은 {len(skips)}번{skip_text}이었고, 피날레에서 머뭇거린 아동은 {len(hes)}명입니다.",
        ]
    draft = "\n\n".join([
        f"{rep['label']} 동안 유코마블 보드게임과 짝꿍 미션 카드로 아동 {kids}명과 또래 상호작용 활동을 진행했습니다. "
        f"짝꿍 미션은 모두 {n_missions}건이었습니다.",
        f"미션 직후 멘토가 기록한 또래관계 반응은 {reactions}이었습니다."
        + (" " + " ".join(focus_lines) if focus_lines else f" '좋음'이 가장 많았던 아동은 {top}."),
        report_coaching[-1] if report_coaching else "다음 회기에는 아직 낯설어하는 아동이 부담 없이 참여할 수 있는 짝꿍 미션을 이어 갈 예정입니다.",
    ])
    return {"summary": summary, "coaching": list(coaching), "report_coaching": list(report_coaching), "draft": draft, "ai": False}


# 받침 있는 말 뒤 / 없는 말 뒤에 붙는 조사 짝 — 긴 조사부터 찾도록 JOSA_RE 에서 길이순으로 묶는다
JOSA_PAIRS = {
    "과": ("과", "와"), "와": ("과", "와"), "은": ("은", "는"), "는": ("은", "는"),
    "이": ("이", "가"), "가": ("이", "가"), "을": ("을", "를"), "를": ("을", "를"),
    "이랑": ("이랑", "랑"), "랑": ("이랑", "랑"), "이나": ("이나", "나"), "나": ("이나", "나"),
    "이와": ("과", "와"), "으로": ("으로", "로"), "로": ("으로", "로"),
    "이에요": ("이에요", "예요"), "예요": ("이에요", "예요"), "이었다": ("이었다", "였다"), "였다": ("이었다", "였다"),
}
JOSA_RE = "|".join(sorted(JOSA_PAIRS, key=len, reverse=True))


def final_consonant(word):
    # 마지막 글자의 받침 — 없으면 "", ㄹ이면 "ㄹ", 그 밖의 받침은 "o"
    # 한글은 글자 코드로, 영문 끝 글자(아동 A 등)는 읽는 소리(엘=ㄹ, 엠·엔=받침)로, 숫자도 읽는 소리로
    last = word.strip()[-1:]
    if "가" <= last <= "힣":
        jong = (ord(last) - ord("가")) % 28
        return "" if jong == 0 else "ㄹ" if jong == 8 else "o"
    if last.upper() in "LR" or last in "178":
        return "ㄹ"
    if last.upper() in "MN" or last in "036":
        return "o"
    return ""


def has_batchim(word):
    return final_consonant(word) != ""


def josa(word, particle):
    # word 뒤에 붙일 조사를 받침에 맞춰 고른다 — josa("아동 A", "은") → "는", josa("민준", "로") → "으로"
    pair = JOSA_PAIRS[particle]
    if pair == ("으로", "로"):
        # ㄹ 받침 뒤에는 '로' (서울로, 아동 L로)
        return "으로" if final_consonant(word) == "o" else "로"
    return pair[0 if has_batchim(word) else 1]


def ids_to_names(text):
    # 저장된 child_id(C01, N01 …)를 화면·PDF에 보여 줄 때만 실명으로 되돌린다 — 보고서와 [지난 대화 목록]에서 쓴다
    # 긴 번호부터 바꾸고, 다른 번호 속 숫자는 건드리지 않는다. 모르는 번호는 번호 그대로
    # 번호 뒤 조사는 실명 끝 글자에 맞춰 고친다 (C01과 → 아동 A와)
    ids = set(NAME_TO_ID.values()) | set(st.session_state.new_ids.values())
    for cid in sorted(ids, key=len, reverse=True):
        name = name_of(cid)
        # AI가 "C01 아동은"처럼 번호 뒤에 '아동'을 붙이면 "아동 A 아동은"이 되므로 '아동'을 뺀다
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?![0-9])\s*아동", cid, text)

        def swap(m, name=name):
            particle = m.group(1)
            return name + josa(name, particle) if particle else name

        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?![0-9])({JOSA_RE})?(?![가-힣])", swap, text)
        # 조사 뒤에 한글이 바로 이어지는 경우(C01이랑 등)는 이름만 바꾼다
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?![0-9])", name, text)
    return text


def find_pdf_font():
    for regular, bold in PDF_FONTS:
        if regular.exists():
            return regular, bold if bold.exists() else regular
    return None


class ReportPDF(FPDF):
    # 모든 쪽 아래에 서비스 이름과 쪽 번호 (n / 전체)
    def footer(self):
        self.set_y(-13)
        self.set_font("KR", "", 8)
        self.set_text_color(150, 160, 185)
        self.cell(0, 6, f"유코마블 · 짝꿍 미션 카드   ·   {self.page_no()} / {{nb}}", align="C")


def report_pdf(doc):
    # 보고서 PDF — doc: 제목·부제·숫자 칸·요약·코칭·지표 표·정량 분석 문장·그림·보고서 글
    # 여백 20mm, 문단 사이 간격을 넉넉히, 그림은 쪽을 넘기지 않게 크기를 맞춘다
    regular, bold = find_pdf_font()
    pdf = ReportPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=22)
    pdf.add_font("KR", "", str(regular))
    pdf.add_font("KR", "B", str(bold))
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    navy, ink, sub = (30, 42, 90), (27, 34, 64), (98, 112, 150)

    def text(t, size=10.5, style="", color=ink, h=6.6, indent=0):
        pdf.set_font("KR", style, size)
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(width - indent, h, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def section(title):
        if pdf.get_y() > pdf.h - 55:
            pdf.add_page()
        pdf.ln(7)
        text(title, 13, "B", navy, 8)
        pdf.set_draw_color(205, 222, 241)
        pdf.set_line_width(0.4)
        pdf.line(pdf.l_margin, pdf.get_y() + 0.5, pdf.l_margin + width, pdf.get_y() + 0.5)
        pdf.ln(4)

    def bullets(items, numbered=False):
        for i, s in enumerate(items, 1):
            # 쪽 끝에 걸리면 점(•)만 남고 글이 다음 쪽으로 넘어가므로, 한 줄이 들어갈 자리가 없으면 먼저 쪽을 넘긴다
            pdf.set_font("KR", "", 10.5)
            need = 6.6 * max(1, len(pdf.multi_cell(width - 7, 6.6, s, dry_run=True, output="LINES")))
            if pdf.get_y() + need > pdf.page_break_trigger:
                pdf.add_page()
            y = pdf.get_y()
            pdf.set_font("KR", "B", 10.5)
            pdf.set_text_color(*navy)
            pdf.set_xy(pdf.l_margin, y)
            pdf.cell(7, 6.6, f"{i}." if numbered else "•")
            pdf.set_xy(pdf.l_margin + 7, y)
            text(s, 10.5, "", ink, 6.6, indent=7)
            pdf.ln(1.2)

    # 머리 띠
    pdf.set_fill_color(*navy)
    pdf.rect(0, 0, pdf.w, 40, style="F")
    pdf.set_xy(pdf.l_margin, 10)
    text("유코마블 · 짝꿍 미션 카드", 10, "B", (255, 216, 77), 6)
    text(doc["title"], 21, "B", (255, 255, 255), 12)
    pdf.set_y(47)
    text(doc["subtitle"], 10, "", sub, 6)

    # 숫자 칸
    kpis = doc["kpis"]
    pdf.ln(4)
    gap = 3.5
    box_w = (width - gap * (len(kpis) - 1)) / len(kpis)
    top = pdf.get_y()
    for i, (label, value) in enumerate(kpis):
        x = pdf.l_margin + i * (box_w + gap)
        pdf.set_fill_color(234, 243, 252)
        pdf.rect(x, top, box_w, 20, style="F", round_corners=True, corner_radius=3)
        pdf.set_xy(x, top + 3)
        pdf.set_font("KR", "", 8.5)
        pdf.set_text_color(*sub)
        pdf.cell(box_w, 4, label, align="C")
        pdf.set_xy(x, top + 9)
        pdf.set_font("KR", "B", 13.5)
        pdf.set_text_color(*navy)
        pdf.cell(box_w, 7, str(value), align="C")
    pdf.set_y(top + 24)

    section("핵심 요약")
    bullets(doc["summary"])
    if doc.get("coaching"):
        section(doc.get("coaching_title", "지도 코칭"))
        bullets(doc["coaching"], numbered=True)

    table = doc.get("table")
    if table and table["rows"]:
        section(table["title"])
        cols = len(table["header"])
        widths = table.get("widths") or [width / cols] * cols
        scale = width / sum(widths)
        widths = [w * scale for w in widths]
        pdf.set_font("KR", "B", 9)
        pdf.set_fill_color(230, 240, 251)
        pdf.set_text_color(*navy)
        pdf.set_draw_color(214, 226, 240)
        for w, h in zip(widths, table["header"]):
            pdf.cell(w, 8, h, border=1, align="C", fill=True)
        pdf.ln(8)
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(*ink)
        for row in table["rows"]:
            if pdf.get_y() > pdf.h - 32:
                pdf.add_page()
            for w, v in zip(widths, row):
                pdf.cell(w, 7.2, str(v), border=1, align="C")
            pdf.ln(7.2)

    if doc.get("figures"):
        section("정량 분석")
        text("반응 점수 : 좋음 2 · 보통 1 · 기피 0.  p < 0.05 이면 '유의미'. 기록이 적으면 결과가 흔들릴 수 있습니다.", 8.5, "", sub, 5)
        pdf.ln(2)
        if doc.get("stats"):
            bullets(doc["stats"])
        for title, png, ratio in doc["figures"]:
            w = width if ratio >= 1.25 else width * 0.78
            h = w / ratio
            room = pdf.h - 22 - 30
            if h > room:
                w, h = room * ratio, room
            if pdf.get_y() + h + 12 > pdf.h - 22:
                pdf.add_page()
            pdf.ln(3)
            text(title, 10.5, "B", navy, 6.5)
            pdf.ln(1)
            pdf.image(io.BytesIO(png), x=pdf.l_margin + (width - w) / 2, w=w, h=h)
            pdf.ln(3)

    section("보고서")
    for para in [p.strip() for p in doc["draft"].split("\n\n") if p.strip()]:
        text(para, 10.5, "", ink, 7)
        pdf.ln(3)

    pdf.ln(4)
    text("AI가 쓴 초안을 멘토가 확인·수정한 보고서입니다.  © 2026 짝꿍 미션 카드 · YUCO MARBLE", 8, "", (150, 160, 185), 5)
    return bytes(pdf.output())


def report_docx(doc):
    # 같은 내용을 Word 파일로 — 내려받아 Word 에서 마음껏 고칠 수 있다
    d = Document()
    sec = d.sections[0]
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(2))
    navy = RGBColor(0x1E, 0x2A, 0x5A)
    font_name = "Malgun Gothic"
    for style_name in ("Normal", "Title", "Heading 1", "Heading 2", "List Bullet", "List Number"):
        style = d.styles[style_name]
        style.font.name = font_name
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font_name)
    d.styles["Normal"].font.size = Pt(10.5)
    for style_name in ("Title", "Heading 1", "Heading 2"):
        d.styles[style_name].font.color.rgb = navy

    p = d.add_paragraph("유코마블 · 짝꿍 미션 카드")
    p.runs[0].font.size = Pt(9)
    p.runs[0].font.color.rgb = RGBColor(0xB8, 0x8A, 0x00)
    d.add_paragraph(doc["title"], style="Title")
    sub = d.add_paragraph(doc["subtitle"])
    sub.runs[0].font.color.rgb = RGBColor(0x62, 0x70, 0x96)

    kpis = doc["kpis"]
    t = d.add_table(rows=2, cols=len(kpis))
    t.style = "Table Grid"
    for i, (label, value) in enumerate(kpis):
        t.cell(0, i).text = label
        t.cell(1, i).text = str(value)
        t.cell(1, i).paragraphs[0].runs[0].bold = True
        for r in (0, 1):
            t.cell(r, i).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    d.add_heading("핵심 요약", level=1)
    for s in doc["summary"]:
        d.add_paragraph(s, style="List Bullet")
    if doc.get("coaching"):
        d.add_heading(doc.get("coaching_title", "지도 코칭"), level=1)
        for s in doc["coaching"]:
            d.add_paragraph(s, style="List Number")

    table = doc.get("table")
    if table and table["rows"]:
        d.add_heading(table["title"], level=1)
        tt = d.add_table(rows=1, cols=len(table["header"]))
        tt.style = "Table Grid"
        for i, h in enumerate(table["header"]):
            tt.rows[0].cells[i].text = h
            tt.rows[0].cells[i].paragraphs[0].runs[0].bold = True
        for row in table["rows"]:
            cells = tt.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = str(v)

    if doc.get("figures"):
        d.add_heading("정량 분석", level=1)
        d.add_paragraph("반응 점수 : 좋음 2 · 보통 1 · 기피 0.  p < 0.05 이면 '유의미'. 기록이 적으면 결과가 흔들릴 수 있습니다.")
        for s in doc.get("stats", []):
            d.add_paragraph(s, style="List Bullet")
        for title, png, ratio in doc["figures"]:
            d.add_heading(title, level=2)
            d.add_picture(io.BytesIO(png), width=Cm(17 if ratio >= 1.25 else 13))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    d.add_heading("보고서", level=1)
    for para in [p.strip() for p in doc["draft"].split("\n\n") if p.strip()]:
        d.add_paragraph(para)
    sec.footer.paragraphs[0].text = "AI가 쓴 초안을 멘토가 확인·수정한 보고서입니다.  © 2026 짝꿍 미션 카드 · YUCO MARBLE"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------- 정량 분석 (회귀 분석 · 관계 · 성향) ----------
# 반응 점수(좋음 2 · 보통 1 · 기피 0)를 결과로 두고 본다. p < 0.05 이면 '유의미'
MIN_TREND_ROWS = 4      # 아동별 추세 회귀에 필요한 최소 기록 수
SIG_LEVEL = 0.05
SCORE_CMAP = LinearSegmentedColormap.from_list("yuco", ["#F2A65A", "#F6FAFF", "#1E2A5A"])


def plot_style():
    # seaborn 기본 꼴 + 유코마블 색, 한글 글꼴(PDF와 같은 글꼴)
    sns.set_theme(style="whitegrid", rc={
        "axes.edgecolor": "#C8DBF0", "grid.color": "#E6EEF7", "axes.labelcolor": "#1B2240",
        "xtick.color": "#5B6B94", "ytick.color": "#5B6B94", "axes.titleweight": "bold",
    })
    font = find_pdf_font()
    if font:
        font_manager.fontManager.addfont(str(font[0]))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font[0])).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def fig_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def judge(slope, p, n):
    if n < MIN_TREND_ROWS:
        return "기록 부족"
    if p != p:  # p 가 NaN — 반응이 늘 같아 기울기를 따질 수 없다
        return "늘 같은 반응"
    if p < SIG_LEVEL:
        return "유의미하게 좋아짐 ▲" if slope > 0 else "유의미하게 낮아짐 ▼"
    return "뚜렷한 변화 없음"


@st.cache_data(show_spinner=False)
def analyze(df):
    # df: report_data 의 아동별 줄. 결과는 표(DataFrame)와 해석 문장들
    out = {}

    # 1) 아동별 추세 — 반응 점수 ~ 회차 (단순 선형 회귀)
    trend = []
    for child, g in df.groupby("아동"):
        n, rounds = len(g), g["회차"].nunique()
        slope = p = r2 = float("nan")
        if n >= MIN_TREND_ROWS and rounds >= 2:
            if g["점수"].nunique() > 1:
                fit = smf.ols("score ~ rnd", data=pd.DataFrame({"score": g["점수"], "rnd": g["회차"]})).fit()
                slope, p, r2 = fit.params["rnd"], fit.pvalues["rnd"], fit.rsquared
            else:
                slope = 0.0
        trend.append({"아동": child, "기록": n, "회차 수": rounds, "평균 점수": g["점수"].mean(),
                      "기울기(회차당)": slope, "p값": p, "R²": r2, "판정": judge(slope, p, n)})
    out["trend"] = pd.DataFrame(trend).sort_values("아동", key=lambda s: s.map(lambda n: (n.startswith("추가 아동"), n)))

    # 2) 다중 회귀 — 반응 점수 ~ 회차 + 미션 종류 + 난이도 + 성향(아동 2명 이상이 가진 성향만)
    # 함께한 인원은 미션 종류와 겹치므로(개인 미션 = 늘 1명) 넣지 않는다
    # AI 미션 카드 기록은 종류·난이도를 몰라 다중 회귀에서만 뺀다
    known = df[df["미션종류"] != "AI 미션 카드"]
    data = pd.DataFrame({"score": known["점수"], "rnd": known["회차"],
                         "mtype": known["미션종류"], "diff": known["난이도"]})
    labels = {"rnd": "회차(1회차 늘 때)"}
    trait_kids = Counter(t for cid in known["child_id"].unique() for t in TRAITS_BY_ID.get(cid, []))
    terms = ["rnd"]
    for i, (t, k) in enumerate(sorted(trait_kids.items())):
        col = f"t{i}"
        data[col] = known["child_id"].map(lambda c, t=t: int(t in TRAITS_BY_ID.get(c, [])))
        if k >= 2 and 0 < data[col].mean() < 1:
            terms.append(col)
            labels[col] = f"성향: {t}"
    # 미션 종류와 난이도가 거의 같이 움직이면(예: 개인=쉬움, 경쟁=어려움) 둘의 효과를 나눌 수 없다
    # → 크라메르 V(두 범주 변수가 얼마나 겹치는지, 0~1)가 0.8 이상이면 난이도는 빼고 미션 종류만 넣는다
    cat_vars = [("mtype", "미션 종류"), ("diff", "난이도")]
    out["dropped_diff"] = None
    table = pd.crosstab(data["mtype"], data["diff"])
    if min(table.shape) >= 2:
        chi2 = chi2_contingency(table, correction=False)[0]
        v = (chi2 / (table.values.sum() * (min(table.shape) - 1))) ** 0.5
        if v >= 0.8:
            cat_vars = [("mtype", "미션 종류")]
            out["dropped_diff"] = v
    cats = []
    for col, name in cat_vars:
        levels = data[col].value_counts()
        if len(levels) >= 2:
            ref = "개인" if col == "mtype" and "개인" in levels else "쉬움" if col == "diff" and "쉬움" in levels else levels.index[0]
            cats.append(f'C({col}, Treatment(reference="{ref}"))')
            for lv in levels.index:
                if lv != ref:
                    labels[f'C({col}, Treatment(reference="{ref}"))[T.{lv}]'] = f"{name}: {lv} (기준 {ref})"
    k = len(terms) + sum(data[c.split(",")[0][2:]].nunique() - 1 for c in cats)
    fit = None
    if len(data) >= k + 10 and data["score"].nunique() > 1:
        fit = smf.ols("score ~ " + " + ".join(terms + cats), data=data).fit(cov_type="HC3")
        # 변수끼리 완전히 겹치면(한 성향이 한 미션 종류에만 있는 등) 겹치는 성향부터 하나씩 빼고 다시 맞춘다
        while np.linalg.matrix_rank(fit.model.exog) < fit.model.exog.shape[1] and len(terms) > 1:
            terms.pop()
            fit = smf.ols("score ~ " + " + ".join(terms + cats), data=data).fit(cov_type="HC3")
        if np.linalg.matrix_rank(fit.model.exog) < fit.model.exog.shape[1]:
            fit = None
    if fit is not None:
        ci = fit.conf_int()
        coef = pd.DataFrame({
            "변수": [labels.get(v, v) for v in fit.params.index], "계수": fit.params.values,
            "하한": ci[0].values, "상한": ci[1].values, "p값": fit.pvalues.values,
        })
        out["coef"] = coef[coef["변수"] != "Intercept"].reset_index(drop=True)
        out["model"] = {"n": int(fit.nobs), "r2": fit.rsquared, "adj_r2": fit.rsquared_adj,
                        "ai_rows": int((df["미션종류"] == "AI 미션 카드").sum())}
    else:
        out["coef"], out["model"] = None, {"n": len(data), "need": k + 10}

    # 3) 관계 — 함께 미션한 두 아동의 평균 반응 점수 (같은 기록에 둘 다 있을 때)
    pairs = []
    for _, g in df.groupby("기록"):
        names = sorted(g["아동"].unique())
        score = g["점수"].iloc[0]
        pairs += [(a, b, score) for i, a in enumerate(names) for b in names[i + 1:]]
    if pairs:
        pdf_ = pd.DataFrame(pairs, columns=["a", "b", "score"])
        both = pd.concat([pdf_, pdf_.rename(columns={"a": "b", "b": "a"})])
        out["pair_mean"] = both.pivot_table(index="a", columns="b", values="score", aggfunc="mean")
        out["pair_n"] = both.pivot_table(index="a", columns="b", values="score", aggfunc="count")
        top = pdf_.groupby(["a", "b"])["score"].agg(["mean", "count"]).reset_index()
        out["pair_top"] = top[top["count"] >= 2].sort_values(["mean", "count"], ascending=False)
    else:
        out["pair_mean"] = None

    # 4) 성향별 평균 반응 점수
    rows = [(t, s) for cid, s in zip(df["child_id"], df["점수"]) for t in (TRAITS_BY_ID.get(cid) or ["성향 정보 없음"])]
    out["traits"] = pd.DataFrame(rows, columns=["성향", "점수"])
    return out


@st.cache_data(show_spinner=False)
def analysis_figures(df):
    # 정량 분석 그림 4장 — PNG 바이트와 가로·세로 비율. 화면과 PDF 모두 이 그림을 쓴다
    a = analyze(df)
    plot_style()
    figs = {}
    yt = dict(ticks=[0, 1, 2], labels=["기피", "보통", "좋음"])

    # 1) 아동별 추세 — 점(기록), 꺾은선(회차 평균), 회귀선(95% 신뢰 구간)
    kids = list(a["trend"]["아동"])
    cols = 2
    rows_n = -(-len(kids) // cols)
    fig, axes = plt.subplots(rows_n, cols, figsize=(7, 2.3 * rows_n), squeeze=False, sharey=True)
    for ax, (_, t) in zip(axes.flat, a["trend"].iterrows()):
        g = df[df["아동"] == t["아동"]]
        mean = g.groupby("회차")["점수"].mean()
        ax.scatter(g["회차"], g["점수"] + (pd.Series(range(len(g)), index=g.index) % 3 - 1) * 0.04,
                   s=14, color="#7DBDF3", alpha=.8, zorder=2)
        ax.plot(mean.index, mean.values, color="#F2A65A", lw=1.6, marker="o", ms=3.5, zorder=3, label="회차 평균")
        if t["판정"] not in ("기록 부족",) and g["회차"].nunique() >= 2:
            sns.regplot(x=g["회차"], y=g["점수"], ax=ax, scatter=False, ci=95, truncate=True,
                        line_kws={"color": "#1E2A5A", "lw": 2}, color="#1E2A5A")
        mark = "▲" if "좋아짐" in t["판정"] else "▼" if "낮아짐" in t["판정"] else ""
        p_txt = f"p={t['p값']:.3f}" if t["p값"] == t["p값"] else t["판정"]
        ax.set_title(f"{t['아동']} {mark}  ({p_txt})", fontsize=10,
                     color="#1E2A5A" if mark else "#5B6B94")
        ax.set_yticks(**yt)
        ax.set_ylim(-0.3, 2.3)
        ax.set_xlabel("회차", fontsize=8)
        ax.set_ylabel("")
        ax.tick_params(labelsize=8)
        # 회차는 1, 2, 3 … 정수만 (2.5 같은 눈금이 나오지 않게)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    for ax in list(axes.flat)[len(kids):]:
        ax.axis("off")
    fig.tight_layout()
    figs["trend"] = (fig_png(fig), 7 / (2.3 * rows_n))

    # 2) 다중 회귀 계수 — 점과 95% 신뢰 구간, 유의미한 변수는 남색
    if a["coef"] is not None:
        c = a["coef"].iloc[::-1]
        fig, ax = plt.subplots(figsize=(7, 0.42 * len(c) + 1.1))
        colors = ["#1E2A5A" if p < SIG_LEVEL else "#AAB6CC" for p in c["p값"]]
        ax.hlines(range(len(c)), c["하한"], c["상한"], colors=colors, lw=2.2)
        ax.scatter(c["계수"], range(len(c)), color=colors, s=36, zorder=3)
        ax.axvline(0, color="#F2A65A", lw=1.2, ls="--")
        ax.set_yticks(range(len(c)), [f"{v}{' *' if p < SIG_LEVEL else ''}" for v, p in zip(c["변수"], c["p값"])], fontsize=8.5)
        ax.set_xlabel("반응 점수에 주는 영향 (계수, 95% 신뢰 구간)", fontsize=8.5)
        fig.tight_layout()
        figs["coef"] = (fig_png(fig), 7 / (0.42 * len(c) + 1.1))

    # 3) 관계 히트맵 — 함께한 두 아동의 평균 반응 점수, 칸 안에 (함께한 횟수)
    if a["pair_mean"] is not None:
        m, n = a["pair_mean"], a["pair_n"]
        order = sorted(set(m.index) | set(m.columns), key=lambda x: (x.startswith("추가 아동"), x))
        m, n = m.reindex(index=order, columns=order), n.reindex(index=order, columns=order)
        annot = m.round(1).astype(str).where(m.notna(), "") + n.fillna(0).astype(int).map(lambda v: f"\n({v})" if v else "")
        size = max(4.2, 0.62 * len(order) + 1.6)
        fig, ax = plt.subplots(figsize=(size, size * 0.86))
        sns.heatmap(m, annot=annot, fmt="", cmap=SCORE_CMAP, vmin=0, vmax=2, center=1, linewidths=1, linecolor="white",
                    cbar_kws={"label": "평균 반응 점수 (기피 0 · 보통 1 · 좋음 2)", "shrink": .7},
                    annot_kws={"fontsize": 7.5}, ax=ax, square=True)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelsize=8)
        fig.tight_layout()
        figs["pairs"] = (fig_png(fig), size / (size * 0.86))

    # 4) 성향별 평균 반응 점수 — 막대 + 표준오차
    tr = a["traits"]
    order = tr.groupby("성향")["점수"].mean().sort_values(ascending=False).index
    fig, ax = plt.subplots(figsize=(7, 0.38 * len(order) + 1.2))
    sns.barplot(data=tr, y="성향", x="점수", order=order, errorbar="se", color="#1E2A5A", ax=ax,
                err_kws={"color": "#F2A65A", "linewidth": 1.5})
    counts = tr["성향"].value_counts()
    ax.set_yticks(range(len(order)), [f"{o}  (n={counts[o]})" for o in order], fontsize=8.5)
    ax.set_xlim(0, 2.1)
    ax.set_xlabel("평균 반응 점수 (기피 0 · 보통 1 · 좋음 2)", fontsize=8.5)
    ax.set_ylabel("")
    fig.tight_layout()
    figs["traits"] = (fig_png(fig), 7 / (0.38 * len(order) + 1.2))
    return figs


def analysis_lines(a):
    # 정량 분석을 짧은 문장으로 — 화면 해석, PDF, AI 입력에 함께 쓴다 (아동은 화면용 이름)
    lines = []
    sig = a["trend"][a["trend"]["판정"].str.startswith("유의미")]
    if len(sig):
        for _, t in sig.iterrows():
            lines.append(f"{t['아동']}: 회차가 지날수록 반응 점수가 회차당 {t['기울기(회차당)']:+.2f}점 ({t['판정'][:-2]}, p={t['p값']:.3f}, 기록 {t['기록']}건)")
    else:
        lines.append("아동별 추세: 회차에 따라 유의미하게 바뀐 아동은 아직 없습니다 (p<0.05 기준).")
    if a["coef"] is not None:
        sig_c = a["coef"][a["coef"]["p값"] < SIG_LEVEL]
        for _, c in sig_c.iterrows():
            lines.append(f"다중 회귀 — {c['변수']}: 반응 점수 평균 {c['계수']:+.2f}점 (p={c['p값']:.3f})")
        if not len(sig_c):
            lines.append(f"다중 회귀: 유의미한 변수가 없습니다 (기록 {a['model']['n']}건, R²={a['model']['r2']:.2f}).")
    else:
        lines.append(f"다중 회귀: 기록이 {a['model']['n']}건이라 아직 분석하지 않았습니다 ({a['model']['need']}건 이상 필요).")
    if a["pair_mean"] is not None and len(a["pair_top"]):
        best = a["pair_top"].iloc[0]
        lines.append(f"관계: {best['a']}·{best['b']} 짝이 함께한 {int(best['count'])}번의 평균 반응 점수가 {best['mean']:.2f}점으로 가장 높았습니다.")
    return lines


# ---------- 개인 리포트 · 관계 리포트 (아동 선택) ----------
def record_sets(df):
    # 기록(미션 한 건) → (그 미션에 참여한 아동 번호 집합, 반응 점수, 회차)
    return {k: (set(g["child_id"]), g["점수"].iloc[0], g["회차"].iloc[0]) for k, g in df.groupby("기록")}


def child_focus(df, skips, finales, a, cid):
    # 개인 지표 — 참여 수, 평균 점수, 좋음·기피 비율, 추세(단순 회귀), 스킵, 머뭇거림, 미션 종류별·친구별 평균
    g = df[df["child_id"] == cid]
    name = report_name(cid)
    tr = a["trend"].set_index("아동")
    t = tr.loc[name] if name in tr.index else None
    part = g.assign(p=g["함께한"].str.split(",")).explode("p")
    part = part[part["p"].fillna("") != ""]
    partners = part.groupby("p")["점수"].agg(["mean", "count"]).reset_index()
    partners["아동"] = partners["p"].map(report_name)
    types = g.groupby("미션종류")["점수"].agg(["mean", "count"]).reset_index()
    return {
        "name": name, "n": len(g), "rounds": g["회차"].nunique(),
        "mean": g["점수"].mean() if len(g) else float("nan"),
        "good": (g["반응"] == "좋음").mean() if len(g) else 0.0,
        "avoid": (g["반응"] == "기피").mean() if len(g) else 0.0,
        "slope": t["기울기(회차당)"] if t is not None else float("nan"),
        "p": t["p값"] if t is not None else float("nan"),
        "judge": t["판정"] if t is not None else "기록 부족",
        "skips": sum(cid in child_list(r["child_ids"]) for r in skips),
        "hesitant": sum(cid in child_list(f.get("hesitant_ids")) for f in finales),
        "partners": partners.sort_values(["mean", "count"], ascending=False),
        "types": types.sort_values(["mean", "count"], ascending=False),
    }


def relation_focus(df, ids):
    # 관계 지표 — 고른 아동 둘씩: 함께한 횟수·함께 평균·각자 평균·시너지(함께 평균 − 각자 평균의 평균)
    recs = record_sets(df)
    means = df.groupby("child_id")["점수"].mean()
    chosen = set(ids)
    pairs = []
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            joint = [s for kids, s, _ in recs.values() if x in kids and y in kids]
            base = (means.get(x, float("nan")) + means.get(y, float("nan"))) / 2
            jm = sum(joint) / len(joint) if joint else float("nan")
            pairs.append({"짝": f"{report_name(x)}·{report_name(y)}", "a": x, "b": y, "함께한 횟수": len(joint),
                          "함께 평균": jm, "좋음 비율": (sum(s == 2 for s in joint) / len(joint)) if joint else float("nan"),
                          "각자 평균": base, "시너지": jm - base})
    group = [(rnd, s) for kids, s, rnd in recs.values() if len(kids & chosen) >= 2]
    together_all = [s for kids, s, _ in recs.values() if chosen <= kids]
    split = []
    for c in ids:
        alone = [s for kids, s, _ in recs.values() if c in kids and not (kids & chosen) - {c}]
        withs = [s for kids, s, _ in recs.values() if c in kids and (kids & chosen) - {c}]
        split.append({"아동": report_name(c), "따로": sum(alone) / len(alone) if alone else float("nan"), "따로 n": len(alone),
                      "함께": sum(withs) / len(withs) if withs else float("nan"), "함께 n": len(withs)})
    return {"pairs": pd.DataFrame(pairs), "group": group, "all": together_all, "split": pd.DataFrame(split)}


def fmt(v, spec=".2f", empty="-"):
    return empty if v is None or v != v else format(v, spec)


def mentor_coaching(kind, m=None, r=None):
    # 화면 [지도 코칭] 탭용 — 멘토가 현장에서 바로 읽는 말투("~해 보세요")
    # 보고서(편집 탭·PDF·Word)에는 아래 default_coaching 의 보고서 문체가 들어간다
    if kind == "개인":
        tips = []
        best_t = m["types"][m["types"]["count"] >= 2].head(1)
        if len(best_t):
            bt = best_t.iloc[0]
            tips.append(f"{m['name']}{josa(m['name'], '은')} '{bt['미션종류']}' 미션에서 반응이 가장 좋았어요(평균 {bt['mean']:.2f}점). 다음 회기 첫 미션으로 권해 보세요.")
        best_p = m["partners"][(m["partners"]["count"] >= 2) & (m["partners"]["mean"] >= 1.5)].head(1)
        if len(best_p):
            bp = best_p.iloc[0]
            tips.append(f"{bp['아동']}{josa(bp['아동'], '와')} 함께할 때 평균 {bp['mean']:.2f}점으로 잘 어울렸어요. 낯선 친구와 짝을 지을 때 {bp['아동']}{josa(bp['아동'], '을')} 다리 역할로 함께 넣어 보세요.")
        if m["avoid"] > 0:
            tips.append("기피가 나온 미션은 바로 다시 내기보다, 말 대신 몸짓·그림으로 답할 수 있는 합동 미션으로 천천히 이어 주세요.")
        tips.append("미션이 끝나면 결과보다 시도한 순간을 짧게 짚어 칭찬해 주세요.")
        return tips[:4]
    if kind == "관계":
        tips = []
        p = r["pairs"].dropna(subset=["함께 평균"]).sort_values("시너지", ascending=False)
        if len(p):
            best = p.iloc[0]
            tips.append(f"{best['짝']} 짝은 함께할 때 각자보다 {best['시너지']:+.2f}점이었어요. 새 미션을 시작할 때 이 짝을 먼저 묶어 분위기를 열어 주세요.")
            worst = p.iloc[-1]
            if len(p) > 1 and worst["시너지"] < 0:
                tips.append(f"{worst['짝']} 짝은 아직 함께할 때 반응이 낮아요({worst['함께 평균']:.2f}점). 경쟁보다 합동 미션으로, 잘 어울리는 친구를 한 명 더 넣어 이어 주세요.")
        if r["pairs"]["함께한 횟수"].eq(0).any():
            tips.append("아직 함께한 적 없는 짝이 있어요. 부담이 적은 쉬움 난이도 합동 미션으로 첫 만남을 만들어 주세요.")
        tips.append("미션 뒤에는 서로에게 고마웠던 점을 한 마디씩 나누게 해 관계를 이어 주세요.")
        return tips[:4]
    return ["'좋음'이 많았던 미션 종류를 다음 회기 앞쪽에 배치해 보세요.",
            "기피가 나온 짝은 바로 다시 붙이기보다 합동 미션으로 천천히 이어 주세요.",
            "'룰 미숙지' 스킵이 나온 미션은 시작 전에 규칙을 한 번 더 짧게 보여 주세요."]


def default_coaching(kind, m=None, r=None, a=None):
    # AI를 못 쓸 때의 지도 코칭 — 기록 숫자에서 바로 뽑아 멘토링 보고서 문체(합니다체)로 쓴다
    # 좋아진 근거(유의미한 상승, 2번 이상 함께한 양의 시너지)가 있을 때만 "개선되었습니다/좋아졌습니다"라고 쓰고,
    # 부족한 점은 "~해야 합니다/~이 필요합니다", 다음 회기 계획은 "~할 예정입니다"로 쓴다
    if kind == "개인":
        tips = []
        if "좋아짐" in m["judge"]:
            tips.append(f"회차가 진행될수록 반응 점수가 회차당 {m['slope']:+.2f}점씩 유의미하게 상승하여(p={m['p']:.3f}), "
                        f"짝꿍 미션을 통해 {m['name']}의 또래 상호작용이 개선되었습니다.")
        best_t = m["types"][m["types"]["count"] >= 2].head(1)
        if len(best_t):
            bt = best_t.iloc[0]
            tips.append(f"{m['name']}{josa(m['name'], '은')} '{bt['미션종류']}' 미션에서 평균 {bt['mean']:.2f}점으로 가장 높은 반응을 보였습니다. "
                        "다음 회기에는 이 미션 종류를 첫 미션으로 배치할 예정입니다.")
        # '안정적인 관계'는 2번 이상 함께했고 평균이 1.5점(보통과 좋음 사이) 이상일 때만 쓴다
        best_p = m["partners"][(m["partners"]["count"] >= 2) & (m["partners"]["mean"] >= 1.5)].head(1)
        if len(best_p):
            bp = best_p.iloc[0]
            tips.append(f"{bp['아동']}{josa(bp['아동'], '와')} 함께한 미션에서 평균 {bp['mean']:.2f}점으로 안정적인 또래 관계를 보였습니다. "
                        f"새로운 친구와의 관계 확장을 위해 {bp['아동']}{josa(bp['아동'], '을')} 연결 역할로 함께 배치할 예정입니다.")
        if m["avoid"] > 0:
            tips.append("기피 반응이 나온 미션은 바로 반복하지 않고, 몸짓·그림으로 참여할 수 있는 합동 미션으로 단계적으로 연결해야 합니다.")
        tips.append("미션 후에는 결과보다 시도한 과정을 구체적으로 칭찬하여 참여 동기를 높일 예정입니다.")
        return tips[:4]
    if kind == "관계":
        tips = []
        p = r["pairs"].dropna(subset=["함께 평균"]).sort_values("시너지", ascending=False)
        if len(p):
            best = p.iloc[0]
            if best["시너지"] > 0 and best["함께한 횟수"] >= 2:
                tips.append(f"{best['짝']} 짝은 함께할 때 각자 평균보다 {best['시너지']:+.2f}점 높은 반응을 보여, 함께한 활동을 통해 관계가 좋아졌습니다. "
                            "다음 회기에도 새 미션의 시작을 이 짝으로 열 예정입니다.")
            else:
                tips.append(f"{best['짝']} 짝은 함께한 미션에서 평균 {best['함께 평균']:.2f}점을 보였습니다. "
                            "함께하는 횟수를 늘려 관계 변화를 더 살펴볼 예정입니다.")
            worst = p.iloc[-1]
            if len(p) > 1 and worst["시너지"] < 0:
                tips.append(f"{worst['짝']} 짝은 함께한 미션의 평균이 {worst['함께 평균']:.2f}점으로 아직 관계 형성이 필요합니다. "
                            "경쟁보다 합동 미션으로, 잘 어울리는 친구를 한 명 더 배치해 관계를 개선할 예정입니다.")
        if r["pairs"]["함께한 횟수"].eq(0).any():
            tips.append("아직 함께한 적이 없는 짝이 있어, 부담이 적은 쉬움 난이도 합동 미션으로 첫 상호작용을 만들 예정입니다.")
        tips.append("미션 후에는 서로에게 고마웠던 점을 한 마디씩 나누는 시간을 운영하여 관계를 이어 갈 예정입니다.")
        return tips[:4]
    tips = []
    if a is not None and a["coef"] is not None:
        rnd = a["coef"][a["coef"]["변수"].str.startswith("회차")]
        if len(rnd) and rnd.iloc[0]["p값"] < SIG_LEVEL and rnd.iloc[0]["계수"] > 0:
            tips.append(f"회차가 진행될수록 전체 반응 점수가 회차당 {rnd.iloc[0]['계수']:+.2f}점씩 유의미하게 상승하여(p={rnd.iloc[0]['p값']:.3f}), "
                        "짝꿍 미션을 통해 아동들의 또래 상호작용이 개선되었습니다.")
    tips += ["'좋음' 반응이 많았던 미션 종류를 다음 회기 앞부분에 배치하여 참여 분위기를 높일 예정입니다.",
             "기피 반응이 나온 짝은 즉시 다시 연결하지 않고, 합동 미션을 통해 단계적으로 관계를 개선할 예정입니다.",
             "'룰 미숙지'로 넘긴 미션은 시작 전에 규칙을 짧게 다시 안내해야 합니다."]
    return tips[:4]


@st.cache_data(show_spinner=False)
def fig_overall(df):
    # 전체 보고서용 — 아동별 반응 수(가로 누적 막대)
    plot_style()
    ct = pd.crosstab(df["아동"], df["반응"]).reindex(columns=REACTION_ORDER, fill_value=0)
    ct = ct.loc[child_order(ct.index)[::-1]]
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(ct) + 1.2))
    left = pd.Series(0, index=ct.index)
    for k, color in zip(REACTION_ORDER, REACTION_COLORS):
        ax.barh(ct.index, ct[k], left=left, color=color, label=k, height=0.62)
        left += ct[k]
    ax.legend(ncol=3, loc="lower right", frameon=False, fontsize=8.5)
    ax.set_xlabel("미션 수", fontsize=9)
    ax.tick_params(labelsize=8.5)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout()
    return fig_png(fig), 8 / (0.42 * len(ct) + 1.2)


@st.cache_data(show_spinner=False)
def fig_individual(df, cid):
    # 개인 리포트 그림 4칸 — 추세(회귀), 회차별 반응, 미션 종류별 평균, 친구별 평균
    plot_style()
    g = df[df["child_id"] == cid]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    yt = dict(ticks=[0, 1, 2], labels=["기피", "보통", "좋음"])

    ax = axes[0, 0]
    mean = g.groupby("회차")["점수"].mean()
    ax.scatter(g["회차"], g["점수"], s=18, color="#7DBDF3", alpha=.8, zorder=2)
    ax.plot(mean.index, mean.values, color="#F2A65A", lw=1.8, marker="o", ms=4, zorder=3, label="회차 평균")
    if len(g) >= MIN_TREND_ROWS and g["회차"].nunique() >= 2 and g["점수"].nunique() > 1:
        sns.regplot(x=g["회차"], y=g["점수"], ax=ax, scatter=False, ci=95, truncate=True,
                    line_kws={"color": "#1E2A5A", "lw": 2}, color="#1E2A5A")
    ax.set_yticks(**yt)
    ax.set_ylim(-0.3, 2.3)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title("회차별 추세 (꺾은선 = 회차 평균, 남색 = 회귀선)", fontsize=10)
    ax.set_xlabel("회차", fontsize=8.5)
    ax.set_ylabel("")

    ax = axes[0, 1]
    ct = pd.crosstab(g["회차"], g["반응"]).reindex(columns=REACTION_ORDER, fill_value=0)
    bottom = pd.Series(0, index=ct.index)
    xs = [f"{n}차" for n in ct.index]
    for k, color in zip(REACTION_ORDER, REACTION_COLORS):
        ax.bar(xs, ct[k], bottom=bottom, color=color, label=k, width=0.6)
        bottom += ct[k]
    # 범례는 막대를 가리지 않게 그림 아래로
    ax.legend(ncol=3, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title("회차별 반응 수", fontsize=10)
    ax.tick_params(axis="x", labelsize=7.5, rotation=0)

    ax = axes[1, 0]
    tm = g.groupby("미션종류")["점수"].agg(["mean", "count"]).sort_values("mean")
    ax.barh(tm.index, tm["mean"], color="#1E2A5A", height=0.55)
    for y, (v, n) in enumerate(zip(tm["mean"], tm["count"])):
        ax.text(v + 0.04, y, f"{v:.2f} (n={n})", va="center", fontsize=8, color="#5B6B94")
    ax.set_xlim(0, 2.6)
    ax.set_title("미션 종류별 평균 반응 점수", fontsize=10)
    ax.tick_params(labelsize=8.5)

    ax = axes[1, 1]
    part = g.assign(p=g["함께한"].str.split(",")).explode("p")
    part = part[part["p"].fillna("") != ""]
    if len(part):
        pm = part.groupby("p")["점수"].agg(["mean", "count"])
        pm.index = [report_name(c) for c in pm.index]
        pm = pm.sort_values("mean")
        ax.barh(pm.index, pm["mean"], color="#7DBDF3", height=0.55)
        for y, (v, n) in enumerate(zip(pm["mean"], pm["count"])):
            ax.text(v + 0.04, y, f"{v:.2f} (n={n})", va="center", fontsize=8, color="#5B6B94")
        ax.set_xlim(0, 2.6)
    else:
        ax.text(0.5, 0.5, "함께한 친구 기록이 없어요", ha="center", va="center", transform=ax.transAxes, color="#5B6B94")
        ax.axis("off")
    ax.set_title("함께한 친구별 평균 반응 점수", fontsize=10)
    ax.tick_params(labelsize=8.5)
    fig.tight_layout(h_pad=2.2, w_pad=2)
    return fig_png(fig), 10 / 7


@st.cache_data(show_spinner=False)
def fig_relation(df, ids):
    # 관계 리포트 그림 4칸 — 짝 히트맵, 짝별 시너지, 함께한 미션 추세, 따로·함께 평균 비교
    plot_style()
    r = relation_focus(df, list(ids))
    names = [report_name(c) for c in ids]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.4))

    ax = axes[0, 0]
    m = pd.DataFrame(index=names, columns=names, dtype=float)
    n = pd.DataFrame(0, index=names, columns=names)
    for _, p in r["pairs"].iterrows():
        x, y = report_name(p["a"]), report_name(p["b"])
        m.loc[x, y] = m.loc[y, x] = p["함께 평균"]
        n.loc[x, y] = n.loc[y, x] = p["함께한 횟수"]
    annot = m.round(1).astype(str).where(m.notna(), "") + n.map(lambda v: f"\n({v})" if v else "")
    sns.heatmap(m, annot=annot, fmt="", cmap=SCORE_CMAP, vmin=0, vmax=2, center=1, linewidths=1, linecolor="white",
                cbar=False, annot_kws={"fontsize": 9}, ax=ax, square=True)
    ax.set_title("함께한 평균 반응 점수 (괄호 = 횟수)", fontsize=10)
    ax.tick_params(labelsize=8.5)
    ax.tick_params(axis="y", rotation=0)

    ax = axes[0, 1]
    p = r["pairs"].dropna(subset=["시너지"]).sort_values("시너지")
    if len(p):
        colors = ["#1E2A5A" if v >= 0 else "#F2A65A" for v in p["시너지"]]
        ax.barh(p["짝"], p["시너지"], color=colors, height=0.55)
        for y, (v, k) in enumerate(zip(p["시너지"], p["함께한 횟수"])):
            ax.text(v + (0.03 if v >= 0 else -0.03), y, f"{v:+.2f} (n={k})", va="center",
                    ha="left" if v >= 0 else "right", fontsize=8, color="#5B6B94")
        ax.axvline(0, color="#AAB6CC", lw=1)
        lim = max(0.6, p["시너지"].abs().max() + 0.45)
        ax.set_xlim(-lim, lim)
    else:
        ax.text(0.5, 0.5, "함께한 기록이 아직 없어요", ha="center", va="center", transform=ax.transAxes, color="#5B6B94")
        ax.axis("off")
    ax.set_title("짝별 시너지 (함께 평균 - 각자 평균)", fontsize=10)
    ax.tick_params(labelsize=8.5)

    ax = axes[1, 0]
    if r["group"]:
        gdf = pd.DataFrame(r["group"], columns=["회차", "점수"])
        gm = gdf.groupby("회차")["점수"].mean()
        ax.scatter(gdf["회차"], gdf["점수"], s=18, color="#7DBDF3", alpha=.8)
        ax.plot(gm.index, gm.values, color="#F2A65A", lw=1.8, marker="o", ms=4)
        if len(gdf) >= MIN_TREND_ROWS and gdf["회차"].nunique() >= 2 and gdf["점수"].nunique() > 1:
            sns.regplot(data=gdf, x="회차", y="점수", ax=ax, scatter=False, ci=95, truncate=True,
                        line_kws={"color": "#1E2A5A", "lw": 2}, color="#1E2A5A")
        ax.set_yticks([0, 1, 2], ["기피", "보통", "좋음"])
        ax.set_ylim(-0.3, 2.3)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylabel("")
    else:
        ax.text(0.5, 0.5, "고른 아동이 함께한 미션이 없어요", ha="center", va="center", transform=ax.transAxes, color="#5B6B94")
        ax.axis("off")
    ax.set_title("고른 아동끼리 함께한 미션의 추세", fontsize=10)

    ax = axes[1, 1]
    s = r["split"]
    ys = range(len(s))
    ax.barh([y + 0.18 for y in ys], s["따로"].fillna(0), height=0.34, color="#C8DBF0", label="따로(고른 친구 없이)")
    ax.barh([y - 0.18 for y in ys], s["함께"].fillna(0), height=0.34, color="#1E2A5A", label="함께(고른 친구와)")
    ax.set_yticks(list(ys), s["아동"])
    ax.set_xlim(0, 2.3)
    # 범례는 막대를 가리지 않게 그림 아래로
    ax.legend(fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    ax.set_title("따로 할 때 vs 함께할 때 평균 반응 점수", fontsize=10)
    ax.tick_params(labelsize=8.5)
    fig.tight_layout(h_pad=2.2, w_pad=2)
    return fig_png(fig), 10 / 7.4


def kpi_tiles(kpis):
    tiles = "".join(
        f'<div class="yuco-kpi"><div class="yuco-kpi-l">{label}</div><div class="yuco-kpi-v">{value}</div></div>'
        for label, value in kpis
    )
    cols = min(len(kpis), 6)
    st.markdown(f'<div class="yuco-kpis" style="grid-template-columns:repeat({cols},1fr)">{tiles}</div>',
                unsafe_allow_html=True)


def screen_report():
    # 보고서 화면 — 넓은 화면으로 펼치고, 탭으로 나눠 한눈에 본다
    # 전체: 한눈에 / 아동별 추세 / 다중 회귀 / 관계·성향 / 보고서 편집
    # 개인·관계: 한눈에 / 그래프 / 지도 코칭 / 보고서 편집
    st.markdown("<style>[data-testid='stMainBlockContainer']{max-width:920px !important;}</style>", unsafe_allow_html=True)
    st.button("← 돌아가기", on_click=go, args=(st.session_state.get("report_back", "s1"),), key="report_back_btn")
    rep = st.session_state.get("report")
    if not rep:
        st.subheader("멘토링 보고서")
        st.info("사이드바에서 범위를 고르고 [멘토링 보고서 제작]을 눌러 주세요.")
        return
    kind, kids = rep.get("kind", "전체"), rep.get("kids", [])
    try:
        rows, df, skips, finales, rounds = report_data(rep)
    except Exception:
        st.error("기록을 불러오지 못했어요.  \n인터넷 연결을 확인하고 다시 눌러 주세요.")
        return
    mission_rows = [r for r in rows if r.get("feedback_type") != "skip" and r.get("reaction") in REACTION_ORDER]
    n_missions = len(mission_rows)
    names = [report_name(c) for c in kids]
    title = {"전체": "멘토링 보고서", "개인": f"{names[0] if names else ''} 개인 리포트",
             "관계": f"{'·'.join(names)} 관계 리포트"}[kind]
    # 기간 — 회기별이면 그 회차들이 열린 날짜(첫 기록 ~ 마지막 기록)를, 기간별이면 그 날짜에 든 회차를 함께 보여 준다
    period = report_period(rows, rounds)
    subtitle = f"{period}  ·  {kind} 보고서" + (f"  ·  대상 {', '.join(names)}" if names else "")
    st.subheader(title)
    st.markdown(f'<div class="yuco-period"><span class="yuco-period-k">기간</span>{html.escape(period)}</div>',
                unsafe_allow_html=True)
    st.caption(f"{kind} 보고서" + (f"  ·  대상 {', '.join(names)}" if names else "")
               + f"  ·  범위 안 미션 {n_missions}건 · 스킵 {len(skips)}건")
    if df.empty:
        st.warning("고른 범위에 반응 기록이 없어요.  \n사이드바에서 범위를 바꿔 주세요.")
        return

    a = analyze(df)
    figs = analysis_figures(df)
    lines = analysis_lines(a)
    counts = Counter(r["reaction"] for r in mission_rows)

    # 종류별 숫자 칸 · 지표 표 · 대상 지표 문장 · 그림
    m = r = None
    if kind == "개인":
        m = child_focus(df, skips, finales, a, kids[0])
        if not m["n"]:
            st.warning(f"{m['name']}{josa(m['name'], '은')} 고른 범위에 반응 기록이 없어요.")
            return
        trend_txt = "▲ 좋아짐" if "좋아짐" in m["judge"] else "▼ 낮아짐" if "낮아짐" in m["judge"] else "변화 없음" if m["judge"] == "뚜렷한 변화 없음" else m["judge"]
        kpis = [("참여 미션", f"{m['n']}건"), ("평균 점수", fmt(m["mean"])), ("좋음 비율", f"{m['good']:.0%}"),
                ("기피 비율", f"{m['avoid']:.0%}"), ("추세", trend_txt), ("스킵", f"{m['skips']}번")]
        table = {"title": "개인 지표", "header": ["지표", "값", "설명"], "widths": [3.2, 3.4, 5.4], "rows": [
            ["참여 미션", f"{m['n']}건 ({m['rounds']}회차)", "고른 범위에서 반응을 기록한 미션 수"],
            ["평균 반응 점수", fmt(m["mean"]), "좋음 2 · 보통 1 · 기피 0 의 평균"],
            ["좋음 / 기피 비율", f"{m['good']:.0%} / {m['avoid']:.0%}", "전체 미션 중 비율"],
            ["회차당 기울기", fmt(m["slope"], "+.3f"), "회차가 하나 늘 때 점수 변화 (단순 회귀)"],
            ["p값 · 판정", f"{fmt(m['p'], '.3f')} · {m['judge']}", "p < 0.05 면 유의미"],
            ["스킵 / 피날레 머뭇거림", f"{m['skips']}번 / {m['hesitant']}번", "미션을 넘긴 횟수 / 칭찬 카드 릴레이"],
        ] + [[f"미션 종류: {t['미션종류']}", f"{t['mean']:.2f}", f"{int(t['count'])}건"] for _, t in m["types"].iterrows()]
          + [[f"함께한 친구: {p['아동']}", f"{p['mean']:.2f}", f"{int(p['count'])}번 함께"] for _, p in m["partners"].head(5).iterrows()]}
        focus_lines = [
            f"{m['name']}: 참여 미션 {m['n']}건, 평균 반응 점수 {fmt(m['mean'])}점, 좋음 {m['good']:.0%} · 기피 {m['avoid']:.0%}.",
            f"{m['name']}의 회차별 추세: 회차당 {fmt(m['slope'], '+.3f')}점 (p={fmt(m['p'], '.3f')}, {m['judge']}).",
        ]
        # '가장 좋았던' 것은 2건 이상인 것 중에서 고른다 (1건짜리는 우연일 수 있다) — 없으면 1건짜리라도 쓴다
        types2 = m["types"][m["types"]["count"] >= 2]
        if len(m["types"]):
            bt = (types2 if len(types2) else m["types"]).iloc[0]
            focus_lines.append(f"{m['name']}의 반응이 가장 좋았던 미션 종류: {bt['미션종류']} (평균 {bt['mean']:.2f}점, {int(bt['count'])}건).")
        partners2 = m["partners"][m["partners"]["count"] >= 2]
        if len(m["partners"]):
            bp = (partners2 if len(partners2) else m["partners"]).iloc[0]
            focus_lines.append(f"{m['name']}{josa(m['name'], '과')} 가장 잘 어울린 친구: {bp['아동']} (함께 {int(bp['count'])}번, 평균 {bp['mean']:.2f}점).")
        focus_lines.append(f"스킵 {m['skips']}번, 피날레 머뭇거림 {m['hesitant']}번.")
        focus_fig = ("개인 그래프", *fig_individual(df, kids[0]))
        coaching_title = "개인 맞춤 지도 코칭"
        mentor_tips, report_tips = mentor_coaching("개인", m=m), default_coaching("개인", m=m)
    elif kind == "관계":
        r = relation_focus(df, kids)
        gm = sum(s for _, s in r["group"]) / len(r["group"]) if r["group"] else float("nan")
        best = r["pairs"].dropna(subset=["시너지"]).sort_values("시너지", ascending=False)
        kpis = [("고른 아동", f"{len(kids)}명"), ("함께한 미션", f"{len(r['group'])}건"), ("함께 평균", fmt(gm)),
                ("모두 함께", f"{len(r['all'])}건"), ("최고 시너지", best.iloc[0]["짝"] if len(best) else "-")]
        table = {"title": "관계 지표 (짝별)", "header": ["짝", "함께한 횟수", "함께 평균", "좋음 비율", "각자 평균", "시너지"],
                 "widths": [3, 2, 2, 2, 2, 2], "rows": [
                     [p["짝"], f"{int(p['함께한 횟수'])}번", fmt(p["함께 평균"]),
                      "-" if p["좋음 비율"] != p["좋음 비율"] else f"{p['좋음 비율']:.0%}", fmt(p["각자 평균"]), fmt(p["시너지"], "+.2f")]
                     for _, p in r["pairs"].iterrows()]}
        focus_lines = [f"고른 아동 {len(kids)}명이 둘 이상 함께한 미션 {len(r['group'])}건, 평균 반응 점수 {fmt(gm)}점, 모두 함께한 미션 {len(r['all'])}건."]
        for _, p in r["pairs"].iterrows():
            focus_lines.append(f"{p['짝']}: 함께 {int(p['함께한 횟수'])}번, 함께 평균 {fmt(p['함께 평균'])}점, 각자 평균 {fmt(p['각자 평균'])}점, 시너지 {fmt(p['시너지'], '+.2f')}.")
        for _, s in r["split"].iterrows():
            focus_lines.append(f"{s['아동']}: 고른 친구 없이 {fmt(s['따로'])}점({int(s['따로 n'])}건) / 고른 친구와 {fmt(s['함께'])}점({int(s['함께 n'])}건).")
        focus_fig = ("관계 그래프", *fig_relation(df, tuple(kids)))
        coaching_title = "관계 맞춤 지도 코칭"
        mentor_tips, report_tips = mentor_coaching("관계", r=r), default_coaching("관계", r=r)
    else:
        kpis = [("미션", f"{n_missions}건")] + [(k, f"{counts.get(k, 0)}건") for k in REACTION_ORDER]
        tr = a["trend"]
        table = {"title": "아동별 지표", "header": ["아동", "기록", "평균 점수", "회차당 기울기", "p값", "판정"],
                 "widths": [3, 1.6, 2, 2.4, 1.8, 3.4], "rows": [
                     [t["아동"], f"{t['기록']}건", fmt(t["평균 점수"]), fmt(t["기울기(회차당)"], "+.3f"), fmt(t["p값"], ".3f"), t["판정"]]
                     for _, t in tr.iterrows()]}
        focus_lines = []
        focus_fig = None
        coaching_title = "다음 회기 지도 코칭"
        mentor_tips, report_tips = mentor_coaching("전체"), default_coaching("전체", a=a)

    kpi_tiles(kpis)

    # AI 요약 · 코칭 · 초안 — 범위·아동마다 한 번만 만든다 (다시 그릴 때 Gemini를 또 부르지 않게)
    # 문체를 바꾼 뒤 예전에 만든 요약이 남지 않게 새 이름(v2)으로 담는다
    cache = st.session_state.setdefault("report_ai_v3", {})
    if rep["key"] not in cache:
        result, note = make_report_text(rep, rows, df, skips, finales, rounds,
                                        names_to_ids(lines, df), names_to_ids(focus_lines, df))
        if result is None:
            result = fallback_report(rep, df, skips, finales, n_missions, counts, focus_lines, mentor_tips, report_tips)
            result["note"] = note
        cache[rep["key"]] = result
    res = cache[rep["key"]]
    summary = [ids_to_names(s) for s in res["summary"]]
    # 화면 [지도 코칭] 탭 = 멘토용 말투 / 보고서(편집 탭·PDF·Word) = 보고서 문체
    coaching = [ids_to_names(s) for s in res.get("coaching") or mentor_tips]
    report_coaching = [ids_to_names(s) for s in res.get("report_coaching") or report_tips]
    ai_note = "AI가 쓴 초안입니다." if res.get("ai") else res.get("note") or "기록 숫자로 만든 기본 요약입니다."

    def summary_box():
        with st.container(border=True):
            st.markdown("**핵심 요약**")
            for s in summary:
                st.markdown(f"- {s}")
            st.caption(ai_note)
            if not res.get("ai"):
                st.button("AI 요약 다시 만들기", on_click=lambda: cache.pop(rep["key"], None), key="report_retry")

    def table_view():
        st.dataframe(pd.DataFrame(table["rows"], columns=table["header"]), hide_index=True, width="stretch")

    scale = alt.Scale(domain=REACTION_ORDER, range=REACTION_COLORS)
    legend = alt.Legend(orient="top", title=None)

    if kind == "전체":
        tabs = st.tabs(["한눈에", "아동별 추세", "다중 회귀", "관계·성향", "보고서 편집"])
        with tabs[0]:
            left, right = st.columns([1, 1], gap="medium")
            with left:
                summary_box()
                with st.container(border=True):
                    st.markdown("**정량 분석 핵심**")
                    for line in lines:
                        st.markdown(f"- {line}")
            with right, st.container(border=True):
                st.markdown("**아동별 반응**")
                overall = df.groupby(["아동", "반응"]).size().reset_index(name="횟수")
                overall["순서"] = overall["반응"].map(REACTION_ORDER.index)
                st.altair_chart(
                    alt.Chart(overall).mark_bar(cornerRadius=3).encode(
                        y=alt.Y("아동:N", title=None, sort=child_order(overall["아동"].unique())),
                        x=alt.X("횟수:Q", title="미션 수", axis=alt.Axis(tickMinStep=1)),
                        color=alt.Color("반응:N", scale=scale, legend=legend),
                        order=alt.Order("순서:Q"), tooltip=["아동", "반응", "횟수"],
                    ), width="stretch",
                )
        with tabs[1]:
            st.image(figs["trend"][0], width="stretch")
            st.caption("점 = 미션 한 건, 주황 꺾은선 = 회차 평균, 남색 선 = 회귀선(옅은 띠는 95% 신뢰 구간).  \n"
                       f"기록이 {MIN_TREND_ROWS}건 미만인 아동은 회귀선을 긋지 않아요.")
            table_view()
        with tabs[2]:
            if "coef" in figs:
                st.image(figs["coef"][0], width="stretch")
                mm = a["model"]
                st.caption(f"반응 점수 ~ 회차 + 미션 종류 + 난이도 + 성향(아동 2명 이상이 가진 성향).  \n"
                           f"기록 {mm['n']}건 · R² {mm['r2']:.2f} (보정 R² {mm['adj_r2']:.2f}) · 표준오차 HC3.  \n"
                           + (f"종류·난이도를 모르는 AI 미션 카드 기록 {mm['ai_rows']}건은 다중 회귀에서만 뺐어요.  \n" if mm["ai_rows"] else "")
                           + (f"난이도는 미션 종류와 거의 겹쳐(크라메르 V {a['dropped_diff']:.2f}) 효과를 나눌 수 없어 넣지 않았어요.  \n"
                              if a["dropped_diff"] else "")
                           + "점이 주황 점선(0)보다 오른쪽이면 반응이 좋아지는 쪽, 왼쪽이면 낮아지는 쪽이에요. * = 유의미.")
                st.dataframe(a["coef"], hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="%+.3f") for c in ["계수", "하한", "상한"]}
                             | {"p값": st.column_config.NumberColumn(format="%.3f")})
            else:
                st.info(f"다중 회귀는 기록이 {a['model']['need']}건 이상 쌓이면 보여 드려요.  \n지금 {a['model']['n']}건이에요.")
        with tabs[3]:
            c1, c2 = st.columns(2, gap="medium")
            with c1:
                if "pairs" in figs:
                    st.image(figs["pairs"][0], width="stretch")
                    st.caption("칸 숫자 = 두 아동이 함께한 미션의 평균 반응 점수, (괄호) = 함께한 횟수.")
            with c2:
                st.image(figs["traits"][0], width="stretch")
                st.caption("성향별 평균 반응 점수 (주황 선 = 표준오차, n = 기록 수).")
        edit_tab = tabs[4]
        doc_figs = [("아동별 반응 수", *fig_overall(df)),
                    ("아동별 추세 (단순 선형 회귀 · 꺾은선 = 회차 평균)", *figs["trend"])]
        if "coef" in figs:
            doc_figs.append(("다중 회귀 계수 (95% 신뢰 구간, * = 유의미)", *figs["coef"]))
        if "pairs" in figs:
            doc_figs.append(("관계 — 함께한 두 아동의 평균 반응 점수", *figs["pairs"]))
        doc_figs.append(("성향별 평균 반응 점수", *figs["traits"]))
        doc_stats = lines
    else:
        tabs = st.tabs(["한눈에", "그래프", "지도 코칭", "보고서 편집"])
        with tabs[0]:
            left, right = st.columns([1, 1], gap="medium")
            with left:
                summary_box()
            with right, st.container(border=True):
                st.markdown(f"**{table['title']}**")
                table_view()
        with tabs[1]:
            st.image(focus_fig[1], width="stretch")
            st.caption("반응 점수 : 좋음 2 · 보통 1 · 기피 0.  꺾은선 = 회차 평균, 남색 선 = 회귀선(옅은 띠는 95% 신뢰 구간).  \n"
                       + ("시너지 = 두 아동이 함께한 미션의 평균 − 두 아동 각자의 평균.  남색 = 함께할 때 더 좋음, 주황 = 아직 낯설어함."
                          if kind == "관계" else "n = 미션 수. 기록이 적으면 결과가 크게 흔들릴 수 있어요."))
            for line in focus_lines:
                st.markdown(f"- {line}")
        with tabs[2]:
            with st.container(border=True):
                st.markdown(f"**{coaching_title}**")
                for i, tip in enumerate(coaching, 1):
                    st.markdown(f"{i}. {tip}")
                st.caption((ai_note if res.get("ai") else "기록 숫자로 만든 기본 코칭이에요.")
                           + "  \n멘토가 현장에서 보는 코칭이에요. 보고서(편집·PDF·Word)에는 보고서 문체로 들어가요.")
        edit_tab = tabs[3]
        doc_figs = [(focus_fig[0], focus_fig[1], focus_fig[2])]
        doc_stats = focus_lines

    # 보고서 편집 — 제목·요약·코칭·본문을 고친 뒤 PDF 또는 Word 로 내려받는다
    with edit_tab:
        k = rep["key"]
        defaults = {f"ed_title_{k}": title, f"ed_sum_{k}": "\n".join(summary),
                    f"ed_coach_{k}": "\n".join(report_coaching), f"ed_draft_{k}": ids_to_names(res["draft"])}
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)
        st.caption("PDF·Word 에 들어갈 글을 여기서 고쳐요. 고친 뒤 칸 밖을 한 번 누르면 저장돼요.  \n"
                   "Word 로 내려받으면 그림까지 넣은 채로 Word 에서 더 고칠 수 있어요.")
        st.text_input("보고서 제목", key=f"ed_title_{k}")
        c1, c2 = st.columns(2, gap="medium")
        c1.text_area("핵심 요약 (한 줄에 하나)", key=f"ed_sum_{k}", height=150)
        c2.text_area(f"{coaching_title} (한 줄에 하나)", key=f"ed_coach_{k}", height=150)
        st.text_area("보고서 본문 (빈 줄로 문단 나누기)", key=f"ed_draft_{k}", height=260)
        with_figs = st.checkbox("그래프·정량 분석 넣기", value=True, key=f"ed_figs_{k}")

        def split_lines(text):
            return [line.strip().lstrip("-•· ").strip() for line in text.splitlines() if line.strip()]

        doc = {
            "title": st.session_state[f"ed_title_{k}"].strip() or title,
            "subtitle": subtitle + f"  ·  만든 날 {datetime.now(KST):%Y.%m.%d}",
            "kpis": kpis[:6],
            "summary": split_lines(st.session_state[f"ed_sum_{k}"]),
            "coaching": split_lines(st.session_state[f"ed_coach_{k}"]),
            "coaching_title": coaching_title,
            "table": table,
            "stats": doc_stats if with_figs else [],
            "figures": doc_figs if with_figs else [],
            "draft": st.session_state[f"ed_draft_{k}"],
        }
        file_base = f"{title.replace(' ', '_')}_{rep['label']}"
        d1, d2 = st.columns(2, gap="medium")
        if find_pdf_font() is None:
            d1.warning("PDF에 쓸 한글 글꼴을 찾지 못했어요.  \nstatic 폴더에 report-regular.ttf 를 넣어 주세요.")
        else:
            try:
                d1.download_button("PDF로 내려받기", data=report_pdf(doc), file_name=f"{file_base}.pdf",
                                   mime="application/pdf", type="primary", use_container_width=True, key="report_pdf")
            except Exception:
                d1.error("PDF를 만들지 못했어요.  \n잠시 뒤 다시 눌러 주세요.")
        try:
            d2.download_button("Word로 내려받기 (.docx)", data=report_docx(doc), file_name=f"{file_base}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               use_container_width=True, key="report_docx")
        except Exception:
            d2.error("Word 파일을 만들지 못했어요.  \n잠시 뒤 다시 눌러 주세요.")


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


# 저장된 child_id를 이름으로 되돌리는 ids_to_names 는 위 멘토링 보고서 부분에 있다 (조사도 이름에 맞춰 고친다)


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
# 사이드바 멘토링 보고서 필터·버튼 — 화면보다 먼저 그려, 버튼을 누르면 같은 실행에서 보고서 화면으로 바뀐다
report_sidebar()

{
    "s_start": screen_start,
    "s_report": screen_report,
    "s1": screen_1,
    "s1_card": screen_1_card,
    "s1_1": screen_1_1,
    "s_finale": screen_finale,
    "s2": screen_2,
    "s2_1": screen_2_1,
    "s3": screen_3,
}[st.session_state.screen]()

# 모든 화면 맨 아래 저작권 한 줄
st.caption("© 2026 짝꿍 미션 카드 · YUCO MARBLE")

if st.session_state.popup == "p1":
    popup_1()
elif st.session_state.popup == "p2":
    popup_2()
