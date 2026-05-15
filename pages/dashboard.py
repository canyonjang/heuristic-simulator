"""
교수 대시보드
- 세션 시작/종료, 학생 시작 신호
- 로그인/완료 학생 수 (수동 새로고침)
- 결과 확인 (전체/학생별)
"""

import streamlit as st
from supabase import create_client
import pandas as pd
import altair as alt

st.set_page_config(
    page_title="대시보드",
    page_icon="📊",
    layout="wide",
)

# 교수 인증 확인
if st.session_state.get("role") != "teacher":
    st.warning("⚠️ 교수 로그인이 필요합니다. 메인 페이지에서 로그인 후 다시 들어와주세요.")
    st.stop()

@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])

sb = init_supabase()

# ============================================================
# 상단: 분반 선택 & 세션 제어
# ============================================================
st.title("📊 휴리스틱 체험 — 교수 대시보드")

class_code = st.sidebar.selectbox("분반 선택", ["인하대", "숙대1", "숙대2"])

# 현재 게임 상태 조회 (캐시 안 함 — 교수는 항상 최신값 봐야 함)
def get_game_state(cc):
    res = sb.table("heuristic_game_state").select("*").eq("class_code", cc).execute()
    return res.data[0] if res.data else None

game = get_game_state(class_code)
if not game:
    st.error(f"분반 '{class_code}'를 찾을 수 없습니다. 스키마 SQL의 INSERT 부분이 실행되었는지 확인하세요.")
    st.stop()

st.markdown(f"### 현재 분반: **{class_code}**")
st.markdown(f"라운드 번호: **{game['reset_token']}** · 시작 상태: **{'▶️ 시작됨' if game['is_started'] else '⏸️ 대기 중'}**")

# ============================================================
# 세션 제어 버튼들
# ============================================================
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🆕 새 라운드 시작", help="새 라운드를 만들고 학생 로그인을 받습니다", use_container_width=True):
        # reset_token 증가 → 이전 라운드 학생 분리
        sb.table("heuristic_game_state").update({
            "is_started": False,
            "reset_token": game["reset_token"] + 1,
            "started_at": None,
        }).eq("class_code", class_code).execute()
        st.success("새 라운드 시작! 학생들이 로그인할 수 있습니다.")
        st.rerun()

with col2:
    if st.button("▶️ 학생 시작", type="primary", help="로그인한 학생들에게 시나리오 시작 신호를 보냅니다", use_container_width=True):
        sb.table("heuristic_game_state").update({
            "is_started": True,
            "started_at": "now()",
        }).eq("class_code", class_code).execute()
        st.success("학생들에게 시작 신호를 보냈습니다! (학생 화면 최대 4초 내 진행)")
        st.rerun()

with col3:
    if st.button("🔄 새로고침", help="로그인/완료 학생 수를 갱신합니다", use_container_width=True):
        st.rerun()

with col4:
    if st.button("📊 결과 확인", help="시나리오별 결과와 학생별 리포트를 표시합니다", use_container_width=True):
        st.session_state["show_results"] = True
        st.rerun()

st.markdown("---")

# ============================================================
# 학생 현황 (수동 새로고침 시에만 조회)
# ============================================================
def get_current_round_sessions():
    res = sb.table("heuristic_sessions").select("*") \
        .eq("class_code", class_code).eq("reset_token", game["reset_token"]).execute()
    return pd.DataFrame(res.data)

sessions_df = get_current_round_sessions()

c1, c2, c3 = st.columns(3)
c1.metric("👥 로그인 학생 수", len(sessions_df))
finished_count = len(sessions_df[sessions_df["finished_at"].notna()]) if not sessions_df.empty else 0
c2.metric("✅ 완료 학생 수", finished_count)
c3.metric("⏳ 진행 중", len(sessions_df) - finished_count)

if not sessions_df.empty:
    with st.expander("로그인한 학생 목록"):
        display_df = sessions_df[["login_order", "nickname", "started_at", "finished_at"]].copy()
        display_df.columns = ["순서", "별명", "로그인 시각", "완료 시각"]
        display_df["상태"] = display_df["완료 시각"].apply(lambda x: "✅ 완료" if pd.notna(x) else "⏳ 진행 중")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ============================================================
# 결과 표시 (결과 확인 버튼 눌렀을 때만)
# ============================================================
if not st.session_state.get("show_results"):
    st.info("👆 모든 학생이 완료되면 **결과 확인** 버튼을 눌러주세요.")
    st.stop()

if sessions_df.empty:
    st.warning("아직 응답이 없습니다.")
    st.stop()

# 응답 데이터 로드 (한 번만)
session_ids = sessions_df["id"].tolist()
resp_res = sb.table("heuristic_responses").select("*").in_("session_id", session_ids).execute()
responses_df = pd.DataFrame(resp_res.data)

if responses_df.empty:
    st.warning("아직 응답이 없습니다.")
    st.stop()

