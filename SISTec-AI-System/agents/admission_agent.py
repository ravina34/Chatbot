import json
import logging
import time
import requests
import os

# --- Configuration for Gemini API ---
# Note: In the actual runtime environment, API key handling might be managed 
# by the Canvas platform, but we set up the structure for clarity.
# Using a placeholder for the API key and model endpoint.
API_KEY = os.environ.get('GEMINI_API_KEY', '') # Use empty string if not set
MODEL_NAME = 'gemini-2.5-flash-preview-09-2025' 
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"

# System instruction to define the AI's persona and mandate
SYSTEM_PROMPT = (
    "You are the friendly, professional, and knowledgeable Admissions and Support Counselor for the Sagar Institute of Science and Technology (SISTEC)."
    "Your primary goal is to provide accurate, concise, and helpful information related to admissions, courses, campus facilities, and general queries about the institution."
    "Maintain a respectful and encouraging tone, suitable for prospective or current students."
    "Always use the available Google Search tool to ensure your information is up-to-date and grounded in external facts, especially for sensitive or time-bound information like fees, dates, or contact details."
    "Respond in Hindi or English as requested by the user query. If the query is ambiguous, use English."
)

# Configure logging format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_ai_response(query_text: str) -> str:
    """
    Calls the Gemini API to get a grounded response based on the query.

    Args:
        query_text: The user's query text.

    Returns:
        The generated text response or a fallback error message.
    """
    
    # 1. Construct the API Payload
    payload = {
        "contents": [{"parts": [{"text": query_text}]}],
        # Enable Google Search grounding for real-time, accurate information
        "tools": [{"google_search": {}}],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.2
        }
    }

    headers = {
        'Content-Type': 'application/json'
    }

    # 2. Implement Exponential Backoff Retry Logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logging.info(f"Attempt {attempt + 1}: Sending query to Gemini API for: '{query_text[:30]}...'")
            
            # Making the API call
            response = requests.post(
                API_URL, 
                headers=headers, 
                data=json.dumps(payload), 
                timeout=20 # Set a reasonable timeout
            )
            
            # 3. Check for API errors (4xx or 5xx)
            if response.status_code >= 400:
                # Log the full response text (which contains the error details) for debugging
                error_details = response.text
                logging.error(f"Attempt {attempt + 1}: API call failed with status {response.status_code}. Details: {error_details}")
                # Raise the HTTPError to jump to the except block for retry logic
                response.raise_for_status() 

            # If successful (200 OK), parse the result
            result = response.json()
            candidate = result.get('candidates', [{}])[0]

            # Extract generated text
            if candidate and candidate.get('content') and candidate['content'].get('parts'):
                generated_text = candidate['content']['parts'][0].get('text', '').strip()
                if generated_text:
                    logging.info(f"Successfully received response on attempt {attempt + 1}. Response length: {len(generated_text)}")
                    return generated_text
            
            # If the response was successful but contained no content (e.g., blocked or empty response)
            logging.warning(f"AI response was empty or malformed on attempt {attempt + 1}. Full result: {result}")
            return "Sorry, I received an empty or malformed response from the AI. The query has been marked for Admin review."

        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, and HTTP errors caught by raise_for_status()
            if attempt < max_retries - 1:
                # Calculate delay using exponential backoff (1s, 2s, 4s)
                wait_time = 2 ** attempt
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                # Final attempt failed
                logging.error("All Gemini API attempts failed. Returning fallback message.")
                return "AI system is currently unavailable or timed out. Please try again later or wait for Admin assistance."
        except Exception as e:
            logging.error(f"Unexpected error processing AI response: {e}")
            return "Sorry, an internal error occurred while fetching the AI response."

    return "Sorry, I am currently unable to fetch an answer for this query."
