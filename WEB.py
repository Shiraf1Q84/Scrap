import os
import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import markdown
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

# e-Gov 法令 API の設定
API_VERSION = "1"
API_BASE_URL = f"https://elaws.e-gov.go.jp/api/{API_VERSION}"

# Streamlitページ設定
st.set_page_config(
    page_title="Gemini PDFベースチャットボット with Toggleable Search",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# セッション状態の初期化
if "documents" not in st.session_state:
    st.session_state.documents = []
if "checkbox_values" not in st.session_state:
    st.session_state.checkbox_values = {}
if "file_names" not in st.session_state:
    st.session_state.file_names = {}
if "next_file_id" not in st.session_state:
    st.session_state.next_file_id = 0
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ファイル処理関数は変更なし

def search_law_by_keyword_api(keyword):
    search_url = f"{API_BASE_URL}/lawdata;keyword={keyword}"
    try:
        response = requests.get(search_url)
        response.raise_for_status()
        data = response.json()
        if 'lawdata' in data and data['lawdata']:
            return data['lawdata']
        else:
            st.warning(f"キーワード '{keyword}' に一致する法令が見つかりませんでした。")
            return []
    except requests.RequestException as e:
        st.error(f"法令の検索中にエラーが発生しました: {e}")
        return []

def get_law_content_api(law_number):
    content_url = f"{API_BASE_URL}/articles;lawNum={law_number}"
    try:
        response = requests.get(content_url)
        response.raise_for_status()
        data = response.json()
        if 'articles' in data:
            return data['articles']
        else:
            st.warning(f"法令番号 '{law_number}' の内容が見つかりませんでした。")
            return None
    except requests.RequestException as e:
        st.error(f"法令内容の取得中にエラーが発生しました: {e}")
        return None

def search_law_by_keyword_web(keyword):
    base_url = "https://elaws.e-gov.go.jp"
    search_url = f"{base_url}/search/elawsSearch/elaws_search/lsg0100/?keyword={quote(keyword)}"
    try:
        response = requests.get(search_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        search_results = soup.find_all("div", class_="search-result-item")
        results = []
        for result in search_results:
            title_element = result.find("a", class_="result-title")
            if title_element:
                title = title_element.text.strip()
                url = urljoin(base_url, title_element['href'])
                results.append({'lawTitle': title, 'lawNum': url})
        return results
    except requests.RequestException as e:
        st.error(f"法令の検索中にエラーが発生しました: {e}")
        return []

def get_law_content_web(law_url):
    try:
        response = requests.get(law_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        law_content = soup.find("div", class_="law-content")
        if law_content:
            articles = law_content.find_all(["div", "p"], class_=re.compile("ArticleTitle|ArticleCaption|Paragraph"))
            return [{'articleTitle': article.get_text(strip=True)} for article in articles]
        else:
            st.warning("法令の内容が見つかりませんでした。")
            return None
    except requests.RequestException as e:
        st.error(f"法令内容の取得中にエラーが発生しました: {e}")
        return None

def extract_relevant_laws(query, model):
    prompt = f"""
    以下の質問から、関連する可能性のある日本の法令のキーワードを抽出してください。
    キーワードは3つまで抽出し、カンマ区切りのリストとして出力してください。
    適切なキーワードが見つからない場合は、「該当なし」と出力してください。

    質問: {query}

    キーワード:
    """
    
    response = model.generate_content(prompt)
    keywords = [kw.strip() for kw in response.text.split(',') if kw.strip() != '該当なし']
    return keywords

def law_specific_search(query, model, use_api):
    keywords = extract_relevant_laws(query, model)
    if not keywords:
        st.info("関連する法令のキーワードが見つかりませんでした。")
        return []

    st.info(f"抽出されたキーワード: {', '.join(keywords)}")
    
    search_results = []
    
    for keyword in keywords:
        if use_api:
            law_data = search_law_by_keyword_api(keyword)
            for law in law_data:
                law_number = law.get('lawNum')
                if law_number:
                    law_content = get_law_content_api(law_number)
                    if law_content:
                        search_results.append({
                            'title': law.get('lawTitle', '不明な法令'),
                            'number': law_number,
                            'content': law_content
                        })
        else:
            law_data = search_law_by_keyword_web(keyword)
            for law in law_data:
                law_url = law.get('lawNum')
                if law_url:
                    law_content = get_law_content_web(law_url)
                    if law_content:
                        search_results.append({
                            'title': law.get('lawTitle', '不明な法令'),
                            'number': law_url,
                            'content': law_content
                        })

    return search_results

def display_search_results(search_results, use_api):
    if search_results:
        st.subheader("関連法令検索結果")
        for result in search_results:
            with st.expander(f"{result['title']} ({'法令番号' if use_api else 'URL'}: {result['number']})"):
                for article in result['content']:
                    st.markdown(f"**{article.get('articleTitle', '条文')}**")
                    if use_api:
                        st.write(article.get('articleText', '内容なし'))
    else:
        st.info("この質問に関連する法令検索結果は得られませんでした。")

def display_chat_interface(use_api):
    st.title("PDFベースチャットボット with Toggleable Search (Gemini)")

    # システムプロンプト設定
    system_prompt = st.text_area(
        "システムプロンプトを入力してください",
        """
        あなたはナレッジベースに提供されている書類と最新の法令検索結果に基づいて情報を提供するチャットボットです。
        利用者の質問に、正確かつなるべく詳細に、参考資料を引用しながら答えてください。
        情報は800文字以上、4000文字以内に収めてください。
        マークダウン形式で見やすく出力してください。
        情報源を明記して回答するように努めてください。
        複数の解釈がある場合は、それぞれを提示してください。
        与えられた情報だけでは判断できない場合には、判断できない旨を伝えてください。
        法令の解釈が必要な場合は、その旨を明確に述べ、可能な解釈を示してください。
        検索結果が提供された場合、それらを参照しながら回答してください。
        """,
        height=300
    )

    # チャットインターフェースと検索結果を並べて表示するためのカラムを作成
    chat_column, results_column = st.columns([2, 1])

    # チャットインターフェースのコンテナ
    with chat_column:
        chat_container = st.container()

        # ユーザー入力（常に画面下部に固定）
        user_input = st.chat_input("質問を入力してください")

        # チャット履歴の表示
        with chat_container:
            for message in st.session_state.chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

    if user_input and api_key:
        # ユーザーの質問をチャット履歴に追加
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        # Geminiモデルの初期化
        model = genai.GenerativeModel(model_name)

        # チェックされているドキュメントのみを使用してコンテキストを作成
        context = ""
        for doc in st.session_state.documents:
            if st.session_state.checkbox_values.get(doc["id"], True):
                context += f"ファイル名: {st.session_state.file_names.get(doc['id'], 'Unknown File')}\n"
                context += f"内容:\n{doc['content']}\n\n"

        # 改善された法令特化検索関数を使用
        search_results = law_specific_search(user_input, model, use_api)

        # 検索結果を表示
        with results_column:
            display_search_results(search_results, use_api)

        # プロンプトの作成
        prompt = f"{system_prompt}\n\n"
        prompt += "参考文書:\n"
        prompt += f"{context}\n\n"
        prompt += f"ユーザーの質問: {user_input}\n\n"
        prompt += "関連法令:\n"
        for result in search_results:
            prompt += f"法令名: {result['title']} ({'法令番号' if use_api else 'URL'}: {result['number']})\n"
            for article in result['content'][:3]:  # 最初の3つの条文のみを含める
                prompt += f"条文: {article.get('articleTitle', '不明')}\n"
                if use_api:
                    prompt += f"内容: {article.get('articleText', '内容なし')[:200]}...\n\n"

        prompt += """
        上記の情報を基に、ユーザーの質問に答えてください。関連法令からの情報を使用する場合は、必ず該当する法令名と条文番号を明記してください。
        法令の解釈が必要な場合は、その旨を明確に述べ、可能な解釈を示してください。
        情報が不足している場合は、どのような追加情報が必要かを説明してください。
        """

        # ストリーミング出力のための空のプレースホルダーを作成
        with chat_column:
            with chat_container:
                with st.chat_message("assistant"):
                    response_placeholder = st.empty()

        # ストリーミングレスポンスを生成
        response = model.generate_content(prompt, stream=True)

        # ストリーミング出力
        full_response = ""
        for chunk in response:
            full_response += chunk.text
            response_placeholder.markdown(full_response + "▌")

        # 最終的な応答を表示
        response_placeholder.markdown(full_response)

        # アシスタントの回答をチャット履歴に追加
        st.session_state.chat_history.append({"role": "assistant", "content": full_response})

    elif not api_key:
        st.warning("APIキーを設定してください。")

# UI部分
left_column, right_column = st.columns([1, 3])

with left_column:
    # APIキー入力欄
    st.title("Google API キー")
    api_key = st.text_input("APIキーを入力してください:", type="password")
    if st.button("APIキーを設定"):
        genai.configure(api_key=api_key)
        st.success("APIキーが設定されました")

    # モデル選択
    model_name = st.selectbox("モデルを選択してください:", ["gemini-1.5-pro", "gemini-pro"])

    # 検索方法のトグル
    use_api = st.toggle("e-Gov法令APIを使用", value=True)

    # ファイルアップロード
    uploaded_files = st.file_uploader(
        "PDFまたはマークダウンファイルを選択してください",
        accept_multiple_files=True,
        type=["pdf", "md"],
    )

    # ファイル処理
    if uploaded_files:
        new_files = [file for file in uploaded_files if file.name not in st.session_state.file_names.values()]
        for uploaded_file in new_files:
            file_extension = os.path.splitext(uploaded_file.name)[1]
            if file_extension == ".pdf":
                text = extract_text_from_pdf(uploaded_file)
            elif file_extension == ".md":
                text = extract_text_from_markdown(uploaded_file)
            else:
                st.warning(f"未対応のファイル形式です: {uploaded_file.name}")
                continue

            file_id = str(st.session_state.next_file_id)
            st.session_state.next_file_id += 1
            st.session_state.documents.append({"id": file_id, "content": text})
            
            # ファイル名を保存/更新
            st.session_state.file_names[file_id] = uploaded_file.name
            
# チェックボックスの初期状態を設定
            st.session_state.checkbox_values[file_id] = True

        if new_files:
            st.success(f"{len(new_files)}個の新しいファイルがアップロードされました。")

    # アップロードされたファイル一覧の表示
    st.subheader("アップロードされたファイル")
    for doc in st.session_state.documents:
        file_id = doc["id"]
        file_name = st.session_state.file_names.get(file_id, "Unknown File")
        checked = st.checkbox(
            file_name,
            value=st.session_state.checkbox_values.get(file_id, True),
            key=f"checkbox_{file_id}"
        )
        # チェックボックスの状態を更新
        st.session_state.checkbox_values[file_id] = checked

with right_column:
    display_chat_interface(use_api)
    
# メイン関数の呼び出し
if __name__ == "__main__":
    st.sidebar.title("設定")
    st.sidebar.info("左側のパネルで設定を行ってください。")