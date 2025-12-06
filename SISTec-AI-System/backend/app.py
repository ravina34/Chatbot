import os
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, make_response
from functools import wraps
from datetime import datetime
from agents.admission_agent import get_ai_response
import json

# Placeholder for database (replace with actual database integration like SQLAlchemy/MongoDB/Firestore)
# For this example, we'll use a simple in-memory dictionary.
# In a real app, NEVER store passwords like this. Use hashing (e.g., bcrypt)!
users = {}
admin = {"admin@sistec.edu": "adminpass"}
queries = {}
query_counter = 1

app = Flask(__name__)
# IMPORTANT: In a production environment, use a complex, random secret key.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_very_insecure') 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Utility Functions ---

def login_required(f):
    """Decorator to require login for certain routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin login for certain routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    # If already logged in, redirect to user page
    if 'user_id' in session and session.get('user_role') == 'user':
        return redirect(url_for('user_dashboard'))
    return render_template('login.html')

@app.route('/admin_login')
def admin_login():
    # If already logged in as admin, redirect to admin dashboard
    if 'user_id' in session and session.get('user_role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            return jsonify({"message": "Email and password are required."}), 400

        if email in users:
            return jsonify({"message": "User already exists. Please login."}), 409
        
        # In a real app, hash the password: users[email] = generate_password_hash(password)
        users[email] = {'password': password, 'id': str(len(users) + 1)}
        logging.info(f"New user registered: {email}")
        
        # Automatically log in the user after successful registration
        session['user_id'] = users[email]['id']
        session['user_role'] = 'user'
        
        # Successful registration - usually redirects to the dashboard
        return jsonify({"message": "Registration successful. Redirecting to user dashboard.", "redirect": url_for('user_dashboard')}), 200

    return render_template('register.html')

# !!! CRITICAL FIX APPLIED HERE !!!
@app.route('/student_login_page', methods=['POST'])
def student_login_page():
    email = request.form.get('email')
    password = request.form.get('password')

    user_data = users.get(email)

    if user_data and user_data['password'] == password:
        session['user_id'] = user_data['id']
        session['user_role'] = 'user'
        logging.info(f"User logged in: {email}")
        
        # --- THE FIX: Instead of returning a JSON response, we redirect ---
        # We return a JSON response with a redirect URL, which frontend JS should handle.
        # This is often done for AJAX login requests.
        return jsonify({"message": "Login successful.", "redirect": url_for('user_dashboard')}), 200
    
    # If login fails, return 401 Unauthorized with the error message
    return jsonify({"message": "Invalid email or password."}), 401

@app.route('/admin_login', methods=['POST'])
def admin_login_post():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if admin.get(email) == password:
        session['user_id'] = 'admin'
        session['user_role'] = 'admin'
        logging.info("Admin logged in.")
        return jsonify({"message": "Admin login successful.", "redirect": url_for('admin_dashboard')}), 200
        
    return jsonify({"message": "Invalid credentials for admin."}), 401

@app.route('/user')
@login_required
def user_dashboard():
    # Only regular users can access this page
    if session.get('user_role') != 'user':
        return redirect(url_for('login'))
    return render_template('user_dashboard.html', user_id=session['user_id'])

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    # Only admin can access this page
    if session.get('user_role') != 'admin':
        return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Chat API for User ---
@app.route('/api/chat', methods=['POST'])
@login_required
def chat_endpoint():
    global query_counter
    data = request.json
    user_query = data.get('query', '').strip()
    user_id = session['user_id']

    if not user_query:
        return jsonify({"response": "Please enter a question."}), 400

    # 1. First, attempt to get response from the AI agent
    try:
        ai_response_text = get_ai_response(user_query)
        is_answered = True
        response_status = "AI"
    except Exception as e:
        logging.error(f"AI response failed for user {user_id}: {e}")
        ai_response_text = "AI system is currently unavailable. Your query has been logged for Admin review."
        is_answered = False
        response_status = "Pending"

    # 2. Log the query
    q_id = str(query_counter)
    queries[q_id] = {
        'id': q_id,
        'user_id': user_id,
        'query': user_query,
        'answer': ai_response_text,
        'is_answered': is_answered,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': response_status
    }
    query_counter += 1

    # If AI failed, mark as pending and return AI's fallback message
    if not is_answered:
        return jsonify({"response": ai_response_text, "status": "pending"})

    # If AI succeeded, return the AI response
    return jsonify({"response": ai_response_text, "status": "answered"})


# --- History and Admin APIs ---

@app.route('/api/chat_history', methods=['GET'])
@login_required
def chat_history():
    user_id = session['user_id']
    # Filter queries for the current user
    user_history = [q for q in queries.values() if q['user_id'] == user_id]
    
    # Sort by timestamp (or ID which acts as sequence)
    user_history.sort(key=lambda x: x['id'])
    
    # Only return essential fields for the user
    simplified_history = [{'query': h['query'], 'answer': h['answer'], 'status': h['status']} for h in user_history]
    
    # Return as JSON
    return jsonify(simplified_history), 200

@app.route('/api/admin/pending_queries', methods=['GET'])
@admin_required
def pending_queries_api():
    pending = [q for q in queries.values() if q['status'] == 'Pending']
    # Return all fields for admin
    return jsonify(pending), 200

@app.route('/api/admin/answer_query', methods=['POST'])
@admin_required
def answer_query_api():
    data = request.json
    query_id = data.get('query_id')
    admin_answer = data.get('answer', '').strip()

    if query_id in queries and admin_answer:
        queries[query_id]['answer'] = admin_answer
        queries[query_id]['is_answered'] = True
        queries[query_id]['status'] = 'Admin Answered'
        logging.info(f"Query {query_id} answered by admin.")
        return jsonify({"message": f"Query {query_id} successfully answered."}), 200
    
    return jsonify({"message": "Invalid query ID or empty answer."}), 400

# --- Error Handling ---

@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('404.html'), 404

# Run the app
if __name__ == '__main__':
    # Add a dummy user for testing
    if not users:
        users['test@user.com'] = {'password': 'password123', 'id': 'u1'}
    # Run on the required port for the environment
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)

# Add placeholder HTML files (index.html, login.html, etc.) if they don't exist
# This is typically done to ensure the app runs without immediate file errors,
# but since you only provided logs, I'll assume standard Flask structure
# and focus on the Python logic fix.