# session_id → nickname 매핑
nick_map = dict(zip(sessions_df["id"], sessions_df["nickname"]))
responses_df["nickname"] = responses_df["session_id"].map(nick_map)

# ============================================================
# 시나리오 메타데이터 & 해설
# ============================================================
SCENARIO_META = {
    "q1_descending": {
        "label": "🧮 워밍업 A (8×7×6...)",
        "heuristic": "기준점 효과 (Anchoring)",
    },
    "q1_ascending": {
        "label": "🧮 워밍업 B (1×2×3...)",
        "heuristic": "기준점 효과 (Anchoring)",
    },
    "q2": {"label": "📈 시나리오 1: 펀드", "heuristic": "인지 휴리스틱 (Recognition)"},
    "q3": {"label": "💰 시나리오 2: 적금", "heuristic": "하나의 단서 휴리스틱 (One-reason)"},
    "q4": {"label": "💳 시나리오 3: 카드", "heuristic": "디폴트 휴리스틱 (Default)"},
    "q5": {"label": "💻 시나리오 4: 노트북", "heuristic": "만족화 휴리스틱 (Satisficing)"},
}

SCENARIO_EXPLAIN = {
    "q1": """
**📚 기준점 효과 (Anchoring) — 카너먼**

- 두 문제의 정답은 모두 **40,320**
- 카너먼 실험 결과: 8부터 시작 → 평균 **2,250** / 1부터 시작 → 평균 **512**
- 처음 본 숫자가 '기준점(닻)'이 되어 어림짐작이 좌우됨
- 금융 광고에서도 마찬가지: "원래 8% → 5%로!" 의 '8%'가 닻 역할
""",
    "q2": """
**📚 인지 휴리스틱 (Recognition Heuristic) — Goldstein & Gigerenzer, 2002**

> "두 개의 대안 중 인식되는 대안에 더 높은 가치를 부여"

- 미래에셋: 실제 대형 운용사 (들어본 이름)
- 노바셀·핀브릿지: 이 실험용 가상 이름
- **수익률·보수 모두 다른 두 펀드가 우월**한데도 익숙한 이름에 끌림
- 수업 자료: "펀드는 △△자산운용이 제일 유명하잖아요"
""",
    "q3": """
**📚 하나의 단서 휴리스틱 (One-reason Heuristic) — Todd & Gigerenzer, 2003**

> "하나의 단서에 의한 의사결정"

- '최고금리 4.5%!' 라는 **하나의 숫자**만으로 결정
- 실제 기본금리는 1.8% — 모든 우대조건 충족은 비현실적
- 평균 충족률을 고려하면 푸른은행(3.2%)이 더 유리
- 광고는 이 휴리스틱을 **의도적으로 유도**함
""",
    "q4": """
**📚 디폴트 휴리스틱 (Default Heuristic) — Johnson & Goldstein, 2003**

> "default가 있다면 아무것도 하지 않음 → 일이 자동으로 흐름"

- 라디오 버튼이 **이미 'AI 추천'에 체크되어 있었음**
- AI 점수 98점이라는 권위 + 기본 선택의 편리함
- AI 시대에는 **AI 추천 1순위가 새로운 디폴트**가 됨
- 수업 자료: "AI는 어떤 기준으로 이 상품을 추천했는가?"라는 질문 필요
""",
    "q5": """
**📚 만족화 휴리스틱 (Satisficing Heuristic) — Simon, 1955**

> "기대수준을 초과하는 첫 번째 대안을 선택"

- AI 요약 → "이 정도면 충분해" → 탐색 종료
- AI가 빠뜨린 것: CPU·RAM 사양, 배터리, A/S, 실제 사용 후기 등
- 만족도 별점의 산정 기준 (응답자? 표본 크기?) 도 불명
- 수업 자료: "AI 시대의 핵심 역량은 단순 검색이 아니라 **검증·해석 능력**"
""",
}

# ============================================================
# 시나리오별 전체 결과
# ============================================================
st.header("📊 시나리오별 전체 결과")

# 워밍업: 닻 효과는 두 그룹 비교가 더 의미있음
warmup_df = responses_df[responses_df["scenario_id"].str.startswith("q1")].copy()
if not warmup_df.empty:
    with st.container(border=True):
        st.subheader("🧮 워밍업: 카너먼 닻 효과")
        warmup_df["answer"] = pd.to_numeric(warmup_df["choice"], errors="coerce")
        desc = warmup_df[warmup_df["scenario_id"] == "q1_descending"]["answer"]
        asc = warmup_df[warmup_df["scenario_id"] == "q1_ascending"]["answer"]
        
        wc1, wc2 = st.columns(2)
        with wc1:
            st.markdown("**📉 8×7×6×... 그룹 (홀수 입장)**")
            if len(desc) > 0:
                st.metric("우리 반 평균", f"{desc.mean():,.0f}", help=f"카너먼 실험: 2,250")
                st.caption(f"참여 {len(desc)}명 · 카너먼 실험 평균: 2,250")
            else:
                st.info("응답 없음")
        with wc2:
            st.markdown("**📈 1×2×3×... 그룹 (짝수 입장)**")
            if len(asc) > 0:
                st.metric("우리 반 평균", f"{asc.mean():,.0f}", help=f"카너먼 실험: 512")
                st.caption(f"참여 {len(asc)}명 · 카너먼 실험 평균: 512")
            else:
                st.info("응답 없음")
        st.success("**정답: 40,320** — 두 그룹 평균 차이가 곧 '닻 효과'의 증거")
        st.markdown(SCENARIO_EXPLAIN["q1"])

