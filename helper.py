import os

import streamlit as st
from dotenv import load_dotenv
from google import genai

# .env 의 Gemini 키를 읽는다 — 어느 폴더에서 실행해도 이 파일 옆 .env 를 찾는다
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 공식 모델 문서(ai.google.dev/gemini-api/docs/models)가 새 프로젝트에 권하는 안정판
# gemini-3.8-flash 는 요청이 몰려 47초 기다린 뒤 503 을 돌려줘서, 바로 답하는 이 모델을 쓴다
MODEL = "gemini-3.5-flash-lite"

st.set_page_config(page_title="챗봇")

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

st.title("챗봇")

# 키 값 자체는 화면에 보이지 않게 하고, 채워져 있는지만 알려 준다
if os.getenv("GEMINI_API_KEY", "").strip():
    st.write("✅ GEMINI_API_KEY 가 채워져 있습니다.")
else:
    st.write("❌ GEMINI_API_KEY 가 비어 있습니다. .env 를 확인해 주세요.")

# 빈칸에 넣은 말을 Gemini 에 보내고, 받은 답을 아래에 보여 준다
question = st.text_input("물어볼 말")

if st.button("보내기"):
    if not question.strip():
        st.write("빈칸에 물어볼 말을 넣어 주세요.")
    else:
        try:
            # 키는 GEMINI_API_KEY 환경변수에서 알아서 읽는다
            client = genai.Client()
            with st.spinner("답을 기다리는 중..."):
                interaction = client.interactions.create(model=MODEL, input=question)
            st.write(interaction.output_text)

            # 이번 요청에 쓴 토큰 수 — 합계에는 답하기 전에 생각한 토큰도 들어간다
            usage = interaction.usage
            if usage:
                st.caption(
                    f"토큰 {usage.total_tokens or 0}개 "
                    f"(보낸 말 {usage.total_input_tokens or 0} · "
                    f"받은 답 {usage.total_output_tokens or 0} · "
                    f"생각 {usage.total_thought_tokens or 0})"
                )
        except Exception as e:
            if getattr(e, "status_code", None) == 503:
                st.write("지금 Gemini 가 붐벼서 답을 받지 못했습니다. 잠시 뒤 다시 눌러 주세요.")
            else:
                st.write(f"답을 받지 못했습니다: {e}")
