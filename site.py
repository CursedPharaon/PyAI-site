from flask import Flask, request, jsonify, send_file
import requests
import json
import os
from datetime import datetime, timedelta
import re

app = Flask(__name__)

# ============================================
# НАСТРОЙКИ
# ============================================
JSONBIN_KEY = "$2a$10$3T6Ssc3MDy8btFzOD4PTjOzciiAlCszOrB4zJDiorULg2BRrdPWRS"
BIN_ID = "6a90a8efda38895dfe19be69"
ADMIN_NAME = "cursed_dev"

OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = "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"

FREE_DAILY_LIMIT = 5  # Бесплатных запросов в день

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
        if not isinstance(users, dict):
            users = {}
        r = requests.put(url, json=users, headers=headers, timeout=10)
        print(f"save_users: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"save_users error: {e}")
        return False

# ============================================
# ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
# ============================================
def get_user(username):
    users = load_users()
    return users.get(username)

def check_password(username, password):
    user = get_user(username)
    if not user:
        return False
    return user.get("password") == password

def check_subscription(username):
    user = get_user(username)
    if not user:
        return None
    status = user.get("status", "inactive")
    end_date = user.get("end_date")
    
    if status == "active" and end_date:
        if datetime.now().isoformat() > end_date:
            user["status"] = "inactive"
            user["plan"] = None
            user["end_date"] = None
            save_users(load_users())
            return "inactive"
    return status

def get_subscription_info(username):
    user = get_user(username)
    if not user:
        return None
    status = user.get("status", "inactive")
    plan_key = user.get("plan")
    PLANS = {"1": "Неделя", "2": "Месяц", "3": "Год", "4": "Вечная"}
    plan_name = PLANS.get(plan_key, "Нет")
    end_date = user.get("end_date")
    if status == "active" and end_date:
        end = datetime.fromisoformat(end_date)
        days_left = (end - datetime.now()).days
        if days_left < 0:
            days_left = 0
        return {"status": status, "plan": plan_name, "days_left": days_left}
    elif status == "active" and not end_date:
        return {"status": status, "plan": "Вечная", "days_left": "∞"}
    else:
        return {"status": "inactive", "plan": "Нет", "days_left": 0}

# ============================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ЧАТАМИ И ЛИМИТАМИ
# ============================================
def get_user_data(username):
    """Получает данные пользователя: чаты, лимиты, подписку"""
    users = load_users()
    if username not in users:
        return None
    
    user = users[username]
    
    # Инициализируем структуру, если её нет
    if "chats" not in user:
        user["chats"] = {}
        user["current_chat"] = None
        user["daily_requests"] = 0
        user["daily_reset"] = datetime.now().isoformat()
        save_users(users)
    
    # Проверяем сброс лимита (строго через 24 часа)
    if "daily_reset" in user:
        reset_time = datetime.fromisoformat(user["daily_reset"])
        if datetime.now() >= reset_time + timedelta(days=1):
            user["daily_requests"] = 0
            user["daily_reset"] = datetime.now().isoformat()
            save_users(users)
    
    return user

def get_chat_history(username, chat_id):
    """Получает историю конкретного чата"""
    user_data = get_user_data(username)
    if not user_data:
        return []
    
    chats = user_data.get("chats", {})
    chat = chats.get(str(chat_id), {})
    return chat.get("history", [])

def save_chat_history(username, chat_id, history, title=None):
    """Сохраняет историю чата"""
    users = load_users()
    
    if username not in users:
        return False
    
    if "chats" not in users[username]:
        users[username]["chats"] = {}
    
    chat_id_str = str(chat_id)
    if chat_id_str not in users[username]["chats"]:
        users[username]["chats"][chat_id_str] = {
            "title": title or "Новый чат",
            "created_at": datetime.now().isoformat(),
            "history": []
        }
    
    users[username]["chats"][chat_id_str]["history"] = history
    if title:
        users[username]["chats"][chat_id_str]["title"] = title
    
    return save_users(users)

def create_new_chat(username):
    """Создаёт новый чат и возвращает его ID"""
    users = load_users()
    
    if username not in users:
        return None
    
    if "chats" not in users[username]:
        users[username]["chats"] = {}
    
    chat_id = int(time.time() * 1000)
    chat_id_str = str(chat_id)
    
    users[username]["chats"][chat_id_str] = {
        "title": "Новый чат",
        "created_at": datetime.now().isoformat(),
        "history": []
    }
    users[username]["current_chat"] = chat_id_str
    
    save_users(users)
    return chat_id

def get_current_chat_id(username):
    """Возвращает ID текущего чата пользователя"""
    user_data = get_user_data(username)
    if not user_data:
        return None
    
    current = user_data.get("current_chat")
    if current and current in user_data.get("chats", {}):
        return current
    
    return create_new_chat(username)

def add_message_to_chat(username, chat_id, role, content):
    """Добавляет сообщение в историю чата"""
    history = get_chat_history(username, chat_id)
    history.append({"role": role, "content": content})
    
    if len(history) > 50:
        history = history[-50:]
    
    return save_chat_history(username, chat_id, history)

def check_free_limit(username):
    """Проверяет, не превышен ли бесплатный лимит"""
    user_data = get_user_data(username)
    if not user_data:
        return True, 0
    
    status = user_data.get("status", "inactive")
    if status == "active":
        return True, 0
    
    daily_requests = user_data.get("daily_requests", 0)
    remaining = FREE_DAILY_LIMIT - daily_requests
    
    return remaining > 0, remaining

def increment_requests(username):
    """Увеличивает счётчик запросов"""
    users = load_users()
    
    if username not in users:
        return False
    
    users[username]["daily_requests"] = users[username].get("daily_requests", 0) + 1
    return save_users(users)

def generate_chat_title(question):
    """Генерирует короткое название чата на основе первого сообщения"""
    title = question.strip()
    if len(title) > 30:
        title = title[:27] + "..."
    return title

def get_all_chats(username):
    """Возвращает список всех чатов пользователя"""
    user_data = get_user_data(username)
    if not user_data:
        return []
    
    chats = user_data.get("chats", {})
    result = []
    for chat_id, chat in chats.items():
        result.append({
            "id": chat_id,
            "title": chat.get("title", "Новый чат"),
            "created_at": chat.get("created_at")
        })
    return sorted(result, key=lambda x: x.get("created_at", ""), reverse=True)

# ============================================
# OPENROUTER
# ============================================
def ask_ai_with_history(username, chat_id, question):
    """Отправляет запрос к OpenRouter с историей чата"""
    history = get_chat_history(username, chat_id)
    
    messages = [
        {"role": "system", "content": "Ты — PyAI, дружелюбная нейросеть. Отвечай полезно, структурированно и понятно."}
    ]
    
    for msg in history[-10:]:
        messages.append(msg)
    
    messages.append({"role": "user", "content": question})
    
    try:
        r = requests.post(
            OPENROUTER_URL,
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_API_KEY}'
            },
            timeout=30
        )
        
        print(f"OpenRouter статус: {r.status_code}")
        
        if r.status_code != 200:
            return f"⚠️ Ошибка API: {r.status_code}"
        
        response = r.json()['choices'][0]['message']['content']
        add_message_to_chat(username, chat_id, "user", question)
        add_message_to_chat(username, chat_id, "assistant", response)
        return response
    except Exception as e:
        print(f"OpenRouter ошибка: {e}")
        return f"⚠️ Ошибка: {str(e)[:200]}"

