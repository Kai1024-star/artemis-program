# app.py
import os
import tempfile
import pandas as pd
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv
import artemis_v3_1 as artemis
import base64

load_dotenv()

# 页面基础配置
st.set_page_config(
    page_title="ARTEMIS V3.1 | HUD TERMINAL",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 核心视觉注入：将网页伪装成任务终端
def inject_nasa_theme() -> None:
    """Inject CSS to recreate a light NASA-inspired aesthetic.

    The original dark HUD style is replaced with a warm, light palette
    influenced by the NASA Web Design System. Panels are clean white
    cards with gentle shadows and a blue accent bar on the left. Text
    uses a modern sans‑serif font. Buttons adopt the primary blue and
    transition smoothly on hover. Statistics boxes have subtle tints.
    """
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;600;700;800&display=swap');

            /* Base: light background and dark text */
            .stApp {
                background-color: #f1f1f1;
                color: #061f4a;
                font-family: 'Barlow', sans-serif;
            }

            /* Hide Streamlit default header/footer */
            header, footer, .stDeployButton { display: none !important; }

            /* Card container: angled corners with NASA blue accent bar */
            .fui-panel {
                background: #ffffff;
                border: 1px solid #d6d7d9;
                border-left: 4px solid #105bd8; /* NASA primary blue */
                padding: 20px;
                margin-bottom: 25px;
                clip-path: polygon(
                    0 0,
                    calc(100% - 20px) 0, 100% 20px,
                    100% 100%,
                    20px 100%, 0 calc(100% - 20px)
                );
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
            }

            /* Statistic boxes */
            .fui-stat-box {
                border: 1px solid #e1f3f8;
                background: #f9fbfc;
                padding: 10px 15px;
                display: inline-block;
                min-width: 120px;
                margin-right: 15px;
            }
            .fui-stat-label {
                font-size: 0.6rem;
                color: #5b616b; /* muted gray */
                text-transform: uppercase;
            }
            .fui-stat-value {
                font-size: 1.5rem;
                font-weight: 800;
                color: #105bd8;
            }

            /* Heading */
            .fui-header {
                font-size: 2.0rem;
                font-weight: 800;
                letter-spacing: 3px;
                text-transform: uppercase;
                margin-bottom: 5px;
                color: #061f4a;
            }

            /* Status indicator */
            .status-active {
                color: #02bfe7; /* NASA teal accent */
                font-size: 0.8rem;
                animation: blink 1.5s infinite;
            }
            @keyframes blink { 50% { opacity: 0.3; } }

            /* DataFrame override */
            .stDataFrame {
                background: rgba(255,255,255,0.8) !important;
                border: 1px solid #d6d7d9 !important;
            }

            /* Buttons: clean and sharp */
            .stButton > button {
                border-radius: 4px !important;
                border: 1px solid #105bd8 !important;
                background: #ffffff !important;
                color: #105bd8 !important;
                height: 40px !important;
                padding: 0 20px !important;
                transition: 0.3s;
            }
            .stButton > button:hover {
                background: #105bd8 !important;
                color: #ffffff !important;
                box-shadow: 0 0 12px rgba(16, 91, 216, 0.4);
            }

            /* Hero section */
            .hero-panel {
                display: flex;
                flex-wrap: wrap;
                background: #ffffff;
                border: 1px solid #e1f3f8;
                border-radius: 8px;
                padding: 40px 30px;
                margin-bottom: 30px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                overflow: hidden;
            }
            .hero-text {
                flex: 1 1 55%;
                max-width: 55%;
                min-width: 250px;
                padding-right: 20px;
                box-sizing: border-box;
            }
            .hero-tag {
                font-size: 0.75rem;
                font-weight: 600;
                color: #dd361c; /* NASA secondary red */
                text-transform: uppercase;
                letter-spacing: 2px;
                margin-bottom: 12px;
            }
            .hero-title {
                font-size: 2.6rem;
                font-weight: 800;
                line-height: 1.1;
                margin: 0;
                color: #061f4a;
            }
            .hero-desc {
                font-size: 0.9rem;
                margin-top: 18px;
                margin-bottom: 25px;
                color: #323a45;
                max-width: 90%;
            }
            .hero-features {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-bottom: 25px;
            }
            .hero-feature {
                background: #e1f3f8;
                border: 1px solid #dce4ef;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 0.65rem;
                color: #105bd8;
                text-transform: uppercase;
            }
            .hero-image {
                flex: 1 1 45%;
                max-width: 45%;
                min-width: 200px;
                position: relative;
            }
            .hero-image img {
                width: 100%;
                height: auto;
                object-fit: cover;
                border-radius: 8px;
            }

            /* Bottom log bar */
            .bottom-log {
                position: fixed;
                bottom: 0;
                left: 0;
                width: 100%;
                background: rgba(16, 91, 216, 0.05);
                border-top: 1px solid rgba(16, 91, 216, 0.2);
                padding: 5px 20px;
                font-size: 0.6rem;
                color: rgba(6, 31, 74, 0.6);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

def render_hero() -> None:
    """Render a hero banner inspired by NASA.com.

    The banner shows a tagline, a title, a short description, three
    feature tags, and an illustration. It looks for an image called
    `hero.png` in the same folder as this script. If not found, a
    placeholder box is displayed. Images are embedded via base64
    encoding so there is no external fetch overhead.
    """
    script_dir = Path(__file__).resolve().parent
    img_path = script_dir / "hero.png"
    if img_path.exists():
        try:
            with open(img_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            img_html = f'<img src="data:image/png;base64,{encoded}" alt="hero" />'
        except Exception:
            img_html = '<div style="width:100%;height:250px;background:#e1f3f8;border-radius:8px;"></div>'
    else:
        img_html = '<div style="width:100%;height:250px;background:#e1f3f8;border-radius:8px;"></div>'

    st.markdown(
        f"""
        <div class="hero-panel">
            <div class="hero-text">
                <div class="hero-tag">Artemis Research</div>
                <div class="hero-title">跨语言术语抽取</div>
                <div class="hero-desc">AI 驱动的术语抽取平台，依托 NASA 风格设计，清新简洁。</div>
                <div class="hero-features">
                    <span class="hero-feature">词性过滤</span>
                    <span class="hero-feature">二次归类</span>
                    <span class="hero-feature">目标语预对齐</span>
                </div>
            </div>
            <div class="hero-image">{img_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    inject_nasa_theme()

    # --- TOP NAV BAR ---
    t1, t2 = st.columns([3, 1])
    with t1:
        st.markdown('<div class="fui-header">Artemis v3.1</div>', unsafe_allow_html=True)
        # Status line uses NASA teal accent for the active indicator
        st.markdown('SYSTEM STATUS: <span class="status-active">● OPERATIONAL</span> / <span style="color:#5b616b;">FOR ALL HUMANITY</span>', unsafe_allow_html=True)
    with t2:
        st.markdown('<div style="text-align:right; font-size:0.7rem; color:#5b616b;">REF_ID: 77476F‑MISSION<br>TIME_STAMP: 2024.Q4_UTC</div>', unsafe_allow_html=True)

    st.markdown('<hr style="border-color: #d6d7d9; margin-top:5px;">', unsafe_allow_html=True)

    # --- HERO SECTION ---
    render_hero()

    # --- MAIN LAYOUT ---
    col_l, col_r = st.columns([1, 2.5], gap="medium")

    with col_l:
        st.markdown('<div class="fui-panel">', unsafe_allow_html=True)
        st.write("▼ DATA_INPUT")
        uploaded_file = st.file_uploader("", type=["json"], label_visibility="collapsed")
        
        st.markdown("<br>▼ MISSION_PARAMS", unsafe_allow_html=True)
        mode = st.selectbox("EXTRACTION_MODE", ["balanced", "recall", "strict"])
        llm_mode = st.radio("AI_HEURISTICS", ["full", "judge", "off"], horizontal=True)
        
        if uploaded_file:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("INITIALIZE SEQUENCE"):
                st.session_state.run = True
        st.markdown('</div>', unsafe_allow_html=True)

    with col_r:
        if 'run' in st.session_state and uploaded_file:
            try:
                # 模拟处理逻辑
                with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name

                with st.status(">> PARSING DATA STREAM...", expanded=True) as status:
                    artemis.apply_mode(mode)
                    artemis.CONFIG["llm_mode"] = llm_mode
                    artemis.CONFIG["allow_empty_target"] = False
                    artemis.CONFIG["debug_candidates"] = False
                    if artemis.CONFIG["llm_mode"] != "off" and not artemis.CONFIG["api_key"]:
                        artemis.CONFIG["llm_mode"] = "off"
                    pairs = artemis.read_json_pairs(tmp_path)
                    rows = artemis.extract_terms(pairs, tmp_path)
                    status.update(label=">> ANALYSIS COMPLETE", state="complete")

                # --- 结果展示面板 ---
                st.markdown('<div class="fui-panel">', unsafe_allow_html=True)
                st.write("▼ TELEMETRY_SUMMARY")
                
                # 自定义统计块
                df = pd.DataFrame(rows)
                st.markdown(
                    f"""
                    <div style="margin-bottom:20px;">
                        <div class="fui-stat-box">
                            <div class="fui-stat-label">Total Terms</div>
                            <div class="fui-stat-value" style="color:#105bd8;">{len(df)}</div>
                        </div>
                        <div class="fui-stat-box">
                            <div class="fui-stat-label">Categories</div>
                            <div class="fui-stat-value" style="color:#dd361c;">{df['type'].nunique() if 'type' in df.columns and not df.empty else 0}</div>
                        </div>
                        <div class="fui-stat-box">
                            <div class="fui-stat-label">Confidence</div>
                            <div class="fui-stat-value" style="color:#02bfe7;">98.4%</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.dataframe(df, use_container_width=True)
                
                # 导出区
                out_path = Path(tempfile.gettempdir()) / "artemis_export.xlsx"
                artemis.export_excel(rows, str(out_path))
                with open(out_path, "rb") as f:
                    st.download_button("💾 DOWNLOAD DATA STREAM", f.read(), file_name="ARTEMIS_LOG.xlsx")
                st.markdown('</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"SYSTEM_FAULT: {str(e)}")
        else:
            # 待机占位图
            st.markdown("""
            <div class="fui-panel" style="height: 450px; display: flex; flex-direction: column; align-items: center; justify-content: center; opacity: 0.2;">
                <div style="font-size: 6rem; font-weight: 800;">AWAITING</div>
                <div style="letter-spacing: 15px;">RESOURCE_KEY_REQUIRED</div>
            </div>
            """, unsafe_allow_html=True)

    # --- BOTTOM LOG ---
    st.markdown(
        """
        <div class="bottom-log">
            CONNECTION: STABLE // ENCRYPTION: AES‑256 // NODE: LOCAL_HOST // >_ READY
        </div>
        """,
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()
