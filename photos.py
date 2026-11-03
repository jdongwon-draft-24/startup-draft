import datetime
import uuid
from pathlib import Path

import requests
import streamlit as st

# 이 파일 옆 .env 에 적힌 Supabase 주소와 키
ENV_PATH = Path(__file__).parent / ".env"
BUCKET = "photos"  # data/77_photos_storage.sql 로 만든 버킷
TYPES = ["png", "jpg", "jpeg", "gif", "webp"]
COLS = 3  # 한 줄에 보여 줄 그림 수


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


def load_photos():
    # 최근에 올린 그림이 앞에 오게 가져온다
    r = requests.post(
        f"{BASE_URL}/storage/v1/object/list/{BUCKET}",
        headers=HEADERS,
        json={"prefix": "", "limit": 1000, "sortBy": {"column": "created_at", "order": "desc"}},
        timeout=10,
    )
    r.raise_for_status()
    # 폴더(id 없음)와 Supabase 가 만드는 빈 자리 표시 파일은 뺀다
    return [f for f in r.json() if f.get("id") and not f["name"].startswith(".")]


def upload_photo(file):
    # Supabase Storage 는 한글 파일 이름을 받지 않으므로 시각+임의 글자로 이름을 새로 붙인다
    ext = Path(file.name).suffix.lower()
    name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ext
    r = requests.post(
        f"{BASE_URL}/storage/v1/object/{BUCKET}/{name}",
        headers={**HEADERS, "Content-Type": file.type or "application/octet-stream"},
        data=file.getvalue(),
        timeout=30,
    )
    r.raise_for_status()


def public_url(name):
    return f"{BASE_URL}/storage/v1/object/public/{BUCKET}/{name}"


def to_local(created_at):
    # Supabase 는 UTC(세계 표준시)로 주므로 한국 시간으로 바꿔 보여준다
    t = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return t.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")


st.title("사진 보관함")

if not BASE_URL or not KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
    st.stop()

with st.form("upload", clear_on_submit=True):
    files = st.file_uploader("그림 고르기", type=TYPES, accept_multiple_files=True)
    submitted = st.form_submit_button("올리기")

if submitted:
    if not files:
        st.warning("올릴 그림을 골라 주세요.")
    else:
        done = 0
        for file in files:
            try:
                upload_photo(file)
                done += 1
            except requests.RequestException as e:
                st.error(f"'{file.name}' 을 올리지 못했어요: {e}")
        if done:
            st.success(f"그림 {done}장을 올렸어요.")

try:
    photos = load_photos()
except requests.RequestException as e:
    st.error(f"사진 목록을 불러오지 못했어요: {e}")
    st.stop()

if not photos:
    st.info("아직 올린 그림이 없어요.")
else:
    st.caption(f"모두 {len(photos)}장")
    cols = st.columns(COLS)
    for i, photo in enumerate(photos):
        with cols[i % COLS]:
            st.image(
                public_url(photo["name"]),
                caption=to_local(photo["created_at"]),
                width="stretch",
                alt=photo["name"],
            )
