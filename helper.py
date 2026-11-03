import json
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

# 이 파일 옆 .env 에 적힌 Gemini 키
ENV_PATH = Path(__file__).parent / ".env"

# 공식 문서(ai.google.dev/gemini-api/docs/text-generation)에 나온 모델과 주소
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


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


def ask_gemini(api_key, text):
    """text 를 Gemini 에 보내고, (받은 답 글, 토큰 사용량 사전)을 돌려준다."""
    body = json.dumps({"model": GEMINI_MODEL, "input": text}).encode("utf-8")
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
        return "", usage
    parts = outputs[-1].get("content", [])
    answer = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return answer, usage


env = read_env(ENV_PATH)

st.title("챗봇")

# 키 값 자체는 화면에 보여주지 않고, 채워져 있는지만 알려 준다
if env.get("GEMINI_API_KEY"):
    st.write("GEMINI_API_KEY 가 채워져 있습니다.")
else:
    st.write("GEMINI_API_KEY 가 비어 있습니다. .env 에 값을 넣어 주세요.")

question = st.text_input("Gemini 에게 보낼 말")

if st.button("보내기"):
    if not env.get("GEMINI_API_KEY"):
        st.error("GEMINI_API_KEY 가 비어 있어 보낼 수 없습니다.")
    elif not question.strip():
        st.warning("보낼 말을 입력해 주세요.")
    else:
        try:
            with st.spinner("Gemini 의 답을 기다리는 중..."):
                answer, usage = ask_gemini(env["GEMINI_API_KEY"], question)
            st.write(answer or "받은 답이 비어 있습니다.")
            st.caption(
                f"사용한 토큰: 합계 {usage.get('total_tokens', 0)}"
                f" (보낸 말 {usage.get('total_input_tokens', 0)}"
                f", 받은 답 {usage.get('total_output_tokens', 0)})"
            )
        except urllib.error.HTTPError as e:
            st.error(f"Gemini 요청이 실패했습니다 ({e.code}): {e.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            st.error(f"Gemini 에 연결하지 못했습니다: {e.reason}")
