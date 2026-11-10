"""전북대 사대부고사거리 근처 맛집 대시보드.

카카오 로컬 API(키워드로 장소 검색)로 음식점을 찾아 표·정렬·차트로 보여 준다.
API 는 [검색] 버튼을 눌렀을 때만 부른다. 정렬·필터는 이미 받은 결과로만 다시 그린다.

실행: streamlit run lunch.py
공식 문서: https://developers.kakao.com/docs/latest/ko/local/dev-guide
"""

import os
import random
from pathlib import Path
from urllib.parse import quote

import altair as alt
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

# 이 파일 옆 .env 에서 KAKAO_REST_API_KEY 를 읽는다
load_dotenv(Path(__file__).parent / ".env")

# 키워드로 장소 검색 — GET, 헤더 Authorization: KakaoAK {REST API 키}
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
# 주소 검색(주소 → 좌표) — 같은 헤더. 동네 이름("금암동")은 여기서 행정동 중심 좌표가 나온다
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
# 카테고리 그룹 코드: FD6 = 음식점
FOOD_CODE = "FD6"
# 공식 문서 기준 한 번에 받을 수 있는 최대 개수(size 최대 15), 페이지는 최대 45
PAGE_SIZE = 15
# 내 조건 기본값
DEFAULT_CENTER = "서울역"
DEFAULT_FOOD = "샤브샤브"
DEFAULT_RADIUS = 500


def kakao_get(params: dict, url: str = KEYWORD_URL) -> dict:
    """카카오 로컬 API 를 한 번 부르고 JSON 을 돌려준다. 실패하면 RuntimeError."""
    key = os.getenv("KAKAO_REST_API_KEY")
    if not key:
        raise RuntimeError(".env 에 KAKAO_REST_API_KEY 가 없어요.")
    try:
        res = requests.get(
            url,
            headers={"Authorization": f"KakaoAK {key}"},
            params=params,
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"카카오 서버에 연결하지 못했어요: {e.__class__.__name__}") from e
    if res.status_code != 200:
        # 카카오 오류 응답은 {"errorType": ..., "message": ...} 형태 — 키 값은 화면에 남기지 않는다
        try:
            body = res.json()
            detail = body.get("message") or body.get("msg") or ""
        except ValueError:
            detail = ""
        hint = ""
        if res.status_code in (401, 403):
            hint = " REST API 키가 맞는지, 카카오 개발자 콘솔에서 카카오맵(로컬) 사용이 켜져 있는지 확인해 주세요."
        raise RuntimeError(f"카카오 API 오류 {res.status_code}: {detail}{hint}")
    return res.json()


def find_center(place: str) -> dict:
    """기준 장소 이름을 좌표로 바꾼다. 화면에는 카카오가 돌려준 이름·주소만 쓴다.

    1) 주소 검색 — 동네·주소("금암동", "백제대로 642")면 여기서 찾는다
    2) 없으면 키워드 장소 검색 — 역·건물·가게 이름("서울역")은 여기서 찾는다
    """
    docs = kakao_get({"query": place, "size": 1}, ADDRESS_URL).get("documents", [])
    if docs:
        d = docs[0]
        return {"name": d["address_name"], "address": d["address_name"],
                "x": d["x"], "y": d["y"], "via": "주소 검색"}

    docs = kakao_get({"query": place, "size": 1}).get("documents", [])
    if docs:
        d = docs[0]
        address = d["road_address_name"] or d["address_name"]
        return {"name": d["place_name"], "address": address,
                "x": d["x"], "y": d["y"], "via": "장소 검색"}

    raise RuntimeError(f"카카오에서 '{place}' 위치를 찾지 못했어요. 역·동네 이름을 다시 적어 주세요.")


def search_food(keyword: str, center: dict, radius: int, max_pages: int) -> tuple[pd.DataFrame, int]:
    """기준 좌표 반경 안의 음식점을 거리순으로 여러 페이지 받아 표로 만든다.

    돌려주는 값: (가게 표, 카카오가 찾은 전체 개수 meta.total_count)
    """
    rows = []
    total = 0
    for page in range(1, max_pages + 1):
        data = kakao_get({
            "query": keyword,
            "category_group_code": FOOD_CODE,
            "x": center["x"],
            "y": center["y"],
            "radius": radius,
            "sort": "distance",
            "page": page,
            "size": PAGE_SIZE,
        })
        rows.extend(data.get("documents", []))
        meta = data.get("meta", {})
        total = meta.get("total_count", total)
        if meta.get("is_end", True):
            break

    if not rows:
        return pd.DataFrame(), total

    df = pd.DataFrame(rows).drop_duplicates(subset="id")
    # 반경 밖 가게가 섞여 오더라도 표·차트·지도에는 반경 안 가게만 남긴다
    df = df[pd.to_numeric(df["distance"], errors="coerce") <= radius]
    if df.empty:
        return pd.DataFrame(), total
    # category_name 예: "음식점 > 한식 > 국밥" → 종류 "한식", 세부 "국밥"
    parts = df["category_name"].str.split(" > ")
    df["종류"] = parts.str[1].fillna("기타")
    df["세부"] = parts.str[2:].str.join(" > ").replace("", "-")
    df["거리(m)"] = pd.to_numeric(df["distance"], errors="coerce").astype("Int64")
    df["주소"] = df["road_address_name"].where(df["road_address_name"] != "", df["address_name"])
    df["전화"] = df["phone"].replace("", "-")
    # 지도에 찍을 좌표 — 카카오는 x = 경도, y = 위도 (문자열로 온다)
    df["lat"] = pd.to_numeric(df["y"], errors="coerce")
    df["lon"] = pd.to_numeric(df["x"], errors="coerce")
    return df.rename(columns={"place_name": "이름", "place_url": "카카오맵"})[
        ["이름", "종류", "세부", "거리(m)", "주소", "전화", "카카오맵", "lat", "lon"]
    ].reset_index(drop=True), total


