import streamlit as st
from datetime import datetime
import os
from dotenv import load_dotenv
import google.generativeai as genai
from streamlit_mic_recorder import mic_recorder
import tempfile
import time
import io
import requests
from bs4 import BeautifulSoup
from docx import Document

import hmac

# 1. 환경 변수(.env) 또는 클라우드(Secrets)에서 API 키 불러오기
if "GEMINI_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    # 내 컴퓨터(로컬) 환경인 경우 .env 사용
    load_dotenv(override=True)
    GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if GOOGLE_API_KEY and GOOGLE_API_KEY != "여기에_발급받은_API_키를_입력하세요":
    genai.configure(api_key=GOOGLE_API_KEY)
    # 가장 최신 버전의 음성/문서 분석 모델 (3.6 Flash) 사용
    model = genai.GenerativeModel('gemini-3.6-flash')
else:
    model = None

# 페이지 기본 설정
st.set_page_config(page_title="AI 회의록 작성 프로그램", page_icon="📝", layout="centered")

# --- 비밀번호 확인 (권한 설정) 로직 ---
def check_password():
    """비밀번호가 맞으면 True를 반환합니다."""
    def password_entered():
        # 사용자가 입력한 비밀번호와 secrets.toml에 저장된 비밀번호를 비교합니다.
        if hmac.compare_digest(st.session_state["password"], st.secrets["password"]):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 보안을 위해 세션에서 비밀번호 삭제
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 로그인")
    st.text_input("프로그램 접속 비밀번호를 입력하세요:", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state:
        st.error("😕 비밀번호가 틀렸습니다. 다시 시도해 주세요.")
    return False

# 비밀번호를 맞추지 못하면 아래 코드는 실행되지 않고 멈춥니다.
if not check_password():
    st.stop()
# -----------------------------------

# 화면 제목
st.title("📝 똑똑한 AI 회의록 작성 프로그램")
st.markdown("회의가 시작할 때 마이크 버튼을 눌러 녹음을 시작하세요. 종료 시 AI가 핵심 내용을 파악하여 전문적인 회의록을 작성해 드립니다.")

if model is None:
    st.error("⚠️ `.env` 파일에 Google Gemini API 키가 설정되지 않았습니다. API 키를 입력하고 프로그램을 다시 시작해 주세요.")
    st.stop() # API 키가 없으면 아래 코드는 실행하지 않습니다.

# 입력 폼
with st.container():
    st.subheader("1. 행사 정보 입력")
    
    event_title = st.text_input("행사 제목", "제목 없는 행사")
    
    col1, col2 = st.columns(2)
    with col1:
        # [수정됨] 과제평가 추가
        event_type = st.selectbox("행사 유형", ("회의", "세미나", "교육", "포럼", "과제평가"))
    with col2:
        event_date = st.date_input("날짜", datetime.today())
        event_time = st.time_input("시간", datetime.now().time())
        
    col3, col4 = st.columns(2)
    with col3:
        role_type = st.selectbox("담당자 역할", ("주최자", "강의자", "발표자", "평가자"))
    with col4:
        person_name = st.text_input("담당자 이름", "홍길동")
        
    st.write("") # 간격 띄우기
    event_lang = st.radio("회의 진행 언어", ("한국어", "영어 (영문 원본 및 한글 번역본 동시 제공)"), horizontal=True)

with st.container():
    st.subheader("2. 참고 자료 첨부 (선택 사항)")
    st.markdown("회의와 관련된 문서(PDF, 텍스트 등)나 웹사이트 주소를 입력해 주세요. AI가 문맥을 더 정확하게 파악합니다.")
    context_file = st.file_uploader("참고 문서 업로드", type=['pdf', 'txt', 'md', 'csv', 'docx'])
    context_url = st.text_input("참고 웹사이트 주소 (URL)")

with st.container():
    st.subheader("3. 회의 녹음하기")
    st.markdown("마이크 아이콘을 한 번 클릭하면 **녹음이 시작**되고, 다시 한 번 클릭하면 **녹음이 종료**되면서 회의록 작성이 시작됩니다.")
    
    # [수정됨] 마이크 녹음 컴포넌트 변경 (시작/중지 버튼 명확화)
    audio = mic_recorder(
        start_prompt="⏺️ 녹음 시작",
        stop_prompt="⏹️ 녹음 중지",
        just_once=True,
        key='recorder'
    )

# 녹음이 완료되어 오디오 데이터가 생겼을 때 실행되는 부분
if audio:
    audio_bytes = audio['bytes']
    st.audio(audio_bytes, format="audio/wav")
    st.success("녹음이 성공적으로 완료되었습니다! AI가 분석을 시작합니다... (잠시만 기다려 주세요 ⏳)")
    
    # 1) 녹음된 데이터를 임시 파일로 저장합니다. (Gemini API로 보내기 위함)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_file_path = tmp_file.name

    try:
        with st.spinner('인공지능이 음성을 듣고 회의록을 작성 중입니다...'):
            files_to_send = []
            
            # [추가] 참고 자료가 있다면 구글 서버에 먼저 업로드합니다.
            if context_file:
                file_ext = context_file.name.split('.')[-1] if '.' in context_file.name else 'txt'
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp_ctx:
                    tmp_ctx.write(context_file.read())
                    tmp_ctx_path = tmp_ctx.name
                uploaded_ctx = genai.upload_file(path=tmp_ctx_path)
                files_to_send.append(uploaded_ctx)

            # [추가] 참고 자료(웹사이트)가 있다면 텍스트 추출 후 추가
            if context_url:
                try:
                    res = requests.get(context_url, timeout=5)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    url_text = soup.get_text(separator=' ', strip=True)
                    prompt_url = f"\n\n**[웹사이트 참고 자료]** 다음은 첨부된 웹사이트({context_url})의 텍스트입니다:\n{url_text[:5000]}\n"
                    files_to_send.append(prompt_url)
                except Exception as e:
                    st.warning(f"웹사이트 주소를 불러오는데 실패했습니다: {e}")

            # 2) 임시 저장된 오디오 파일을 구글 서버에 업로드합니다.
            uploaded_file = genai.upload_file(path=tmp_file_path)
            files_to_send.append(uploaded_file)
            
            # 3) AI에게 지시할 명령어(프롬프트)를 아주 구체적으로 작성합니다.
            prompt = f"""
당신은 전문적이고 꼼꼼한 비서입니다. 첨부된 오디오 파일(및 참고자료)을 주의 깊게 듣고 회의록을 작성해 주세요.
진행된 행사의 제목은 '{event_title}', 종류는 '{event_type}'이며, 일시는 {event_date} {event_time} 입니다.
{role_type}는 {person_name}님 입니다.
"""
            # 참고 자료가 있을 경우 프롬프트에 안내 문구를 추가합니다.
            if context_file:
                prompt += "\n**[중요] 오디오 파일과 함께 참고 자료가 첨부되었습니다. 이 참고 자료의 내용을 바탕으로 오디오의 문맥을 더 정확히 이해하고 회의록을 풍성하게 작성해 주세요.**\n"
                
            # [추가] 영어 회의일 경우 영문/국문 번역 지시 추가
            if "영어" in event_lang:
                prompt += "\n**[중요 언어 지침] 이 회의는 영어로 진행되었습니다. 따라서 작성되는 모든 내용(핵심 내용, 주요 내용, 향후 계획 등)은 반드시 먼저 '영어(English)' 원문으로 상세히 작성하고, 각 항목 바로 아래에 자연스러운 '한국어 번역(Korean Translation)'을 함께 병기해 주세요.**\n"

            prompt += f"""
[작성 규칙]
1. 문서의 가장 서두에 이 행사를 통해 **'전달하려는 핵심 내용 (Key Takeaway)'**을 2~3줄로 강력하게 요약하여 배치하세요.
2. 내용은 체계적이고 전문적인 비즈니스 문체로 작성하세요.
3. 다음 양식을 꼭 지켜주세요:

---
# 📝 [{event_type}] {event_title} 요약 보고서

**일시:** {event_date} {event_time}
**{role_type}:** {person_name}

### 💡 핵심 내용 (Key Takeaway)
(여기에 가장 중요한 핵심 메시지 2~3줄 요약)
"""
            if event_type == "과제평가":
                prompt += """
### 📋 평가 기준 및 주요 안건
(과제를 평가하기 위해 기준이 된 항목들이나 주요 안건을 정리)

### 🗣️ 개별 평가 내용 및 피드백
(각 과제에 대한 평가 내용, 칭찬할 점, 보완할 점을 구체적으로 정리)

### ✅ 총평 및 향후 계획
(전체적인 총평과 결정된 사항 정리)
---
"""
            else:
                prompt += """
### 🗣️ 논의된 주요 내용
(오디오 파일에서 파악한 구체적인 내용들을 글머리 기호를 사용해 상세히 정리)

### ✅ 향후 계획 및 Action Item
(앞으로 해야 할 일이나 결정된 사항을 정리)
---
"""
            
            # 4) AI 모델에게 파일들과 명령어를 전달하여 결과를 받습니다.
            files_to_send.append(prompt)
            response = model.generate_content(files_to_send)
            
            # 5) 결과를 화면에 출력합니다.
            st.divider()
            st.subheader("✨ 완성된 회의록")
            st.markdown(response.text)
            
            # 6) 워드 파일(.docx) 생성
            doc = Document()
            doc.add_heading(f"[{event_type}] {event_title}", 0)
            
            for line in response.text.split('\n'):
                clean_line = line.strip()
                if not clean_line or clean_line == "---":
                    continue
                if clean_line.startswith('# '):
                    doc.add_heading(clean_line.replace('# ', ''), level=1)
                elif clean_line.startswith('## '):
                    doc.add_heading(clean_line.replace('## ', ''), level=2)
                elif clean_line.startswith('### '):
                    doc.add_heading(clean_line.replace('### ', ''), level=3)
                elif clean_line.startswith('- '):
                    doc.add_paragraph(clean_line[2:], style='List Bullet')
                elif clean_line.startswith('**') and clean_line.endswith('**'):
                    p = doc.add_paragraph()
                    p.add_run(clean_line.replace('**', '')).bold = True
                else:
                    doc.add_paragraph(clean_line)
                    
            doc_stream = io.BytesIO()
            doc.save(doc_stream)
            doc_stream.seek(0)
            
            # 다운로드 버튼
            st.download_button(
                label="📥 워드 파일(.docx)로 예쁘게 저장하기",
                data=doc_stream,
                file_name=f"{event_date}_{event_title}_회의록.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            
            # 7) 구글 서버에 올린 임시 파일을 삭제하여 보안을 유지합니다.
            genai.delete_file(uploaded_file.name)
            if context_file:
                genai.delete_file(uploaded_ctx.name)
            
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")
    
    finally:
        # 내 컴퓨터에 만들었던 임시 파일들도 모두 삭제합니다.
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        if context_file and os.path.exists(tmp_ctx_path):
            os.remove(tmp_ctx_path)