# ============================================
# АДМИН-ФУНКЦИИ
# ============================================
def give_access(username, plan_key):
    users = load_users()
    if username not in users:
        return False
    
    PLANS = {
        "1": {"name": "Неделя", "days": 7},
        "2": {"name": "Месяц", "days": 30},
        "3": {"name": "Год", "days": 365},
        "4": {"name": "Вечная", "days": None}
    }
    plan = PLANS.get(plan_key)
    if not plan:
        return False
    
    users[username]["plan"] = plan_key
    users[username]["status"] = "active"
    
    if plan["days"] is None:
        users[username]["end_date"] = None
    else:
        users[username]["end_date"] = (datetime.now() + timedelta(days=plan["days"])).isoformat()
    
    return save_users(users)

def remove_access(username):
    users = load_users()
    if username not in users:
        return False
    users[username]["status"] = "inactive"
    users[username]["plan"] = None
    users[username]["end_date"] = None
    return save_users(users)

def delete_user(username):
    users = load_users()
    if username not in users:
        return False
    del users[username]
    return save_users(users)

def list_users():
    users = load_users()
    result = []
    PLANS = {"1": "Неделя", "2": "Месяц", "3": "Год", "4": "Вечная"}
    for username, data in users.items():
        plan_key = data.get("plan")
        plan_name = PLANS.get(plan_key, "Нет")
        result.append({
            "username": username,
            "status": data.get("status", "inactive"),
            "plan": plan_name,
            "end_date": data.get("end_date")
        })
    return result

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
        return jsonify({'success': False, 'error': 'Пароль ≥ 4 символов'})
    
    users = load_users()
    if username in users:
        return jsonify({'success': False, 'error': 'Имя занято'})
    
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
    chat_id = data.get('chat_id')
    
    if not username or not message:
        return jsonify({'success': False, 'error': 'Введите имя и сообщение'})
    
    status = check_subscription(username)
    
    # Проверяем лимит
    can_use, remaining = check_free_limit(username)
    if status != "active" and not can_use:
        reset_time = datetime.fromisoformat(get_user_data(username)["daily_reset"])
        next_reset = reset_time + timedelta(days=1)
        wait_hours = int((next_reset - datetime.now()).total_seconds() / 3600) + 1
        return jsonify({
            'success': False, 
            'error': f'❌ Бесплатный лимит ({FREE_DAILY_LIMIT} запросов в день) исчерпан.\nСледующее обновление через ~{wait_hours} часов.\nКупи подписку у @cursed_pharaon'
        })
    
    # Если не указан chat_id, берём текущий или создаём новый
    if not chat_id:
        chat_id = get_current_chat_id(username)
    
    # Проверяем, есть ли история в этом чате
    history = get_chat_history(username, chat_id)
    
    # Если это первое сообщение в чате — генерируем название
    if len(history) == 0:
        title = generate_chat_title(message)
        save_chat_history(username, chat_id, [], title)
    
    # Отправляем запрос к ИИ
    response = ask_ai_with_history(username, chat_id, message)
    
    # Увеличиваем счётчик запросов
    if status != "active":
        increment_requests(username)
    
    # Получаем обновлённую информацию о лимите
    _, remaining_after = check_free_limit(username)
    
    return jsonify({
        'success': True, 
        'response': response,
        'chat_id': chat_id,
        'remaining': remaining_after,
        'is_free': status != "active"
    })

