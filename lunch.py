from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st

# 이 파일 옆 .env 에 적힌 카카오 REST API 키
ENV_PATH = Path(__file__).parent / ".env"

# 공식 문서(developers.kakao.com/docs/ko/local/dev-guide)에 나온 주소와 값
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"  # 키워드로 장소 검색
CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"  # 카테고리로 장소 검색
FOOD_CODE = "FD6"  # 카테고리 그룹 코드 중 '음식점'
PAGE_SIZE = 15  # 한 번에 받을 수 있는 최대 개수(size 최대 15)
MAX_PAGES = 3  # 15개 × 3쪽 = 45개, 카카오가 보여 주는 최대 개수(pageable_count 최대 45)

DEFAULT_CENTER = "전주 객사"  # 기준 장소 칸의 처음 값 — 이 장소 좌표를 먼저 찾고 그 둘레를 찾는다


def read_env(path):
    """.env 파일의 '이름=값' 줄을 읽어 사전으로 돌려준다."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        env[name.strip()] = value.strip().strip("\"'")
    return env


def kakao_get(url, api_key, params):
    """카카오 로컬 API 를 GET 으로 부르고 받은 JSON 을 돌려준다. 실패하면 RuntimeError."""
    response = requests.get(
        url,
        headers={"Authorization": f"KakaoAK {api_key}"},
        params=params,
        timeout=10,
    )
    if response.status_code != 200:
        try:
            body = response.json()
            detail = body.get("message") or body.get("msg") or response.text
        except ValueError:
            detail = response.text
        raise RuntimeError(f"카카오 API 오류 {response.status_code}: {detail}")
    return response.json()


def find_center(api_key, query):
    """기준 장소(역·동네 이름 등)를 키워드로 찾아 카카오가 준 첫 장소의 이름·주소·좌표를 돌려준다."""
    data = kakao_get(KEYWORD_URL, api_key, {"query": query, "size": 1})
    if not data["documents"]:
        raise RuntimeError(f"카카오에서 '{query}' 장소를 찾지 못했습니다. 이름을 바꿔 다시 넣어 주세요.")
    place = data["documents"][0]
    return {
        "query": query,
        "name": place["place_name"],
        "address": place["road_address_name"] or place["address_name"],
        "x": place["x"],
        "y": place["y"],
    }


def search_restaurants(api_key, keyword, x, y, radius):
    """기준점 반경 안의 음식점을 최대 45개까지 모아 목록으로 돌려준다.

    keyword 가 있으면 키워드 검색에 음식점 카테고리를 걸고, 없으면 음식점 카테고리 전체를 찾는다.
    """
    params = {
        "category_group_code": FOOD_CODE,
        "x": x,
        "y": y,
        "radius": radius,
        "sort": "distance",
        "size": PAGE_SIZE,
    }
    url = CATEGORY_URL
    if keyword:
        url = KEYWORD_URL
        params["query"] = keyword

    places = []
    for page in range(1, MAX_PAGES + 1):
        data = kakao_get(url, api_key, {**params, "page": page})
        places.extend(data["documents"])
        if data["meta"]["is_end"]:  # 마지막 쪽이면 더 부르지 않는다
            break
    return places


def to_table(places):
    """카카오가 준 장소 목록을 화면용 표로 바꾼다."""
    rows = []
    for p in places:
        # category_name 예: "음식점 > 한식 > 육류,고기" → 두 번째 칸 "한식"을 종류로 쓴다
        parts = [s.strip() for s in p["category_name"].split(">")]
        rows.append(
            {
                "이름": p["place_name"],
                "종류": parts[1] if len(parts) > 1 else parts[0],
                "세부 분류": parts[-1],
                "거리(m)": int(p["distance"]) if p.get("distance") else None,
                "전화": p["phone"],
                "주소": p["road_address_name"] or p["address_name"],
                "지도": p["place_url"],
                "lat": float(p["y"]),
                "lon": float(p["x"]),
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(page_title="근처 맛집", page_icon=":material/restaurant:", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = None  # 마지막 검색 결과 표
    st.session_state.center = None  # 마지막으로 카카오에서 찾은 기준 장소 (find_center 가 돌려준 사전)

st.title(":material/restaurant: 근처 맛집 찾기")
st.caption("기준 장소 둘레 반경 안의 음식점을 카카오 로컬 API로 찾습니다. 검색 버튼을 누를 때만 카카오를 부릅니다.")

api_key = read_env(ENV_PATH).get("KAKAO_REST_API_KEY", "")
if not api_key:
    st.error(".env 파일에 KAKAO_REST_API_KEY 를 적어 주세요.", icon=":material/key_off:")
    st.stop()

with st.form("search"):
    cols = st.columns([3, 3, 2, 1], vertical_alignment="bottom")
    center_query = cols[0].text_input("기준 장소", value=DEFAULT_CENTER, placeholder="예: 전주역, 서학동, 강남역")
    keyword = cols[1].text_input("찾을 음식", placeholder="예: 비빔밥, 콩나물국밥 (비우면 음식점 전체)")
    radius = cols[2].slider("반경(m)", min_value=100, max_value=5000, value=500, step=100)
    clicked = cols[3].form_submit_button("검색", icon=":material/search:", type="primary", width="stretch")

if clicked:
    center_query = center_query.strip()
    if not center_query:
        st.error("기준 장소를 넣어 주세요.", icon=":material/error:")
    else:
        try:
            with st.spinner("카카오에서 찾는 중..."):
                center = st.session_state.center
                if center is None or center["query"] != center_query:  # 같은 기준 장소면 다시 찾지 않는다
                    center = find_center(api_key, center_query)
                places = search_restaurants(api_key, keyword.strip(), center["x"], center["y"], radius)
            # 둘 다 성공했을 때만 바꾼다 — 화면의 기준 장소와 결과가 늘 같은 검색에서 나온 것이 되도록
            st.session_state.center = center
            st.session_state.results = to_table(places)
        except (requests.RequestException, RuntimeError) as error:
            st.error(f"검색하지 못했습니다. {error}", icon=":material/error:")

df = st.session_state.results
if df is None:
    st.info("기준 장소·찾을 음식·반경을 고른 뒤 검색 버튼을 눌러 주세요.", icon=":material/info:")
    st.stop()

# 기준 장소는 카카오가 돌려준 이름·주소를 그대로 보여 준다
center = st.session_state.center
with st.container(border=True):
    st.markdown(f":material/location_on: **기준 장소: {center['name']}**")
    st.caption(f"주소: {center['address'] or '카카오가 주소를 주지 않았습니다'} · 입력한 말: {center['query']}")

if df.empty:
    st.warning("반경 안에 맞는 음식점이 없습니다. 반경을 넓히거나 다른 음식으로 찾아 보세요.")
    st.stop()

# 아래 거르기·정렬은 이미 받은 결과 안에서만 한다 — 카카오를 다시 부르지 않는다
with st.container(horizontal=True, vertical_alignment="bottom"):
    name_filter = st.text_input("이름으로 거르기", placeholder="결과 안에서 이름 찾기")
    kinds = st.multiselect("종류", sorted(df["종류"].unique()))
    sort_by = st.segmented_control("정렬", ["가까운 순", "먼 순", "이름순"], default="가까운 순")

view = df
if name_filter:
    view = view[view["이름"].str.contains(name_filter, case=False, regex=False)]
if kinds:
    view = view[view["종류"].isin(kinds)]
if sort_by == "먼 순":
    view = view.sort_values("거리(m)", ascending=False)
elif sort_by == "이름순":
    view = view.sort_values("이름")
else:
    view = view.sort_values("거리(m)")

with st.container(horizontal=True):
    st.metric("찾은 음식점", f"{len(view)}곳", border=True)
    st.metric("가장 가까운 곳", f"{view['거리(m)'].min():,}m" if len(view) else "-", border=True)
    st.metric("평균 거리", f"{view['거리(m)'].mean():,.0f}m" if len(view) else "-", border=True)
    st.metric("종류 수", f"{view['종류'].nunique()}가지", border=True)
st.caption("카카오는 한 번에 최대 45곳까지만 보여 줍니다.")

if view.empty:
    st.warning("거르기 조건에 맞는 음식점이 없습니다.")
    st.stop()

left, right = st.columns(2)
with left.container(border=True):
    st.subheader("종류별 음식점 수")
    counts = view.groupby("종류").size().reset_index(name="곳 수")
    chart = (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("곳 수:Q", title="곳 수"),
            y=alt.Y("종류:N", sort="-x", title=None),
            tooltip=["종류", "곳 수"],
        )
    )
    st.altair_chart(chart, alt="종류별 음식점 수 막대 차트")
with right.container(border=True):
    st.subheader("거리별 음식점 수")
    dist = (
        alt.Chart(view)
        .mark_bar()
        .encode(
            x=alt.X("거리(m):Q", bin=alt.Bin(step=100), title="거리(m), 100m 단위"),
            y=alt.Y("count():Q", title="곳 수"),
            tooltip=[alt.Tooltip("count():Q", title="곳 수")],
        )
    )
    st.altair_chart(dist, alt="거리 100m 단위별 음식점 수 막대 차트")

st.subheader("음식점 목록")
st.dataframe(
    view.drop(columns=["lat", "lon"]),
    hide_index=True,
    column_config={
        "지도": st.column_config.LinkColumn("지도", display_text="카카오맵"),
        "거리(m)": st.column_config.NumberColumn("거리(m)", format="%d m"),
    },
    alt="검색한 음식점 목록 표",
)

with st.expander("지도에서 보기", icon=":material/map:"):
    st.map(view[["lat", "lon"]], alt="찾은 음식점 위치 지도")
