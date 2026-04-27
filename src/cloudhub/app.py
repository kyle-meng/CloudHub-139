import os
import json
import time
import threading
import urllib.parse
from datetime import datetime
from collections import deque
from dotenv import load_dotenv
from .client import YunClient
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
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>云资源管理 - 概览</title>
    <style>
        :root {
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --success: #10b981;
            --success-hover: #059669;
            --warning: #f59e0b;
            --danger: #ef4444;
            --bg-body: #f1f5f9;
            --bg-card: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-light: #e2e8f0;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.1);
            --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
            --shadow-lg: 0 10px 25px -3px rgba(0,0,0,0.05);
            --radius-md: 10px;
            --radius-lg: 16px;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
            padding: 40px 20px; 
            background: var(--bg-body); 
            color: var(--text-main);
            line-height: 1.5;
        }

        .container { 
            max-width: 880px; 
            margin: auto; 
            background: var(--bg-card); 
            padding: 40px; 
            border-radius: var(--radius-lg); 
            box-shadow: var(--shadow-lg); 
        }

        /* --- Header --- */
        .header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid var(--border-light);
        }
        .header h1 { 
            font-size: 28px; font-weight: 800; letter-spacing: -0.5px;
            background: linear-gradient(135deg, #0f172a 0%, var(--primary) 100%); 
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
        }
        .stat-box { text-align: right; }
        .stat-label { font-size: 13px; color: var(--text-muted); font-weight: 500; margin-bottom: 2px; }
        .stat-value { font-size: 24px; font-weight: 800; color: var(--primary); letter-spacing: -0.5px; }

        .subtitle {
            color: var(--text-muted); font-size: 14px; margin-bottom: 25px; 
            font-style: italic; border-left: 4px solid var(--primary); 
            padding-left: 12px; line-height: 1.6; background: #f8fafc; padding-top: 8px; padding-bottom: 8px; border-radius: 0 8px 8px 0;
        }

        /* --- Tags --- */
        .tags-wrapper { display: flex; gap: 12px; margin-bottom: 35px; flex-wrap: wrap; }
        .tag {
            padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 600; 
            display: flex; align-items: center; gap: 6px; box-shadow: var(--shadow-sm);
        }
        .tag-blue { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
        .tag-green { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
        .tag-pink { background: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; }

        /* --- Action Controls (Grid) --- */
        .action-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px;
        }
        .action-card {
            background: #f8fafc; padding: 20px; border-radius: var(--radius-md); 
            border: 1px solid var(--border-light);
        }
        .action-title { font-size: 14px; color: var(--text-main); margin-bottom: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px;}
        
        /* Forms & Inputs */
        .form-group { display: flex; gap: 10px; margin-bottom: 15px; }
        .form-group:last-child { margin-bottom: 0; }
        
        input[type="text"] {
            flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid #cbd5e1; 
            outline: none; font-size: 14px; transition: all 0.2s; width: 100%;
        }
        input[type="text"]:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
        
        button {
            padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; 
            transition: all 0.2s; border: none; font-size: 14px; white-space: nowrap;
        }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-hover); transform: translateY(-1px); }
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { background: var(--success-hover); transform: translateY(-1px); }
        .btn-outline { background: white; color: #6366f1; border: 1px solid #6366f1; }
        .btn-outline:hover { background: #e0e7ff; }

        .divider { border-top: 1px dashed #cbd5e1; margin: 15px 0; }
        input[type="file"] { font-size: 13px; color: var(--text-muted); flex: 1; }
        input[type="file"]::file-selector-button {
            padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-light);
            background: white; color: var(--text-main); cursor: pointer; font-size: 12px; margin-right: 10px; transition: 0.2s;
        }
        input[type="file"]::file-selector-button:hover { background: #f1f5f9; }

        /* --- Terminal Logs (Popup Modal Style) --- */
        .logs-section {
            display: none; /* 默认隐藏 */
            margin-bottom: 35px; background: #0f172a; border-radius: var(--radius-md); 
            padding: 20px; color: #f8fafc; font-family: 'Consolas', 'Monaco', monospace; 
            font-size: 13px; border: 1px solid #1e293b; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3), inset 0 2px 10px rgba(0,0,0,0.5);
        }
        .terminal-show {
            display: block;
            animation: slideDownFade 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        @keyframes slideDownFade {
            0% { opacity: 0; transform: translateY(-10px); }
            100% { opacity: 1; transform: translateY(0); }
        }

        .log-header {
            display: flex; justify-content: space-between; align-items: center; 
            margin-bottom: 15px; border-bottom: 1px solid #1e293b; padding-bottom: 12px;
        }
        .log-title { color: #38bdf8; font-size: 14px; margin: 0; display: flex; align-items: center; gap: 8px; font-weight: 600; }
        .status-badge { font-size: 11px; color: #475569; font-weight: bold; letter-spacing: 1px; background: #1e293b; padding: 4px 8px; border-radius: 4px;}
        
        .close-terminal-btn {
            background: transparent; border: none; color: #94a3b8; font-size: 18px; 
            line-height: 1; cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: 0.2s;
        }
        .close-terminal-btn:hover { background: #1e293b; color: #f8fafc; }

        #log-container {
            height: 200px; overflow-y: auto; display: flex; flex-direction: column; 
            gap: 6px; padding-right: 10px; scroll-behavior: smooth;
        }
        #log-container::-webkit-scrollbar { width: 6px; }
        #log-container::-webkit-scrollbar-track { background: transparent; }
        #log-container::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
        #log-container::-webkit-scrollbar-thumb:hover { background: #475569; }

        /* --- Link Cards --- */
        .section-title { font-size: 18px; margin-bottom: 15px; font-weight: 700; color: #1e293b; }
        .links-container { display: flex; flex-direction: column; gap: 12px; }
        
        .link-card { 
            display: flex; justify-content: space-between; align-items: center;
            padding: 18px 20px; border: 1px solid var(--border-light); border-radius: var(--radius-md); 
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); text-decoration: none; color: inherit; background: white;
        }
        .link-card:hover { 
            border-color: var(--primary); background: #f8fafc; 
            transform: translateY(-2px); box-shadow: var(--shadow-md);
        }
        .link-info h3 { margin: 0 0 4px 0; color: #334155; font-size: 16px; font-weight: 600; }
        .link-id { font-size: 13px; color: var(--text-muted); font-family: ui-monospace, monospace; }
        .enter-btn { 
            background: #eff6ff; color: var(--primary); padding: 8px 16px; 
            border-radius: 6px; font-weight: 600; font-size: 13px; transition: 0.2s;
        }
        .link-card:hover .enter-btn { background: var(--primary); color: white; }

        .empty-state { padding: 30px; text-align: center; color: var(--text-muted); background: #f8fafc; border-radius: var(--radius-md); border: 1px dashed #cbd5e1; }

        /* Animations */
        @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(1.2); } 100% { opacity: 1; transform: scale(1); } }
        .dot-pulse { width: 8px; height: 8px; background: var(--success); border-radius: 50%; display: inline-block; box-shadow: 0 0 10px var(--success); animation: pulse 2s infinite; }
        @keyframes highlight { 0% { background: #10b98122; border-color: var(--success); transform: scale(1.02); } 100% { background: white; border-color: var(--border-light); transform: scale(1); } }

        /* Responsive */
        @media (max-width: 768px) {
            .action-grid { grid-template-columns: 1fr; }
            .container { padding: 25px 20px; margin: 0; border-radius: 0; box-shadow: none; }
            body { padding: 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>139 云影聚合中心</h1>
            <div class="stat-box">
                <div class="stat-label">库总大小</div>
                <div class="stat-value">{{ total_size }}</div>
            </div>
        </header>

        <div class="subtitle">
            “独乐乐不如众乐乐 —— 欢迎分享<strong>永久有效</strong>的优质 Link ID，共建海量云端影院。”
        </div>

        <div class="tags-wrapper">
            <span class="tag tag-blue">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path></svg>
                无需转存
            </span>
            <span class="tag tag-green">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"></path></svg>
                不占空间
            </span>
            <span class="tag tag-pink">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
                链接挂载播放
            </span>
        </div>

        <div class="action-grid">
            <div class="action-card">
                <div class="action-title">
                    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                    全库检索
                </div>
                <form action="/search" method="GET" class="form-group" style="flex-direction: column;">
                    <input type="text" name="q" placeholder="输入关键词 (如: 异形, 4K)..." required>
                    <button type="submit" class="btn-primary" style="width: 100%;">全库搜索</button>
                </form>
            </div>

            <div class="action-card">
                <div class="action-title">
                    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"></path></svg>
                    添加资源
                </div>
                <form id="add-form" class="form-group">
                    <input type="text" id="link-id-input" name="link_id" placeholder="粘贴分享 ID/链接" required>
                    <button type="submit" class="btn-success">抓取</button>
                </form>
                
                <div class="divider"></div>
                
                <form id="upload-form" enctype="multipart/form-data" class="form-group">
                    <input type="file" name="file" accept=".json" required>
                    <button type="submit" class="btn-outline">导入本地 JSON</button>
                </form>
            </div>
        </div>

        <div id="terminal-popup" class="logs-section">
            <div class="log-header">
                <h2 class="log-title">
                    <span class="dot-pulse"></span>
                    实时抓取终端
                </h2>
                <div style="display: flex; align-items: center; gap: 15px;">
                    <span class="status-badge">STATUS: ACTIVE</span>
                    <button class="close-terminal-btn" onclick="hideTerminal()">×</button>
                </div>
            </div>
            <div id="log-container">
                <div style="color: #475569; font-style: italic; font-family: inherit;">等待系统就绪...</div>
            </div>
        </div>

        <h2 class="section-title">已收录的视频库</h2>
        <div id="links-container" class="links-container">
            {% for lid, data in links.items() %}
            {% set share_name = data.tree.caLst[0].caName if (data.tree and data.tree.caLst and data.tree.caLst|length > 0) else (data.tree.coLst[0].coName if (data.tree and data.tree.coLst and data.tree.coLst|length > 0) else lid) %}
            <a href="/view/{{ lid }}" class="link-card" id="card-{{ lid }}">
                <div class="link-info">
                    <h3>{{ share_name }}</h3>
                    <span class="link-id">ID: {{ lid }}</span>
                </div>
                <div class="enter-btn">进入视频库</div>
            </a>
            {% endfor %}
        </div>
        {% if not links %}
        <div class="empty-state">
            <svg width="40" height="40" style="margin: 0 auto 10px auto; color: #cbd5e1;" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path></svg>
            <p>暂无可用链接，请在上方添加抓取或导入 JSON 数据。</p>
        </div>
        {% endif %}
    </div>

    <script>
        const terminalPopup = document.getElementById('terminal-popup');
        const logContainer = document.getElementById('log-container');
        const linksContainer = document.getElementById('links-container');
        
        // 展开与隐藏终端的快捷函数
        function showTerminal(initialMessage) {
            terminalPopup.classList.add('terminal-show');
            logContainer.innerHTML = `<div style="color: #475569; font-style: italic; font-family: inherit;">${initialMessage}</div>`;
        }
        function hideTerminal() {
            terminalPopup.classList.remove('terminal-show');
        }

        // 处理添加表单
        document.getElementById('add-form').onsubmit = async (e) => {
            e.preventDefault();
            const input = document.getElementById('link-id-input');
            const linkId = input.value.trim();
            if (!linkId) return;
            
            // 点击后展开终端
            showTerminal('开始建立连接并初始化抓取...');
            
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

        // 处理实时日志
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
                // 如果空状态存在，移除它
                const emptyState = document.querySelector('.empty-state');
                if (emptyState) emptyState.remove();

                // 打印完成信息
                const finishMsg = document.createElement('div');
                finishMsg.style.lineHeight = '1.6';
                finishMsg.innerHTML = `<br><span style="color: #10b981; font-weight: bold; font-size: 14px;">✓ 抓取完成，资源已入库，即将自动收起...</span>`;
                logContainer.appendChild(finishMsg);
                logContainer.scrollTop = logContainer.scrollHeight;

                // 动态插入卡片
                if (!document.getElementById('card-' + data.link_id)) {
                    const card = document.createElement('a');
                    card.href = '/view/' + data.link_id;
                    card.className = 'link-card';
                    card.id = 'card-' + data.link_id;
                    card.innerHTML = `
                        <div class="link-info">
                            <h3>${data.name}</h3>
                            <span class="link-id">ID: ${data.link_id}</span>
                        </div>
                        <div class="enter-btn">进入视频库</div>
                    `;
                    linksContainer.prepend(card);
                    
                    card.style.animation = 'highlight 2s ease';
                }

                // 延迟 3 秒后自动隐藏终端
                setTimeout(() => {
                    hideTerminal();
                }, 3000);
            }
        };

        // 处理本地导入表单
        document.getElementById('upload-form').onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.disabled = true;
            const originalText = btn.innerText;
            btn.innerText = '上传中...';
            
            // 点击后展开终端
            showTerminal('准备导入本地 JSON 文件...');

            const appendLog = (msg, isError = false) => {
                const div = document.createElement('div');
                div.style.color = isError ? '#f87171' : '#10b981';
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
                    appendLog('✅ 导入成功，界面即将刷新...');
                    setTimeout(() => window.location.reload(), 1500);
                }
            } catch (err) {
                appendLog(`❌ 网络异常: ${err}`, true);
            } finally {
                btn.disabled = false;
                btn.innerText = originalText;
            }
        };
    </script>
</body>
</html>
"""

SEARCH_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>搜索结果 - {{ query }}</title>
    <style>
        :root {
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --success: #10b981;
            --bg-body: #f1f5f9;
            --bg-card: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-light: #e2e8f0;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.1);
            --shadow-lg: 0 10px 25px -3px rgba(0,0,0,0.05);
            --radius-md: 10px;
            --radius-lg: 16px;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
            padding: 40px 20px; 
            background: var(--bg-body); 
            color: var(--text-main);
            line-height: 1.5;
        }

        .container { 
            max-width: 900px; 
            margin: auto; 
            background: var(--bg-card); 
            padding: 40px; 
            border-radius: var(--radius-lg); 
            box-shadow: var(--shadow-lg); 
        }

        /* --- Header & Navigation --- */
        .header-top { display: flex; flex-direction: column; gap: 15px; margin-bottom: 30px; border-bottom: 1px solid var(--border-light); padding-bottom: 25px; }
        
        .back-link { 
            display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); 
            text-decoration: none; font-size: 14px; font-weight: 500; transition: color 0.2s;
            align-self: flex-start;
        }
        .back-link:hover { color: var(--primary); }

        h1 { 
            color: var(--text-main); font-size: 26px; font-weight: 800; margin: 0;
            display: flex; align-items: center; gap: 10px;
        }
        .search-word { color: var(--primary); }
        .search-stats { 
            color: var(--text-muted); font-size: 14px; background: #f8fafc; 
            padding: 8px 16px; border-radius: 20px; display: inline-block; font-weight: 500;
        }

        /* --- Result List --- */
        .result-list { display: flex; flex-direction: column; }
        
        .result-item { 
            padding: 20px; border-bottom: 1px solid var(--border-light); 
            display: flex; justify-content: space-between; align-items: center;
            transition: all 0.2s ease; gap: 20px;
        }
        .result-item:last-child { border-bottom: none; }
        .result-item:hover { background: #f8fafc; padding-left: 25px; }

        .res-main { display: flex; gap: 16px; align-items: flex-start; flex: 1; min-width: 0; }
        
        .icon-box {
            flex-shrink: 0; width: 40px; height: 40px; border-radius: 10px;
            display: flex; align-items: center; justify-content: center;
        }
        .icon-file { background: #eff6ff; color: var(--primary); }
        .icon-folder { background: #fef2f2; color: #ef4444; }

        .res-content { flex: 1; min-width: 0; }
        .res-content h4 { 
            margin: 0 0 6px 0; color: #1e293b; font-size: 16px; font-weight: 600;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        
        .res-path { 
            font-size: 13px; color: var(--text-muted); 
            display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
        }
        .badge-source { 
            background: #e2e8f0; color: #475569; padding: 2px 8px; 
            border-radius: 4px; font-size: 11px; font-weight: 600;
        }
        .path-text { color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 400px; }

        /* --- Actions --- */
        .action-btn { 
            text-decoration: none; font-size: 14px; font-weight: 600; flex-shrink: 0;
            padding: 8px 20px; border-radius: 8px; transition: all 0.2s;
            display: inline-flex; align-items: center; gap: 6px;
        }
        .btn-play { background: var(--primary); color: white; border: 1px solid var(--primary); box-shadow: var(--shadow-sm); }
        .btn-play:hover { background: var(--primary-hover); border-color: var(--primary-hover); transform: translateY(-1px); }
        
        .btn-locate { background: white; color: var(--text-main); border: 1px solid #cbd5e1; }
        .btn-locate:hover { border-color: var(--text-muted); background: #f8fafc; }

        /* --- Empty State --- */
        .no-results { text-align: center; padding: 60px 20px; color: var(--text-muted); }
        .no-results-icon { 
            width: 64px; height: 64px; margin: 0 auto 20px auto; 
            background: #f1f5f9; border-radius: 50%; display: flex; 
            align-items: center; justify-content: center; color: #cbd5e1;
        }
        .no-results p { font-size: 16px; font-weight: 500; }

        /* Responsive */
        @media (max-width: 640px) {
            .container { padding: 25px 20px; border-radius: 0; box-shadow: none; }
            body { padding: 0; }
            .result-item { flex-direction: column; align-items: flex-start; }
            .action-btn { width: 100%; justify-content: center; }
            .path-text { max-width: 200px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-top">
            <a href="/" class="back-link">
                <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                返回云资源概览
            </a>
            <h1>检索: <span class="search-word">"{{ query }}"</span></h1>
            <div><span class="search-stats">为您找到 {{ results|length }} 个相关资源</span></div>
        </div>

        {% if results %}
        <div class="result-list">
            {% for res in results %}
            <div class="result-item">
                <div class="res-main">
                    <div class="icon-box {{ 'icon-file' if res.type == 'file' else 'icon-folder' }}">
                        {% if res.type == 'file' %}
                        <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        {% else %}
                        <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path></svg>
                        {% endif %}
                    </div>
                    
                    <div class="res-content">
                        <h4>{{ res.name }}</h4>
                        <div class="res-path">
                            <span class="badge-source">{{ res.share_name }}</span>
                            {% if res.path %}
                            <span style="color: #cbd5e1;">/</span>
                            <span class="path-text" title="{{ res.path }}">{{ res.path }}</span>
                            {% endif %}
                        </div>
                    </div>
                </div>
                
                <div>
                    {% if res.type == 'file' %}
                    <a href="/view/{{ res.link_id }}?play={{ res.id }}&name={{ res.name|urlencode }}" class="action-btn btn-play">
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 3l14 9-14 9V3z"></path></svg>
                        立即播放
                    </a>
                    {% else %}
                    <a href="/view/{{ res.link_id }}#folder-{{ res.id }}" class="action-btn btn-locate">
                        <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                        定位目录
                    </a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="no-results">
            <div class="no-results-icon">
                <svg width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
            </div>
            <p>抱歉，未找到匹配 "{{ query }}" 的内容，请尝试更换关键词。</p>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

VIEW_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ link_id }} - 在线预览</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        :root {
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --bg-body: #f1f5f9;
            --bg-card: #ffffff;
            --bg-player: #0f172a;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-light: #e2e8f0;
            --border-focus: #cbd5e1;
            --radius-md: 8px;
            --radius-lg: 16px;
            --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
            --shadow-xl: 0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; 
            background: var(--bg-body); 
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .app-container {
            display: flex;
            gap: 20px;
            width: 100%;
            max-width: 1600px;
            height: calc(100vh - 40px);
            padding: 0 20px;
        }

        /* --- Sidebar (Directory Tree) --- */
        .sidebar { 
            flex: 0 0 380px; 
            background: var(--bg-card); 
            border-radius: var(--radius-lg); 
            box-shadow: var(--shadow-md); 
            display: flex; 
            flex-direction: column;
            overflow: hidden;
            border: 1px solid var(--border-light);
        }

        .sidebar-header {
            padding: 20px;
            border-bottom: 1px solid var(--border-light);
            background: #f8fafc;
        }

        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }

        .home-link { 
            font-size: 13px; text-decoration: none; color: var(--primary); 
            font-weight: 600; display: inline-flex; align-items: center; gap: 4px;
            background: #eff6ff; padding: 4px 10px; border-radius: 20px; transition: 0.2s;
        }
        .home-link:hover { background: #dbeafe; color: var(--primary-hover); }

        h1 { color: var(--text-main); font-size: 18px; font-weight: 700; line-height: 1.3; }
        .link-id-badge { display: inline-block; font-family: ui-monospace, monospace; color: var(--text-muted); font-size: 12px; margin-top: 4px; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; }

        .tree-container {
            flex: 1;
            overflow-y: auto;
            padding: 15px 20px;
        }
        
        /* Custom Scrollbar for Tree */
        .tree-container::-webkit-scrollbar { width: 6px; }
        .tree-container::-webkit-scrollbar-track { background: transparent; }
        .tree-container::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
        .tree-container::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

        /* Tree Styles */
        .folder-section { 
            margin-top: 8px; 
            margin-left: 8px; 
            border-left: 2px solid #f1f5f9; 
            padding-left: 12px; 
        }
        .folder-title { 
            font-size: 14px; font-weight: 600; color: #334155; 
            margin-bottom: 6px; display: flex; align-items: center; 
            padding: 6px 0; border-radius: 6px; gap: 6px;
        }
        .folder-icon { color: #f59e0b; flex-shrink: 0; }

        .file-list { list-style: none; margin-left: 4px; display: flex; flex-direction: column; gap: 2px; }
        .file-item { 
            padding: 8px 10px; border-radius: var(--radius-md); 
            display: flex; justify-content: space-between; align-items: center; 
            transition: background 0.2s; gap: 10px;
        }
        .file-item:hover { background: #f8fafc; box-shadow: inset 0 0 0 1px #f1f5f9; }
        
        .file-name { 
            color: #475569; font-size: 13px; font-weight: 500;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; 
            flex: 1; display: flex; align-items: center; gap: 8px;
        }
        .file-icon { color: var(--primary); flex-shrink: 0; opacity: 0.8; }

        .play-btn { 
            background: #eff6ff; color: var(--primary); padding: 5px 12px; 
            border-radius: 20px; cursor: pointer; border: 1px solid transparent; 
            font-size: 12px; font-weight: 600; transition: all 0.2s;
            display: flex; align-items: center; gap: 4px;
        }
        .file-item:hover .play-btn { background: var(--primary); color: white; box-shadow: 0 2px 4px rgba(59,130,246,0.3); }

        .empty-hint { color: #94a3b8; font-size: 13px; padding: 10px; font-style: italic; }

        /* --- Player Area --- */
        .player-area { 
            flex: 1; 
            background: var(--bg-player); 
            border-radius: var(--radius-lg); 
            overflow: hidden; 
            position: relative; 
            box-shadow: var(--shadow-xl);
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid #1e293b;
        }
        
        video { 
            width: 100%; height: 100%; 
            object-fit: contain; /* Ensures video isn't cropped */
            background: #000;
        }

        .current-title { 
            color: rgba(255,255,255,0.9); 
            background: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%); 
            position: absolute; top: 0; left: 0; right: 0; 
            padding: 20px 20px 40px 20px; font-size: 16px; font-weight: 500;
            z-index: 10; pointer-events: none;
            text-shadow: 0 1px 2px rgba(0,0,0,0.8);
            display: flex; align-items: center; gap: 8px;
        }

        /* --- Responsive Design --- */
        @media (max-width: 900px) {
            body { height: auto; overflow: auto; padding: 0; background: var(--bg-card); }
            .app-container { flex-direction: column-reverse; height: auto; gap: 0; padding: 0; margin: 0; max-width: 100%; }
            .player-area { 
                border-radius: 0; height: 35vh; min-height: 250px; 
                position: sticky; top: 0; z-index: 50; border: none; border-bottom: 1px solid #1e293b;
            }
            .sidebar { flex: none; border-radius: 0; border: none; box-shadow: none; overflow: visible; }
            .tree-container { overflow-y: visible; padding-bottom: 40px; }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="sidebar">
            <div class="sidebar-header">
                <div class="header-top">
                    {% set share_name = results.tree.caLst[0].caName if (results.tree and results.tree.caLst and results.tree.caLst|length > 0) else (results.tree.coLst[0].coName if (results.tree and results.tree.coLst and results.tree.coLst|length > 0) else link_id) %}
                    <a href="/" class="home-link">
                        <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                        返回首页
                    </a>
                </div>
                <h1>{{ share_name }}</h1>
                <span class="link-id-badge">ID: {{ link_id }}</span>
            </div>

            <div class="tree-container root-container">
                {% macro render_tree(node) %}
                    {% if node %}
                        {# 渲染当前层级的文件 #}
                        {% if node.coLst %}
                            <ul class="file-list">
                                {% for file in node.coLst %}
                                <li class="file-item">
                                    <span class="file-name" title="{{ file.coName }}">
                                        <svg class="file-icon" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                                        {{ file.coName }}
                                    </span>
                                    <button class="play-btn" onclick="playVideo('{{ link_id }}', '{{ file.coID }}', '{{ file.coName }}')">
                                        播放
                                    </button>
                                </li>
                                {% endfor %}
                            </ul>
                        {% endif %}

                        {# 递归渲染子文件夹 #}
                        {% if node.caLst %}
                            {% for sub in node.caLst %}
                            <div class="folder-section" id="folder-{{ sub.caID }}">
                                <div class="folder-title">
                                    <svg class="folder-icon" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path></svg>
                                    {{ sub.caName }}
                                </div>
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

                {% if results.tree %}
                    {{ render_tree(results.tree) }}
                {% else %}
                    <div class="empty-hint">该分享未抓取到有效内容，请尝试删除 data 目录后重试。</div>
                {% endif %}
            </div>
        </div>

        <div class="player-area">
            <div id="videoTitle" class="current-title">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"></path></svg>
                等待选择视频播放...
            </div>
            <video id="video" controls></video>
        </div>
    </div>

    <script>
        var video = document.getElementById('video');
        var hls = new Hls();

        function playVideo(lid, coId, coName) {
            // 更新标题（保留了原有的文本更新逻辑，并附加上图标）
            document.getElementById('videoTitle').innerHTML = '<svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="margin-right:8px;"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg> 正在加载: ' + coName;
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
                        // 滚动到该元素并在树视图中居中
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        // 浅黄色背景高亮，兼容深色/浅色模式过渡
                        el.style.background = '#fef9c3'; 
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
    
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == "__main__":
    main()
