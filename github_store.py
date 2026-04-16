"""GitHub API persistence layer for tracker and screener results."""
import json, base64, urllib.request, urllib.error
from datetime import datetime
from config import GITHUB_TOKEN, GITHUB_REPO, TRACKER_FILE, SCREENER_FILE

def _gh_headers(): ...
def _gh_get_file(filepath): ...      # Generic - works for any file
def _gh_put_file(filepath, content, sha=None): ...

def load_tracker():     ...  # Returns (list, sha)
def save_tracker(content_list, sha): ...
def add_tracked_stock(ticker, company_name, rec, target, entry,
                      metrics, thesis, email): ...
def load_screener_results_raw(): ...  # No @st.cache - that's app.py's job
