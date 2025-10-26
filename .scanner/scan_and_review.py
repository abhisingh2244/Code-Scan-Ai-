import os
import sys
import json
import requests
import subprocess

# --- 1. Configuration ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini" # Use a fast, cheap, and powerful model

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("REPO_NAME")
PR_NUMBER = os.environ.get("PR_NUMBER")
BASE_REF = os.environ.get("BASE_REF") # e.g., "main"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_NAME}/issues/{PR_NUMBER}/comments"

SCANNER_RESULTS_FILE = "semgrep_results.json"


def call_openai(system_prompt, user_prompt):
    """Generic function to call the OpenAI Chat API."""
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set.")
        return "Error: OPENAI_API_KEY not set."

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=data, timeout=180)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        print(f"Error calling OpenAI: {e}")
        return f"Error connecting to AI: {e}"


# --- 2. Git & File Helpers ---

def get_pr_diff():
    """Gets the git diff for the PR against the base branch."""
    try:
        # Diff against the forked (origin) base branch
        diff_command = ["git", "diff", f"origin/{BASE_REF}"]
        result = subprocess.run(diff_command, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error getting git diff: {e}")
        return None

def load_scanner_results(filepath):
    """Loads the JSON results from the Semgrep scan."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Scanner results file not found.")
        return None
    except json.JSONDecodeError:
        print("Error decoding scanner JSON.")
        return None

def get_code_snippet(file_path, start_line, end_line):
    """Extracts a specific code snippet from a file."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        # Adjust for 0-based indexing and ensure we don't go out of bounds
        start = max(0, start_line - 1)
        end = min(len(lines), end_line)
        return "".join(lines[start:end])
    except FileNotFoundError:
        return f"Code snippet for {file_path} not found."

# --- 3. AI Analysis Functions ---

def get_ai_summary(diff_content):
    """Task 1: AI-Powered Pull Request Summary"""
    print("Getting AI summary for PR diff...")
    system_prompt = (
        "You are an expert code reviewer. "
        "Review the following git diff and provide a concise, high-level summary of the changes. "
        "Focus on the 'why' of the change, not just listing the files. Use bullet points."
    )
    user_prompt = f"Git Diff:\n\n{diff_content}"
    
    return call_openai(system_prompt, user_prompt)

def get_ai_fixes(scanner_results):
    """Task 2: AI-Generated Fixes for Scanner Issues"""
    print(f"Analyzing {len(scanner_results.get('results', []))} scanner findings...")
    ai_fixes = []
    
    # Check if 'results' key exists and is a list
    findings = scanner_results.get('results')
    if not findings or not isinstance(findings, list):
        print("No valid findings in scanner results.")
        return []

    for finding in findings:
        path = finding['path']
        start_line = finding['start']['line']
        end_line = finding['end']['line']
        message = finding['extra']['message']
        
        # Get the vulnerable code
        code_snippet = get_code_snippet(path, start_line, end_line)
        
        system_prompt = (
            "You are an expert security developer and code reviewer. "
            "A static analysis tool has found the following issue. "
            "Your task is to:\n"
            "1. Briefly explain the *risk* of this issue in simple terms.\n"
            "2. Provide a clear, actionable code suggestion to fix it.\n"
            "3. Format your response clearly with 'Risk:' and 'Suggestion:' labels."
        )
        user_prompt = (
            f"**File:** `{path}` (Lines {start_line}-{end_line})\n\n"
            f"**Issue:** {message}\n\n"
            f"**Vulnerable Code Snippet:**\n```\n{code_snippet}\n```"
        )
        
        fix_suggestion = call_openai(system_prompt, user_prompt)
        
        # Add the file path to the suggestion for context
        full_suggestion = f"**File: `{path}` (Lines {start_line}-{end_line})**\n\n{fix_suggestion}"
        ai_fixes.append(full_suggestion)

    return ai_fixes

# --- 4. Main Orchestration ---

def format_final_comment(summary, fixes):
    """Builds the final Markdown comment to be posted on the PR."""
    body = "## 🤖 CodeScan-AI Review\n\n"
    body += "### 📝 PR Summary\n"
    body += f"{summary}\n\n"
    body += "---\n\n"
    
    if fixes:
        body += "### 🚨 Anomalies Detected\n\n"
        body += "I found the following issues that should be addressed:\n\n"
        body += "\n\n---\n\n".join(fixes)
    else:
        body += "### ✅ No Anomalies Found\n\n"
        body += "My automated scan found no critical issues. Great job!"
        
    return body

def post_to_pr(comment_body):
    """Posts the final comment to the GitHub Pull Request."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    data = {"body": comment_body}
    
    try:
        response = requests.post(GITHUB_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        print("Successfully posted comment to PR.")
    except requests.RequestException as e:
        print(f"Error posting to GitHub: {e}")
        if e.response:
            print(f"Response body: {e.response.text}")

def main():
    if not all([OPENAI_API_KEY, GITHUB_TOKEN, REPO_NAME, PR_NUMBER, BASE_REF]):
        print("Error: Missing one or more environment variables.")
        sys.exit(1)

    diff = get_pr_diff()
    if not diff:
        print("Could not get PR diff. Exiting.")
        sys.exit(1)
        
    scanner_results = load_scanner_results(SCANNER_RESULTS_FILE)
    if not scanner_results:
        print("Could not load scanner results. Exiting.")
        sys.exit(1)
    
    ai_summary = get_ai_summary(diff)
    ai_fixes = get_ai_fixes(scanner_results)
    
    final_comment = format_final_comment(ai_summary, ai_fixes)
    
    print("\n--- Final Comment ---")
    print(final_comment)
    print("---------------------\n")
    
    post_to_pr(final_comment)

if __name__ == "__main__":
    main()