st.set_page_config(page_title="내 조건 맛집", page_icon="🍚", layout="wide")
st.title("🍚 내 조건 맛집 대시보드")
st.caption("카카오 로컬 API로 근처 음식점을 찾아요. [검색]을 눌렀을 때만 새로 불러옵니다.")

# ---------- 내 조건으로 찾기 (form 이라 [검색]을 눌러야만 제출된다) ----------
with st.form("search"):
    st.markdown("**내 조건으로 찾기**")
    c1, c2 = st.columns(2)
    center_name = c1.text_input("기준 장소", DEFAULT_CENTER,
                                help="역이나 동네 이름. 예: 서울역, 전주역, 전주 금암동. "
                                     "같은 이름 동네가 여러 곳이면 '전주 금암동'처럼 시 이름을 붙여 주세요.")
    keyword = c2.text_input("찾을 음식", DEFAULT_FOOD,
                            help="예: 샤브샤브, 국밥, 돈까스, 분식. 전체를 보려면 '음식점'")
    c3, c4 = st.columns(2)
    radius = c3.slider("반경 (m)", 100, 3000, DEFAULT_RADIUS, step=100)
    max_pages = c4.slider("불러올 양 (페이지당 15곳)", 1, 3, 3,
                          help="카카오는 한 검색어당 최대 45곳까지 보여 줘요.")
    submitted = st.form_submit_button("검색", type="primary")

if submitted:
    if not center_name.strip() or not keyword.strip():
        st.warning("기준 장소와 찾을 음식을 모두 적어 주세요.")
    else:
        try:
            with st.spinner("카카오에서 찾는 중..."):
                center = find_center(center_name.strip())
                center["input"] = center_name.strip()
                center["food"] = keyword.strip()
                st.session_state.lunch_center = center
                st.session_state.lunch_df, st.session_state.lunch_total = search_food(
                    keyword.strip(), center, radius, max_pages)
                st.session_state.lunch_radius = radius
                # 새로 검색하면 지난 뽑기 결과는 지운다
                st.session_state.pop("lunch_pick", None)
        except RuntimeError as e:
            st.error(str(e))

df = st.session_state.get("lunch_df")
# 지도 기능 전에 받아 둔 결과에는 좌표가 없으니 다시 검색하게 한다
if df is not None and not df.empty and "lat" not in df.columns:
    df = None
# 전체 개수 칸이나 기준 장소 주소가 생기기 전에 받아 둔 결과도 다시 검색하게 한다
if "lunch_total" not in st.session_state or "address" not in st.session_state.get("lunch_center", {}):
    df = None
if df is None:
    st.info("조건을 정하고 [검색]을 눌러 주세요.")
    st.stop()

# 기준 장소 — 카카오가 실제로 돌려준 이름·주소만 보여 준다
center = st.session_state.lunch_center
st.subheader(f"📍 {center['name']} 반경 {st.session_state.lunch_radius:,}m · {center['food']}")
st.caption(f"입력: '{center['input']}' → 카카오 {center['via']} 결과 · 주소: {center['address']}")

if df.empty:
    st.warning("조건에 맞는 음식점이 없어요. 반경을 넓히거나 찾을 음식을 바꿔 보세요.")
    st.stop()

# ---------- 필터·정렬 (받아 둔 결과로만 다시 그린다 — API 호출 없음) ----------
with st.container(border=True):
    f1, f2, f3 = st.columns([2, 3, 2])
    name_q = f1.text_input("이름으로 찾기", placeholder="가게 이름 일부")
    kinds = sorted(df["종류"].unique())
    picked = f2.multiselect("종류", kinds, placeholder="전체")
    sort_by = f3.selectbox("정렬", ["가까운 순", "먼 순", "이름순", "종류순"])

view = df
if name_q.strip():
    view = view[view["이름"].str.contains(name_q.strip(), case=False, regex=False)]
if picked:
    view = view[view["종류"].isin(picked)]
