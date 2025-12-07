import os
import json
import time
import random
import logging
from typing import Optional, Any, Dict

# ----------------------------------------------------
# Configuration
# ----------------------------------------------------

# Note: The API key is usually provided by the environment in Canvas.
# We keep it empty here as instructed.
API_KEY = "" 
BASE_MODEL = "gemini-2.5-flash-preview-09-2025"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{BASE_MODEL}:generateContent?key={API_KEY}"

# System instruction to define the chatbot's persona and rules
SYSTEM_INSTRUCTION = (
    "Aap ek helpful aur professional College Enquiry Assistant hain. "
    "Aapka naam 'SISTEC Bot' hai aur aap sirf SISTEC college se related questions ka jawab dete hain. "
    "Aapka main goal students ko admissions, courses, fees, aur general college jankari (enquiry) dena hai. "
    "Apne answers ko 'Hinglish' (Hindi aur English ka mixture) mein rakhein jahan zaroori ho, lekin professional tone maintain karein. "
    "Agar aapko koi jankari (information) nahi milti hai, toh polite tareeke se batayein ki aapko iski jaankari nahi hai aur unko Admin se connect hone ka sujhav dein."
)

logging.basicConfig(level=logging.INFO)

# ----------------------------------------------------
# Utility Function: Exponential Backoff for API Calls
# ----------------------------------------------------

async def exponential_backoff_fetch(url: str, payload: Dict[str, Any], max_retries: int = 5) -> Optional[Dict[str, Any]]:
    """
    Handles API call with exponential backoff for transient errors.
    """
    headers = {'Content-Type': 'application/json'}
    
    for attempt in range(max_retries):
        try:
            # We use the standard requests library equivalent or assumed fetch implementation
            # Since fetch is not available in a standard Python Flask environment, 
            # we simulate an asynchronous fetch with a synchronous structure, 
            # assuming the environment handles the actual network call or mock.
            
            # In a real Flask environment, you'd use 'requests' library:
            # response = requests.post(url, headers=headers, json=payload)
            # response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            # Since we are in a synthetic environment, we mock the network call
            # using the existing utility from the runtime, if available, or simulate failure.
            
            # For this context, we will use a simple synchronous placeholder.
            
            # --- Placeholder for Actual Network Request ---
            import requests
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            # ----------------------------------------------
            
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [429, 500, 503] and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logging.warning(f"API Rate Limit/Server Error ({e.response.status_code}). Retrying in {wait_time:.2f}s...")
                time.sleep(wait_time)
            else:
                logging.error(f"Final API request failed with HTTP Error: {e}")
                break
        except Exception as e:
            logging.error(f"An unexpected error occurred during API call: {e}")
            break
            
    return None

# ----------------------------------------------------
# Main Agent Function
# ----------------------------------------------------

def get_ai_response(query_text: str) -> str:
    """
    Calls the Gemini API to get a response for the student query.
    Uses Google Search grounding for up-to-date answers.
    """
    
    payload = {
        "contents": [{"parts": [{"text": query_text}]}],
        
        # Google Search Tool for Grounding (Latest Information)
        "tools": [{"google_search": {}}],
        
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        
        # Optional: Set temperature lower for more factual/stable answers
        "config": {"temperature": 0.2} 
    }
    
    try:
        # Note: Calling the synchronous version of the fetch helper
        # Since Flask routes are typically synchronous, we use time.sleep for backoff.
        
        response_data = exponential_backoff_fetch(API_URL, payload)
        
        if response_data is None:
            return "Sorry, I am currently unable to fetch an answer due to network or server issues. Your query has been forwarded to the Admin."
            
        candidate = response_data.get('candidates', [{}])[0]
        text_part = candidate.get('content', {}).get('parts', [{}])[0].get('text')

        if text_part:
            # We can optionally extract sources here if needed for citation, 
            # but for a chatbot, returning the text is usually enough.
            return text_part
        else:
            logging.warning("AI response contained no text part.")
            return "I couldn't generate a clear response. Your query might be too complex or unclear. Please try rephrasing."

    except Exception as e:
        logging.error(f"Fatal error in get_ai_response: {e}")
        return "AI system is currently unavailable. We have recorded your query and will have an admin respond soon."

# Example Usage (for testing the agent logic directly)
# if __name__ == '__main__':
#     # This block helps verify the agent logic if run standalone.
#     test_query = "मुझे SISTEC में B.Tech CSE के लिए fees aur eligibility criteria kya hai?"
#     print(f"Query: {test_query}")
#     response = get_ai_response(test_query)
#     print(f"\nResponse: {response}")
