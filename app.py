import streamlit as st
import streamlit.components.v1 as components
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
import markdown
import urllib.parse
import re

# 세션 상태 초기화
if 'first_pass_result' not in st.session_state:
    st.session_state.first_pass_result = None
if 'post_process_result' not in st.session_state:
    st.session_state.post_process_result = None

# 1. 환경 변수(.env) 또는 클라우드(Secrets)에서 API 키 불러오기
if "GEMINI_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    load_dotenv(override=True)
    GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if GOOGLE_API_KEY and GOOGLE_API_KEY != "여기에_발급받은_API_키를_입력하세요":
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-pro')
else:
    model = None

# 페이지 기본 설정
st.set_page_config(page_title="AI 회의록 작성 프로그램", page_icon="📝", layout="centered")

def check_password():
    def password_entered():
        if hmac.compare_digest(st.session_state["password"], st.secrets["password"]):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 로그인")
    st.text_input("프로그램 접속 비밀번호를 입력하세요:", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state:
        st.error("😕 비밀번호가 틀렸습니다. 다시 시도해 주세요.")
    return False

if not check_password():
    st.stop()

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .main-title {
        font-size: 2.8rem;
        font-weight: 900;
        background: -webkit-linear-gradient(45deg, #1e3c72, #2a5298);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
        text-align: center;
        padding-top: 10px;
    }
    .sub-title {
        font-size: 1.1rem;
        color: #555555;
        text-align: center;
        margin-bottom: 30px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='main-title'>✨ IntelliMeet AI</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-title'>스마트한 비즈니스를 위한 AI 회의록 작성 솔루션</p>", unsafe_allow_html=True)
st.write("")

if model is None:
    st.error("⚠️ `.env` 파일에 Google Gemini API 키가 설정되지 않았습니다.")
    st.stop()

with st.container(border=True):
    st.subheader("📋 1. 행사 정보 입력")
    event_title = st.text_input("행사 제목", "제목 없는 행사")
    col1, col2 = st.columns(2)
    with col1:
        event_type = st.selectbox("행사 유형", ("회의", "세미나", "교육", "포럼", "과제평가", "심사원 과정 교육 (시험대비)"))
    with col2:
        event_date = st.date_input("날짜", datetime.today())
        event_time = st.time_input("시간", datetime.now().time())
    col3, col4 = st.columns(2)
    with col3:
        role_type = st.selectbox("담당자 역할", ("주최자", "강의자", "발표자", "평가자"))
    with col4:
        person_name = st.text_input("담당자 이름", "홍길동")
    event_lang = st.radio("회의 진행 언어", ("한국어", "영어 (영문 원본 및 한글 번역본 동시 제공)"), horizontal=True)

with st.expander("📎 2. 참고 자료 첨부 (선택 사항) - 클릭하여 열기"):
    context_file = st.file_uploader("참고 문서 업로드", type=['pdf', 'txt', 'md', 'csv', 'docx'])
    context_url = st.text_input("참고 웹사이트 주소 (URL)")

with st.container(border=True):
    st.subheader("🎙️ 3. 음성 파일 업로드 또는 회의 녹음")
    
    tab1, tab2 = st.tabs(["📁 파일 업로드", "⏺️ 직접 녹음"])
    with tab1:
        st.info("기존에 녹음된 회의 음성 파일(mp3, wav, m4a 등)을 업로드하세요.")
        uploaded_audio = st.file_uploader("음성 파일 선택", type=['wav', 'mp3', 'm4a', 'ogg', 'flac'])
    with tab2:
        st.markdown("아래 **[녹음 시작]** 버튼을 눌러 회의를 직접 녹음하세요.")
        audio = mic_recorder(
            start_prompt="⏺️ 녹음 시작",
            stop_prompt="⏹️ 녹음 중지",
            just_once=True,
            key='recorder'
        )

audio_bytes = None
if uploaded_audio is not None:
    audio_bytes = uploaded_audio.read()
elif audio is not None:
    audio_bytes = audio['bytes']

if audio_bytes:
    st.audio(audio_bytes, format="audio/wav")
    st.success("음성 데이터가 성공적으로 인식되었습니다! AI가 분석을 시작합니다... (잠시만 기다려 주세요 ⏳)")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_file_path = tmp_file.name

    try:
        with st.spinner('인공지능이 음성을 분석하고 회의록을 작성 중입니다...'):
            files_to_send = []
            
            if context_file:
                file_ext = context_file.name.split('.')[-1] if '.' in context_file.name else 'txt'
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp_ctx:
                    tmp_ctx.write(context_file.read())
                    tmp_ctx_path = tmp_ctx.name
                uploaded_ctx = genai.upload_file(path=tmp_ctx_path)
                files_to_send.append(uploaded_ctx)

            if context_url:
                try:
                    res = requests.get(context_url, timeout=5)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    url_text = soup.get_text(separator=' ', strip=True)
                    prompt_url = f"\n\n**[웹사이트 참고 자료]** 다음은 첨부된 웹사이트({context_url})의 텍스트입니다:\n{url_text[:5000]}\n"
                    files_to_send.append(prompt_url)
                except Exception as e:
                    st.warning(f"웹사이트 주소를 불러오는데 실패했습니다: {e}")

            uploaded_file = genai.upload_file(path=tmp_file_path)
            files_to_send.append(uploaded_file)
            
            prompt = f"""
당신은 전문적이고 꼼꼼한 비서입니다. 첨부된 오디오 파일(및 참고자료)을 주의 깊게 듣고 회의록을 작성해 주세요.
진행된 행사의 제목은 '{event_title}', 종류는 '{event_type}'이며, 일시는 {event_date} {event_time} 입니다.
{role_type}는 {person_name}님 입니다.
"""
            if context_file:
                prompt += "\n**[중요] 오디오 파일과 함께 참고 자료가 첨부되었습니다. 이 참고 자료의 내용을 바탕으로 오디오의 문맥을 더 정확히 이해하고 회의록을 풍성하게 작성해 주세요.**\n"
                
            if "영어" in event_lang:
                prompt += "\n**[중요 언어 지침] 이 회의는 영어로 진행되었습니다. 따라서 작성되는 모든 내용(핵심 내용, 주요 내용, 향후 계획 등)은 반드시 먼저 '영어(English)' 원문으로 상세히 작성하고, 각 항목 바로 아래에 자연스러운 '한국어 번역(Korean Translation)'을 함께 병기해 주세요.**\n"

            prompt += f"""
[작성 규칙]
1. 분석 결과는 반드시 다음 6가지 섹션을 포함하여 체계적으로 작성하세요.
2. 내용은 체계적이고 전문적인 비즈니스 문체로 작성하세요.

---
# 📝 [{event_type}] {event_title} 회의록

**일시:** {event_date} {event_time}
**{role_type}:** {person_name}
**프로젝트/행사명:** {event_title}

### 1. 📌 제목 및 안건 (Title & Agenda Topics)
(회의의 성격에 맞는 제목을 달고, 다루어졌던 주요 안건들을 개요 형태로 배치)

### 2. 💡 핵심 논의 내용 (Discussion Highlights)
(긴 대화 중 중요한 발언과 논의 포인트를 문단 형태로 요약)
"""
            if event_type == "심사원 과정 교육 (시험대비)":
                prompt += "\n**[특수 조건] '핵심 논의 내용' 부분에 강사가 강조한 부분과 시험 예상 문제/힌트, ISO 9001 주요 심사 포인트를 중점적으로 기록해 주세요.**\n"
            elif event_type == "과제평가":
                prompt += "\n**[특수 조건] '핵심 논의 내용' 부분에 개별 평가 내용 및 피드백, 평가 기준에 따른 분석을 중점적으로 기록해 주세요.**\n"

            prompt += f"""
### 3. 🎯 주요 결정 사항 (Key Decisions)
(회의를 통해 최종적으로 합의되거나 결정된 사항들을 명시)

### 4. ✅ 액션 아이템 (Action Items)
(회의 중 언급된 향후 과제나 할 일들을 '담당자'와 '기한'이 포함된 표(Table) 형태로 정리)
| 담당자 | 기한 | 할 일 (Task) |
|---|---|---|
| ... | ... | ... |

### 5. 🗣️ 화자가 분리된 전체 대화록 (Full Transcript with Speaker Labels)
(누가 어떤 발언을 했는지 화자 이름표(Speaker A, Speaker B 등 식별 가능한 이름)가 달린 대화록 원문)

### 6. 🧠 핵심 키워드 마인드맵 (Mind Map)
회의 내용의 핵심 키워드들을 계층 구조로 정리하여 아래와 같은 Mermaid js 문법으로 출력해 주세요.
반드시 ````mermaid 로 시작하고 ```` 로 끝나야 합니다. (아래 예시 참고)
````mermaid
mindmap
  root((회의 주제))
    키워드1
      상세1
      상세2
    키워드2
      상세3
````
---
"""
            
            files_to_send.append(prompt)
            response = model.generate_content(files_to_send)
            
            st.session_state.first_pass_result = response.text
            st.session_state.post_process_result = None
            
            genai.delete_file(uploaded_file.name)
            if context_file:
                genai.delete_file(uploaded_ctx.name)
            
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")
    finally:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        if context_file and os.path.exists(tmp_ctx_path):
            os.remove(tmp_ctx_path)

if st.session_state.first_pass_result:
    st.divider()
    st.subheader("✨ AI 회의록 분석 결과")
    
    display_text = st.session_state.post_process_result if st.session_state.post_process_result else st.session_state.first_pass_result
    
    # 텍스트 출력
    with st.container(border=True):
        st.markdown(display_text)
    
    # 마인드맵 렌더링
    mermaid_match = re.search(r'```mermaid\n(.*?)\n```', display_text, re.DOTALL)
    if mermaid_match:
        st.subheader("🧠 한눈에 보는 마인드맵")
        mermaid_code = mermaid_match.group(1).strip()
        htmlcode = f"""
        <div class="mermaid">
        {mermaid_code}
        </div>
        <script type="module">
          import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
          mermaid.initialize({{ startOnLoad: true }});
        </script>
        """
        components.html(htmlcode, height=500, scrolling=True)
    
    st.write("")
    st.subheader("💾 내보내기 및 공유")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    doc = Document()
    doc.add_heading(f"[{event_type}] {event_title}", 0)
    for line in display_text.split('\n'):
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
    
    with col1:
        st.download_button(
            label="📥 Word",
            data=doc_stream,
            file_name=f"{event_date}_{event_title}_회의록.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        
    with col2:
        st.download_button(
            label="📝 Markdown",
            data=display_text,
            file_name=f"{event_date}_{event_title}_회의록.md",
            mime="text/markdown"
        )
        
    with col3:
        html_content = markdown.markdown(display_text, extensions=['tables'])
        full_html = f"""<html>
<head>
<meta charset='utf-8'>
<style>
    body {{ font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; padding: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>{html_content}</body>
</html>"""
        st.download_button(
            label="🌐 HTML (PDF용)",
            data=full_html,
            file_name=f"{event_date}_{event_title}_회의록.html",
            mime="text/html"
        )
        
    with col4:
        # 대화 원본만 분리해서 다운로드
        transcript_text = ""
        parts = display_text.split("### 5. 🗣️ 화자가 분리된 전체 대화록 (Full Transcript with Speaker Labels)")
        if len(parts) > 1:
            transcript_part = parts[1].split("### 6. 🧠 핵심 키워드 마인드맵 (Mind Map)")[0]
            transcript_text = transcript_part.strip()
            # 마크다운 백틱 등 제거
            transcript_text = transcript_text.replace("```", "")
        else:
            transcript_text = display_text # 분리 실패시 전체 텍스트
            
        st.download_button(
            label="💬 대화록 TXT",
            data=transcript_text,
            file_name=f"{event_date}_{event_title}_대화록.txt",
            mime="text/plain"
        )

    with col5:
        subject = urllib.parse.quote(f"[{event_type}] {event_title} 회의록 공유")
        body = urllib.parse.quote(display_text)
        mailto_link = f"mailto:?subject={subject}&body={body}"
        st.markdown(f'<a href="{mailto_link}"><button style="width:100%; border-radius:8px; padding:0.4rem; background-color:white; border:1px solid #dcdede; cursor:pointer;">📧 공유</button></a>', unsafe_allow_html=True)
        
    st.divider()
    with st.expander("🔄 2차 가공 (보고서/기획안 형식으로 자동 변환)", expanded=True):
        st.info("원하는 문서 양식이나 추가 지시사항을 입력하면 AI가 회의록을 바탕으로 새로운 문서를 만들어줍니다.\n(예: '주간 회의 보고서 형태로 만들어줘', '이 내용을 바탕으로 새로운 서비스 기획안 초안을 표와 함께 정리해줘')")
        
        custom_prompt = st.text_area("추가 작업 지시 (Prompt):", placeholder="예: 내용을 요약해서 표로 만들어줘")
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("✨ 변환 실행"):
                if custom_prompt:
                    with st.spinner("AI가 문서를 재구성하고 있습니다..."):
                        try:
                            refine_prompt = f"""
다음은 회의록 원본 데이터입니다:

{st.session_state.first_pass_result}

위 내용을 바탕으로, 다음 사용자의 추가 지시사항에 맞게 문서를 완벽하게 재구성해 주세요:
[지시사항]: "{custom_prompt}"

전문적이고 깔끔한 비즈니스 문서 형태로 마크다운(표, 리스트 등)을 적극 활용하여 작성해 주세요.
반드시 6번 섹션으로 마인드맵도 포함해 주세요 (Mermaid 포맷 유지).
"""
                            refined_response = model.generate_content([refine_prompt])
                            st.session_state.post_process_result = refined_response.text
                            st.rerun() 
                        except Exception as e:
                            st.error(f"변환 중 오류가 발생했습니다: {e}")
                else:
                    st.warning("지시사항을 입력해 주세요.")
        
        with col_btn2:
            if st.session_state.post_process_result:
                if st.button("↩️ 원본 회의록으로 복구"):
                    st.session_state.post_process_result = None
                    st.rerun()