sort_rules = {
    "가까운 순": (["거리(m)"], [True]),
    "먼 순": (["거리(m)"], [False]),
    "이름순": (["이름"], [True]),
    "종류순": (["종류", "거리(m)"], [True, True]),
}
cols, asc = sort_rules[sort_by]
view = view.sort_values(cols, ascending=asc).reset_index(drop=True)

if view.empty:
    st.warning("필터에 맞는 가게가 없어요.")
    st.stop()

# ---------- 요약 숫자 ----------
nearest = view.loc[view["거리(m)"].idxmin()]
with st.container(horizontal=True):
    st.metric("찾은 가게", f"{len(view)}곳", border=True)
    st.metric("카카오 검색 결과 전체", f"{st.session_state.lunch_total:,}곳", border=True,
              help="카카오가 찾은 전체 개수예요. 카카오는 이 중 최대 45곳까지만 보여 줘요.")
    st.metric("가장 가까운 곳", f"{int(nearest['거리(m)'])}m", border=True,
              help=f"{nearest['이름']}")
    st.metric("평균 거리", f"{int(view['거리(m)'].mean())}m", border=True)

# ---------- 맛집 뽑기 (지금 표에 보이는 가게 안에서만 — API 호출 없음) ----------
with st.container(border=True):
    if st.button("🎲 맛집 뽑기", help="지금 표에 보이는 가게 중 한 곳을 무작위로 골라요."):
        st.session_state.lunch_pick = view.iloc[random.randrange(len(view))].to_dict()
    pick = st.session_state.get("lunch_pick")
    # 필터를 바꿔 뽑힌 가게가 표에서 빠지면 결과를 숨긴다
    if pick and pick["카카오맵"] in set(view["카카오맵"]):
        kind = pick["종류"] if pick["세부"] == "-" else f"{pick['종류']} · {pick['세부']}"
        st.markdown(f"## 🍽️ {pick['이름']}")
        st.markdown(f"### {kind} · {int(pick['거리(m)'])}m")
        st.markdown(f"[카카오맵에서 보기]({pick['카카오맵']})")
    else:
        st.caption("버튼을 누르면 지금 표에 보이는 가게 중 한 곳을 골라 드려요.")

# ---------- 차트 ----------
ch1, ch2 = st.columns(2)
with ch1, st.container(border=True):
    st.markdown("**종류별 가게 수**")
    kind_count = view["종류"].value_counts().rename_axis("종류").reset_index(name="가게 수")
    bar = alt.Chart(kind_count).mark_bar().encode(
        x=alt.X("가게 수:Q", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("종류:N", sort="-x", title=None),
        tooltip=["종류", "가게 수"],
    )
    st.altair_chart(bar, width="stretch")

with ch2, st.container(border=True):
    st.markdown("**거리대별 가게 수**")
    start = (view["거리(m)"] // 100 * 100).astype(int)
    dist_count = (
        pd.DataFrame({"시작": start, "거리대": start.astype(str) + "–" + (start + 100).astype(str) + "m"})
        .groupby(["시작", "거리대"]).size().reset_index(name="가게 수")
    )
    hist = alt.Chart(dist_count).mark_bar().encode(
        x=alt.X("가게 수:Q", axis=alt.Axis(tickMinStep=1)),
        # 가까운 거리대가 위로 오게 시작값 순서로 놓는다
        y=alt.Y("거리대:N", sort=alt.EncodingSortField("시작", order="ascending"), title=None),
        tooltip=["거리대", "가게 수"],
    )
    st.altair_chart(hist, width="stretch")

# ---------- 지도 ----------
with st.container(border=True):
    st.markdown("**가게 위치** (빨간 점 = 가게, 파란 점 = 기준 장소)")
    shops = view[["lat", "lon"]].assign(color="#d62728cc", size=12)
    base = pd.DataFrame([{
        "lat": float(center["y"]), "lon": float(center["x"]),
        "color": "#1f77b4", "size": 18,
    }])
    st.map(pd.concat([shops, base], ignore_index=True),
           latitude="lat", longitude="lon", color="color", size="size", zoom=15)

# ---------- 표 ----------
with st.container(border=True):
    st.markdown("**가게 목록**")
    # 네이버 지도 링크 — "가게 이름 도로명 주소"를 주소에 넣을 수 있게 바꿔(%EA… 형태) 이어 붙인다
    # 주소 칸은 도로명 주소이고, 카카오에 도로명 주소가 없는 가게만 지번 주소가 들어 있다
    table = view.assign(
        네이버지도="https://map.naver.com/p/search/" + (view["이름"] + " " + view["주소"]).map(quote)
    )
    st.dataframe(
        table,
        column_order=["이름", "종류", "세부", "거리(m)", "주소", "전화", "카카오맵", "네이버지도"],
        hide_index=True,
        width="stretch",
        column_config={
            "거리(m)": st.column_config.NumberColumn(format="%d m"),
            "카카오맵": st.column_config.LinkColumn(display_text="지도 보기"),
            # 표 안의 링크는 Streamlit 이 늘 새 탭으로 연다
            "네이버지도": st.column_config.LinkColumn("네이버 지도", display_text="네이버에서 보기"),
        },
    )
