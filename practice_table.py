from pathlib import Path

import pandas as pd
import streamlit as st

# data 폴더의 문의 CSV — 어느 폴더에서 실행해도 이 파일 옆 data 폴더를 찾는다
CSV_PATH = Path(__file__).parent / "data" / "56_practice-inquiries.csv"

st.set_page_config(page_title="문의 내역 표")

st.title("문의 내역 표")
st.caption(f"원본 파일: data/{CSV_PATH.name}")

df = pd.read_csv(CSV_PATH, encoding="utf-8")

# 줄 수 요약 — 전체 / 유형별(배송·환불·교환)
counts = df["type"].value_counts()
cols = st.columns(4)
cols[0].metric("전체", len(df))
for col, kind in zip(cols[1:], ["배송", "환불", "교환"]):
    col.metric(kind, int(counts.get(kind, 0)))

# 필터 — type 열로 거른다. 처음에는 "전체"라서 모든 줄이 보인다
choice = st.selectbox("유형으로 거르기", ["전체"] + list(df["type"].unique()))
shown = df if choice == "전체" else df[df["type"] == choice]

# 필터 2 — status 열로 한 번 더 거른다. 두 필터에서 고른 값이 둘 다 맞는 줄만 남는다
status_choice = st.selectbox("상태로 거르기", ["전체"] + list(df["status"].unique()))
if status_choice != "전체":
    shown = shown[shown["status"] == status_choice]
st.write(f"**지금 보이는 줄 수: {len(shown)}**")

# 표 — 열 이름만 한글로 바꿔 보여 준다 (원본 파일은 그대로)
st.dataframe(
    shown.rename(columns={"date": "날짜", "type": "유형", "message": "문의 내용", "status": "상태"}),
    hide_index=True,
)