@app.route('/chats', methods=['POST'])
def get_chats():
    """Возвращает список всех чатов пользователя"""
    data = request.json
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'success': False, 'error': 'Имя не указано'})
    
    chats = get_all_chats(username)
    return jsonify({'success': True, 'chats': chats})

@app.route('/chats/switch', methods=['POST'])
def switch_chat():
    """Переключается на другой чат"""
    data = request.json
    username = data.get('username', '').strip()
    chat_id = data.get('chat_id')
    
    if not username or not chat_id:
        return jsonify({'success': False, 'error': 'Укажите имя и ID чата'})
    
    users = load_users()
    if username not in users:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    if "chats" not in users[username]:
        return jsonify({'success': False, 'error': 'Нет чатов'})
    
    if str(chat_id) not in users[username]["chats"]:
        return jsonify({'success': False, 'error': 'Чат не найден'})
    
    users[username]["current_chat"] = str(chat_id)
    save_users(users)
    
    history = get_chat_history(username, chat_id)
    return jsonify({
        'success': True, 
        'chat_id': chat_id,
        'history': history
    })

@app.route('/chats/delete', methods=['POST'])
def delete_chat():
    """Удаляет чат"""
    data = request.json
    username = data.get('username', '').strip()
    chat_id = data.get('chat_id')
    
    if not username or not chat_id:
        return jsonify({'success': False, 'error': 'Укажите имя и ID чата'})
    
    users = load_users()
    if username not in users:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    if "chats" not in users[username]:
        return jsonify({'success': False, 'error': 'Нет чатов'})
    
    chat_id_str = str(chat_id)
    if chat_id_str not in users[username]["chats"]:
        return jsonify({'success': False, 'error': 'Чат не найден'})
    
    del users[username]["chats"][chat_id_str]
    
    if users[username].get("current_chat") == chat_id_str:
        # Если удалили текущий чат, переключаем на другой или создаём новый
        remaining_chats = list(users[username]["chats"].keys())
        if remaining_chats:
            users[username]["current_chat"] = remaining_chats[0]
        else:
            users[username]["current_chat"] = None
            # Создаём новый чат
            new_chat_id = int(time.time() * 1000)
            users[username]["chats"][str(new_chat_id)] = {
                "title": "Новый чат",
                "created_at": datetime.now().isoformat(),
                "history": []
            }
            users[username]["current_chat"] = str(new_chat_id)
    
    save_users(users)
    return jsonify({'success': True, 'message': 'Чат удалён'})

