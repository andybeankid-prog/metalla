import time
import streamlit as st

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

# --------------------------
# Helpers
# --------------------------

def init_api(access_token: str):
    """初始化 API（只需 token）"""
    FacebookAdsApi.init(access_token=access_token)

def _sdk_edge(cursor_callable, fields):
    """呼叫 SDK edge 並回傳 list[dict]"""
    items = []
    cursor = cursor_callable(fields=fields)
    for obj in cursor:
        items.append({k: obj.get(k) for k in fields})
    return items

def _graph_get_custom_audiences(ad_account_id: str, fields):
    """直接呼叫 Graph API（相容沒有 SDK 方法時）"""
    api = FacebookAdsApi.get_default_api()
    edge = f"/{ad_account_id}/customaudiences"
    params = {"fields": ",".join(fields), "limit": 5000}
    data = []
    while True:
        resp = api.call("GET", edge, params=params).json()
        data.extend(resp.get("data", []))
        paging = resp.get("paging", {})
        next_url = paging.get("next")
        if not next_url:
            break
        # 透過 after 續傳
        cursors = paging.get("cursors", {})
        after = cursors.get("after")
        if not after:
            break
        params["after"] = after
    # 轉成一致格式
    return [{k: item.get(k) for k in fields} for item in data]

def get_all_custom_audiences(ad_account_id: str):
    """
    回傳 list[dict]: [{id, name, approximate_count}]
    先試 SDK（不同版本方法名可能不同），不行就走 Graph API。
    """
    fields = ["id", "name", "approximate_count"]
    acc = AdAccount(ad_account_id)

    # 嘗試多個可能的方法名稱
    for method_name in ("get_custom_audiences", "get_customaudiences"):
        method = getattr(acc, method_name, None)
        if callable(method):
            return sorted(_sdk_edge(method, fields), key=lambda x: (x.get("name") or "").lower())

    # SDK 無對應方法 → 走 Graph API
    items = _graph_get_custom_audiences(ad_account_id, fields)
    return sorted(items, key=lambda x: (x.get("name") or "").lower())

def get_all_custom_audience_names(ad_account_id: str):
    """回傳 set[str]：現有所有 CA 名稱，供重名檢查。"""
    fields = ["name"]
    acc = AdAccount(ad_account_id)

    # 試 SDK
    for method_name in ("get_custom_audiences", "get_customaudiences"):
        method = getattr(acc, method_name, None)
        if callable(method):
            names = set()
            for obj in method(fields=fields):
                n = obj.get("name")
                if n:
                    names.add(n)
            return names

    # 走 Graph API
    items = _graph_get_custom_audiences(ad_account_id, fields)
    return {it.get("name") for it in items if it.get("name")}

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
    """命名規則：COUNTRY-PCT%-SOURCE_NAME（例：TW-1%-會員再行銷）"""
    pct = f"{int(round(ratio * 100))}%"
    return f"{country}-{pct}-{source_name}"

def next_available_name(base_name: str, existing_names: set, strategy: str):
    """
    重名處理：
      - append：自動加尾碼（-2, -3, ...）
      - skip  ：略過（回傳 None）
      - fail  ：丟錯
    """
    if base_name not in existing_names:
        return base_name
    if strategy == "skip":
        return None
    if strategy == "fail":
        raise ValueError(f"命名重複：{base_name}")

    i = 2
    while True:
        candidate = f"{base_name}-{i}"
        if candidate not in existing_names:
            return candidate
        i += 1

def create_lookalike(ad_account_id: str, source_id: str, ratio: float, country: str, final_name: str):
    """建立 Lookalike Audience（使用 AdAccount edge）"""
    acc = AdAccount(ad_account_id)
    return acc.create_custom_audience(
        fields=[],
        params={
            "subtype": "LOOKALIKE",
            "origin_audience_id": source_id,
            "lookalike_spec": {"ratio": ratio, "country": country},
            "name": final_name,
        },
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
    unsafe_allow_html=True,
)

st.title("🔁 Facebook Lookalike 受眾產生器（獨立網頁版）")
st.caption("命名規則：<span class='pill'>{COUNTRY}-{PCT}%-{SOURCE_NAME}</span>", unsafe_allow_html=True)

# —— 使用 Secrets 儲存 Token（優先）——
SECRET_TOKEN = st.secrets.get("ACCESS_TOKEN", "")

