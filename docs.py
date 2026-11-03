import base64
import datetime
import uuid
from pathlib import Path
from urllib.parse import quote

import requests
import streamlit as st

# 이 파일 옆 .env 에 적힌 Supabase 주소와 키
ENV_PATH = Path(__file__).parent / ".env"
BUCKET = "docs"  # data/78_docs_storage.sql 로 만든 비공개 버킷
TYPES = ["pdf", "docx", "xlsx", "pptx", "hwp", "hwpx", "txt", "csv"]
LINK_SECONDS = 60  # 내려받기 링크가 열려 있는 시간(초)


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


def make_name(original):
    # Supabase Storage 는 한글 파일 이름을 받지 않으므로
    # 원래 이름을 base64(글자를 영문·숫자로 바꿔 적는 방식)로 바꿔 시각 뒤에 붙인다
    path = Path(original)
    code = base64.urlsafe_b64encode(path.stem.encode("utf-8")).decode().rstrip("=")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    return f"{stamp}__{code}{path.suffix.lower()}"


def original_name(name):
    # make_name 으로 붙인 이름에서 원래 파일 이름을 되살린다 (실패하면 저장된 이름 그대로)
    path = Path(name)
    if "__" not in path.stem:
        return name
    code = path.stem.split("__", 1)[1]
    try:
        stem = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode("utf-8")
    except ValueError:
        return name
    return stem + path.suffix


def load_docs():
    # 최근에 올린 문서가 앞에 오게 가져온다
    r = requests.post(
        f"{BASE_URL}/storage/v1/object/list/{BUCKET}",
        headers=HEADERS,
        json={"prefix": "", "limit": 1000, "sortBy": {"column": "created_at", "order": "desc"}},
        timeout=10,
    )
    r.raise_for_status()
    # 폴더(id 없음)와 Supabase 가 만드는 빈 자리 표시 파일은 뺀다
    return [f for f in r.json() if f.get("id") and not f["name"].startswith(".")]


def upload_doc(file):
    r = requests.post(
        f"{BASE_URL}/storage/v1/object/{BUCKET}/{make_name(file.name)}",
        headers={**HEADERS, "Content-Type": file.type or "application/octet-stream"},
        data=file.getvalue(),
        timeout=30,
    )
    r.raise_for_status()


def signed_urls(names):
    # 문서마다 LINK_SECONDS 초 동안만 열리는 내려받기 링크를 한 번에 받는다
    r = requests.post(
        f"{BASE_URL}/storage/v1/object/sign/{BUCKET}",
        headers=HEADERS,
        json={"expiresIn": LINK_SECONDS, "paths": names},
        timeout=10,
    )
    r.raise_for_status()
    urls = {}
    for item in r.json():
        if item.get("signedURL"):
            # download= 를 붙이면 브라우저가 원래 이름으로 저장한다
            download = quote(original_name(item["path"]))
            urls[item["path"]] = f"{BASE_URL}/storage/v1{item['signedURL']}&download={download}"
    return urls


def to_local(created_at):
    # Supabase 는 UTC(세계 표준시)로 주므로 한국 시간으로 바꿔 보여준다
    t = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return t.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")


def to_size(doc):
    size = (doc.get("metadata") or {}).get("size", 0)
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"


st.title("문서 보관함")

if not BASE_URL or not KEY:
    st.error(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣어 주세요.")
    st.stop()

with st.form("upload", clear_on_submit=True):
    files = st.file_uploader("문서 고르기", type=TYPES, accept_multiple_files=True)
    submitted = st.form_submit_button("올리기", icon=":material/upload:")

if submitted:
    if not files:
        st.warning("올릴 문서를 골라 주세요.")
    else:
        done = 0
        for file in files:
            try:
                upload_doc(file)
                done += 1
            except requests.RequestException as e:
                st.error(f"'{file.name}' 을 올리지 못했어요: {e}")
        if done:
            st.success(f"문서 {done}개를 올렸어요.")

try:
    docs = load_docs()
    urls = signed_urls([d["name"] for d in docs]) if docs else {}
except requests.RequestException as e:
    st.error(f"문서 목록을 불러오지 못했어요: {e}")
    st.stop()

if not docs:
    st.info("아직 올린 문서가 없어요.")
else:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"모두 {len(docs)}개 · 내려받기 링크는 {LINK_SECONDS}초 동안만 열려요")
        st.button("링크 새로 받기", icon=":material/refresh:")  # 누르면 화면을 다시 그려 새 링크를 받는다
    for doc in docs:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{original_name(doc['name'])}**  \n{to_local(doc['created_at'])} · {to_size(doc)}")
            if doc["name"] in urls:
                st.link_button("내려받기", urls[doc["name"]], icon=":material/download:")
            else:
                st.caption("링크를 만들지 못했어요")
