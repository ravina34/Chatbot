from flask import Flask, render_template, request, redirect, url_for, session, abort, Response
import psycopg2
import os

# --- Path Configuration (Template Folder Fix) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Assumes 'frontend' folder is one level up from app.py, if app.py is in 'backend'
TEMPLATE_DIR = os.path.join(BASE_DIR, '..', 'frontend')
app = Flask(__name__, template_folder=TEMPLATE_DIR)

# Session secret key for managing user login state
# IMPORTANT: Change this to a truly random value in production
app.secret_key = 'super_secret_key_for_sistec_ai'
# -----------------------------------------------

# Database Connection function
def get_db_connection():
    # PostgreSQL database se connect karta hai aur connection object return karta hai.
    # NOTE: Please ensure your database settings (host, dbname, user, password) are correct.
    return psycopg2.connect(
        host="localhost",
        database="Chatbot",
        user="postgres",
        password="root"
    )

# --- Main Landing Page ---
@app.route("/")
def home():
    # Home page render karta hai jahan se user Student/Admin select karta hai.
    return render_template("home.html")

# --- HELPER FUNCTION: Get Student Info (from 'users' table) ---
def get_student_info(email):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetches data from the 'users' table
        cur.execute("SELECT user_id, full_name, password FROM users WHERE email = %s;", (email,))
        user_data = cur.fetchone()

        if user_data:
            # Returns (user_id, full_name, password)
            return user_data
        return None
    except psycopg2.Error as e:
        print(f"Database error while fetching student: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- HELPER FUNCTION: Get Admin Info (from 'admin' table) ---
def get_admin_info(email):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetches data from the dedicated 'admin' table
        cur.execute("SELECT email, password FROM admin WHERE email = %s;", (email,))
        admin_data = cur.fetchone()

        if admin_data:
            # Returns (email, password)
            return admin_data
        return None
    except psycopg2.Error as e:
        print(f"Database error while fetching admin: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- 1. Registration Route ---
@app.route("/register", methods=["GET", "POST"])
def register():
    conn = None
    cur = None
    error_message = None

    if request.method == "POST":
        try:
            # Extract form data
            name = request.form["name"]
            address = request.form.get("address", "")
            mobile = request.form.get("mobile", "")
            email = request.form["email"]
            password = request.form["password"]

            if not all([name, email, password]):
                error_message = "All fields are required."
                return render_template("register.html", error=error_message)

            conn = get_db_connection()
            cur = conn.cursor()

            # Check if user already exists in 'users' table
            if get_student_info(email):
                error_message = "This email address is already registered. Please login."
                return render_template("register.html", error=error_message)

            # Insert new user into the database
            cur.execute("""
                INSERT INTO users (full_name, email, mobile, password, address)
                VALUES (%s, %s, %s, %s, %s);
            """, (name, email, mobile, password, address))

            conn.commit()

            # Registration successful, redirect to Student Login
            return redirect(url_for('student_login_page'))

        except psycopg2.IntegrityError:
            if conn: conn.rollback()
            error_message = "This email address is already registered. Please login."

        except psycopg2.Error as e:
            if conn: conn.rollback()
            print(f"Database error during registration: {e}")
            error_message = "Registration failed due to a server error."

        finally:
            if cur: cur.close()
            if conn: conn.close()

    return render_template("register.html", error=error_message)

# --- 2A. Student Login Route (/login) ---
@app.route("/login", methods=["GET", "POST"])
def student_login_page():
    error_message = None

    if request.method == "POST":
        email = request.form["email"]
        input_password = request.form["password"]

        user_info = get_student_info(email)

        if user_info:
            user_id, full_name, stored_password = user_info

            if input_password == stored_password:
                # Student login successful
                session.clear()
                session['logged_in'] = True
                session['user_id'] = user_id
                session['full_name'] = full_name
                session['role'] = 'student' # Set role

                return redirect(url_for('user_chat_page'))
            else:
                error_message = "Invalid email or password."
        else:
            error_message = "Invalid email or password."

    return render_template("st_login.html", error=error_message)

# --- 2B. Admin Login Route (/admin_login) ---
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login_page():
    error_message = None

    if request.method == "POST":
        email = request.form["email"]
        input_password = request.form["password"]

        admin_info = get_admin_info(email)

        if admin_info:
            _, stored_password = admin_info # email is the first item, password is the second

            if input_password == stored_password:
                # Admin login successful
                session.clear()
                session['logged_in'] = True
                session['email'] = email # Storing email for Admin, as Admin table doesn't have user_id/full_name
                session['role'] = 'admin' # Set role

                return redirect(url_for('admin'))
            else:
                error_message = "Invalid email or password."
        else:
            error_message = "Invalid email or password."

    return render_template("ad_login.html", error=error_message)

# --- Logout Route ---
@app.route("/logout")
def logout():
    # Logout ke baad, session clear karo aur Student Login par redirect karo
    session.clear()
    return redirect(url_for('student_login_page'))

# --- User Chat Page (Protected) ---
@app.route("/user", methods=["GET", "POST"])
def user_chat_page():

    # Security Check: Must be logged in AND must be a student
    if not session.get('logged_in') or session.get('role') != 'student':
        return redirect(url_for('student_login_page'))

    user_id = session.get('user_id')
    conn = None
    cur = None

    # NEW SAFETY CHECK: Check if user_id is valid before proceeding to database operations
    if user_id is None or (not isinstance(user_id, int) and not str(user_id).isdigit()):
        print(f"Session Error: Invalid or missing user_id in session: {user_id}. Clearing session.")
        session.clear()
        return redirect(url_for('student_login_page'))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == "POST":
            # Handle new query submission
            query_text = request.form["query_text"].strip()

            if not query_text:
                # ignore empty queries
                return redirect(url_for('user_chat_page'))

            # --------- DUPLICATE QUESTION CHECK (search across answered queries) ---------
            # We search for any previously answered query with same text (case-insensitive).
            cur.execute("""
                SELECT q.query_id, r.response_text
                FROM queries q
                JOIN query_responses r ON q.query_id = r.query_id
                WHERE LOWER(q.query_text) = LOWER(%s)
                  AND r.response_text IS NOT NULL
                ORDER BY q.query_id DESC
                LIMIT 1;
            """, (query_text,))
            found = cur.fetchone()

            if found:
                # Old answered query found -> create a new query record but auto-fill with old answer
                old_qid, old_answer = found

                # Insert new query and mark as answered
                cur.execute("""
                    INSERT INTO queries(user_id, query_text, status)
                    VALUES (%s, %s, %s)
                    RETURNING query_id;
                """, (user_id, query_text, 'answered'))
                new_qid = cur.fetchone()[0]

                # Copy the old answer into query_responses for the new query
                cur.execute("""
                    INSERT INTO query_responses(query_id, response_text)
                    VALUES (%s, %s);
                """, (new_qid, old_answer))

                conn.commit()
                return redirect(url_for('user_chat_page'))

            # If not found -> normal flow: create pending query
            cur.execute("""
                INSERT INTO queries(user_id, query_text, status)
                VALUES (%s, %s, %s);
            """, (user_id, query_text, 'pending'))
            conn.commit()

            return redirect(url_for('user_chat_page')) # Single redirect after successful POST

        # GET: Fetch all previous queries and responses for the user, including status
        cur.execute("""
           SELECT q.query_id, q.query_text, r.response_text, q.status
FROM queries q
LEFT JOIN query_responses r ON q.query_id = r.query_id
WHERE q.user_id = %s
ORDER BY q.query_id DESC;

        """, (user_id,))
        rows = cur.fetchall() # rows is a list of (query_id, query_text, response_text, status)

        # Also compute pending count for this user (helpful for UI)
        cur.execute("""
            SELECT COUNT(*) FROM queries
            WHERE user_id = %s AND (status IS NULL OR status != 'answered');
        """, (user_id,))
        pending_count = cur.fetchone()[0] if cur.rowcount != 0 else 0

        # Renders the st_dashboard.html (Student Chat Interface)
        return render_template("st_dashboard.html", queries=rows, full_name=session.get('full_name'), pending_count=pending_count)

    except psycopg2.Error as e:
        # Proper error handling: print error, rollback, and return 500 error page
        print(f"Database error in user_chat_page route: {e}")
        if conn:
            conn.rollback() # Ensure no partial transactions are committed
        return "A database error occurred.", 500

    finally:
        # Ensure connections are closed regardless of success or failure
        if cur: cur.close()
        if conn: conn.close()

# --- Admin Page (Protected) ---
@app.route("/admin", methods=["GET", "POST"])
def admin():
    # Security Check: Must be logged in AND must be an admin (using the new session['role'])
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('admin_login_page'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == "POST":
            # Handle admin response submission
            query_id = request.form["query_id"]
            response_text = request.form["response_text"]

            # 1. Insert response
            cur.execute("INSERT INTO query_responses(query_id, response_text) VALUES (%s, %s);", (query_id, response_text))

            # 2. Update query status to 'answered'
            cur.execute("UPDATE queries SET status='answered' WHERE query_id=%s;", (query_id,))

            conn.commit()

            return redirect(url_for('admin'))

        # Fetch all pending queries (where there is no response yet)
        cur.execute("""
        SELECT q.query_id, q.query_text, u.full_name
        FROM queries q
        LEFT JOIN query_responses r ON q.query_id = r.query_id
        JOIN users u ON q.user_id = u.user_id
        WHERE r.response_id IS NULL
        ORDER BY q.query_id ASC;
        """)
        rows = cur.fetchall()

        return render_template("ad_dash.html", queries=rows)

    except psycopg2.Error as e:
        print(f"Database error in admin route: {e}")
        if conn: conn.rollback()
        return "A database error occurred.", 500

    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- Placeholder for Success Page (redirecting to student login) ---
@app.route("/success")
def success_page():
    return redirect(url_for('student_login_page'))

if __name__ == "__main__":
    app.run(debug=True)
