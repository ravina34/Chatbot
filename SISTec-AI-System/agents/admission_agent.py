import os
import requests
import json
import logging
import time

# ===============================================
# AI CONFIGURATION
# ===============================================
# API Key must be set in Render environment variable: GEMINI_API_KEY
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', "")
# API Endpoint and Model
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"
MODEL_NAME = "gemini-2.5-flash-preview-09-2025"

# System Instruction to define the AI's persona
SYSTEM_PROMPT = (
    "You are the SIStec AI College Assistant. Your primary function is to answer student queries "
    "about the college, courses, admissions, fees, and general information concisely and professionally. "
    "Use Google Search for grounding to ensure all facts are up-to-date and reliable. "
    "If you are asked a question that is clearly outside the scope of college information (e.g., 'What is the meaning of life?'), "
    "politely state that your function is limited to college-related queries."
)

def get_ai_response(query_text: str) -> str:
    """
    Calls the Gemini API to get a response for the student's query.
    
    Returns: The generated text response from the AI (may include sources).
    """
    if not GEMINI_API_KEY:
        logging.error("GEMINI_API_KEY is not set. Cannot call AI.")
        return "AI system is currently unavailable. Please contact the admin."

    # Construct the API payload
    payload = {
        "contents": [{"parts": [{"text": query_text}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        # Enable Google Search grounding for up-to-date information
        "tools": [{"google_search": {}}],
        "model": MODEL_NAME
    }

    headers = {
        'Content-Type': 'application/json'
    }

    # Use exponential backoff for resilience
    max_retries = 3
    for attempt in range(max_retries):
        try:
            full_url = f"{API_URL}?key={GEMINI_API_KEY}"
            response = requests.post(full_url, headers=headers, data=json.dumps(payload), timeout=20)
            response.raise_for_status()
            
            result = response.json()
            
            # --- Text Extraction ---
            text_part = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0]
            text = text_part.get('text', 'No response found.')
            
            # --- Citation Extraction ---
            sources = []
            grounding_metadata = result.get('candidates', [{}])[0].get('groundingMetadata')
            if grounding_metadata and grounding_metadata.get('groundingAttributions'):
                sources = grounding_metadata['groundingAttributions']
                
            if sources:
                source_links = "\n\n--- Sources ---\n" + "\n".join([
                    f"[{s.get('web', {}).get('title', 'Source Link')}]({s.get('web', {}).get('uri', '#')})" 
                    for s in sources if s.get('web', {}).get('uri')
                ])
                # Add Markdown line breaks for clean display
                return text.replace('\n', '<br>') + source_links.replace('\n', '<br>')

            return text.replace('\n', '<br>')

        except requests.exceptions.Timeout:
            logging.warning(f"AI API Call timed out on attempt {attempt + 1}")
        except requests.exceptions.RequestException as e:
            logging.error(f"AI API Call failed on attempt {attempt + 1}: {e}")
        except Exception as e:
            logging.error(f"Error processing AI response on attempt {attempt + 1}: {e}")
        
        # Exponential backoff delay
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    return "Sorry, I am currently unable to fetch an answer from the AI. Please try again later or contact the admin."