with st.sidebar:
    st.header("🔐 連線設定")
    ad_account_id = st.text_input("廣告帳號 ID", value="act_924798139306112")

    st.header("🧮 參數設定")
    countries_str = st.text_input("國家代碼（多國逗號分隔）", value="TW")
    ratios_str = st.text_input("比例（小數，逗號分隔；例：0.01=1%）", value="0.01,0.02,0.05")

    conflict_ui = st.radio(
        "命名重複處理",
        ["自動加尾碼", "同名略過", "嚴格模式"],
        index=0,
    )
    strategy_map = {"自動加尾碼": "append", "同名略過": "skip", "嚴格模式": "fail"}

    # 若沒在 Secrets 設定，才顯示輸入框（備援）
    if not SECRET_TOKEN:
        access_token = st.text_input("Access Token（未設定 Secrets 才需填）", type="password")
    else:
        access_token = SECRET_TOKEN
        st.info("🔒 使用 Secrets 中的 ACCESS_TOKEN，不需手動貼 Token。")

    connect = st.button("🔌 連線並載入受眾")

if connect:
    try:
        if not access_token:
            st.error("尚未提供 Access Token（請在 .streamlit/secrets.toml 或雲端 Secrets 設定 ACCESS_TOKEN）")
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

if "audiences" in st.session_state:
    # 搜尋/篩選
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        keyword = st.text_input("搜尋受眾（名稱包含）", value="")
    with c2:
        min_size = st.number_input("最小名單數（可選）", value=0, min_value=0, step=100)
    with c3:
        max_size = st.number_input("最大名單數（可選，0 表不限）", value=0, min_value=0, step=100)
    with c4:
        st.markdown("<div class='small'>列表顯示：名稱（人數）— ID</div>", unsafe_allow_html=True)

    # 過濾後的多選
    filtered = []
    for a in st.session_state["audiences"]:
        nm = a.get("name") or ""
        ct = a.get("approximate_count") or 0
        if keyword and keyword.lower() not in nm.lower():
            continue
        if min_size and ct < min_size:
            continue
        if max_size and max_size > 0 and ct > max_size:
            continue
        label = f"{nm} ({ct if ct else 'N/A'}) — {a.get('id')}"
        filtered.append((label, a.get("id"), nm))

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

        id_by_label = {lab: _id for (lab, _id, _nm) in filtered}
        name_by_id = {_id: _nm for (_lab, _id, _nm) in filtered}
        selected_ids = [id_by_label[lab] for lab in selected]

        if not selected_ids:
            st.warning("請至少選一個來源受眾")
            st.stop()

        # 再同步一次現有名稱，避免外部同時建立
        try:
            existing_names = get_all_custom_audience_names(ad_account_id)
        except Exception as e:
            st.error(f"讀取現有名稱失敗：{e}")
            st.stop()

        total = len(selected_ids) * len(ratios) * len(countries)
        st.info(f"即將建立 {total} 個組合（同名策略：{conflict_ui}）")
        prog = st.progress(0)
        done = 0

        successes, skipped, failures = [], [], []

        for sid in selected_ids:
            src_name = name_by_id.get(sid, sid)
            for r in ratios:
                for country in countries:
                    base_name = build_name(country, r, src_name)
                    try:
                        final_name = next_available_name(base_name, existing_names, strategy_map[conflict_ui])
                        if final_name is None:
                            skipped.append(base_name)
                        else:
                            obj = create_lookalike(ad_account_id, sid, r, country, final_name)
                            successes.append((final_name, obj.get("id")))
                            # 立刻加入，避免同批次再撞名
                            existing_names.add(final_name)
                    except Exception as e:
                        failures.append((base_name, str(e)))

                    done += 1
                    prog.progress(min(done / total, 1.0))
                    time.sleep(0.25)  # 避免節流

        st.subheader("結果")
        if successes:
            st.success(f"✅ 成功 {len(successes)} 項：")
            for n, _id in successes:
                st.write(f"- {n}（ID: {_id}）")
        if skipped:
            st.warning(f"⏭️ 同名略過 {len(skipped)} 項：")
            for n in skipped[:20]:
                st.write(f"- {n}")
            if len(skipped) > 20:
                st.write(f"…以及 {len(skipped) - 20} 項")
        if failures:
            st.error(f"❌ 失敗 {len(failures)} 項（前 20 筆）：")
            for n, err in failures[:20]:
                st.write(f"- {n}｜原因：{err}")
            if len(failures) > 20:
                st.write(f"…以及 {len(failures) - 20} 項")
