import os
import json
import logging
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text

# FIX: Import the Google GenAI SDK using the full, stable package name
import google.generativeai as genai
from google.genai.errors import APIError

# --- CONFIGURATION AND INITIALIZATION ---

# Set up logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
# IMPORTANT: For secure production, use a long, complex secret key.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_change_me')
CORS(app)

# Database connection setup
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # Fix for newer SQLAlchemy versions for compatibility with Render's URL format
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = None
if DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL)
        logging.info("Database engine created successfully.")
    except Exception as e:
        logging.error(f"Error creating database engine: {e}")
else:
    logging.error("DATABASE_URL environment variable is not set.")

def setup_db():
    """Ensures necessary tables exist."""
    if not engine:
        logging.error("Cannot set up DB: Engine is None.")
        return

    try:
        with engine.connect() as connection:
            # 1. Students Table (for login/registration)
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

            # 2. Chat History Table
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES students(id),
                    user_query TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
                );
            """))
            connection.commit()
            logging.info("Database tables checked/created successfully.")
    except Exception as e:
        logging.error(f"Database setup error: {e}")

# Run DB setup when the app starts
with app.app_context():
    setup_db()

# --- GEMINI CLIENT SETUP ---

def get_gemini_client():
    """Initializes and returns the Gemini client."""
    # The SDK automatically reads the GEMINI_API_KEY environment variable.
    try:
        # Use the client interface from the imported genai alias
        client = genai.Client() 
        return client
    except Exception as e:
        logging.error(f"Failed to initialize Gemini Client: {e}")
        return None

# --- UTILITY FUNCTIONS ---

def get_user_id_from_session():
    """Checks if a user is logged in and returns their ID."""
    return session.get('user_id')

def get_chat_history(user_id):
    """Fetches chat history for a specific user."""
    if not engine: return []
    try:
        with engine.connect() as connection:
            result = connection.execute(text("""
                SELECT user_query, bot_response FROM chat_history 
                WHERE user_id = :user_id 
                ORDER BY timestamp ASC
            """), {"user_id": user_id})
            # Convert query history into a format suitable for the chat model (optional for this simple example, but good practice)
            history = [{'user': row[0], 'bot': row[1]} for row in result.fetchall()]
            return history
    except Exception as e:
        logging.error(f"Error fetching chat history: {e}")
        return []

def save_chat_entry(user_id, query, response):
    """Saves a single chat turn to the database."""
    if not engine: return
    try:
        with engine.connect() as connection:
            connection.execute(text("""
                INSERT INTO chat_history (user_id, user_query, bot_response)
                VALUES (:user_id, :query, :response)
            """), {"user_id": user_id, "query": query, "response": response})
            connection.commit()
    except Exception as e:
        logging.error(f"Error saving chat entry: {e}")

# --- ROUTES ---

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
def student_dashboard():
    # Only allow access if the user is logged in
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized access, please log in."}), 401
    return send_from_directory('../frontend', 'st_dashboard.html')

# --- AUTHENTICATION ROUTES ---

@app.route('/register', methods=['POST'])
def register():
    if not engine:
        return jsonify({"message": "Database error: Cannot connect."}), 500

    try:
        data = request.form
        name = data['name']
        mobile = data['mobile']
        email = data['email']
        address = data.get('address', '')
        password = data['password']

        # Hashing the password for security
        password_hash = generate_password_hash(password)

        with engine.connect() as connection:
            # Check if email or mobile already exists
            exists = connection.execute(text("SELECT id FROM students WHERE email = :email OR mobile = :mobile"), 
                                        {"email": email, "mobile": mobile}).fetchone()
            if exists:
                return jsonify({"message": "Registration failed. User with this email or mobile already exists."}), 409

            # Insert new student
            connection.execute(text("""
                INSERT INTO students (name, mobile, email, address, password_hash)
                VALUES (:name, :mobile, :email, :address, :password_hash)
            """), {"name": name, "mobile": mobile, "email": email, "address": address, "password_hash": password_hash})
            connection.commit()
            return jsonify({"message": "Registration successful. You can now log in."}), 201
            
    except Exception as e:
        logging.error(f"Registration error: {e}")
        return jsonify({"message": "Registration failed due to a server error."}), 500

@app.route('/login', methods=['POST'])
def login():
    if not engine:
        return jsonify({"message": "Database error: Cannot connect."}), 500

    try:
        data = request.form
        email = data['email']
        password = data['password']

        with engine.connect() as connection:
            student = connection.execute(text("SELECT id, name, password_hash FROM students WHERE email = :email"), 
                                          {"email": email}).fetchone()
            
            if student and check_password_hash(student[2], password):
                session['user_id'] = student[0]
                session['user_name'] = student[1]
                return jsonify({
                    "message": "Login successful.", 
                    "redirect_url": "/user",
                    "user_name": student[1]
                }), 200
            else:
                return jsonify({"message": "Invalid email or password."}), 401
    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({"message": "Login failed due to a server error."}), 500

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    return jsonify({"message": "Logged out successfully.", "redirect_url": "/login"}), 200

# --- CHAT ROUTE (THE FIX) ---

@app.route('/chat', methods=['POST'])
def handle_chat():
    user_id = get_user_id_from_session()
    if not user_id:
        return jsonify({"response": "Please log in to use the chat."}), 401

    try:
        data = request.json
        user_query = data.get('query')
        if not user_query:
            return jsonify({"response": "Query is empty."}), 400

        # Initialize the Gemini Client
        client = get_gemini_client()
        if not client:
            raise APIError("Gemini Client failed to initialize. Check API Key.")
        
        # Define the system prompt to guide the AI's persona
        system_prompt = (
            "You are the SISTec College Admission Assistant. "
            "Your goal is to provide accurate, helpful, and friendly information "
            "about SISTec college admissions, courses, facilities, and campus life. "
            "Keep your responses concise and professional."
        )

        # Call the Gemini API for a grounded response (using Google Search for real-time data)
        response = client.models.generate_content(
            model='gemini-2.5-flash', # Use a stable, fast model
            contents=[user_query],
            config={
                "system_instruction": system_prompt,
                "tools": [{"google_search": {}}] # Enable Google Search for grounding
            }
        )
        
        bot_response = response.text
        
        # Extract citations (optional but good for showing sources)
        sources = []
        if response.candidates and response.candidates[0].grounding_metadata and response.candidates[0].grounding_metadata.grounding_attributions:
            sources = [
                {
                    'title': attr.web.title, 
                    'uri': attr.web.uri
                } 
                for attr in response.candidates[0].grounding_metadata.grounding_attributions
            ]
            
            # Format sources for display (e.g., append to the response)
            if sources:
                source_text = "\n\n**Sources:**\n"
                for i, source in enumerate(sources):
                    source_text += f"{i+1}. [{source['title']}]({source['uri']})\n"
                bot_response += source_text

        save_chat_entry(user_id, user_query, bot_response)
        
        return jsonify({'response': bot_response}), 200

    except APIError as api_err:
        # This catches errors specific to the Gemini API (e.g., invalid key, rate limits)
        logging.error(f"Gemini API Call Failed: {api_err}")
        # Return a user-friendly error message
        return jsonify({
            'response': "I'm sorry, I'm currently unable to access my knowledge base (Gemini API). Please inform the Admin team. (Status: API Configuration Error)"
        }), 500

    except Exception as e:
        # General exception handling (e.g., malformed request, database error)
        logging.error(f"Chat processing error: {e}")
        # Return the original error message for the Admin team
        return jsonify({
            'response': "I couldn't process this query due to an external service error. The query has been forwarded to the Admin team for manual review.", 
            'status': 'Pending Admin Review'
        }), 500

# --- MAIN RUN ---

if __name__ == '__main__':
    # Use 0.0.0.0 for external visibility in deployment environments like Render
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
