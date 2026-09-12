import sys
from google import genai
from config import GEMINI_API_KEY
import traceback

def test_models():
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    models_to_test = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-flash-lite-latest"
    ]
    
    with open("model_test_results.txt", "w", encoding="utf-8") as f:
        for model_id in models_to_test:
            f.write(f"Testing {model_id}...\n")
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents="Say hello in 1 word."
                )
                f.write(f"Success! Response: {response.text.strip()}\n\n")
            except Exception as e:
                f.write(f"Failed: {type(e).__name__} - {str(e)}\n\n")

if __name__ == "__main__":
    test_models()
