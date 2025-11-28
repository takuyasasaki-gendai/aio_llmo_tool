import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote
import json
import re
import urllib3
from duckduckgo_search import DDGS

# ==========================================
# 🔒 セキュリティ設定 (パスワード制限)
# ==========================================
# 任意のパスワードに変更してください
LOGIN_PASSWORD = "password" 

# サイドバーでパスワード入力を求める
with st.sidebar:
    st.markdown("### 🔐 認証")
    input_password = st.text_input("パスワードを入力", type="password")

# パスワードが一致しない場合、ここで処理を止める
if input_password != LOGIN_PASSWORD:
    st.warning("👈 サイドバーにパスワードを入力してください。")
    st.stop()

# ==========================================
# 設定 & ヘルパー関数
# ==========================================

# SSL無視設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_search_results(keyword, max_results=10):
    """ DuckDuckGo検索 (エラーハンドリング付き) """
    results = []
    try:
        with DDGS() as ddgs:
            ddg_gen = ddgs.text(keyword, region='jp-jp', timelimit='y', max_results=max_results, backend='html')
            for r in ddg_gen:
                results.append(r)
    except Exception:
        return None
    return results

def generate_local_schema(name, url, phone="03-xxxx-xxxx"):
    data = {
        "@context": "https://schema.org",
        "@type": "SportsActivityLocation",
        "name": name,
        "url": url,
        "telephone": phone,
        "address": {"@type": "PostalAddress", "addressLocality": "市区町村", "addressRegion": "都道府県", "streetAddress": "番地"},
        "priceRange": "¥5,000〜¥10,000"
    }
    return json.dumps(data, indent=2, ensure_ascii=False)

def generate_faq_schema():
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": "初心者でも大丈夫ですか？", "acceptedAnswer": {"@type": "Answer", "text": "はい、初心者講習をご用意しています。"}}]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)

def generate_table_html():
    return """<table><thead><tr><th>コース名</th><th>料金(税込)</th></tr></thead><tbody><tr><td>レギュラー</td><td>10,000円</td></tr></tbody></table>"""

# ==========================================
# 診断ロジック関数群
# ==========================================

def get_page_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup, "OK"
    except Exception as e:
        return None, str(e)

def analyze_keywords(soup, target_keywords_str):
    tasks = []
    if not target_keywords_str: return tasks
    keywords = [k.strip() for k in target_keywords_str.replace("　", " ").split(" ") if k.strip()]
    if not keywords: return tasks

    unit_points = 20 / (len(keywords) * 3)
    title = soup.title.string if soup.title else ""
    
    h1_tags = soup.find_all('h1')
    h1_text_list = []
    for tag in h1_tags:
        h1_text_list.append(tag.get_text().replace("\n", ""))
        imgs = tag.find_all('img')
        for img in imgs: h1_text_list.append(img.get('alt', ''))
    h1_text = " ".join(h1_text_list)
    body = soup.get_text().replace("\n", "")

    for kw in keywords:
        if kw not in title: tasks.append({"msg": f"Title不備: 「{kw}」を追加", "points": unit_points, "tag": "keyword"})
        if kw not in h1_text: tasks.append({"msg": f"H1不備: 「{kw}」を追加", "points": unit_points, "tag": "keyword"})
        if kw not in body: tasks.append({"msg": f"本文不備: 「{kw}」を追加", "points": unit_points, "tag": "keyword"})
    return tasks

def check_local_elements(soup):
    tasks = []
    clean_text = re.sub(r'\s+', '', soup.get_text())
    has_address = any(x in clean_text for x in ["住所", "所在地", "〒", "都", "県", "市", "区"])
    tel_links = soup.find_all('a', href=re.compile(r'^tel:'))
    has_phone = len(tel_links) > 0 or re.search(r'\d{2,4}-\d{2,4}-\d{4}', soup.get_text())

    has_map = False
    iframes = soup.find_all('iframe')
    map_patterns = ["maps.google", "goo.gl/maps", "googleusercontent.com/maps"]
    for iframe in iframes:
        src = (iframe.get('src') or "") + (iframe.get('data-src') or "") + (iframe.get('data-lazy-src') or "")
        if any(p in src for p in map_patterns): has_map = True; break
    
    if not has_map:
        scripts = soup.find_all('script')
        for script in scripts:
            src = script.get('src') or ""
            if "maps.googleapis.com" in src: has_map = True; break
    
    js_map_trace = False
    if not has_map:
        if len(soup.find_all('div', id=re.compile(r'map|Map'), class_=re.compile(r'map|Map'))) > 0: js_map_trace = True

    if not has_address: tasks.append({"msg": "住所テキストの追加", "points": 7, "tag": "nap"})
    if not has_phone: tasks.append({"msg": "電話番号リンク(tel:)の設定", "points": 7, "tag": "nap"})
    if not has_map:
        if js_map_trace: tasks.append({"msg": "Googleマップ埋め込み (現在JS表示の可能性あり)", "points": 3, "tag": "nap"})
        else: tasks.append({"msg": "Googleマップ埋め込み (iframe)", "points": 6, "tag": "nap"})
    return tasks

