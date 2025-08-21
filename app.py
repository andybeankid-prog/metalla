# FB Lookalike Audience Tool
# 使用 Streamlit 建立 Lookalike Audience 的網頁工具
# 完整程式碼請參考先前提供的版本，此處為 placeholder
print("import streamlit as st
import time

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.customaudience import CustomAudience

# --------------------------
# Helper functions
# --------------------------
def init_api(token: str):
    FacebookAdsApi.init(access_token=token)

def get_all_custom_audiences(ad_account_id: str):
    """
    回傳 list[dict]: [{id, name, count}]
    """
    acc = AdAccount(ad_account_id)
    fields = ["id", "name", "approximate_count"]
    items = []
    for ca in acc.get_customaudiences(fields=fields):
        items.append({
            "id": ca.get("id"),
            "name": ca.get("name") or "",
            "count": ca.get("approximate_count")
        })
    # 依名稱排序
    items.sort(key=lambda x: x["name"].lower())
    return items

def get_all_custom_audience_names(ad_account_id: str):
    """
    回傳 set[str]: 現有所有 Custom Audience 名稱（用於重名檢查）
    """
    acc = AdAccount(ad_account_id)
    fields = ["name"]
    names = set()
    for ca in acc.get_customaudiences(fields=fields):
        n = ca.get("name")
        if n:
            names.add(n)
    return names

def parse_ratios(text: str):
    vals = []
    for part in text.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            v = float(p)
            if v <= 0 or v > 0.20:
                raise ValueError("比例建議 0 < ratio ≤ 0.20（例如 0.01 代表 1%）")
            vals.append(v)
        except Exception:
            raise ValueError(f"比例格式錯誤：{p}（請用小數，如 0.01 代表 1%）")
    if not vals:
        raise ValueError("請至少輸入一個比例")
    return vals

def build_name(country: str, ratio: float, source_name: str):
    """
    命名規則：國家縮寫 + 百分比 + 來源名稱，例如：TW-1%-會員再行銷清單
    """
    pct = f"{int(round(ratio*100))}%"
    return f"{country}-{pct}-{source_name}"

def next_available_name(base_name: str, existing_names: set, strategy: str):
    """
    重名處理：
      - 'append': 自動加尾碼（-2, -3, ...）
      - 'skip'  : 直接略過（回傳 None）
      - 'fail'  : 丟出錯誤
    """
    if base_name not in existing_names:
        return base_name

    if strategy == "skip":
        return None
    if strategy == "fail":
        raise ValueError(f"命名重複：{base_name}")

    # append
    i = 2
    while True:
        candidate = f"{base_name}-{i}"
        if candidate not in existing_names:
            return candidate
        i += 1

def create_lookalike(ad_account_id: str, source_id: str, ratio: float, country: str, final_name: str):
    """
    透過 AdAccount 建立 LAL
    """
    acc = AdAccount(ad_account_id)
    return acc.create_custom_audience(
        fields=[],
        params={
            "subtype": "LOOKALIKE",
            "origin_audience_id": source_id,
            "lookalike_spec": {
                "ratio": ratio,
                "country": country
            },
            "name": final_name
        }
    )

# --------------------------
# Streamlit UI
# --------------------------
st.set_page_config(page_title="FB Lookalike Tool", page_icon="🔁", layout="wide")

st.markdown(
    """
    <style>
      .small { color:#6B7280; font-size:12px; }
      .pill { display:inline-block; padding:2px 8px; border:1px solid #E5E7EB; border-radius:999px; margin-right:6px; font-size:12px; color:#374151; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🔁 Facebook Lookalike 受眾產生器（獨立網頁版）")
st.caption("命名規則：<span class='pill'>{COUNTRY}-{PCT}%-{SOURCE_NAME}</span>", unsafe_allow_html=True)

# Sidebar：連線與參數
with st.sidebar:
    st.header("🔐 連線設定")
    access_token = st.text_input("Access Token", type="password", help="貼入你的（長效）存取權杖")
    ad_account_id = st.text_input("廣告帳號 ID", value="act_924798139306112")

    st.header("🧮 參數設定")
    countries_str = st.text_input("國家代碼（多國用逗號分隔）", value="TW,US")
    ratios_str = st.text_input("比例（逗號分隔，小數；例：0.01=1%）", value="0.01,0.02,0.05")

    conflict_strategy = st.radio(
        "命名重複處理",
        ["自動加尾碼", "同名略過", "嚴格模式"],
        index=0,
        help="遇到同名時的處理方式"
    )
    strategy_map = {
        "自動加尾碼": "append",
        "同名略過": "skip",
        "嚴格模式": "fail"
    }

    connect = st.button("🔌 連線並載入受眾")

# 主區：受眾列表與操作
if connect:
    try:
        if not access_token:
            st.error("請填入 Access Token")
            st.stop()

        init_api(access_token)

        with st.spinner("讀取受眾中…"):
            audiences = get_all_custom_audiences(ad_account_id)
            existing_names = get_all_custom_audience_names(ad_account_id)

        st.session_state["audiences"] = audiences
        st.session_state["existing_names"] = existing_names
        st.success(f"✅ 已載入受眾：{len(audiences)} 筆")

    except Exception as e:
        st.error(f"❌ 連線或載入失敗：{e}")

# 已載入後才顯示選擇與建立
if "audiences" in st.session_state:
    # 搜尋與篩選
    cols = st.columns([1,1,1,2])
    with cols[0]:
        keyword = st.text_input("搜尋受眾（名稱包含）", value="")
    with cols[1]:
        min_size = st.number_input("最小名單數（可選）", value=0, min_value=0, step=100)
    with cols[2]:
        max_size = st.number_input("最大名單數（可選，0 表不限）", value=0, min_value=0, step=100)
    with cols[3]:
        st.markdown("<div class='small'>提示：列表格式為「名稱（人數）— ID」</div>", unsafe_allow_html=True)

    # 過濾
    filtered = []
    for a in st.session_state["audiences"]:
        nm = a["name"]
        ct = a["count"] or 0
        if keyword and keyword.lower() not in nm.lower():
            continue
        if min_size and ct < min_size:
            continue
        if max_size and max_size > 0 and ct > max_size:
            continue
        label = f"{nm} ({ct if ct else 'N/A'}) — {a['id']}"
        filtered.append((label, a["id"], nm))

    # 多選
    options = [lab for (lab, _id, _nm) in filtered]
    selected = st.multiselect("選擇來源受眾（可多選）", options)

    # 建立
    start = st.button("🚀 建立 Lookalike Audience")
    if start:
        try:
            ratios = parse_ratios(ratios_str.strip())
            countries = [c.strip().upper() for c in countries_str.split(",") if c.strip()]
            if not countries:
                st.error("請至少輸入一個國家代碼")
                st.stop()
        except Exception as e:
            st.error(str(e))
            st.stop()

        # 解析選取到的 ID 與名稱
        id_by_label = {lab: _id for (lab, _id, _nm) in filtered}
        name_by_id = { _id: _nm for (_lab, _id, _nm) in filtered }
        selected_ids = [id_by_label[lab] for lab in selected]

        if not selected_ids:
            st.warning("請至少選一個來源受眾")
            st.stop()

        # 重新抓一次現有名稱，避免外部同時建立造成衝突
        try:
            existing_names = get_all_custom_audience_names(ad_account_id)
        except Exception as e:
            st.error(f"讀取現有名稱失敗：{e}")
            st.stop()

        total = len(selected_ids) * len(ratios) * len(countries)
        st.info(f"即將建立 {total} 個組合（同名策略：{conflict_strategy}）")
        prog = st.progress(0)
        done = 0

        successes, skipped, failures = [], [], []

        for sid in selected_ids:
            src_name = name_by_id.get(sid, sid)
            for r in ratios:
                for country in countries:
                    base_name = build_name(country, r, src_name)
                    try:
                        final_name = next_available_name(base_name, existing_names, strategy_map[conflict_strategy])
                        if final_name is None:
                            skipped.append(base_name)
                        else:
                            obj = create_lookalike(ad_account_id, sid, r, country, final_name)
                            successes.append((final_name, obj.get("id")))
                            existing_names.add(final_name)  # 立即加入避免同批次再撞名
                    except Exception as e:
                        failures.append((base_name, str(e)))

                    done += 1
                    prog.progress(min(done/total, 1.0))
                    time.sleep(0.25)  # 降低頻率，避免 API 節流

        st.subheader("結果")
        if successes:
            st.success(f"✅ 成功 {len(successes)} 項：")
            for n, _id in successes:
                st.write(f"- {n}  (ID: {_id})")
        if skipped:
            st.warning(f"⏭️ 同名略過 {len(skipped)} 項：")
            for n in skipped[:20]:
                st.write(f"- {n}")
            if len(skipped) > 20:
                st.write(f"…以及 {len(skipped)-20} 項")
        if failures:
            st.error(f"❌ 失敗 {len(failures)} 項（前 20 筆）：")
            for n, err in failures[:20]:
                st.write(f"- {n}｜原因：{err}")
            if len(failures) > 20:
                st.write(f"…以及 {len(failures)-20} 項")")
