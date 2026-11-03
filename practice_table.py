import csv
from pathlib import Path

import streamlit as st

# 이 파일 옆 data 폴더의 연습용 문의 목록
CSV_PATH = Path(__file__).parent / "data" / "56_practice-inquiries.csv"

# 표 머리글을 한국어로 바꿔 보여 준다
COLUMN_NAMES = {
    "date": "날짜",
    "type": "종류",
    "message": "문의 내용",
    "status": "상태",
}


@st.cache_data
def load_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{COLUMN_NAMES.get(key, key): value for key, value in row.items()} for row in csv.DictReader(f)]


st.title("연습용 문의 목록")

rows = load_rows(CSV_PATH)

st.caption(f"출처: data/56_practice-inquiries.csv · 모두 {len(rows)}건")

# type 열(종류) 값으로 거르는 필터 — 처음에는 전체를 보여 준다
ALL = "전체"
types = list(dict.fromkeys(row["종류"] for row in rows))
selected = st.segmented_control("종류", [ALL, *types], default=ALL)

if selected in (None, ALL):
    shown_rows = rows
else:
    shown_rows = [row for row in rows if row["종류"] == selected]

# status 열(상태) 값으로 한 번 더 거른다 — 두 필터에 모두 맞는 줄만 남는다
statuses = list(dict.fromkeys(row["상태"] for row in rows))
selected_status = st.segmented_control("상태", [ALL, *statuses], default=ALL)

if selected_status not in (None, ALL):
    shown_rows = [row for row in shown_rows if row["상태"] == selected_status]

st.markdown(f"보이는 줄 수: **{len(shown_rows)}**")
st.dataframe(shown_rows,hide_index=True, alt="2026년 9월 고객 문의 목록 (날짜, 종류, 문의 내용, 상태)")
