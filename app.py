import csv
import datetime
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import requests
import streamlit as st

# 이 파일 옆 data 폴더의 샘플 세무·행정 항목 자료
CSV_PATH = Path(__file__).parent / "data" / "sample-tax-items.csv"

# 이 파일 옆 .env 에 적힌 Supabase 주소와 키
ENV_PATH = Path(__file__).parent / ".env"
CHAT_TABLE = "chat_logs"  # 상담 챗봇에 물은 말과 받은 답을 남기는 표
CHAT_LOG_LIMIT = 20  # 대화창 아래 지난 대화 목록에 보여 줄 최근 대화 수


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

# 공식 문서(ai.google.dev/gemini-api/docs/text-generation, /docs/models)에 나온 모델과 주소 — helper.py 와 같다
GEMINI_KEY = env.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

PRD_PATH = Path(__file__).parent / "PRD.md"

# 챗봇에게 주는 고정 지시문 — 이 파일 옆 chatbot_instruction.txt 에 있고, 이 뒤에 PRD.md 전체를 붙여서 보낸다
INSTRUCTION_PATH = Path(__file__).parent / "chatbot_instruction.txt"


def load_instruction(path):
    # 질문할 때마다 새로 읽는다 — 파일을 고치면 앱을 다시 띄우지 않아도 다음 질문부터 바뀐다
    return path.read_text(encoding="utf-8").strip() + "\n\n"


@st.cache_data
def load_prd(path):
    return path.read_text(encoding="utf-8")


def ask_gemini(api_key, text, instruction, previous_id=None):
    """text 를 Gemini 에 보내고, (받은 답 글, 토큰 사용량 사전, 이번 대화 번호)를 돌려준다.

    previous_id 에 앞 대화 번호를 넣으면 Gemini 가 앞 대화를 이어서 답한다.
    """
    payload = {"model": GEMINI_MODEL, "system_instruction": instruction, "input": text}
    if previous_id:
        payload["previous_interaction_id"] = previous_id
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GEMINI_URL,
        data=body,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    # 답 글은 steps 안의 model_output 단계 → content 안의 text 항목에 들어 있다
    usage = data.get("usage", {})
    outputs = [s for s in data.get("steps", []) if s.get("type") == "model_output"]
    if not outputs:
        return "", usage, data.get("id")
    parts = outputs[-1].get("content", [])
    answer = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return answer, usage, data.get("id")


def save_chat(question, answer):
    # 물은 말과 받은 답 한 쌍을 Supabase chat_logs 표에 한 줄로 남긴다
    r = requests.post(
        f"{BASE_URL}/rest/v1/{CHAT_TABLE}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        json={"question": question, "answer": answer},
        timeout=10,
    )
    r.raise_for_status()
    load_chat_logs.clear()  # 지난 대화 목록에 방금 대화가 바로 보이게 한다


