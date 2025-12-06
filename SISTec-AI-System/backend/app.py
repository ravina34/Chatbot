import os
import requests
import json
from functools import wraps
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2

app = Flask(__name__)
# Replace with your actual secret key
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key_change_me")

# --- Database Connection Setup ---
# Use the DATABASE_URL from Render environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    # Use the connection string provided by Render
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# --- API Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash" # Fast and capable model

def ask_gemini(user_query, system_instruction):
    """
    Sends a query to the Gemini API and returns the response text.
    Uses Google Search grounding for up-to-date information.
    """
    if not GEMINI_API_KEY:
        return "Error: Gemini API Key is not configured."

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    # Define the core instructions and the query
    contents = [{
        "parts": [{"text": user_query}]
    }]

    # System instruction to guide the AI's persona
    system_instruction_part = {
        "parts": [{"text": system_instruction}]
    }

    # Payload for the API call
    payload = {
        "contents": contents,
        "systemInstruction": system_instruction_part,
        # Enable Google Search grounding for real-time information
        "tools": [{"google_search": {}}]
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": GEMINI_API_KEY  # Pass the API key in the header
    }

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)

        data = response.json()

        # Extract the text from the response
        generated_text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', 'AI response not found.')

        # Optionally, extract and append citations/sources
        # We will keep it simple for now and just return the text.
        return generated_text

    except requests.exceptions.RequestException as e:
        print(f"API Request Error: {e}")
        return "Sorry, I am having trouble connecting to the AI service right now."
    except Exception as e:
        print(f"General Error: {e}")
        return "An unexpected error occurred."


# Decorator to ensure user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# --- Flask Routes ---

# (Keep your existing home, register, login, logout routes here)

# New Route for AI Chat Interface
@app.route('/ai_chat', methods=['GET', 'POST'])
@login_required
def ai_chat():
    conn = get_db_connection()
    cur = conn.cursor()
    user_id = session['user_id']
    
    # Define the system instruction for the AI (College Enquiry Persona)
    college_persona = (
        "You are a friendly and highly knowledgeable College Enquiry Chatbot. "
        "Your role is to provide accurate, up-to-date, and helpful information about colleges, "
        "courses, admission requirements, fees, and career paths. "
        "Always answer questions concisely and politely. If you don't know the answer, "
        "state that you do not have that specific information."
    )

    if request.method == 'POST':
        user_query = request.form.get('user_query')
        if user_query:
            # 1. Get AI Response
            ai_response = ask_gemini(user_query, college_persona)

            # 2. Save Query and Response to Database (using the 'queries' table you need to create)
            try:
                cur.execute(
                    "INSERT INTO queries (user_id, query_text, response_text, query_status) VALUES (%s, %s, %s, 'completed')",
                    (user_id, user_query, ai_response)
                )
                conn.commit()
            except Exception as db_error:
                print(f"Database error saving query: {db_error}")
                ai_response = f"AI Response: {ai_response}\n(Warning: Database failed to save history.)"

            # Use a technique like redirecting to GET or returning a JSON response
            # For simplicity, we'll redirect back to show the updated history.
            return redirect(url_for('ai_chat'))
        
    # GET request logic (Load chat history)
    try:
        cur.execute(
            "SELECT query_text, response_text FROM queries WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
            (user_id,)
        )
        chat_history_rows = cur.fetchall()
        # Convert rows into a list of dictionaries for easier template rendering
        chat_history = [{'query': row[0], 'response': row[1]} for row in chat_history_rows]
    except Exception as db_error:
        print(f"Database error fetching history: {db_error}")
        chat_history = [] # Fallback to empty list if table doesn't exist yet
    finally:
        cur.close()
        conn.close()

    return render_template('ai_chat.html', chat_history=chat_history)

# ... (Add other routes and functions below this)

# Example placeholder routes (You must implement these in full)
@app.route('/', methods=['GET'])
def home():
    return "Welcome to the College Enquiry System. <a href='/login'>Login</a> or <a href='/register'>Register</a>"

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Placeholder for registration logic
    return "Registration Page" 

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Placeholder for login logic
    return "Login Page" 

# --- Ensure you run the app ---
if __name__ == '__main__':
    app.run(debug=True)