@app.route('/chats/new', methods=['POST'])
def new_chat():
    """Создаёт новый чат"""
    data = request.json
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'success': False, 'error': 'Имя не указано'})
    
    chat_id = create_new_chat(username)
    if chat_id:
        return jsonify({'success': True, 'chat_id': chat_id})
    else:
        return jsonify({'success': False, 'error': 'Ошибка создания чата'})

@app.route('/clear_history', methods=['POST'])
def clear_history_route():
    data = request.json
    username = data.get('username', '').strip()
    chat_id = data.get('chat_id')
    
    if not username:
        return jsonify({'success': False, 'error': 'Имя не указано'})
    
    if not chat_id:
        chat_id = get_current_chat_id(username)
    
    if not chat_id:
        return jsonify({'success': False, 'error': 'Нет чата'})
    
    save_chat_history(username, chat_id, [])
    return jsonify({'success': True, 'message': 'История очищена'})

# ============================================
# АДМИН-МАРШРУТЫ
# ============================================
@app.route('/admin/listusers')
def admin_list_users():
    users = list_users()
    if not users:
        return jsonify({'success': True, 'users': '📭 Нет пользователей'})
    text = ""
    for user in users:
        emoji = "✅" if user["status"] == "active" else "❌"
        end_str = f"до {user['end_date'][:10]}" if user["end_date"] else "бессрочно" if user["status"] == "active" else "-"
        text += f"{emoji} {user['username']} | {user['plan']} | {end_str}\n"
    return jsonify({'success': True, 'users': text})

@app.route('/admin/giveaccess', methods=['POST'])
def admin_give_access():
    data = request.json
    username = data.get('username', '').strip()
    plan = data.get('plan', '').strip()
    if not username or not plan or plan not in ['1','2','3','4']:
        return jsonify({'success': False, 'error': 'Укажите имя и план (1-4)'})
    if give_access(username, plan):
        plan_names = {"1": "Неделя", "2": "Месяц", "3": "Год", "4": "Вечная"}
        return jsonify({'success': True, 'message': f'✅ {username} получил доступ на {plan_names[plan]}'})
    return jsonify({'success': False, 'error': '❌ Пользователь не найден'})

@app.route('/admin/removeaccess', methods=['POST'])
def admin_remove_access():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'success': False, 'error': 'Укажите имя'})
    if remove_access(username):
        return jsonify({'success': True, 'message': f'✅ Доступ отключён для {username}'})
    return jsonify({'success': False, 'error': '❌ Пользователь не найден'})

@app.route('/admin/deleteuser', methods=['POST'])
def admin_delete_user():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'success': False, 'error': 'Укажите имя'})
    if delete_user(username):
        return jsonify({'success': True, 'message': f'✅ Пользователь {username} удалён'})
    return jsonify({'success': False, 'error': '❌ Пользователь не найден'})

@app.route('/admin/stats')
def admin_stats():
    users = list_users()
    total = len(users)
    active = sum(1 for u in users if u["status"] == "active")
    return jsonify({'success': True, 'stats': f'👥 Всего: {total}\n✅ Активных: {active}\n❌ Неактивных: {total - active}'})

@app.route('/ping')
def ping():
    return "OK", 200

if __name__ == "__main__":
    import time
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