@st.cache_data(ttl=60)
def load_chat_logs():
    # 최근 대화가 위로 오게 CHAT_LOG_LIMIT 개만 가져온다
    r = requests.get(
        f"{BASE_URL}/rest/v1/{CHAT_TABLE}",
        headers=HEADERS,
        params={"select": "id,created_at,question,answer", "order": "created_at.desc", "limit": CHAT_LOG_LIMIT},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def to_local(created_at):
    # Supabase 는 UTC(세계 표준시)로 주므로 한국 시간으로 바꿔 보여준다 — guestbook.py 와 같다
    t = datetime.datetime.fromisoformat(created_at)
    return t.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")


def industry_key(name):
    # 띄어쓰기를 모두 빼고 비교한다 — "IT서비스개발업"과 "IT 서비스 개발업"을 같은 업종으로 본다
    return "".join(name.split())


# 등록일부터 며칠 이내라는 기준이 이보다 길면 자료가 잘못 들어간 것으로 본다
MAX_DAYS = 365


def make_date(year, month, day):
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None  # 13월, 2월 30일처럼 달력에 없는 날


def deadline(rule, registered_on):
    """기한_기준 글과 등록일로 마감할 기한을 구한다.

    (종류, 날짜, 덧붙일 글)을 돌려준다. 종류는 "날짜"(계산됨), "조건"(등록일만으로는
    정할 수 없음), "없음"(자료에 기준이 비어 있음), "오류"(기준 글이 잘못됨) 가운데 하나다.
    """
    rule = rule.strip()
    if not rule:
        return "없음", None, ""

    # 예: 등록일이 1~6월이면 그해 7월 25일까지 / 7~12월이면 다음 해 1월 25일까지
    if rule.startswith("등록일이"):
        for part in rule.split("/"):
            m = re.search(r"(\d+)~(\d+)월이면 (그해|다음 해) (\d+)월 (\d+)일까지", part)
            if m and int(m[1]) <= registered_on.month <= int(m[2]):
                year = registered_on.year + (1 if m[3] == "다음 해" else 0)
                d = make_date(year, int(m[4]), int(m[5]))
                return ("날짜", d, "") if d else ("오류", None, part.strip())
        return "오류", None, rule

    # 예: 등록한 해의 다음 해 5월 31일까지
    m = re.fullmatch(r"등록한 해의 (그해|다음 해) (\d+)월 (\d+)일까지", rule)
    if m:
        year = registered_on.year + (1 if m[1] == "다음 해" else 0)
        d = make_date(year, int(m[2]), int(m[3]))
        return ("날짜", d, "") if d else ("오류", None, rule)

    # 예: 등록일부터 30일 이내
    m = re.fullmatch(r"등록일부터 (-?\d+)일 이내", rule)
    if m:
        days = int(m[1])
        if 0 <= days <= MAX_DAYS:
            return "날짜", registered_on + datetime.timedelta(days=days), ""
        return "오류", None, rule

    if rule == "등록일 이후 바로":
        return "날짜", registered_on, "바로"

    # 첫 매출 거래 전, 직원을 처음 뽑은 날부터 14일 이내처럼 등록일과 상관없는 기준
    m = re.search(r"(-\d+)일", rule)
    if m:
        return "오류", None, rule  # 음수 일수는 잘못 들어간 값
    return "조건", None, rule


def deadline_text(rule, registered_on):
    kind, d, note = deadline(rule, registered_on)
    if kind == "날짜":
        return f"마감: {d:%Y-%m-%d}" + (f" ({note})" if note else "")
    if kind == "조건":
        return f"마감: {note} — 등록일만으로는 날짜를 정할 수 없어요"
    if kind == "없음":
        return "마감: 샘플 자료에 기한 기준이 없어요"
    return f"마감: 계산할 수 없어요 — 샘플 자료의 기한 기준이 잘못됐어요 (\"{note}\")"


def deadline_order(rule, registered_on):
    # 마감 날짜가 나오는 항목을 가까운 순으로 앞에, 날짜를 정할 수 없는 항목은 뒤에 둔다
    kind, d, _ = deadline(rule, registered_on)
    return (0, d) if kind == "날짜" else (1, datetime.date.max)


def d_day(d, today):
    # 오늘부터 마감까지 남은 날 수 — 지났으면 D+지난 날 수
    days = (d - today).days
    if days == 0:
        return "D-day"
    return f"D-{days}" if days > 0 else f"D+{-days}"


@st.cache_data
def load_items(path):
    """업종별 항목 이름 목록과, 정리하면서 뺀 줄 목록을 돌려준다."""
    items = {}  # 업종 키 -> {"업종": 보여 줄 이름, "항목": [항목 이름, ...], "기한_기준": {항목 이름: 기준 글}}
    skipped = []  # (줄 번호, 까닭)
    with open(path, encoding="utf-8-sig", newline="") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            industry = (row.get("업종") or "").strip()
            item = (row.get("항목") or "").strip()
            if not industry:
                skipped.append((line_no, f"업종 칸이 비어 있음 ({item})"))
                continue
            if not item:
                skipped.append((line_no, f"항목 칸이 비어 있음 ({industry})"))
                continue
            group = items.setdefault(industry_key(industry), {"업종": industry, "항목": [], "기한_기준": {}})
            if item in group["항목"]:
                skipped.append((line_no, f"같은 항목이 한 번 더 나옴 ({industry} · {item})"))
                continue
            group["항목"].append(item)
            group["기한_기준"][item] = row.get("기한_기준") or ""
    return items, skipped


ITEMS, SKIPPED = load_items(CSV_PATH)

# 전체 항목과 남은 항목 두 열이 나란히 들어가도록 화면 폭을 넓게 쓴다
st.set_page_config(page_title="사업자등록 정보 입력", layout="wide")

if "screen" not in st.session_state:
    st.session_state.screen = 1
    st.session_state.done = []


def go_to(screen):
    st.session_state.screen = screen


# 상담 챗봇 — 화면 오른쪽 아래에 떠 있는 아이콘, 누르면 대화창이 열린다 (화면1~3 어디서든 보인다)
if "chat" not in st.session_state:
    st.session_state.chat = []  # [{"role": "user" 또는 "assistant", "text": 글}, ...]
    st.session_state.chat_id = None  # Gemini 가 돌려준 마지막 대화 번호

# Streamlit 에는 화면 구석에 떠 있는 단추가 없어서, 위치와 동그란 모양만 CSS 로 정한다
st.html(
    """
    <style>
    .st-key-chatbot { position: fixed; right: 24px; bottom: 24px; width: auto; z-index: 1000; }
    .st-key-chatbot button { width: 64px; height: 64px; border-radius: 50%; font-size: 32px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); cursor: grab; touch-action: none; }
    .st-key-chatbot_drag { display: none; }
    </style>
    """
)

# Streamlit 에는 끌어서 옮기는 기능이 없어서, 아이콘을 누른 채 움직이면 따라오게 하는 JavaScript 를 붙인다
# 살짝 누르기만 하면 대화창이 열리고, 끌고 놓은 자리는 브라우저에 기억해 둔다
with st.container(key="chatbot_drag"):
    st.html(
        """
        <script>
        (function () {
          if (window.chatbotDragReady) return;  // 화면이 다시 그려져도 한 번만 붙인다
          window.chatbotDragReady = true;
          const SAVE = "chatbot-position";
          const box = () => document.querySelector(".st-key-chatbot");
          const icon = () => box() && box().querySelector("button");
          let drag = null;
          let moved = false;

          function place(b, x, y) {
            // 화면 밖으로 나가지 않게 막는다
            x = Math.min(Math.max(0, x), window.innerWidth - b.offsetWidth);
            y = Math.min(Math.max(0, y), window.innerHeight - b.offsetHeight);
            Object.assign(b.style, { left: x + "px", top: y + "px", right: "auto", bottom: "auto" });
            return { x, y };
          }

          function restore() {
            const b = box();
            if (!b || b.dataset.placed) return;
            let p = null;
            try { p = JSON.parse(localStorage.getItem(SAVE)); } catch (e) {}
            if (p) place(b, p.x, p.y);
            b.dataset.placed = "1";
          }

          document.addEventListener("pointerdown", (e) => {
            const i = icon();
            if (!i || !i.contains(e.target)) return;
            const r = box().getBoundingClientRect();
            drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY };
            moved = false;
          }, true);

          document.addEventListener("pointermove", (e) => {
            if (!drag) return;
            // 5px 넘게 움직여야 끄는 것으로 본다 — 그보다 적으면 그냥 누른 것
            if (!moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 5) return;
            moved = true;
            e.preventDefault();
            drag.at = place(box(), e.clientX - drag.dx, e.clientY - drag.dy);
          }, true);

          document.addEventListener("pointerup", () => {
            if (drag && moved && drag.at) {
              try { localStorage.setItem(SAVE, JSON.stringify(drag.at)); } catch (e) {}
            }
            drag = null;
          }, true);

          // 끌고 놓았을 때는 대화창이 열리지 않게 한다
          document.addEventListener("click", (e) => {
            const i = icon();
            if (moved && i && i.contains(e.target)) {
              e.preventDefault();
              e.stopPropagation();
            }
            moved = false;
          }, true);

          new MutationObserver(restore).observe(document.body, { childList: true, subtree: true });
          restore();
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )

with st.container(key="chatbot"):
    with st.popover("🐥", help="서비스에 대해 물어보세요"):
        st.markdown("**상담 챗봇**")

        # 대화 자리 — 주고받은 말이 쌓이고, 길어지면 이 안에서 내려 본다
        messages = st.container(height=320, width=320)
        with messages:
            if not st.session_state.chat:
                with st.chat_message("assistant", avatar="🐥"):
                    st.markdown("안녕하세요! 이 서비스에 대해 궁금한 점을 물어보세요.")
            for m in st.session_state.chat:
                with st.chat_message(m["role"], avatar="🐥" if m["role"] == "assistant" else None):
                    st.markdown(m["text"].replace("\n", "  \n"))  # 줄바꿈이 화면에서도 보이게 한다

        # 넣는 자리
        question = st.chat_input("궁금한 점을 입력해 주세요", key="chat_question")
        if question:
            st.session_state.chat.append({"role": "user", "text": question})
            with messages:
                with st.chat_message("user"):
                    st.markdown(question)
                with st.chat_message("assistant", avatar="🐥"):
                    answered = False  # Gemini 가 실제로 답했을 때만 표에 남긴다 — 오류 안내는 남기지 않는다
                    if not GEMINI_KEY:
                        answer = ".env 에 GEMINI_API_KEY 를 넣어 주세요."
                    else:
                        try:
                            with st.spinner("답을 생각하는 중..."):
                                answer, _, st.session_state.chat_id = ask_gemini(
                                    GEMINI_KEY,
                                    question,
                                    load_instruction(INSTRUCTION_PATH) + load_prd(PRD_PATH),
                                    st.session_state.chat_id,
                                )
                            answered = bool(answer)
                            answer = answer or "받은 답이 비어 있습니다."
                        except urllib.error.HTTPError as e:
                            answer = f"Gemini 요청이 실패했습니다 ({e.code}): {e.read().decode('utf-8', 'replace')}"
                        except urllib.error.URLError as e:
                            answer = f"Gemini 에 연결하지 못했습니다: {e.reason}"
                        except FileNotFoundError as e:
                            answer = f"지시문이나 기획서 파일을 찾지 못했습니다: {Path(e.filename).name}"
                    st.markdown(answer.replace("\n", "  \n"))
            st.session_state.chat.append({"role": "assistant", "text": answer})
            if answered and BASE_URL and KEY:
                try:
                    save_chat(question, answer)
                except requests.RequestException as e:
                    st.warning(f"대화를 Supabase에 저장하지 못했어요: {e}")

        st.caption(f"출처: PRD.md + AI({GEMINI_MODEL}) 일반 지식 · AI가 만든 답이라 틀릴 수 있어요")

        # 지난 대화 목록 — Supabase chat_logs 표에 남은 최근 대화를 대화창 아래에 보여 준다
        st.markdown("**지난 대화**")
        if not BASE_URL or not KEY:
            st.caption(".env 에 SUPABASE_URL 과 SUPABASE_KEY 를 넣으면 지난 대화가 보여요.")
        else:
            try:
                logs = load_chat_logs()
            except requests.RequestException as e:
                logs = None
                st.caption(f"지난 대화를 불러오지 못했어요: {e}")
            if logs == []:
                st.caption("아직 남은 대화가 없어요.")
            elif logs:
                with st.container(height=240, width=320):
                    for log in logs:
                        with st.container(border=True):
                            st.caption(to_local(log["created_at"]))
                            st.markdown(f"**물은 말:** {log['question']}")
                            st.markdown("**받은 답:**  \n" + log["answer"].replace("\n", "  \n"))
            st.caption(f"출처: Supabase {CHAT_TABLE} 표 · 최근 {CHAT_LOG_LIMIT}개까지")


def suggest_industry(name):
    """name 과 가장 비슷한 샘플 자료 업종을 찾아 (업종 키, AI 를 못 쓴 까닭)을 돌려준다.

    비슷한 업종이 없으면 (None, None), AI 를 쓸 수 없으면 (None, 까닭 글)이다.
    """
    if not GEMINI_KEY:
        return None, ".env 에 GEMINI_API_KEY 가 없어요"
    names = [group["업종"] for group in ITEMS.values()]
    instruction = (
        "사용자가 적은 업종과 가장 비슷한 업종을 아래 목록에서 하나만 골라 그 이름만 답하라. "
        "목록에 비슷한 업종이 없으면 '없음'이라고만 답하라.\n목록:\n" + "\n".join(f"- {n}" for n in names)
    )
    try:
        answer, _, _ = ask_gemini(GEMINI_KEY, name, instruction)
    except urllib.error.HTTPError as e:
        return None, f"Gemini 요청 실패 ({e.code})"
    except urllib.error.URLError as e:
        return None, f"Gemini 연결 실패 ({e.reason})"
    except (OSError, ValueError) as e:
        return None, f"Gemini 답을 받지 못함 ({e})"  # 시간 초과(OSError), 받은 답을 읽지 못함(ValueError)
    # "**음식점업**", "음식점업입니다"처럼 덧붙인 글자가 있어도 목록 속 업종 이름이 하나만 들어 있으면 그 업종으로 본다
    # AI 가 목록에 없는 이름을 답하면 버린다 — 항목 자료에 있는 업종만 쓴다
    found = [key for key in ITEMS if key in industry_key(answer)]
    return (found[0] if len(found) == 1 else None), None


def answer_suggestion(yes):
    st.session_state.accepted = yes


def toggle(item, key):
    # 체크하면 완료 목록에 넣고 화면3으로, 체크를 풀면 완료 목록에서 뺀다
    if st.session_state[key]:
        if item not in st.session_state.done:
            st.session_state.done.append(item)
        go_to(3)
    elif item in st.session_state.done:
        st.session_state.done.remove(item)


# 왼쪽 사이드바 — 사업자등록 정보 입력 (넣는 자리)
with st.sidebar:
    st.header("사업자등록 정보 입력")

    # 샘플 항목 자료에 있는 업종을 자료에 나온 차례대로 보여 준다
    industries = [group["업종"] for group in ITEMS.values()]

    # 샘플 항목 자료의 업종을 고르거나, 목록에 없는 업종은 직접 쳐서 넣는다
    industry = st.selectbox(
        "업종",
        industries,
        index=None,
        accept_new_options=True,
        placeholder="업종을 고르거나, 목록에 없으면 직접 쳐서 넣어 주세요",
    )
    registered_on = st.date_input("사업자등록일", value=None, format="YYYY-MM-DD")

    # 단추
    if st.button("조회", width="stretch"):
        industry = (industry or "").strip()
        if not industry or registered_on is None:
            st.error("업종과 사업자등록일을 입력해 주세요")
        else:
            # 띄어쓰기만 다른 업종이 이미 있으면 그 이름을 쓴다
            same = [name for name in industries if industry_key(name) == industry_key(industry)]
            if same:
                industry = same[0]
            st.session_state.industry = industry
            st.session_state.registered_on = registered_on
            st.session_state.done = []
            st.session_state.pop("suggestion", None)  # 새로 조회하면 비슷한 업종을 다시 찾는다
            st.session_state.accepted = None
            for key in [k for k in st.session_state if str(k).startswith("item_")]:
                del st.session_state[key]
            go_to(2)
            st.rerun()

    if st.session_state.screen != 1:
        st.button("처음으로 돌아가기", width="stretch", on_click=go_to, args=(1,))

    st.caption(f"업종 목록 출처: data/sample-tax-items.csv · 모두 {len(industries)}개")


def show_checklist():
    """「체크리스트」 탭 — 맨 위에 업종 요약·비슷한 업종 질문, 아래 두 열에 전체 항목과 남은 항목."""
    if st.session_state.screen == 1:
        st.caption("※ 입력 후 조회를 누르면 업종·등록일 기준 세무·행정 항목이 나옵니다")
        return

    group = ITEMS.get(industry_key(st.session_state.industry))
    suggested = None
    if group is None:
        # 샘플 항목 자료에 없는 업종 — AI 가 자료에 있는 업종 가운데 비슷한 것을 찾는다
        # 조회할 때 한 번만 찾아 두고, 체크할 때마다 다시 묻지 않는다
        if "suggestion" not in st.session_state:
            with st.spinner("비슷한 업종을 찾는 중..."):
                st.session_state.suggestion, st.session_state.suggestion_error = suggest_industry(
                    st.session_state.industry
                )
        suggested = st.session_state.suggestion
        if suggested and st.session_state.get("accepted"):
            group = ITEMS[suggested]

    if group is None:
        st.subheader("세무·행정 항목 목록")
        if suggested and st.session_state.get("accepted") is None:
            st.markdown(f"비슷한 업종: {ITEMS[suggested]['업종']} — 이 업종으로 볼까요?")
            yes_col, no_col = st.columns(2)
            yes_col.button("네", width="stretch", on_click=answer_suggestion, args=(True,))
            no_col.button("아니요", width="stretch", on_click=answer_suggestion, args=(False,))
        else:
            st.info(f"'{st.session_state.industry}' 업종의 세무·행정 항목 자료가 아직 없어요.")
            if st.session_state.get("suggestion_error"):
                st.caption(f"AI에 연결하지 못해 비슷한 업종을 찾지 못했어요: {st.session_state.suggestion_error}")
        return
    all_items = group["항목"]
    done = [item for item in all_items if item in st.session_state.done]
    remaining = [item for item in all_items if item not in st.session_state.done]
    registered_on = st.session_state.registered_on

    # 맨 위 — 입력한 업종과 등록일
    with st.container(border=True):
        if suggested:
            shown = f"입력한 업종: {st.session_state.industry} → 비슷한 업종: {group['업종']}"
        else:
            shown = f"업종: {group['업종']}"
        st.markdown(f"{shown} / 등록일: {registered_on:%Y-%m-%d}")

    all_col, left_col = st.columns(2, gap="large")

    with all_col:
        # 화면2 — 세무·행정 항목 목록
        st.subheader("세무·행정 항목 목록")
        for number, item in enumerate(all_items, start=1):
            key = f"item_{number}"
            # 오른쪽 열에서 체크해도 이쪽 체크 표시가 함께 바뀌도록 그리기 전에 맞춰 둔다
            st.session_state[key] = item in st.session_state.done
            with st.container(border=True):
                st.checkbox(rf"{number}\. {item}", key=key, on_change=toggle, args=(item, key))
                # 등록일 기준으로 계산한 마감할 기한
                st.caption(deadline_text(group["기한_기준"][item], registered_on))

    with left_col:
        # 화면3 — 남은 항목 확인 (완료 위 / 남은 항목 아래)
        st.subheader("남은 항목 확인")

        for item in done:
            with st.container(border=True):
                st.checkbox(f"~~{item}~~", value=True, disabled=True, key=f"done_{item}")

        st.divider()
        st.caption("완료 항목은 목록에서 제외되고, 아래에 남은 항목만 표시됩니다")

        # 남은 항목은 마감이 가까운 순으로 보여 준다 — 날짜를 정할 수 없는 항목은 원래 순서대로 맨 뒤
        remaining = sorted(remaining, key=lambda item: deadline_order(group["기한_기준"][item], registered_on))
        today = datetime.date.today()

        for item in remaining:
            key = f"left_{item}"
            with st.container(border=True):
                st.checkbox(item, value=False, key=key, on_change=toggle, args=(item, key))
                # 남은 항목에만 마감할 기한을 보여 준다 — 완료한 항목에는 보여 주지 않는다
                rule = group["기한_기준"][item]
                text = deadline_text(rule, registered_on)
                kind, d, _ = deadline(rule, registered_on)
                if kind == "날짜":
                    text += f" · {d_day(d, today)}"
                st.caption(text)

        st.button("목록으로 돌아가기", width="stretch", on_click=go_to, args=(2,))

    # PRD 에 "화면2·화면3 아래 출처"로 정해져 있어 두 열 바로 아래에 둔다
    if suggested:
        st.caption(f"비슷한 업종: AI({GEMINI_MODEL}) 제안 · 틀릴 수 있어요")


def show_sources():
    """「자료 출처」 탭 — 가끔 보는 항목 자료 출처와 정리하며 뺀 줄 목록."""
    st.markdown(f"출처: data/sample-tax-items.csv · 정리하며 뺀 줄 {len(SKIPPED)}개")
    for line_no, reason in SKIPPED:
        st.markdown(f"- {line_no}번째 줄: {reason}")


checklist_tab, sources_tab = st.tabs(["체크리스트", "자료 출처"])
with checklist_tab:
    show_checklist()
with sources_tab:
    show_sources()
