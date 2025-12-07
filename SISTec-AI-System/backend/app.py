import os
import logging
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text

# Google Gemini
import google.genai as genai
from google.genai.errors import APIError


# ---------------------------------------
# Flask App Setup
# ---------------------------------------

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_change_me')
CORS(app)

# ---------------------------------------
# Database Setup
# ---------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = None
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

    try:
        engine = create_engine(DATABASE_URL)
        logging.info("Database engine created successfully.")
    except Exception as e:
        logging.error(f"Error creating engine: {e}")
else:
    logging.error("DATABASE_URL is not set.")


def setup_db():
    """Create tables if not present (no commit needed)."""
    if not engine:
        logging.error("Cannot set up DB: Engine is None.")
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    mobile TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    address TEXT,
                    password_hash TEXT NOT NULL
                );
            """))

            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES students(id),
                    user_query TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT NOW()
                );
            """))

        logging.info("Database tables created/verified.")
    except Exception as e:
        logging.error(f"Database setup error: {e}")


# Run DB setup
with app.app_context():
    setup_db()


# ---------------------------------------
# Gemini Client
# ---------------------------------------

def get_gemini_client():
    try:
        return genai.Client()
    except Exception as e:
        logging.error(f"Gemini client error: {e}")
        return None


# ---------------------------------------
# Helper Functions
# ---------------------------------------

def get_user_id_from_session():
    return session.get("user_id")


def save_chat_entry(user_id, query, response):
    if not engine: 
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO chat_history (user_id, user_query, bot_response)
                VALUES (:user_id, :query, :response)
            """), {
                "user_id": user_id,
                "query": query,
                "response": response
            })
    except Exception as e:
        logging.error(f"Error saving chat history: {e}")


# ---------------------------------------
# Frontend Routes
# ---------------------------------------

@app.route('/')
def home():
    return send_from_directory('../frontend', 'home.html')

@app.route('/register')
def register_page():
    return send_from_directory('../frontend', 'register.html')

@app.route('/login')
def login_page():
    return send_from_directory('../frontend', 'st_login.html')

@app.route('/user')
def user_dashboard():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized access"}), 401
    return send_from_directory('../frontend', 'st_dashboard.html')


# ---------------------------------------
# Auth Routes
# ---------------------------------------

@app.route('/register', methods=['POST'])
def register():
    if not engine:
        return jsonify({"message": "Database Error"}), 500

    try:
        data = request.form
        name = data['name']
        mobile = data['mobile']
        email = data['email']
        address = data.get('address', '')
        password = data['password']

        password_hash = generate_password_hash(password)

        with engine.begin() as connection:
            exists = connection.execute(text("""
                SELECT id FROM students WHERE email = :email OR mobile = :mobile
            """), {"email": email, "mobile": mobile}).fetchone()

            if exists:
                return jsonify({"message": "Email or Mobile already exists"}), 409

            connection.execute(text("""
                INSERT INTO students (name, mobile, email, address, password_hash)
                VALUES (:name, :mobile, :email, :address, :password_hash)
            """), {
                "name": name,
                "mobile": mobile,
                "email": email,
                "address": address,
                "password_hash": password_hash
            })

        return jsonify({"message": "Registration successful"}), 201

    except Exception as e:
        logging.error(f"Register error: {e}")
        return jsonify({"message": "Server Error"}), 500


@app.route('/login', methods=['POST'])
def login():
    if not engine:
        return jsonify({"message": "Database Error"}), 500

    try:
        data = request.form
        email = data['email']
        password = data['password']

        with engine.connect() as connection:
            user = connection.execute(text("""
                SELECT id, name, password_hash FROM students WHERE email = :email
            """), {"email": email}).fetchone()

            if user and check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                return jsonify({"message": "Login successful", "redirect_url": "/user"}), 200
            else:
                return jsonify({"message": "Invalid email or password"}), 401

    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({"message": "Server Error"}), 500


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200


# ---------------------------------------
# Chat Route (Gemini)
# ---------------------------------------

@app.route('/chat', methods=['POST'])
def chat():
    user_id = get_user_id_from_session()
    if not user_id:
        return jsonify({"response": "Please log in first"}), 401

    try:
        data = request.json
        user_query = data.get("query")

        if not user_query:
            return jsonify({"response": "Query cannot be empty"}), 400

        client = get_gemini_client()
        if not client:
            return jsonify({"response": "Gemini client error"}), 500

        system_prompt = (
            "You are the SISTec College Admission Assistant. "
            "Give correct, helpful, friendly answers about SISTec college."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[user_query],
            config={
                "system_instruction": system_prompt,
                "tools": [{"google_search": {}}]
            }
        )

        bot_response = response.text

        save_chat_entry(user_id, user_query, bot_response)

        return jsonify({"response": bot_response}), 200

    except APIError as e:
        logging.error(f"Gemini API error: {e}")
        return jsonify({"response": "Gemini API Error"}), 500
    except Exception as e:
        logging.error(f"Chat error: {e}")
        return jsonify({"response": "Server Error"}), 500


# ---------------------------------------
# Run App
# ---------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
