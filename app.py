# app.py
import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_cors import CORS
import pandas as pd
import numpy as np

# optional external libs (pyrebase)
try:
    import pyrebase
    PYREBASE_AVAILABLE = True
except Exception:
    PYREBASE_AVAILABLE = False

# Firebase Admin (Firestore) optional
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_ADMIN_AVAILABLE = True
except Exception:
    FIREBASE_ADMIN_AVAILABLE = False

# Flask app
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)
CORS(app)

# --- pyrebase 初期化（存在すれば） ---
auth = None
if PYREBASE_AVAILABLE:
    try:
        # Renderなどで環境変数から設定を取得
        firebase_config_env = os.environ.get("FIREBASE_CONFIG")
        if firebase_config_env:
            firebaseConfig = json.loads(firebase_config_env)
        elif os.path.exists("firebaseConfig.json"):
            with open("firebaseConfig.json", "r", encoding="utf-8") as f:
                firebaseConfig = json.load(f)
        elif os.environ.get("FIREBASE_CONFIG"):
            firebaseConfig = os.getenv("FIREBASE_CONFIG", "firebaseConfig.json")
        else:
            firebaseConfig = None

        if firebaseConfig:
            firebase = pyrebase.initialize_app(firebaseConfig)
            auth = firebase.auth()
        else:
            print("firebaseConfig not provided; Firebase auth disabled.")
    except Exception as e:
        print("pyrebase init failed:", e)
        auth = None
else:
    print("pyrebase not installed; Firebase auth disabled.")

# --- Firestore 初期化設定（オプション） ---
FIREBASE_CRED_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "electrical-equipment-db-firebase-adminsdk-fbsvc-816a1b8dc7.json")
FIRESTORE_COLLECTION = "buildings"

# ----- データ読み込み（キャッシュ） -----
_df_cache = None

def _load_sample_data():
    data = [
        {"建物名称":"Aビル","建物用途":"生産施設","発行目的":"実施設計図","設計会社":"大成建設","変圧器の主な設置場所":"地上",
         "延床面積 [㎡]": 1200.0, "合計設備容量 [kVA]": 500.0, "一般電灯容量 [kVA]": 50.0, "階数": 3},
        {"建物名称":"B工場","建物用途":"生産施設","発行目的":"完成図","設計会社":"鹿島建設","変圧器の主な設置場所":"屋上",
         "延床面積 [㎡]": 3500.0, "合計設備容量 [kVA]": 1800.0, "一般電灯容量 [kVA]": 120.0, "階数": 2},
        {"建物名称":"C研究棟","建物用途":"研究施設","発行目的":"実施設計図","設計会社":"清水建設","変圧器の主な設置場所":"専用室",
         "延床面積 [㎡]": 800.0, "合計設備容量 [kVA]": 300.0, "一般電灯容量 [kVA]": 30.0, "階数": 5},
        {"建物名称":"D物流","建物用途":"物流施設","発行目的":"実施設計図","設計会社":"大林組","変圧器の主な設置場所":"別棟",
         "延床面積 [㎡]": 5000.0, "合計設備容量 [kVA]": 1200.0, "一般電灯容量 [kVA]": 200.0, "階数": 1},
        {"建物名称":"Eその他","建物用途":"その他","発行目的":"完成図","設計会社":"竹中工務店","変圧器の主な設置場所":"ISS",
         "延床面積 [㎡]": 450.0, "合計設備容量 [kVA]": 150.0, "一般電灯容量 [kVA]": 20.0, "階数": 4},
    ]
    return pd.DataFrame(data)

