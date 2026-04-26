import os
import json
import time
import threading
import urllib.parse
from datetime import datetime
from collections import deque
from dotenv import load_dotenv
from yun_client import YunClient
from flask import Flask, render_template_string, Response, request, redirect, url_for

app = Flask(__name__)

# 全局共享状态
shared_state = {
    "client": None,
    "links": {},  # link_id -> full_results
    "logs": deque(maxlen=100) # 存储最近100条日志
}

def log_msg(msg, event_type="log", **kwargs):
    """通用日志函数，支持结构化事件"""
    now = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{now}] {msg}"
    print(formatted)
    event = {"type": event_type, "content": formatted}
    event.update(kwargs)
    shared_state["logs"].append(event)

def get_tree_size(node):
    """递归计算目录树总大小"""
    size = 0
    if not node:
        return 0
    for file in node.get("coLst", []):
        size += file.get("coSize", 0)
    for sub in node.get("caLst", []):
        size += get_tree_size(sub.get("data", {}))
    return size

def format_size(size_bytes):
    """将字节转换为人类可读格式"""
    if size_bytes == 0:
        return "0 B"
    import math
    size_name = ("B", "KB", "MB", "GB", "TB", "PB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])

def update_links_config(link_id, ca_name):
    """自动将发现的资源名称回写到 links.json"""
    if not os.path.exists("links.json"):
        return
    try:
        with open("links.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            return
        
        current_info = config.get(link_id, {})
        # 如果名称缺失，或者是默认的 ID，则更新它
        if not current_info.get("caName") or current_info.get("caName") == link_id:
            config[link_id] = {"caName": ca_name}
            with open("links.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"✨ [Config] 已自动在 links.json 中补全名称: {ca_name}")
    except Exception as e:
        print(f"⚠️ [Config] 更新 links.json 失败: {e}")

def get_share_name_from_results(results):
    """从抓取结果中提取人类可读的资源名称"""
    tree = results.get("tree", {})
    if not tree: return None
    if tree.get("caLst"):
        return tree["caLst"][0].get("caName")
    if tree.get("coLst"):
        return tree["coLst"][0].get("coName")
    return None

# --- HTML 模板 ---

DASHBOARD_HTML = r"""
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
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px;">
            <h1 style="margin: 0;">我的云端分享库</h1>
            <div style="text-align: right;">
                <div style="font-size: 13px; color: #94a3b8; font-weight: 500;">库总大小：</div>
                <div style="font-size: 22px; font-weight: 800; color: #3b82f6; letter-spacing: -0.5px;">{{ total_size }}</div>
            </div>
        </div>
        <p style="color: #64748b; font-size: 14px; margin: -10px 0 30px 0; font-style: italic; border-left: 3px solid #3b82f6; padding-left: 12px; line-height: 1.6;">
            “独乐乐不如众乐乐 —— 欢迎分享<strong>永久有效</strong>的优质 Link ID，共建海量云端影院。”
        </p>

        <!-- 搜索入口 -->
        <div class="search-section" style="margin-bottom: 25px;">
            <form action="/search" method="GET" style="display: flex; gap: 10px;">
                <input type="text" name="q" placeholder="输入关键词搜索全库资源 (如: 异形, 4K)..." required 
                       style="flex: 1; padding: 12px 15px; border-radius: 10px; border: 1px solid #e2e8f0; outline: none; font-size: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                <button type="submit" style="background: #3b82f6; color: white; border: none; padding: 10px 30px; border-radius: 10px; font-weight: bold; cursor: pointer; transition: all 0.2s;">
                    全库搜索
                </button>
            </form>
        </div>

        <!-- 添加入口 -->
        <div style="background: #f8fafc; padding: 20px; border-radius: 12px; border: 2px dashed #e2e8f0; margin-bottom: 20px;">
            <div style="font-size: 13px; color: #64748b; margin-bottom: 15px; font-weight: bold;">远程抓取：</div>
            <form id="add-form" style="display: flex; gap: 10px; margin-bottom: 20px;">
                <input type="text" id="link-id-input" name="link_id" placeholder="粘贴分享 ID 或完整链接" required 
                       style="flex: 1; padding: 10px 15px; border-radius: 8px; border: 1px solid #cbd5e1; outline: none; font-size: 14px;">
                <button type="submit" style="background: #10b981; color: white; border: none; padding: 10px 25px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.2s;">
                    开始抓取
                </button>
            </form>
            
            <div style="border-top: 1px solid #e2e8f0; padding-top: 15px;">
                <div style="font-size: 13px; color: #64748b; margin-bottom: 10px; font-weight: bold;">本地导入 (fetched_results.json)：</div>
                <form id="upload-form" enctype="multipart/form-data" style="display: flex; align-items: center; gap: 10px;">
                    <input type="file" name="file" accept=".json" required style="font-size: 12px; color: #64748b; flex: 1;">
                    <button type="submit" style="background: #6366f1; color: white; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; cursor: pointer;">
                        上传并导入
                    </button>
                </form>
            </div>
        </div>

        <div id="links-container">
            {% for lid, data in links.items() %}
            {% set share_name = data.tree.caLst[0].caName if (data.tree and data.tree.caLst and data.tree.caLst|length > 0) else (data.tree.coLst[0].coName if (data.tree and data.tree.coLst and data.tree.coLst|length > 0) else lid) %}
            <a href="/view/{{ lid }}" class="link-card" id="card-{{ lid }}">
                <div class="link-info">
                    <h3>{{ share_name }}</h3>
                    <span class="link-id">分享 ID: {{ lid }}</span>
                </div>
                <div class="enter-btn">进入视频库</div>
            </a>
            {% endfor %}
        </div>
        {% if not links %}
        <p style="color: #64748b;">暂无可用链接，请在首页添加或在 links.json 中配置。</p>
        {% endif %}

        <!-- 实时日志显示 -->
        <div class="logs-section" style="margin-top: 40px; background: #020617; border-radius: 12px; padding: 20px; color: #f8fafc; font-family: 'Consolas', 'Monaco', monospace; font-size: 14px; border: 1px solid #1e293b; box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 1px solid #1e293b; padding-bottom: 10px;">
                <h2 style="color: #38bdf8; font-size: 14px; margin: 0; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 8px; height: 8px; background: #10b981; border-radius: 50%; display: inline-block; box-shadow: 0 0 10px #10b981; animation: pulse 2s infinite;"></span>
                    实时抓取终端
                </h2>
                <span style="font-size: 11px; color: #475569; font-weight: bold; letter-spacing: 1px;">STATUS: ACTIVE</span>
            </div>
            <div id="log-container" style="height: 250px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 10px; scroll-behavior: smooth;">
                <div style="color: #475569; font-style: italic;">等待系统就绪...</div>
            </div>
        </div>
    </div>

    <style>
        @keyframes pulse {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.2); }
            100% { opacity: 1; transform: scale(1); }
        }
        #log-container::-webkit-scrollbar { width: 6px; }
        #log-container::-webkit-scrollbar-track { background: transparent; }
        #log-container::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 10px; }
        @keyframes highlight {
            0% { background: #10b98133; border-color: #10b981; }
            100% { background: transparent; border-color: #e2e8f0; }
        }
    </style>

    <script>
        const logContainer = document.getElementById('log-container');
        const linksContainer = document.getElementById('links-container');
        
        // 处理表单异步提交
        document.getElementById('add-form').onsubmit = async (e) => {
            e.preventDefault();
            const input = document.getElementById('link-id-input');
            const linkId = input.value.trim();
            if (!linkId) return;
            
            try {
                const response = await fetch('/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `link_id=${encodeURIComponent(linkId)}`
                });
                if (response.ok) {
                    input.value = '';
                } else {
                    const err = await response.text();
                    alert('添加失败: ' + err);
                }
            } catch (err) {
                alert('网络错误');
            }
        };

        // 使用 EventSource 接收实时日志和完成事件
        const source = new EventSource("/stream");
        source.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            if (data.type === 'log') {
                const div = document.createElement('div');
                div.style.lineHeight = '1.6';
                div.style.wordBreak = 'break-all';
                
                const content = data.content;
                const timeMatch = content.match(/^(\[.*?\])\s(.*)/);
                
                if (timeMatch) {
                    div.innerHTML = `<span style="color: #6366f1; font-weight: bold; margin-right: 8px;">${timeMatch[1]}</span><span style="color: #e2e8f0;">${timeMatch[2]}</span>`;
                } else {
                    div.innerHTML = `<span style="color: #e2e8f0;">${content}</span>`;
                }
                
                logContainer.appendChild(div);
                logContainer.scrollTop = logContainer.scrollHeight;
            } 
            else if (data.type === 'done') {
                // 动态添加卡片到列表
                if (!document.getElementById('card-' + data.link_id)) {
                    const card = document.createElement('a');
                    card.href = '/view/' + data.link_id;
                    card.className = 'link-card';
                    card.id = 'card-' + data.link_id;
                    card.innerHTML = `
                        <div class="link-info">
                            <h3>${data.name}</h3>
                            <span class="link-id">分享 ID: ${data.link_id}</span>
                        </div>
                        <div class="enter-btn">进入视频库</div>
                    `;
                    linksContainer.prepend(card);
                    
                    // 闪烁提醒一下
                    card.style.animation = 'highlight 2s ease';
                }
            }
        };

        // 处理上传表单
        document.getElementById('upload-form').onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.disabled = true;
            btn.innerText = '上传中...';
            
            const appendLog = (msg, isError = false) => {
                const div = document.createElement('div');
                div.style.color = isError ? '#f87171' : '#fbbf24';
                div.style.lineHeight = '1.6';
                div.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
                logContainer.appendChild(div);
                logContainer.scrollTop = logContainer.scrollHeight;
            };

            try {
                const res = await fetch('/upload', {
                    method: 'POST',
                    body: new FormData(e.target)
                });
                if (!res.ok) {
                    const err = await res.text();
                    appendLog(`❌ 导入失败: ${err}`, true);
                    alert('导入失败: ' + err);
                } else {
                    appendLog('✅ 导入成功，正在刷新页面...');
                    setTimeout(() => window.location.reload(), 1000);
                }
            } catch (err) {
                appendLog(`❌ 网络异常: ${err}`, true);
            } finally {
                btn.disabled = false;
                btn.innerText = '上传并导入';
            }
        };
    </script>
</body>
</html>
"""

SEARCH_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>搜索结果 - {{ query }}</title>
    <style>
        body { font-family: -apple-system, sans-serif; padding: 40px; background: #f0f2f5; }
        .container { max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 16px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        h1 { color: #1e293b; margin-bottom: 20px; font-size: 24px; }
        .search-stats { color: #64748b; font-size: 14px; margin-bottom: 30px; }
        .result-item { 
            padding: 15px; border-bottom: 1px solid #f1f5f9; 
            display: flex; justify-content: space-between; align-items: center;
        }
        .result-item:hover { background: #f8fafc; }
        .res-main h4 { margin: 0; color: #334155; font-size: 16px; }
        .res-path { font-size: 12px; color: #94a3b8; margin-top: 4px; }
        .res-badge { 
            font-size: 10px; padding: 2px 6px; border-radius: 4px; 
            margin-right: 8px; text-transform: uppercase; font-weight: bold;
        }
        .badge-file { background: #dcfce7; color: #166534; }
        .badge-folder { background: #dbeafe; color: #1e40af; }
        .action-btn { 
            text-decoration: none; color: #3b82f6; font-size: 14px; font-weight: 600;
            padding: 6px 12px; border: 1px solid #3b82f6; border-radius: 6px;
        }
        .action-btn:hover { background: #3b82f6; color: white; }
        .no-results { text-align: center; padding: 50px; color: #94a3b8; }
        .back-link { margin-bottom: 20px; display: inline-block; color: #3b82f6; text-decoration: none; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">← 返回首页</a>
        <h1>搜索: "{{ query }}"</h1>
        <div class="search-stats">找到 {{ results|length }} 个相关资源</div>

        {% for res in results %}
        <div class="result-item">
            <div class="res-main">
                <h4>
                    <span class="res-badge {{ 'badge-file' if res.type == 'file' else 'badge-folder' }}">
                        {{ '文件' if res.type == 'file' else '文件夹' }}
                    </span>
                    {{ res.name }}
                </h4>
                <div class="res-path">
                    来自: <strong style="color: #64748b;">{{ res.share_name }}</strong> 
                    {% if res.path %} > {{ res.path }}{% endif %}
                </div>
            </div>
            <div>
        {% if res.type == 'file' %}
            <a href="/view/{{ res.link_id }}?play={{ res.id }}&name={{ res.name|urlencode }}" class="action-btn">立即播放</a>
        {% else %}
            <a href="/view/{{ res.link_id }}#folder-{{ res.id }}" class="action-btn">定位文件夹</a>
        {% endif %}
            </div>
        </div>
        {% endfor %}

        {% if not results %}
        <div class="no-results">
            <div style="font-size: 48px; margin-bottom: 10px;">🔍</div>
            <p>未找到匹配 "{{ query }}" 的资源</p>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

VIEW_HTML = r"""
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
            {% set share_name = results.tree.caLst[0].caName if (results.tree and results.tree.caLst and results.tree.caLst|length > 0) else (results.tree.coLst[0].coName if (results.tree and results.tree.coLst and results.tree.coLst|length > 0) else link_id) %}
            <span>{{ share_name }} <small style="font-weight: normal; color: #94a3b8; font-size: 0.6em;">{{ link_id }}</small></span>
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
                    <div class="folder-section" id="folder-{{ sub.caID }}">
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

        // 处理自动播放 (来自搜索结果)
        window.onload = function() {
            // 1. 检查播放参数
            const urlParams = new URLSearchParams(window.location.search);
            const playId = urlParams.get('play');
            const playName = urlParams.get('name');
            if (playId && playName) {
                playVideo('{{ link_id }}', playId, decodeURIComponent(playName));
            }

            // 2. 检查位置哈希 (用于定位文件夹)
            if (window.location.hash) {
                const targetId = window.location.hash.substring(1);
                const el = document.getElementById(targetId);
                if (el) {
                    setTimeout(() => {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        el.style.background = '#fef9c3'; // 黄色背景高亮
                        el.style.transition = 'background 2s';
                        setTimeout(() => el.style.background = 'transparent', 2000);
                    }, 500);
                }
            }
        };
    </script>
</body>
</html>
"""

# --- 路由 ---

@app.route("/")
def dashboard():
    total_bytes = 0
    for lid in shared_state["links"]:
        tree = shared_state["links"][lid].get("tree", {})
        total_bytes += get_tree_size(tree)
    
    return render_template_string(
        DASHBOARD_HTML, 
        links=shared_state["links"], 
        total_size=format_size(total_bytes)
    )

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return redirect("/")
    
    all_results = []
    
    def search_recursive(node, q, share_id, share_name, current_path=""):
        results = []
        # 搜索文件
        for file in node.get("coLst", []):
            if q.lower() in file.get("coName", "").lower():
                results.append({
                    "type": "file",
                    "name": file["coName"],
                    "id": file["coID"],
                    "link_id": share_id,
                    "share_name": share_name,
                    "path": current_path
                })
        # 搜索文件夹
        for folder in node.get("caLst", []):
            if q.lower() in folder.get("caName", "").lower():
                results.append({
                    "type": "folder",
                    "name": folder["caName"],
                    "id": folder["caID"],
                    "link_id": share_id,
                    "share_name": share_name,
                    "path": current_path
                })
            # 递归子目录
            results.extend(search_recursive(folder.get("data", {}), q, share_id, share_name, f"{current_path}/{folder['caName']}" if current_path else folder['caName']))
        return results

    for lid, data in shared_state["links"].items():
        share_name = get_share_name_from_results(data) or lid
        tree = data.get("tree", {})
        all_results.extend(search_recursive(tree, query, lid, share_name))
    
    return render_template_string(SEARCH_HTML, query=query, results=all_results)

@app.route("/stream")
def stream():
    """SSE 实时推送日志"""
    def event_stream():
        last_idx = len(shared_state["logs"])
        # 先推一次历史日志
        for log in list(shared_state["logs"]):
            yield f"data: {json.dumps({'type': 'log', 'content': log})}\n\n"
        
        while True:
            if len(shared_state["logs"]) > last_idx:
                for i in range(last_idx, len(shared_state["logs"])):
                    event = shared_state["logs"][i]
                    yield f"data: {json.dumps(event)}\n\n"
                last_idx = len(shared_state["logs"])
            time.sleep(0.5)
            
    return Response(event_stream(), mimetype="text/event-stream")

def background_fetch(client, link_id):
    """后台抓取任务"""
    link_dir = os.path.join("data", link_id)
    results = fetch_and_save_share_info(client, link_id, link_dir)
    if results:
        shared_state["links"][link_id] = results

@app.route("/add", methods=["POST"])
def add_link():
    raw_input = request.form.get("link_id", "").strip()
    if not raw_input:
        return "ID 或链接不能为空", 400
    
    # 自动从 URL 中提取 ID
    link_id = raw_input
    if "yun.139.com" in raw_input or raw_input.startswith("http"):
        clean_url = raw_input.split("?")[0].rstrip("/")
        link_id = clean_url.split("/")[-1]
        log_msg(f"🔗 [Parser] 从 URL 中识别到 Link ID: {link_id}")

    if link_id in shared_state["links"]:
        return "该链接已存在", 400
    
    # 0. 同步校验 ID 有效性 (防止非法 ID 或账号错误写入配置)
    client = shared_state["client"]
    try:
        log_msg(f"🔍 [Check] 正在校验 ID 有效性: {link_id}...")
        test_data = client.get_out_link_info(link_id, p_ca_id="root")
        if not test_data:
            return "无法获取链接信息，请检查 ID 是否正确", 400
    except Exception as e:
        err_msg = str(e)
        if "业务错误" in err_msg:
            return f"校验失败: {err_msg.split(' - ')[1]}", 400
        return f"校验请求异常: {err_msg}", 400

    # 1. 校验通过后，才写入 links.json
    try:
        config = {}
        if os.path.exists("links.json"):
            with open("links.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        if not isinstance(config, dict): config = {}
        
        if link_id not in config:
            config[link_id] = {}
            with open("links.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_msg(f"❌ 更新 links.json 失败: {e}")

    # 2. 异步启动深度后台抓取
    log_msg(f"🌐 [Web] 校验通过，已启动后台深度抓取...")
    thread = threading.Thread(target=background_fetch, args=(client, link_id))
    thread.daemon = True
    thread.start()
        
    return {"status": "ok"}

@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' not in request.files:
        return "没有文件", 400
    file = request.files['file']
    if file.filename == '':
        return "未选择文件", 400
    
    try:
        # 读取并解析 JSON
        data = json.load(file)
        link_id = data.get("linkID")
        if not link_id or "tree" not in data:
            return "JSON 格式不正确 (必须包含 linkID 和 tree)", 400
            
        # 0. 查重逻辑
        if link_id in shared_state["links"]:
            return f"导入失败：ID {link_id} 已存在于库中", 400

        # 1. 建立目录并保存
        link_dir = os.path.join("data", link_id)
        if not os.path.exists(link_dir):
            os.makedirs(link_dir)
            
        output_path = os.path.join(link_dir, "fetched_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        # 2. 更新 links.json 配置
        name = get_share_name_from_results(data)
        if name:
            update_links_config(link_id, name)
            
        # 3. 更新内存状态
        shared_state["links"][link_id] = data
        log_msg(f"📥 [Import] 成功从本地文件导入分享: {link_id} ({name or '未知名称'})")
        
        return redirect("/")
    except Exception as e:
        return f"导入失败: {e}", 400

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

def recursive_fetch(client, link_id, p_ca_id="root", depth=0, max_depth=3, save_cb=None):
    """
    递归抓取目录结构，支持增量保存。
    """
    if depth > max_depth:
        return {"caLst": [], "coLst": []}
    
    try:
        data = client.get_out_link_info(link_id, p_ca_id=p_ca_id)
        if not data:
            return {"caLst": [], "coLst": []}
        
        folders = data.get("caLst") or []
        files = data.get("coLst") or []
        
        result = {
            "caLst": [],
            "coLst": files
        }
        
        # 打印当前层级信息
        ca_name = "Root" if p_ca_id == "root" else (folders[0].get("caName") if folders else "Subfolder")
        log_msg(f"[*] 层级 {depth}: {ca_name} (文件夹:{len(folders)}, 文件:{len(files)})")

        # 遍历所有文件夹 (移除 [:20] 限制，增加请求间隔)
        count = 0
        for folder in folders:
            count += 1
            if count % 10 == 0:
                log_msg(f"    - 正在处理 {ca_name} 的第 {count}/{len(folders)} 个文件夹...")
            
            # 添加小延迟，防止频率过高被封
            time.sleep(2)
            
            sub_tree = recursive_fetch(client, link_id, folder.get("caID"), depth + 1, max_depth, save_cb)
            result["caLst"].append({
                "caID": folder.get("caID"),
                "caName": folder.get("caName"),
                "data": sub_tree
            })
            
            # 增量保存：每抓完一个子文件夹就存一次盘
            if save_cb:
                save_cb()
                
        return result
    except Exception as e:
        log_msg(f"❌ 抓取失败 (ID: {link_id}): {e}")
        return {"caLst": [], "coLst": []}

def fetch_and_save_share_info(client, link_id, output_dir):
    """
    全量递归抓取并保存，支持断点保护。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    log_msg(f"开始全量递归抓取分享: {link_id}")
    
    # 构造初始结果对象
    full_results = {
        "linkID": link_id,
        "tree": {}
    }
    
    output_file = os.path.join(output_dir, "fetched_results.json")
    
    def save_progress():
        """闭包函数：将当前内存中的 full_results 写入磁盘"""
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(full_results, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 增量保存失败: {e}")

    # 执行抓取，传入保存回调
    tree = recursive_fetch(client, link_id, max_depth=3, save_cb=save_progress)
    
    # 检查是否真的抓到了内容
    if not tree.get("caLst") and not tree.get("coLst"):
        log_msg(f"⚠️ 分享 {link_id} 未抓取到任何内容 (可能 ID 错误或账号受限)。", event_type="error")
        # 如果是空的，清理掉创建的目录
        if os.path.exists(output_dir) and not os.listdir(output_dir):
            try: os.rmdir(output_dir)
            except: pass
        return None

    full_results["tree"] = tree
    save_progress()
    
    # 自动更新配置中的名称
    name = get_share_name_from_results(full_results)
    if name:
        update_links_config(link_id, name)
    
    log_msg(f"✅ 分享 {link_id} 抓取完成并已保存。", event_type="done", link_id=link_id, name=name or link_id)
    return full_results

def main():
    load_dotenv()
    ACCOUNT = os.getenv("YUN_ACCOUNT")
    AUTH_TOKEN = os.getenv("YUN_AUTH_TOKEN")
    # 加载分享链接 ID 列表
    LINK_IDS = []
    if os.path.exists("links.json"):
        try:
            with open("links.json", "r", encoding="utf-8") as f:
                config_data = json.load(f)
                if isinstance(config_data, list):
                    LINK_IDS = config_data
                elif isinstance(config_data, dict):
                    LINK_IDS = list(config_data.keys())
            print(f"📂 [Config] 从 links.json 加载了 {len(LINK_IDS)} 个链接")
        except Exception as e:
            print(f"⚠️ [Config] 读取 links.json 失败: {e}")
    
    if not LINK_IDS:
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
                # 检查并补全配置中的名称
                name = get_share_name_from_results(data)
                if name:
                    update_links_config(lid, name)
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
    
    app.run(host='0.0.0.0', port=5000, debug=True   )

if __name__ == "__main__":
    main()
