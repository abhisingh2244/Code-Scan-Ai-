import os

# --- ANOMALY 1: Hardcoded Secret ---
# Semgrep will find this
def get_db_connection():
    password = "super-secret-password-123" # This is a hardcoded secret
    if not password:
        password = os.environ.get("DB_PASS")
    
    return f"connecting_with:{password}"

# --- ANOMALY 2: Dangerous function ---
# Semgrep will find this
def run_command(request_data):
    command = request_data.get("command")
    os.system(command) # This is a command injection vulnerability
    
print("Vulnerable app loaded.")