def load_firestore_data():
    global _df_cache
    if _df_cache is not None:
        return _df_cache

    df = None
    # Try Firestore if available and credential file exists
    if FIREBASE_ADMIN_AVAILABLE and os.path.exists(FIREBASE_CRED_PATH):
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_CRED_PATH)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            docs = db.collection(FIRESTORE_COLLECTION).stream()
            rows = [doc.to_dict() for doc in docs]
            if not rows:
                df = _load_sample_data()
            else:
                df = pd.DataFrame(rows)
        except Exception as e:
            print("Firestore load error:", e)
            df = _load_sample_data()
    else:
        df = _load_sample_data()

    # 型揃え・欠損処理: 数値列の自動推測（既知の列名をfloatに）
    numeric_cols = ["延床面積 [㎡]","生産エリアの延床面積 [㎡]","非生産エリアの延床面積 [㎡]","建築面積 [㎡]","階数",
                    "合計設備容量 [kVA]","一般電灯容量 [kVA]","一般動力容量 [kVA]","一般動力(400V)容量 [kVA]",
                    "生産電灯容量 [kVA]","生産動力容量 [kVA]","生産動力(400V)容量 [kVA]","合計変圧器容量 [kVA]"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    expected_cols = ["建物名称","建物用途","発行目的","設計会社","変圧器の主な設置場所"] + numeric_cols
    for c in expected_cols:
        if c not in df.columns:
            df[c] = pd.NA

    _df_cache = df
    return df

# usage color map
USAGE_COLORS = {
    "生産施設": "#7FB3D5",
    "研究施設": "#82E0AA",
    "物流施設": "#F7DC6F",
    "その他": "#D7BDE2"
}

# ----- ルート: ログイン / インデックス / ログアウト -----
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template("login.html", msg="")
    if auth is None:
        return render_template("login.html", msg="認証機能が利用できません（サーバー設定を確認してください）。")
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    try:
        user = auth.sign_in_with_email_and_password(email, password)
        session['usr'] = email
        return redirect(url_for('index'))
    except Exception:
        return render_template("login.html", msg="メールアドレスまたはパスワードが間違っています。")

@app.route("/", methods=['GET'])
def index():
    usr = session.get('usr')
    # 未ログインならログインページへ（認証無効時はログイン無しで進める想定にしたければここを変更）
    if usr is None and auth is not None:
        return redirect(url_for('login'))

    df = load_firestore_data()
    cols = ["延床面積 [㎡]","生産エリアの延床面積 [㎡]","非生産エリアの延床面積 [㎡]","建築面積 [㎡]","階数",
            "合計設備容量 [kVA]","一般電灯容量 [kVA]","一般動力容量 [kVA]","一般動力(400V)容量 [kVA]",
            "生産電灯容量 [kVA]","生産動力容量 [kVA]","生産動力(400V)容量 [kVA]","合計変圧器容量 [kVA]"]

    # dropna の前に列が存在することを確認
    usages = sorted([str(x) for x in df["建物用途"].dropna().unique()]) if "建物用途" in df.columns else []
    purposes = sorted([str(x) for x in df["発行目的"].dropna().unique()]) if "発行目的" in df.columns else []
    companies = sorted([str(x) for x in df["設計会社"].dropna().unique()]) if "設計会社" in df.columns else []
    transformers = sorted([str(x) for x in df["変圧器の主な設置場所"].dropna().unique()]) if "変圧器の主な設置場所" in df.columns else []

    return render_template("index.html",
                           usr=usr,
                           columns=cols,
                           usages=usages,
                           purposes=purposes,
                           companies=companies,
                           transformers=transformers,
                           usage_colors=USAGE_COLORS)

@app.route('/logout')
def logout():
    session.pop('usr', None)
    return redirect(url_for('login'))

# ----- データ API -----
@app.route("/api/get_data", methods=["POST"])
def api_get_data():
    body = request.get_json(force=True)
    x_col = body.get("x_col")
    y_col = body.get("y_col")
    graph_type = body.get("graph_type", "散布図")
    try:
        degree = int(body.get("degree", 1))
    except Exception:
        degree = 1
    filters = body.get("filters", {}) or {}
    capacity_min = body.get("capacity_min", None)
    capacity_max = body.get("capacity_max", None)
    log_x = bool(body.get("log_x", False))
    log_y = bool(body.get("log_y", False))
    search = (body.get("search") or "").strip().lower()

    df = load_firestore_data().copy()

    # フィルタ適用
    filter_map = {
        "建物用途":"建物用途",
        "発行目的":"発行目的",
        "設計会社":"設計会社",
        "変圧器の主な設置場所":"変圧器の主な設置場所"
    }
    for key, colname in filter_map.items():
        allow = filters.get(key, [])
        if allow and colname in df.columns:
            df = df[df[colname].isin(allow)]

    # 容量範囲フィルタ（合計設備容量を対象）
    if capacity_min is not None and str(capacity_min).strip() != "":
        try:
            minv = float(capacity_min)
            if "合計設備容量 [kVA]" in df.columns:
                df = df[pd.to_numeric(df["合計設備容量 [kVA]"], errors="coerce") >= minv]
        except Exception:
            pass
    if capacity_max is not None and str(capacity_max).strip() != "":
        try:
            maxv = float(capacity_max)
            if "合計設備容量 [kVA]" in df.columns:
                df = df[pd.to_numeric(df["合計設備容量 [kVA]"], errors="coerce") <= maxv]
        except Exception:
            pass

    # 検索（建物名称）
    if search and "建物名称" in df.columns:
        df = df[df["建物名称"].fillna("").str.lower().str.contains(search, na=False)]

    # 必要列チェック
    if x_col not in df.columns or (graph_type == "散布図" and (y_col not in df.columns)):
        return jsonify({"error":"指定された列が存在しません"}), 400

    # 散布図
    if graph_type == "散布図":
        df_plot = df.dropna(subset=[x_col, y_col]).copy()
        df_plot[x_col] = pd.to_numeric(df_plot[x_col], errors="coerce")
        df_plot[y_col] = pd.to_numeric(df_plot[y_col], errors="coerce")
        df_plot = df_plot.dropna(subset=[x_col, y_col])

        traces = []
        group_col = "建物用途" if "建物用途" in df_plot.columns else None
        if group_col:
            groups = df_plot.groupby(group_col)
        else:
            groups = [("全体", df_plot)]

        for usage, group in groups:
            usage_str = usage if (usage is not None and str(usage).strip() != "") else "未定義"
            color = USAGE_COLORS.get(usage_str, "#999999")
            trace = {
                "type":"scatter",
                "mode":"markers",
                "name": usage_str,
                "x": group[x_col].astype(float).tolist(),
                "y": group[y_col].astype(float).tolist(),
                "marker": {"size":8, "color": color},
                "customdata": group[["建物名称","発行目的","設計会社", x_col, y_col]].fillna("").astype(str).values.tolist()
            }
            traces.append(trace)

        # ハイライト
        highlight = []
        if search and "建物名称" in df.columns:
            df_high = load_firestore_data().copy()
            df_high = df_high[df_high["建物名称"].fillna("").str.lower().str.contains(search, na=False)]
            if not df_high.empty and x_col in df_high.columns and y_col in df_high.columns:
                df_high = df_high.dropna(subset=[x_col, y_col])
                df_high[x_col] = pd.to_numeric(df_high[x_col], errors="coerce")
                df_high[y_col] = pd.to_numeric(df_high[y_col], errors="coerce")
                df_high = df_high.dropna(subset=[x_col, y_col])
                if not df_high.empty:
                    highlight = [{
                        "x": df_high[x_col].astype(float).tolist(),
                        "y": df_high[y_col].astype(float).tolist(),
                        "marker": {"size":14, "color":"rgba(255,0,0,0.6)", "symbol":"circle-open"},
                        "type":"scatter",
                        "mode":"markers",
                        "name":"検索ハイライト"
                    }]

        # 近似多項式（全データで計算）
        fit = None
        eq = ""
        try:
            if len(df_plot) >= max(2, degree+1):
                x = df_plot[x_col].astype(float).values
                y = df_plot[y_col].astype(float).values
                coeffs = np.polyfit(x, y, degree)
                p = np.poly1d(coeffs)
                x_sorted = np.linspace(np.nanmin(x), np.nanmax(x), 200)
                y_sorted = p(x_sorted)
                fit = {
                    "x": x_sorted.tolist(),
                    "y": y_sorted.tolist(),
                    "name": f"{degree}次近似",
                    "mode": "lines",
                    "line": {"width":1.5, "color":"#1f77b4"}
                }
                terms = []
                n = len(coeffs)-1
                for i, c in enumerate(coeffs):
                    power = n - i
                    if power == 0:
                        terms.append(f"{c:.3g}")
                    elif power == 1:
                        terms.append(f"{c:.3g}·x")
                    else:
                        terms.append(f"{c:.3g}·x^{power}")
                eq = " + ".join(terms)
            else:
                eq = "データ不足で近似不可"
        except Exception as e:
            fit = None
            eq = f"近似失敗: {str(e)}"

        response = {
            "traces": traces,
            "fit": fit,
            "equation": eq,
            "highlight": highlight,
            "xaxis": {"title": x_col, "type": ("log" if log_x else "linear")},
            "yaxis": {"title": y_col, "type": ("log" if log_y else "linear")},
            "layout": {"showlegend": True}
        }
        return jsonify(response)

    # ヒストグラム
    elif graph_type == "ヒストグラム":
        df_plot = df.dropna(subset=[x_col]).copy()
        df_plot[x_col] = pd.to_numeric(df_plot[x_col], errors="coerce")
        df_plot = df_plot.dropna(subset=[x_col])
        bins = int(body.get("bins", 20))
        try:
            counts, bin_edges = np.histogram(df_plot[x_col].values, bins=bins)
            traces = []
            if "建物用途" in df_plot.columns:
                for usage, group in df_plot.groupby("建物用途"):
                    usage_str = usage if (usage is not None and str(usage).strip() != "") else "未定義"
                    counts_g, _ = np.histogram(group[x_col].values, bins=bin_edges)
                    traces.append({
                        "type":"bar",
                        "name": usage_str,
                        "x": bin_edges[:-1].tolist(),
                        "y": counts_g.tolist(),
                        "marker": {"color": USAGE_COLORS.get(usage_str, "#888888")},
                    })
            else:
                traces.append({
                    "type":"bar",
                    "name":"件数",
                    "x": bin_edges[:-1].tolist(),
                    "y": counts.tolist(),
                })

            response = {
                "traces": traces,
                "xaxis": {"title": x_col, "type": ("log" if log_x else "linear")},
                "yaxis": {"title": "件数", "type": ("log" if log_y else "linear")},
                "layout": {"barmode":"overlay", "barnorm": None}
            }
            return jsonify(response)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"error":"不明な graph_type"}), 400

if __name__ == "__main__":
    # デバッグ実行（本番は Gunicorn 等を推奨）
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)


