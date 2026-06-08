import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_ASSUMPTIONS_MODEL = os.getenv("GROQ_ASSUMPTIONS_MODEL", "llama-3.3-70b-versatile")
GROQ_PARSING_MODEL = os.getenv("GROQ_PARSING_MODEL","llama-3.3-70b-versatile")
STATEMENT_TEXT_MAX_CHARS = int(os.getenv("STATEMENT_TEXT_MAX_CHARS", "20000"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
COVER_PAGES_MAX = int(os.getenv("COVER_PAGES_MAX", "5"))
DEFAULT_TERM_G = 0.03      
DEFAULT_RISKF_R = 0.05      
DEFAULT_NUM_YEARS = 10      
DEFAULT_TAX_RATE = 0.25     