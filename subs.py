import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# 이 파일 옆 .env 에 적힌 Supabase 주소와 키
ENV_PATH = Path(__file__).parent / ".env"
TABLE = "subscriptions"
COLUMNS = ["id", "name", "category", "monthly_fee", "last_used"]


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


env = read_env(ENV_PATH)
BASE_URL = env.get("SUPABASE_URL", "").rstrip("/")
KEY = env.get("SUPABASE_KEY", "")
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
URL = f"{BASE_URL}/rest/v1/{TABLE}"


def load_subs():
    r = requests.get(
        URL,
        headers=HEADERS,
        params={"select": ",".join(COLUMNS), "order": "id.asc"},
        timeout=10,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=COLUMNS)
    # 날짜 칸에서 달력으로 고를 수 있게 글자를 날짜로 바꾼다
    df["last_used"] = pd.to_datetime(df["last_used"]).dt.date
    return df


def add_sub(row):
    r = requests.post(URL, headers={**HEADERS, "Prefer": "return=minimal"}, json=row, timeout=10)
    r.raise_for_status()


def update_sub(sub_id, changes):
    r = requests.patch(
        URL,
        headers={**HEADERS, "Prefer": "return=minimal"},
        params={"id": f"eq.{sub_id}"},
        json=changes,
        timeout=10,
    )
    r.raise_for_status()


def delete_sub(sub_id):
    r = requests.delete(URL, headers=HEADERS, params={"id": f"eq.{sub_id}"}, timeout=10)
    r.raise_for_status()


def clean(row):
    """표에서 바뀐 값을 Supabase 에 보낼 모양으로 고친다. 잘못된 값이 있으면 까닭을 돌려준다."""
    out = {}
    for name, value in row.items():
        if name == "id":
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            return None, "이름·분류·월 요금·마지막 사용일을 모두 채워 주세요."
        if name == "monthly_fee":
            value = int(value)
            if value < 0:
                return None, "월 요금은 0원 이상이어야 해요."
        elif name == "last_used":
            value = str(value)[:10]  # '2026-10-24' 처럼 날짜 부분만 보낸다
        else:
            value = str(value).strip()
        out[name] = value
    return out, None


def save_changes(df, changes):
    """표에서 지운 줄·고친 줄·더한 줄을 Supabase 에 반영한다.
    중간에 일부만 저장되지 않도록, 모든 줄을 먼저 검사한 뒤에 보낸다."""
    deleted = [int(df.iloc[idx]["id"]) for idx in changes["deleted_rows"]]
    updates, adds = [], []
    for idx, edited in changes["edited_rows"].items():
        if int(idx) in changes["deleted_rows"]:
            continue
        row, error = clean(edited)
        if error:
            return error
        updates.append((int(df.iloc[int(idx)]["id"]), row))
    for added in changes["added_rows"]:
        # 새 줄은 네 칸이 모두 있어야 하므로 빠진 칸은 빈 값으로 채워 검사한다
        row, error = clean({c: added.get(c) for c in COLUMNS[1:]})
        if error:
            return error
        adds.append(row)

    for sub_id in deleted:
        delete_sub(sub_id)
    for sub_id, row in updates:
        update_sub(sub_id, row)
    for row in adds:
        add_sub(row)
    return None


st.set_page_config(page_title="구독 정리함", page_icon=":material/subscriptions:")
st.title("구독 정리함")

if not BASE_URL or not KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
    st.stop()

# 저장할 때마다 숫자를 바꿔 표를 새로 그린다 (고치던 흔적이 남지 않게)
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0
if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))

try:
    df = load_subs()
except requests.RequestException as e:
    st.error(f"구독 목록을 불러오지 못했어요: {e}")
    st.stop()

with st.container(horizontal=True):
    st.metric("구독 수", f"{len(df)}개", border=True)
    st.metric("한 달 합계", f"{int(df['monthly_fee'].sum()):,}원", border=True)

st.caption("칸을 눌러 고치고, 맨 아래 줄에서 새 구독을 더하고, 왼쪽 칸을 골라 휴지통으로 지운 뒤 '저장'을 누르세요.")

editor_key = f"editor_{st.session_state.editor_version}"
st.data_editor(
    df,
    key=editor_key,
    num_rows="dynamic",
    hide_index=True,
    column_order=COLUMNS[1:],
    column_config={
        "name": st.column_config.TextColumn("이름", required=True),
        "category": st.column_config.TextColumn("분류", required=True),
        "monthly_fee": st.column_config.NumberColumn(
            "월 요금(원)", min_value=0, step=100, format="localized", required=True
        ),
        "last_used": st.column_config.DateColumn("마지막 사용일", format="YYYY-MM-DD", required=True),
    },
    alt="구독 목록 표",
)

changes = st.session_state[editor_key]
has_changes = any(changes[k] for k in ("edited_rows", "added_rows", "deleted_rows"))

with st.container(horizontal=True):
    save = st.button("저장", type="primary", icon=":material/save:", disabled=not has_changes)
    if st.button("되돌리기", icon=":material/undo:", disabled=not has_changes):
        st.session_state.editor_version += 1
        st.rerun()

if save:
    try:
        error = save_changes(df, changes)
    except requests.RequestException as e:
        error = f"Supabase 에 저장하지 못했어요: {e}"
    if error:
        st.error(error)
    else:
        st.session_state.notice = "저장했어요."
        st.session_state.editor_version += 1
        st.rerun()
