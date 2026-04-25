import os
import json
import time
import urllib.parse
from dotenv import load_dotenv
from yun_client import YunClient
from flask import Flask, render_template_string, Response, request

app = Flask(__name__)

# 全局共享状态
shared_state = {
    "client": None,
    "links": {},  # link_id -> full_results
}

# --- HTML 模板 ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>云资源管理 - 概览</title>
    <style>
        body { font-family: -apple-system, sans-serif; padding: 40px; background: #f0f2f5; }
        .dashboard { max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 16px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        h1 { color: #1e293b; margin-bottom: 30px; }
        .link-card { 
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px; margin-bottom: 15px;
            transition: all 0.2s; text-decoration: none; color: inherit;
        }
        .link-card:hover { border-color: #3b82f6; background: #f8fafc; transform: translateY(-2px); }
        .link-info h3 { margin: 0; color: #334155; }
        .link-id { font-size: 12px; color: #94a3b8; }
        .enter-btn { background: #3b82f6; color: white; padding: 8px 20px; border-radius: 8px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="dashboard">
        <h1>我的云端分享库</h1>
        {% for lid, data in links.items() %}
        <a href="/view/{{ lid }}" class="link-card">
            <div class="link-info">
                <h3>分享 ID: {{ lid }}</h3>
                <span class="link-id">已抓取资源，点击进入查看。</span>
            </div>
            <div class="enter-btn">进入视频库</div>
        </a>
        {% endfor %}
        {% if not links %}
        <p style="color: #64748b;">暂无可用链接，请在 .env 中配置 YUN_LINK_ID。</p>
        {% endif %}
    </div>
</body>
</html>
"""

VIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ link_id }} - 在线预览</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; background: #f8f9fa; display: flex; gap: 20px; height: 95vh; margin: 0; }
        .sidebar { flex: 1; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow-y: auto; }
        .player-area { flex: 1.5; background: #000; border-radius: 12px; overflow: hidden; position: sticky; top: 20px; height: 60vh; border: 4px solid #1e293b; }
        video { width: 100%; height: 100%; }
        h1 { color: #1e293b; font-size: 1.5em; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; }
        .home-link { font-size: 14px; text-decoration: none; color: #3b82f6; font-weight: normal; }
        .folder-section { margin-top: 10px; margin-left: 15px; border-left: 2px solid #e2e8f0; padding-left: 10px; }
        .folder-title { font-size: 0.95em; font-weight: bold; color: #475569; margin-bottom: 5px; display: flex; align-items: center; cursor: pointer; }
        .folder-title::before { content: '📁'; margin-right: 8px; }
        .file-list { list-style: none; padding: 0; margin-left: 15px; }
        .file-item { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; border-radius: 4px; }
        .file-item:hover { background: #f8fafc; }
        .file-name { color: #334155; font-size: 0.85em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 10px; }
        .play-btn { background: #3b82f6; color: white; padding: 4px 10px; border-radius: 4px; cursor: pointer; border: none; font-size: 0.75em; }
        .current-title { color: white; background: rgba(0,0,0,0.8); position: absolute; top: 0; left: 0; right: 0; padding: 12px; font-size: 0.9em; z-index: 10; border-bottom: 1px solid #334155; }
        .empty-hint { color: #94a3b8; font-size: 0.8em; margin-left: 20px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h1>
            <span>资源库 <small style="font-weight: normal; color: #94a3b8; font-size: 0.6em;">{{ link_id }}</small></span>
            <a href="/" class="home-link">返回首页</a>
        </h1>

        {% macro render_tree(node) %}
            {% if node %}
                {# 渲染当前层级的文件 #}
                {% if node.coLst %}
                    <ul class="file-list">
                        {% for file in node.coLst %}
                        <li class="file-item">
                            <span class="file-name">{{ file.coName }}</span>
                            <button class="play-btn" onclick="playVideo('{{ link_id }}', '{{ file.coID }}', '{{ file.coName }}')">播放</button>
                        </li>
                        {% endfor %}
                    </ul>
                {% endif %}

                {# 递归渲染子文件夹 #}
                {% if node.caLst %}
                    {% for sub in node.caLst %}
                    <div class="folder-section">
                        <div class="folder-title">{{ sub.caName }}</div>
                        {{ render_tree(sub.data) }}
                    </div>
                    {% endfor %}
                {% endif %}

                {% if not node.coLst and not node.caLst %}
                    <div class="empty-hint">(空目录)</div>
                {% endif %}
            {% else %}
                <div class="empty-hint">(无数据)</div>
            {% endif %}
        {% endmacro %}

        <div class="root-container">
            {% if results.tree %}
                {{ render_tree(results.tree) }}
            {% else %}
                <div class="empty-hint">该分享未抓取到有效内容，请尝试删除 data 目录后重试。</div>
            {% endif %}
        </div>
    </div>

    <div class="player-area">
        <div id="videoTitle" class="current-title">等待播放...</div>
        <video id="video" controls></video>
    </div>

    <script>
        var video = document.getElementById('video');
        var hls = new Hls();

        function playVideo(lid, coId, coName) {
            document.getElementById('videoTitle').innerText = '正在加载: ' + coName;
            var url = '/play/' + lid + '/' + coId + '/' + encodeURIComponent(coName);
            
            if (Hls.isSupported()) {
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play();
                });
            }
            else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = url;
                video.addEventListener('loadedmetadata', function() {
                    video.play();
                });
            }
        }
    </script>
</body>
</html>
"""

# --- 路由 ---

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML, links=shared_state["links"])

@app.route("/view/<link_id>")
def view_link(link_id):
    if link_id not in shared_state["links"]:
        return "无效的 Link ID", 404
    return render_template_string(VIEW_HTML, link_id=link_id, results=shared_state["links"][link_id])

@app.route("/play/<link_id>/<co_id>/<path:co_name>")
def play_video(link_id, co_id, co_name):
    client = shared_state["client"]
    
    try:
        # 对文件名进行规范化
        base_name = os.path.splitext(co_name)[0]
        safe_filename = "".join([c for c in base_name if ord(c) < 128 or '\u4e00' <= c <= '\u9fff']).strip()
        safe_filename = safe_filename.replace('/', '_').replace('\\', '_')
        safe_filename = f"{safe_filename}.m3u8"
        
        cache_dir = os.path.join("m3u8_downloads", link_id)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        dest_path = os.path.join(cache_dir, safe_filename)
        
        # 缓存检查 (30秒内有效)
        use_cache = False
        if os.path.exists(dest_path):
            if time.time() - os.path.getmtime(dest_path) < 30:
                use_cache = True

        if use_cache:
            print(f"[*] [Cache] 使用本地缓存: {safe_filename}")
            with open(dest_path, "r", encoding="utf-8") as f:
                m3u8_content = f.read()
        else:
            print(f"[*] [Fetch] 正在抓取播放清单: {co_name}")
            m3u8_content = client.get_playlist_m3u8(co_id, link_id)
            if m3u8_content:
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(m3u8_content)

        if m3u8_content:
            filename_encoded = urllib.parse.quote(safe_filename)
            return Response(
                m3u8_content, 
                mimetype='application/vnd.apple.mpegurl',
                headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename_encoded}"}
            )
        return "无法获取播放清单", 404
            
    except Exception as e:
        print(f"❌ 播放请求处理异常: {e}")
        return str(e), 500

# --- 核心逻辑 ---

def recursive_fetch(client, link_id, p_ca_id="root", depth=0, max_depth=3):
    """
    递归抓取目录结构。
    """
    if depth > max_depth:
        return {"caLst": [], "coLst": []}
    
    data = client.get_out_link_info(link_id, p_ca_id=p_ca_id)
    if not data:
        return {"caLst": [], "coLst": []}
    
    folders = data.get("caLst") or []
    files = data.get("coLst") or []
    
    result = {
        "caLst": [],
        "coLst": files
    }
    
    # 限制每一层的文件夹数量，防止请求过多
    for folder in folders[:20]:
        print(f"{'  ' * depth}[*] 抓取层级 {depth}: {folder.get('caName')}")
        sub_tree = recursive_fetch(client, link_id, folder.get("caID"), depth + 1, max_depth)
        result["caLst"].append({
            "caID": folder.get("caID"),
            "caName": folder.get("caName"),
            "data": sub_tree
        })
            
    return result

def fetch_and_save_share_info(client, link_id, output_dir):
    """
    全量递归抓取并保存。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"\n--- 开始全量递归抓取分享: {link_id} ---")
    tree = recursive_fetch(client, link_id, max_depth=3)
    
    full_results = {
        "linkID": link_id,
        "tree": tree
    }
            
    output_file = os.path.join(output_dir, "fetched_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
    
    return full_results

def main():
    load_dotenv()
    ACCOUNT = os.getenv("YUN_ACCOUNT")
    AUTH_TOKEN = os.getenv("YUN_AUTH_TOKEN")
    LINK_IDS = [lid.strip() for lid in os.getenv("YUN_LINK_ID", "").split(",") if lid.strip()]
    SIGN = os.getenv("YUN_SIGN")
    SKEY = os.getenv("YUN_SKEY")

    if not all([ACCOUNT, AUTH_TOKEN, LINK_IDS]):
        print("❌ 错误: .env 参数不足。")
        return

    client = YunClient(AUTH_TOKEN, ACCOUNT)
    if SIGN and SKEY:
        client.set_signatures(SIGN, SKEY)
    
    shared_state["client"] = client

    # 初始化 Link 数据
    if not os.path.exists("data"):
        os.makedirs("data")

    for lid in LINK_IDS:
        link_dir = os.path.join("data", lid)
        link_file = os.path.join(link_dir, "fetched_results.json")
        
        if os.path.exists(link_file):
            with open(link_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 校验缓存格式是否包含最新的 tree 结构
            if "tree" in data:
                print(f"✅ [Local] 发现本地缓存 ({lid})，跳过抓取。")
                shared_state["links"][lid] = data
            else:
                print(f"⚠️ [Local] 缓存格式已过期 ({lid})，重新执行深度递归抓取...")
                results = fetch_and_save_share_info(client, lid, link_dir)
                if results:
                    shared_state["links"][lid] = results
        else:
            print(f"🌐 [Online] 本地无数据 ({lid})，开始深度递归抓取...")
            results = fetch_and_save_share_info(client, lid, link_dir)
            if results:
                shared_state["links"][lid] = results

    print("\n" + "="*40)
    print(f"🚀 Web 服务就绪! 管理资源: {len(shared_state['links'])} 个分享链接")
    print("📍 访问地址: http://127.0.0.1:5000")
    print("="*40 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == "__main__":
    main()
