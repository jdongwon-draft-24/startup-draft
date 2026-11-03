import datetime
from pathlib import Path

import requests
import streamlit as st

# 이 파일 옆 .env 에 적힌 Supabase 주소와 키
ENV_PATH = Path(__file__).parent / ".env"
TABLE = "guestbook"
MAX_LEN = 100  # 한 줄 방명록이므로 글자 수를 이 정도로 제한한다


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


def load_messages():
    # 최근 글이 위로 오게 가져온다
    r = requests.get(
        f"{BASE_URL}/rest/v1/{TABLE}",
        headers=HEADERS,
        params={"select": "id,created_at,message", "order": "created_at.desc"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def add_message(message):
    r = requests.post(
        f"{BASE_URL}/rest/v1/{TABLE}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        json={"message": message},
        timeout=10,
    )
    r.raise_for_status()


def to_local(created_at):
    # Supabase 는 UTC(세계 표준시)로 주므로 한국 시간으로 바꿔 보여준다
    t = datetime.datetime.fromisoformat(created_at)
    return t.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")


st.title("한 줄 방명록")

if not BASE_URL or not KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
    st.stop()

with st.form("write", clear_on_submit=True):
    message = st.text_input("한 줄 남기기", max_chars=MAX_LEN)
    submitted = st.form_submit_button("남기기")

if submitted:
    if not message.strip():
        st.warning("내용을 입력해 주세요.")
    else:
        try:
            add_message(message.strip())
            st.success("방명록에 남겼어요.")
        except requests.RequestException as e:
            st.error(f"글을 저장하지 못했어요: {e}")

try:
    rows = load_messages()
except requests.RequestException as e:
    st.error(f"방명록을 불러오지 못했어요: {e}")
    st.stop()

if not rows:
    st.info("아직 남긴 글이 없어요.")
for row in rows:
    st.markdown(f"**{to_local(row['created_at'])}** — {row['message']}")
