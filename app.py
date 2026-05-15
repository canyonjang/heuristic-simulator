"""
휴리스틱 체험 시뮬레이터
첫 화면에서 학생(별명 로그인) / 교수(비밀번호 로그인) 분기
"""

import streamlit as st
from supabase import create_client, Client

# ============================================================
# 페이지 설정 (학생이 미리 눈치 못 채게 중립적 제목)
# ============================================================
st.set_page_config(
    page_title="휴리스틱 체험",
    page_icon="🎯",
    layout="centered",
)

# ============================================================
# Supabase
# ============================================================
@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])

sb = init_supabase()

# ============================================================
# 세션 상태 초기화
# ============================================================
defaults = {
    "role": None,              # 'student' or 'teacher'
    "stage": "login",          # 'login', 'waiting', 'q1'~'q5', 'done'
    "session_id": None,
    "nickname": None,
    "class_code": None,
    "login_order": None,
    "reset_token": 0,
    "warmup_anchor": None,     # 'descending' or 'ascending'
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 로그인 화면
# ============================================================
def show_login():
    st.title("🎯 휴리스틱 체험")
    st.markdown("---")
    
    tab_student, tab_teacher = st.tabs(["🎓 학생 로그인", "👨‍🏫 교수 로그인"])
    
    with tab_student:
        with st.form("student_login"):
            nickname = st.text_input("별명 (친구가 못 알아볼 이름 추천)", max_chars=20)
            class_code = st.selectbox("분반", ["인하대", "숙대1", "숙대2"])
            submitted = st.form_submit_button("입장하기", type="primary", use_container_width=True)
        
        if submitted:
            if not nickname.strip():
                st.error("별명을 입력해주세요.")
                return
            
            # 이 분반의 현재 reset_token과 로그인 순서 가져오기 (직접 조회)
            game_res = sb.table("heuristic_game_state").select("*").eq("class_code", class_code).execute()
            game = game_res.data[0] if game_res.data else None
            current_token = game["reset_token"] if game else 0
            
            # 같은 token의 기존 세션 수 = 이 학생의 로그인 순서
            existing = sb.table("heuristic_sessions").select("id", count="exact") \
                .eq("class_code", class_code).eq("reset_token", current_token).execute()
            login_order = (existing.count or 0) + 1
            
            # 세션 생성
            res = sb.table("heuristic_sessions").insert({
                "nickname": nickname.strip(),
                "class_code": class_code,
                "login_order": login_order,
                "reset_token": current_token,
            }).execute()
            
            st.session_state.role = "student"
            st.session_state.session_id = res.data[0]["id"]
            st.session_state.nickname = nickname.strip()
            st.session_state.class_code = class_code
            st.session_state.login_order = login_order
            st.session_state.reset_token = current_token
            # 로그인 순서가 홀수면 descending, 짝수면 ascending
            st.session_state.warmup_anchor = "descending" if login_order % 2 == 1 else "ascending"
            st.session_state.stage = "waiting"
            st.rerun()
    
    with tab_teacher:
        with st.form("teacher_login"):
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
        
        if submitted:
            if password == "3383":
                st.session_state.role = "teacher"
                st.success("로그인 성공! 좌측 사이드바에서 'dashboard' 페이지로 이동하세요.")
                st.info("👉 좌측 사이드바 → **dashboard** 클릭")
            else:
                st.error("비밀번호가 올바르지 않습니다.")

# ============================================================
# 대기 화면 (교수 시작 신호 대기)
# ============================================================
def show_waiting():
    st.title("🎯 휴리스틱 체험")
    st.markdown(f"### 환영합니다, **{st.session_state.nickname}** 님!")
    st.markdown(f"분반: **{st.session_state.class_code}** · 입장순서: **{st.session_state.login_order}번째**")
    st.markdown("---")
    
    st.info(
        "👨‍🏫 교수님이 **시작하신 뒤**에 아래 버튼을 눌러주세요.\n\n"
        "교수님이 시작 신호를 보내기 전에 누르면 계속 대기 화면이 보입니다."
    )
    
    if st.button("🚀 시작하기", type="primary", use_container_width=True):
        # 캐시 무시하고 최신 상태 직접 조회 (이때 1회만 네트워크 호출)
        res = sb.table("heuristic_game_state").select("*") \
            .eq("class_code", st.session_state.class_code).execute()
        game = res.data[0] if res.data else None
        
        if game and game["is_started"] and game["reset_token"] == st.session_state.reset_token:
            st.session_state.stage = "q1"
            st.rerun()
        else:
            st.warning("⏸️ 아직 교수님이 시작하지 않으셨어요. 잠시 후 다시 눌러주세요.")

# ============================================================
# 시나리오 응답 저장 (배치 X — 그냥 즉시 1회 insert)
# ============================================================
def save_response(scenario_id: str, choice: str, is_trap: bool, next_stage: str):
    sb.table("heuristic_responses").insert({
        "session_id": st.session_state.session_id,
        "scenario_id": scenario_id,
        "choice": choice,
        "is_trap": is_trap,
    }).execute()
    st.session_state.stage = next_stage
    st.rerun()

def progress_bar(current: int, total: int = 5):
    st.progress(current / total, text=f"{current} / {total}")

# ============================================================
# Q1. 워밍업 (기준점 효과) — 로그인 순서로 분기
# ============================================================
def show_q1():
    progress_bar(1)
    st.markdown("### 잠깐, 워밍업!")
    st.markdown("**계산기·연필 없이, 5초 안에 어림짐작으로** 답해주세요.")
    
    if st.session_state.warmup_anchor == "descending":
        question = "**8 × 7 × 6 × 5 × 4 × 3 × 2 × 1 = ?**"
    else:
        question = "**1 × 2 × 3 × 4 × 5 × 6 × 7 × 8 = ?**"
    
    st.markdown(f"## {question}")
    
    with st.form("q1_form"):
        answer = st.number_input("당신의 어림짐작 답:", min_value=0, step=100, value=0)
        submitted = st.form_submit_button("다음", type="primary")
    
    if submitted:
        # 정답 40,320 — 절반(20,000) 미만이면 닻 효과 함정
        is_trap = answer < 20000
        # heuristic_type 정보는 scenario_id에 인코딩 (분기 추적용)
        scenario_id = f"q1_{st.session_state.warmup_anchor}"
        save_response(scenario_id, str(answer), is_trap, "q2")

# ============================================================
# Q2. 펀드 선택 (인지 휴리스틱)
# ============================================================
def show_q2():
    progress_bar(2)
    st.markdown("### 시나리오 1: 펀드 가입")
    st.info("여유자금 1,000만원을 3년간 투자하려고 합니다. 어떤 펀드를 선택하시겠어요?")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 🏢 미래에셋 글로벌 펀드")
        st.metric("최근 3년 수익률", "+18.2%")
        st.caption("📍 운용규모: 5,200억원")
        st.caption("📍 보수: 연 1.5%")
        st.caption("📍 위험등급: 4등급")
    with col2:
        st.markdown("#### 🏢 노바셀 가치성장 펀드")
        st.metric("최근 3년 수익률", "+34.7%")
        st.caption("📍 운용규모: 480억원")
        st.caption("📍 보수: 연 0.9%")
        st.caption("📍 위험등급: 4등급")
    with col3:
        st.markdown("#### 🏢 핀브릿지 코어 펀드")
        st.metric("최근 3년 수익률", "+29.1%")
        st.caption("📍 운용규모: 320억원")
        st.caption("📍 보수: 연 0.8%")
        st.caption("📍 위험등급: 4등급")
    
    st.markdown("---")
    with st.form("q2_form"):
        choice = st.radio(
            "선택:",
            ["미래에셋 글로벌 펀드", "노바셀 가치성장 펀드", "핀브릿지 코어 펀드"],
            index=None,
        )
        submitted = st.form_submit_button("다음", type="primary")
    
    if submitted:
        if not choice:
            st.warning("선택해주세요.")
            return
        is_trap = choice == "미래에셋 글로벌 펀드"
        save_response("q2", choice, is_trap, "q3")

# ============================================================
# Q3. 적금 선택 (하나의 단서 휴리스틱)
# ============================================================
def show_q3():
    progress_bar(3)
    st.markdown("### 시나리오 2: 적금 가입")
    st.info("월 30만원씩 1년 적금을 들려고 합니다. 광고를 보고 골라주세요.")
    
    with st.container(border=True):
        st.markdown("### 🔥 햇살은행 챔피언 적금")
        st.markdown("# **최고금리 연 4.5%!** 💥")
        st.caption("월 30만원 × 12개월")
        with st.expander("우대조건 보기"):
            st.markdown(
                "- 기본금리 1.8%\n"
                "- 우대조건: 첫 거래(+0.3%), 급여이체(+0.5%), 카드 月 50만원 사용(+0.7%), "
                "마케팅 동의(+0.2%), 신규 청약(+1.0%)\n"
                "- **모든 조건 충족 시에만 4.5%**"
            )
    
    with st.container(border=True):
        st.markdown("### 🌿 푸른은행 정직 적금")
        st.markdown("# 연 3.2% (기본금리)")
        st.caption("우대조건 없음 · 누구나 3.2%")
    
    with st.container(border=True):
        st.markdown("### 🌊 바다은행 베이직 적금")
        st.markdown("# 연 3.0% (기본금리)")
        st.caption("우대조건 없음 · 누구나 3.0%")
    
    st.markdown("---")
    with st.form("q3_form"):
        choice = st.radio(
            "선택:",
            ["햇살은행 챔피언 적금 (4.5%)", "푸른은행 정직 적금 (3.2%)", "바다은행 베이직 적금 (3.0%)"],
            index=None,
        )
        submitted = st.form_submit_button("다음", type="primary")
    
    if submitted:
        if not choice:
            st.warning("선택해주세요.")
            return
        is_trap = "햇살은행" in choice
        save_response("q3", choice, is_trap, "q4")

# ============================================================
# Q4. 카드 선택 (디폴트 휴리스틱)
# ============================================================
def show_q4():
    progress_bar(4)
    st.markdown("### 시나리오 3: 신용카드 선택")
    st.info("AI 카드 추천 서비스를 이용 중입니다. 결과 화면입니다.")
    
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("### 🥇 스마트라이프 카드")
            st.markdown("🏷️ **AI 추천 1순위 · 당신께 가장 적합**")
            st.caption("연회비 30,000원 · 전월실적 50만원")
            st.caption("주유 1.5% / 마트 1.0% / 카페 5%")
        with col2:
            st.markdown("### ⭐")
            st.markdown("**98점**")
    
    with st.container(border=True):
        st.markdown("#### 데일리플러스 카드")
        st.caption("연회비 15,000원 · 전월실적 30만원")
        st.caption("주유 2.0% / 마트 2.0% / 카페 3%")
        st.caption("📊 AI 점수: 85점")
    
    with st.container(border=True):
        st.markdown("#### 베이직 카드")
        st.caption("연회비 무료 · 전월실적 없음")
        st.caption("모든 가맹점 0.8% 적립")
        st.caption("📊 AI 점수: 72점")
    
    st.markdown("---")
    with st.form("q4_form"):
        # 미리 첫 번째 옵션에 체크 (디폴트 함정)
        choice = st.radio(
            "어떻게 진행하시겠어요?",
            [
                "✨ AI 추천대로 스마트라이프 카드 신청 (간편)",
                "🔍 데일리플러스 카드 신청",
                "🔍 베이직 카드 신청",
                "🤔 더 알아보기 (조건 직접 비교)",
            ],
            index=0,
        )
        submitted = st.form_submit_button("다음", type="primary")
    
    if submitted:
        is_trap = "AI 추천대로" in choice
        save_response("q4", choice, is_trap, "q5")

# ============================================================
# Q5. 노트북 선택 (만족화 휴리스틱) — 대학생 친화적으로 변경
# ============================================================
def show_q5():
    progress_bar(5)
    st.markdown("### 시나리오 4: 노트북 구매")
    st.info("새 학기 노트북을 사려고 합니다. AI 챗봇이 비교해줬어요.")
    
    with st.container(border=True):
        st.markdown(
            """
            > **AI 챗봇**: 대학생에게 적합한 노트북 3개를 비교해드렸어요!
            > 
            > 🥇 **A모델**: 130만원, 13인치, 1.2kg, 만족도 ⭐⭐⭐⭐⭐
            > 
            > 🥈 **B모델**: 110만원, 14인치, 1.4kg, 만족도 ⭐⭐⭐⭐
            > 
            > 🥉 **C모델**: 150만원, 15인치, 1.6kg, 만족도 ⭐⭐⭐⭐
            > 
            > **결론: A모델이 가볍고 만족도도 가장 높아 추천드려요!** ✨
            """
        )
    
    st.markdown("---")
    with st.form("q5_form"):
        choice = st.radio(
            "어떻게 하시겠어요?",
            [
                "👍 AI 요약이 충분해 보이니 A모델 구매",
                "📋 각 모델 사양 직접 확인 (CPU, RAM, 배터리 등)",
                "💬 실제 사용 후기·유튜브 리뷰 추가 확인",
                "🏪 매장에서 직접 만져보고 결정",
            ],
            index=None,
        )
        submitted = st.form_submit_button("제출", type="primary")
    
    if submitted:
        if not choice:
            st.warning("선택해주세요.")
            return
        is_trap = "AI 요약이 충분" in choice
        # 마지막 응답 + 세션 완료 표시
        sb.table("heuristic_responses").insert({
            "session_id": st.session_state.session_id,
            "scenario_id": "q5",
            "choice": choice,
            "is_trap": is_trap,
        }).execute()
        sb.table("heuristic_sessions").update({
            "finished_at": "now()",
        }).eq("id", st.session_state.session_id).execute()
        st.session_state.stage = "done"
        st.rerun()

# ============================================================
# 완료 화면 (해설·결과 안 보여줌!)
# ============================================================
def show_done():
    st.title("✅ 수고하셨습니다!")
    st.markdown(f"### **{st.session_state.nickname}** 님, 모든 시나리오를 완료했어요.")
    st.markdown("---")
    st.info("👨‍🏫 결과와 해설은 **교수님 화면에서 다 함께** 확인할 예정입니다.\n\n잠시 화면을 그대로 두고 기다려주세요.")
    st.balloons()

# ============================================================
# 라우팅
# ============================================================
stage = st.session_state.stage

if st.session_state.role is None:
    show_login()
elif st.session_state.role == "teacher":
    # 교수는 dashboard 페이지로 안내
    st.title("👨‍🏫 교수 모드")
    st.success("로그인 성공!")
    st.info("좌측 사이드바에서 **dashboard** 페이지를 클릭해 들어가세요.")
    if st.button("로그아웃"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
elif stage == "waiting":
    show_waiting()
elif stage == "q1":
    show_q1()
elif stage == "q2":
    show_q2()
elif stage == "q3":
    show_q3()
elif stage == "q4":
    show_q4()
elif stage == "q5":
    show_q5()
elif stage == "done":
    show_done()
