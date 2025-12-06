import os
import sys


import json
import logging
import psycopg2
import psycopg2.extras # For RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agents.admission_agent import get_ai_response # AI query system import

# ===============================================
# 1. APP SETUP AND CONFIGURATION
# ===============================================
app = Flask(__name__,
            template_folder='frontend', # HTML files folder
            static_folder='frontend/css') # Static assets folder (e.g., CSS/JS)

# Session configuration for user login management
app.secret_key = os.environ.get('SECRET_KEY', 'your_secure_secret_key_for_sessions')
app.permanent_session_lifetime = timedelta(hours=24)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Database Connection (from environment variable)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logging.error("DATABASE_URL environment variable is not set.")


# ===============================================
# 2. DATABASE UTILITIES & INITIALIZATION
# ===============================================

def get_db_connection():
    """Connects to the PostgreSQL database."""
    if not DATABASE_URL:
        return None
    try:
        # Use the DATABASE_URL which should be in the correct psycopg2 format
        # If your Render URL is 'postgresql://...' you may need to ensure it works, 
        # or use 'postgresql+psycopg2://' format if possible through environment vars.
        # psycopg2 usually handles the standard postgresql://
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None

def db_initialize():
    """Ensures necessary tables and a default admin user exist."""
    conn = get_db_connection()
    if conn is None:
        return

    try:
        cursor = conn.cursor()
        
        # 1. Users Table (For Students and Admin)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                mobile_number VARCHAR(15),
                email VARCHAR(100) UNIQUE NOT NULL,
                residential_address TEXT,
                password_hash TEXT NOT NULL,
                user_role VARCHAR(10) NOT NULL DEFAULT 'student',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Chat History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                query_text TEXT NOT NULL,
                query_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                response_text TEXT,
                response_time TIMESTAMP WITH TIME ZONE,
                query_status VARCHAR(20) NOT NULL DEFAULT 'co', -- 'pending' (for admin) or 'answered' or 'co' (AI check)
                is_admin_response BOOLEAN DEFAULT FALSE
            );
        """)

        # 3. Insert default Admin user if none exists
        # Default Admin credentials: email='admin@sistec.com', password='admin'
        ADMIN_EMAIL = 'admin@sistec.com'
        ADMIN_PASSWORD_HASH = generate_password_hash('admin')
        
        cursor.execute("SELECT id FROM users WHERE email = %s AND user_role = 'admin';", (ADMIN_EMAIL,))
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO users (full_name, email, password_hash, user_role) VALUES (%s, %s, %s, %s);",
                ('System Admin', ADMIN_EMAIL, ADMIN_PASSWORD_HASH, 'admin')
            )
            logging.warning("Default Admin account created: admin@sistec.com / admin")
        
        conn.commit()
        logging.info("Database tables and Admin check completed.")
    except Exception as e:
        logging.error(f"Error initializing database: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()

# Initialize DB when the app starts
db_initialize()

# ===============================================
# 3. DECORATORS AND AUTHENTICATION ROUTES
# ===============================================

def login_required(f):
    """Decorator to check if student user is logged in."""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('user_role') != 'student':
            return redirect(url_for('student_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def admin_required(f):
    """Decorator to check if user is logged in as admin."""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('user_role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@app.route('/')
def home():
    """Renders the homepage (home.html)."""
    return render_template('home.html')

# --- Registration ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles student registration (register.html)."""
    if request.method == 'POST':
        conn = get_db_connection()
        if conn is None:
            return jsonify({'message': 'Registration failed due to server error (DB).'}), 500

        try:
            full_name = request.form['full_name']
            mobile_number = request.form.get('mobile_number', '')
            email = request.form['email']
            residential_address = request.form.get('residential_address', '')
            password = request.form['password']
            
            password_hash = generate_password_hash(password)
            cursor = conn.cursor()
            
            cursor.execute(
                "INSERT INTO users (full_name, mobile_number, email, residential_address, password_hash, user_role) VALUES (%s, %s, %s, %s, %s, 'student') RETURNING id;",
                (full_name, mobile_number, email, residential_address, password_hash)
            )
            user_id = cursor.fetchone()[0]
            conn.commit()
            
            # Auto-login
            session.permanent = True
            session['user_id'] = user_id
            session['user_role'] = 'student'
            session['user_name'] = full_name
            
            return jsonify({'message': 'Registration successful.', 'redirect_url': url_for('student_dashboard')}), 200
            
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return jsonify({'message': 'Email already registered.'}), 409
        except Exception as e:
            conn.rollback()
            logging.error(f"Registration error: {e}")
            return jsonify({'message': f'Registration failed: {e}'}), 500
        finally:
            if conn:
                conn.close()
    
    return render_template('register.html')

