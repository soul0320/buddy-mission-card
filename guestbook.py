import os
from datetime import datetime, timedelta, timezone

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

# .env 의 Supabase 주소와 키를 읽는다 — 어느 폴더에서 실행해도 이 파일 옆 .env 를 찾는다
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 글이 쌓이는 Supabase 표 이름
TABLE = "guestbook"
# 한 줄 방명록이라 글자 수를 제한한다
MAX_LEN = 100
# 저장 시각은 세계 표준시라 한국 시각으로 바꿔 보여 준다
KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="한 줄 방명록")

# app.py 와 같은 휴대폰 세로 화면 폭, 띄어쓰기에서만 줄 바꿈
st.markdown(
    """
    <style>
    .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 420px;
        padding-left: 16px;
        padding-right: 16px;
    }
    body, [data-testid="stMarkdownContainer"] {
        word-break: keep-all;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
        st.stop()
    return create_client(url, key)


def format_time(created_at):
    # 예: 2026-10-14T03:25:50.908058+00:00 → 10/14 12:25
    t = datetime.fromisoformat(created_at).astimezone(KST)
    return t.strftime("%m/%d %H:%M")


client = get_client()

st.title("한 줄 방명록")

# 글을 남기면 입력칸이 비워지도록 form 을 쓴다
with st.form("write", clear_on_submit=True):
    message = st.text_input(
        "한 줄 남기기", max_chars=MAX_LEN, placeholder="하고 싶은 말을 한 줄로 적어 주세요"
    )
    submitted = st.form_submit_button("남기기", use_container_width=True)

if submitted:
    message = message.strip()
    if not message:
        st.warning("내용을 적어 주세요.")
    else:
        try:
            client.table(TABLE).insert({"message": message}).execute()
            st.success("방명록에 남겼어요.")
        except Exception as e:
            st.error(f"저장하지 못했어요: {e}")

st.divider()

# 최신 글이 위로 오게 불러온다
try:
    rows = (
        client.table(TABLE)
        .select("message, created_at")
        .order("created_at", desc=True)
        .execute()
        .data
    )
except Exception as e:
    st.error(f"방명록을 불러오지 못했어요: {e}")
    rows = []

if not rows:
    st.caption("아직 남겨진 글이 없어요. 첫 글을 남겨 주세요.")

for row in rows:
    st.markdown(f"{row['message']}  \n:gray[{format_time(row['created_at'])}]")