def check_qa_and_structure(soup):
    tasks = []
    text = soup.get_text()
    faq_kws = ["よくある質問", "よくあるご質問", "Q&A", "FAQ", "質問と回答", "ご質問"]
    has_faq = any(k in text for k in faq_kws)
    has_structure = len(soup.find_all(['table', 'dl', 'details'])) > 0

    if not has_faq: tasks.append({"msg": "FAQセクションの追加", "points": 10, "tag": "structure"})
    if not has_structure: tasks.append({"msg": "構造化タグ(Table/dl)でのスペック表記", "points": 10, "tag": "table_code"})
    return tasks

def check_trust_signals(soup, url):
    tasks = []
    text = soup.get_text()
    auth_keywords = ["監修", "責任者", "代表", "運営", "プロフィール", "会社概要", "企業情報", "Company", "About"]
    has_auth = any(k in text for k in auth_keywords)

    a_tags = soup.find_all('a', href=True)
    policy_keywords = ["privacy", "policy", "プライバシー", "個人情報", "保護方針"]
    has_policy = False
    for a in a_tags:
        link_url = a.get('href', '').lower()
        link_text = a.get_text().lower()
        if any(kw in link_url for kw in policy_keywords) or any(kw in link_text for kw in policy_keywords):
            has_policy = True; break
    if not has_policy: has_policy = "個人情報保護方針" in text or "プライバシーポリシー" in text

    is_https_scheme = urlparse(url).scheme == "https"
    ssl_valid = False
    if not is_https_scheme:
        tasks.append({"msg": "常時SSL化(https)対応", "points": 10, "tag": "trust"})
    else:
        try:
            requests.get(url, timeout=5, verify=True)
            ssl_valid = True
        except requests.exceptions.SSLError:
            tasks.append({"msg": "SSL証明書の不備修正 (鍵マークが無効です)", "points": 10, "tag": "trust"})
        except:
            ssl_valid = True 

    if not has_auth: tasks.append({"msg": "運営者情報リンクの設置", "points": 10, "tag": "trust"})
    if is_https_scheme and ssl_valid and not has_policy:
         tasks.append({"msg": "プライバシーポリシーへのリンク設置", "points": 10, "tag": "trust"})
    return tasks

def check_tech_schema(soup, base_url):
    tasks = []
    try:
        if requests.get(urljoin(base_url, "/llms.txt"), timeout=3, verify=False).status_code != 200:
             tasks.append({"msg": "llms.txtの設置", "points": 5, "tag": "tech"})
    except: tasks.append({"msg": "llms.txtの設置", "points": 5, "tag": "tech"})

    scripts = soup.find_all('script', type='application/ld+json')
    found_types = []
    for script in scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                 if "@type" in data: found_types.append(data["@type"])
            elif isinstance(data, list):
                for item in data:
                    if "@type" in item: found_types.append(item["@type"])
        except: continue
    
    if "FAQPage" not in found_types: tasks.append({"msg": "FAQPage構造化データの記述", "points": 5, "tag": "faq_code"})
    local_types = ["LocalBusiness", "SportsActivityLocation", "ExerciseGym", "Store", "Restaurant"]
    if not any(t in found_types for t in local_types): tasks.append({"msg": "LocalBusiness構造化データの記述", "points": 10, "tag": "local_code"})
    return tasks

# ==========================================
# UI構築
# ==========================================
st.set_page_config(page_title="店舗AIO改善提案", layout="wide")
# 検索除け
st.markdown("""<meta name="robots" content="noindex">""", unsafe_allow_html=True)

st.title("🛡️ AIO/LLMO 診断チェッカー")

st.info("""
**【スコアと検索順位に関する注釈】**
* 本スコアは、AIの選定基準（内部要因）を最低限満たしているかの指標です。
* **スコアが高いにも関わらずAIに選ばれない（優先度が低い）場合**は、以下の「外部要因」の影響度が高くなります。
    1.  **第三者メディア掲載:** 比較サイトやランキング記事等に上位掲載されているか
    2.  **ドメインパワー:** 指名検索数や被リンク数が強く、ブランド力があるか
    3.  **MEO評価:** Googleマップでの口コミ数や評価が高いか
""")