# --- Student Login ---
@app.route('/login', methods=['GET', 'POST'])
def student_login():
    """Handles student login (st_login.html)."""
    if request.method == 'POST':
        conn = get_db_connection()
        if conn is None:
            return jsonify({'message': 'Login failed due to server error.'}), 500
        
        email = request.form['email']
        password = request.form['password']
        
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, full_name, password_hash FROM users WHERE email = %s AND user_role = 'student';",
                (email,)
            )
            user = cursor.fetchone()
            
            if user and check_password_hash(user[2], password):
                session.permanent = True
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                session['user_role'] = 'student'
                return jsonify({'message': 'Login successful.', 'redirect_url': url_for('student_dashboard')}), 200
            else:
                return jsonify({'message': 'Invalid email or password.'}), 401
                
        except Exception as e:
            logging.error(f"Student login error: {e}")
            return jsonify({'message': 'An unexpected error occurred during login.'}), 500
        finally:
            if conn:
                conn.close()

    return render_template('st_login.html')

# --- Admin Login ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    """Handles admin login (ad_login.html)."""
    if request.method == 'POST':
        conn = get_db_connection()
        if conn is None:
            return jsonify({'message': 'Login failed due to server error.'}), 500
        
        email = request.form['email']
        password = request.form['password']
        
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, full_name, password_hash FROM users WHERE email = %s AND user_role = 'admin';",
                (email,)
            )
            user = cursor.fetchone()
            
            if user and check_password_hash(user[2], password):
                session.permanent = True
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                session['user_role'] = 'admin'
                return jsonify({'message': 'Admin Login successful.', 'redirect_url': url_for('admin_dashboard')}), 200
            else:
                return jsonify({'message': 'Invalid email or password.'}), 401
                
        except Exception as e:
            logging.error(f"Admin login error: {e}")
            return jsonify({'message': 'An unexpected error occurred during admin login.'}), 500
        finally:
            if conn:
                conn.close()
                
    return render_template('ad_login.html')

@app.route('/logout')
def logout():
    """Logs out the current user."""
    session.clear()
    return redirect(url_for('home'))


# ===============================================
# 4. DASHBOARD ROUTES (Views)
# ===============================================

@app.route('/user')
@login_required
def student_dashboard():
    """Renders the student chat dashboard (st_dashboard.html)."""
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'Student')
    return render_template('st_dashboard.html', user_name=user_name, user_id=user_id)

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    """Renders the admin dashboard (ad_dash.html)."""
    user_name = session.get('user_name', 'Admin')
    return render_template('ad_dash.html', user_name=user_name)


# ===============================================
# 5. STUDENT CHAT API ENDPOINTS
# ===============================================

