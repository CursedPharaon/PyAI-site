from flask import Flask, request, jsonify, send_file
import requests
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# ============================================
# НАСТРОЙКИ
# ============================================
JSONBIN_KEY = "$2a$10$3T6Ssc3MDy8btFzOD4PTjOzciiAlCszOrB4zJDiorULg2BRrdPWRS"
BIN_ID = "6a90a8efda38895dfe19be69"

# ============================================
# ПАМЯТЬ: ХРАНИМ ИСТОРИЮ ДИАЛОГОВ ДЛЯ САЙТА
# ============================================
chat_history = {}
MAX_HISTORY = 20

def get_history(user_id):
    if user_id not in chat_history:
        chat_history[user_id] = []
    return chat_history[user_id]

def add_to_history(user_id, role, content):
    history = get_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        chat_history[user_id] = history[-MAX_HISTORY:]

def clear_history(user_id):
    if user_id in chat_history:
        chat_history[user_id] = []

# ============================================
# ФУНКЦИИ JSONBin
# ============================================
def load_users():
    url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
    headers = {"X-Access-Key": JSONBIN_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("record", {})
        return {}
    except Exception as e:
        print(f"load_users error: {e}")
        return {}

def save_users(users):
    url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
    headers = {
        "X-Access-Key": JSONBIN_KEY,
        "Content-Type": "application/json"
    }
    try:
        r = requests.put(url, json=users, headers=headers, timeout=10)
        print(f"save_users: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"save_users error: {e}")
        return False

def check_password(username, password):
    users = load_users()
    user = users.get(username)
    if not user:
        return False
    return user.get("password") == password

def check_subscription(username):
    users = load_users()
    if username not in users:
        return None
    user = users[username]
    status = user.get("status", "inactive")
    end_date = user.get("end_date")
    
    if status == "active" and end_date:
        if datetime.now().isoformat() > end_date:
            user["status"] = "inactive"
            user["plan"] = None
            user["end_date"] = None
            save_users(users)
            return "inactive"
    return status

def get_subscription_info(username):
    users = load_users()
    if username not in users:
        return None
    user = users[username]
    status = user.get("status", "inactive")
    plan_key = user.get("plan")
    
    PLANS = {
        "1": "Неделя",
        "2": "Месяц",
        "3": "Год",
        "4": "Вечная"
    }
    plan_name = PLANS.get(plan_key, "Нет")
    
    end_date = user.get("end_date")
    if status == "active" and end_date:
        end = datetime.fromisoformat(end_date)
        days_left = (end - datetime.now()).days
        if days_left < 0:
            days_left = 0
        return {
            "status": status,
            "plan": plan_name,
            "days_left": days_left
        }
    elif status == "active" and not end_date:
        return {
            "status": status,
            "plan": "Вечная",
            "days_left": "∞"
        }
    else:
        return {
            "status": "inactive",
            "plan": "Нет",
            "days_left": 0
        }

# ============================================
# OPENROUTER С ПАМЯТЬЮ
# ============================================
def ask_ai_with_history(user_id, question):
    try:
        history = get_history(user_id)
        
        messages = [
            {"role": "system", "content": "Ты — PyAI, дружелюбная нейросеть. Отвечай полезно и понятно. Ты можешь играть в игры, викторины и поддерживать диалог. Запоминай, что говорил пользователь ранее."}
        ]
        
        for msg in history[-10:]:
            messages.append(msg)
        
        messages.append({"role": "user", "content": question})
        
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json={
                "model": "openrouter/free",
                "messages": messages
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer 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'
            },
            timeout=30
        )
        r.raise_for_status()
        response = r.json()['choices'][0]['message']['content']
        
        add_to_history(user_id, "user", question)
        add_to_history(user_id, "assistant", response)
        
        return response
    except Exception as e:
        return f"⚠️ Ошибка: {str(e)[:200]}"

# ============================================
# МАРШРУТЫ
# ============================================
@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Введите имя и пароль'})
    
    if check_password(username, password):
        status = check_subscription(username)
        info = get_subscription_info(username)
        return jsonify({
            'success': True,
            'username': username,
            'status': status,
            'plan': info['plan'] if info else 'Нет',
            'days_left': info['days_left'] if info else 0
        })
    else:
        return jsonify({'success': False, 'error': 'Неверное имя или пароль'})

@app.route('/register_web', methods=['POST'])
def register_web():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    if len(password) < 4:
        return jsonify({'success': False, 'error': 'Пароль должен быть не менее 4 символов'})
    
    users = load_users()
    if username in users:
        return jsonify({'success': False, 'error': 'Имя уже занято'})
    
    users[username] = {
        "password": password,
        "user_id": None,
        "status": "inactive",
        "plan": None,
        "end_date": None,
        "created_at": datetime.now().isoformat()
    }
    
    if save_users(users):
        return jsonify({'success': True, 'message': 'Регистрация успешна! Ожидайте активации.'})
    else:
        return jsonify({'success': False, 'error': 'Ошибка сохранения'})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    username = data.get('username', '').strip()
    message = data.get('message', '').strip()
    
    if not username or not message:
        return jsonify({'success': False, 'error': 'Введите имя и сообщение'})
    
    status = check_subscription(username)
    if status != "active":
        return jsonify({'success': False, 'error': 'Подписка неактивна. Напишите @cursed_pharaon для продления'})
    
    # Используем username как ID для памяти на сайте
    user_id = f"web_{username}"
    response = ask_ai_with_history(user_id, message)
    return jsonify({'success': True, 'response': response})

@app.route('/clear_history', methods=['POST'])
def clear_history_route():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'success': False, 'error': 'Имя не указано'})
    
    user_id = f"web_{username}"
    clear_history(user_id)
    return jsonify({'success': True, 'message': 'История очищена'})

@app.route('/ping')
def ping():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