# Q2~Q5 함정률
other_df = responses_df[~responses_df["scenario_id"].str.startswith("q1")].copy()
if not other_df.empty:
    summary = other_df.groupby("scenario_id").agg(
        total=("is_trap", "count"),
        traps=("is_trap", "sum"),
    ).reset_index()
    summary["trap_rate"] = (100 * summary["traps"] / summary["total"]).round(1)
    summary["label"] = summary["scenario_id"].map(lambda x: SCENARIO_META[x]["label"])
    
    st.subheader("🎯 시나리오별 함정에 빠진 비율")
    
    chart = alt.Chart(summary).mark_bar(size=60).encode(
        x=alt.X("label:N", title=None, sort=["📈 시나리오 1: 펀드", "💰 시나리오 2: 적금", "💳 시나리오 3: 카드", "💻 시나리오 4: 노트북"]),
        y=alt.Y("trap_rate:Q", title="함정에 빠진 비율 (%)", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("trap_rate:Q", scale=alt.Scale(scheme="redyellowgreen", reverse=True, domain=[0, 100]), legend=None),
        tooltip=["label", "total", "traps", "trap_rate"],
    ).properties(height=380)
    text = chart.mark_text(dy=-12, fontSize=18, fontWeight="bold").encode(text=alt.Text("trap_rate:Q", format=".1f"))
    st.altair_chart(chart + text, use_container_width=True)
    
    # 각 시나리오별 해설을 expander로
    for sc_id in ["q2", "q3", "q4", "q5"]:
        sub = other_df[other_df["scenario_id"] == sc_id]
        if sub.empty:
            continue
        with st.expander(f"{SCENARIO_META[sc_id]['label']} — 자세히 보기"):
            # 선택지별 분포
            dist = sub.groupby("choice").size().reset_index(name="count")
            dist = dist.sort_values("count", ascending=False)
            st.markdown("**📋 선택 분포**")
            st.dataframe(dist, use_container_width=True, hide_index=True)
            st.markdown(SCENARIO_EXPLAIN[sc_id])

st.markdown("---")

# ============================================================
# 학생별 리포트
# ============================================================
st.header("👥 학생별 휴리스틱 리포트")

# 학생별 함정 개수 집계 (워밍업 제외하고 4개 시나리오 기준)
non_warmup = responses_df[~responses_df["scenario_id"].str.startswith("q1")].copy()
per_student = non_warmup.groupby(["session_id", "nickname"]).agg(
    total=("is_trap", "count"),
    traps=("is_trap", "sum"),
).reset_index()

# 학생별 시나리오별 함정 여부
trap_matrix = non_warmup.pivot_table(
    index="nickname",
    columns="scenario_id",
    values="is_trap",
    aggfunc="first",
)

# 닉네임 매핑 (이름 표시)
def trap_label(row):
    if row["traps"] == 0:
        return "🏆 휴리스틱 마스터"
    elif row["traps"] <= 1:
        return "👍 합리적 소비자"
    elif row["traps"] <= 2:
        return "🤔 평균적 소비자"
    else:
        return "⚠️ 휴리스틱 의존형"

per_student["등급"] = per_student.apply(trap_label, axis=1)
per_student["함정 / 전체"] = per_student.apply(lambda r: f"{int(r['traps'])} / {int(r['total'])}", axis=1)

display = per_student[["nickname", "함정 / 전체", "등급"]].sort_values("nickname")
display.columns = ["별명", "함정 / 전체", "리포트"]
st.dataframe(display, use_container_width=True, hide_index=True)

# 시나리오별 함정 매트릭스 (✅/❌)
st.markdown("### 📋 학생 × 시나리오 매트릭스")
if not trap_matrix.empty:
    matrix_display = trap_matrix.copy()
    matrix_display = matrix_display.rename(columns={
        "q2": "펀드", "q3": "적금", "q4": "카드", "q5": "노트북",
    })
    # True(함정) → ❌, False(피함) → ✅
    matrix_display = matrix_display.map(lambda x: "❌" if x == True else ("✅" if x == False else "—"))
    # 컬럼 순서 정렬
    for col in ["펀드", "적금", "카드", "노트북"]:
        if col not in matrix_display.columns:
            matrix_display[col] = "—"
    matrix_display = matrix_display[["펀드", "적금", "카드", "노트북"]]
    st.dataframe(matrix_display, use_container_width=True)
    st.caption("❌ = 함정에 빠짐 · ✅ = 함정을 피함 · — = 미응답")