@app.route('/api/chat', methods=['POST'])
@login_required
def chat_api():
    """Handles student query, saves to DB, and gets AI response."""
    user_id = session.get('user_id')
    data = request.get_json()
    query_text = data.get('query')
    
    if not query_text:
        return jsonify({'error': 'Query text is required'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection error'}), 500

    chat_id = None
    try:
        cursor = conn.cursor()
        
        # 1. Save the user query to DB with status 'co' (Checking by AI)
        cursor.execute(
            "INSERT INTO chat_history (user_id, query_text, query_status) VALUES (%s, %s, %s) RETURNING id;",
            (user_id, query_text, 'co')
        )
        chat_id = cursor.fetchone()[0]
        
        # 2. Get AI Response
        ai_response_text = get_ai_response(query_text)
        
        # 3. Check if AI returned a fallback message (indicating failure)
        if "AI system is currently unavailable" in ai_response_text or "Sorry, I am currently unable to fetch an answer" in ai_response_text:
            status = 'pending' # Forward to admin
            response_to_user = "I couldn't process this query due to an external service error. The query has been forwarded to the Admin team for manual review."
        else:
            status = 'answered'
            response_to_user = ai_response_text

        # 4. Update DB with final status and response
        cursor.execute(
            """
            UPDATE chat_history 
            SET response_text = %s, response_time = CURRENT_TIMESTAMP, query_status = %s 
            WHERE id = %s;
            """,
            (response_to_user, status, chat_id)
        )
        conn.commit()

        # 5. Return the response to the frontend
        return jsonify({
            'response': response_to_user,
            'status': status,
        }), 200

    except Exception as e:
        conn.rollback()
        logging.error(f"Chat API error: {e}")
        
        # Fallback if unhandled error occurs during DB/AI interaction
        if chat_id:
            try:
                # Mark as pending if the insertion succeeded but AI/Update failed
                cursor.execute(
                    "UPDATE chat_history SET query_status = 'pending' WHERE id = %s;",
                    (chat_id,)
                )
                conn.commit()
            except:
                pass # Ignore if this update fails too

        return jsonify({'error': 'An unrecoverable server error occurred.'}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/chat_history', methods=['GET'])
@login_required
def get_chat_history():
    """Fetches all chat history for the logged-in student."""
    user_id = session.get('user_id')
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection error'}), 500
        
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT id, query_text, query_time, response_text, response_time, query_status, is_admin_response FROM chat_history WHERE user_id = %s ORDER BY query_time ASC;",
            (user_id,)
        )
        history = cursor.fetchall()
        return jsonify(history), 200

    except Exception as e:
        logging.error(f"Error fetching chat history: {e}")
        return jsonify({'error': 'Could not fetch chat history'}), 500
    finally:
        if conn:
            conn.close()


# ===============================================
# 6. ADMIN API ENDPOINTS
# ===============================================

@app.route('/api/admin/pending_queries', methods=['GET'])
@admin_required
def get_pending_queries():
    """Fetches all pending queries for the admin dashboard."""
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection error'}), 500
        
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            """
            SELECT ch.id, ch.query_text, ch.query_time, u.full_name as student_name, u.email as student_email, u.id as student_id
            FROM chat_history ch
            JOIN users u ON ch.user_id = u.id
            WHERE ch.query_status = 'pending'
            ORDER BY ch.query_time ASC;
            """
        )
        pending_queries = cursor.fetchall()
        return jsonify(pending_queries), 200

    except Exception as e:
        logging.error(f"Error fetching pending queries: {e}")
        return jsonify({'error': 'Could not fetch pending queries'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/answer_query', methods=['POST'])
@admin_required
def admin_answer_query():
    """Allows admin to answer a pending query."""
    data = request.get_json()
    chat_id = data.get('chat_id')
    admin_response = data.get('response')

    if not all([chat_id, admin_response]):
        return jsonify({'error': 'Chat ID and response are required'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection error'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE chat_history 
            SET response_text = %s, response_time = CURRENT_TIMESTAMP, query_status = 'answered', is_admin_response = TRUE
            WHERE id = %s AND query_status = 'pending';
            """,
            (admin_response, chat_id)
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'error': 'Query not found or already answered.'}), 404
            
        conn.commit()
        return jsonify({'message': 'Query answered successfully.'}), 200

    except Exception as e:
        conn.rollback()
        logging.error(f"Admin answer query error: {e}")
        return jsonify({'error': 'An unexpected error occurred.'}), 500
    finally:
        if conn:
            conn.close()


# ===============================================
# 7. RUN THE APP
# ===============================================

if __name__ == '__main__':
    # Ensure DB is initialized before running the app
    db_initialize() 
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))