if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'analyzed' not in st.session_state: st.session_state.analyzed = False
if 'meta_data' not in st.session_state: st.session_state.meta_data = {}
if 'search_results' not in st.session_state: st.session_state.search_results = None
if 'search_error' not in st.session_state: st.session_state.search_error = False

with st.container():
    col1, col2 = st.columns(2)
    with col1:
        company_name = st.text_input("店舗名", placeholder="店舗名を入力")
        target_url = st.text_input("店舗URL", placeholder="https://...")
    with col2:
        keywords_input = st.text_input("狙うキーワード", placeholder="エリア 業種 おすすめ")
    
    analyze_btn = st.button("診断スタート", type="primary")

if analyze_btn and target_url:
    with st.spinner("解析・競合調査中..."):
        soup, status = get_page_content(target_url)
        if soup:
            t1 = analyze_keywords(soup, keywords_input)
            t2 = check_local_elements(soup)
            t3 = check_qa_and_structure(soup)
            t4 = check_trust_signals(soup, target_url)
            t5 = check_tech_schema(soup, target_url)
            
            st.session_state.tasks = t1 + t2 + t3 + t4 + t5
            st.session_state.meta_data = {"url": target_url, "name": company_name, "keyword": keywords_input}
            st.session_state.analyzed = True
            
            if keywords_input:
                results = get_search_results(keywords_input)
                if results is None:
                    st.session_state.search_results = []
                    st.session_state.search_error = True
                else:
                    st.session_state.search_results = results
                    st.session_state.search_error = False
        else:
            st.error(f"エラー: {status}")

if st.session_state.analyzed:
    
    st.divider()
    st.subheader("📊 検索上位サイト (AIの参照元候補)")
    
    if st.session_state.search_error:
        st.error("⚠️ 検索結果の自動取得が制限されました。")
        google_url = f"https://www.google.com/search?q={quote(st.session_state.meta_data['keyword'])}"
        st.link_button("Google検索結果を別タブで開く", google_url)
    elif st.session_state.search_results:
        st.markdown("以下のサイトに「御社の名前」が掲載されているか確認してください。")
        with st.expander("上位10サイトを表示", expanded=True):
            for i, res in enumerate(st.session_state.search_results, 1):
                icon = "🔗"
                if any(k in res['title'] for k in ["おすすめ", "選", "ランキング", "比較"]):
                    icon = "👑"
                    st.markdown(f"**{i}. {icon} [{res['title']}]({res['href']})**")
                else:
                    st.markdown(f"{i}. {icon} [{res['title']}]({res['href']})")
    else:
        st.warning("検索結果が見つかりませんでした。")

    current_deduction = 0
    st.divider()
    c1, c2 = st.columns([1, 2])
    
    with c2:
        st.subheader("📝 改善タスク (Check to Resolve)")
        if not st.session_state.tasks:
            st.success("完璧です。")
        else:
            st.markdown("目視で確認できたもの、または対応した項目に**チェック**を入れてください。")
            for i, task in enumerate(st.session_state.tasks):
                pt_display = round(task['points'], 1)
                label = f"**{task['msg']}** (配点: {pt_display}点)"
                checked = st.checkbox(label, key=f"task_{i}")
                if not checked:
                    current_deduction += task['points']
    
    final_score = max(0, int(100 - current_deduction))
    
    with c1:
        st.metric("現在のAIO適合スコア", f"{final_score} / 100")
        st.progress(final_score / 100)
        if final_score >= 80: st.info("サイト内部は合格圏内です。")
        else: st.warning("改善の余地があります。")

    st.divider()
    st.subheader("💡 必要な改善コード")
    has_code = False
    active_tags = [st.session_state.tasks[i]['tag'] for i in range(len(st.session_state.tasks)) if not st.session_state.get(f"task_{i}", False)]

    if "local_code" in active_tags:
        st.markdown("#### 1. 店舗情報の構造化データ (LocalBusiness)")
        st.code(generate_local_schema(st.session_state.meta_data['name'], st.session_state.meta_data['url']), language='json')
        has_code = True

    if "faq_code" in active_tags:
        st.markdown("#### 2. FAQの構造化データ (FAQPage)")
        st.code(generate_faq_schema(), language='json')
        has_code = True

    if "table_code" in active_tags:
        st.markdown("#### 3. 料金表などのHTML記述例")
        st.code(generate_table_html(), language='html')
        has_code = True
        
    if "nap" in active_tags:
        st.markdown("#### 4. 電話番号リンク記述例")
        st.code('<a href="tel:03-xxxx-xxxx">03-xxxx-xxxx</a>', language='html')
        has_code = True

    if not has_code:
        st.caption("現在表示すべきコードはありません。")
