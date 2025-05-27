# app.py - Render-ready version
import os
from datetime import datetime
from typing import List, Dict
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Using PostgreSQL for Render
import psycopg2
from psycopg2.extras import RealDictCursor

# For the AI chat interface
import gradio as gr

# For AI functionality with Anthropic
from anthropic import Anthropic

# Database connection with Render's DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Get database connection - works with both local and Render"""
    if DATABASE_URL:
        # Render provides DATABASE_URL
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        # For local development - don't try to connect if no database
        print("No DATABASE_URL found - running without database features")
        return None

# Initialize database
def init_db():
    """Create tables if they don't exist"""
    conn = get_db_connection()
    if not conn:
        print("Skipping database initialization - no connection available")
        return
        
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        date TIMESTAMP,
        description TEXT,
        debit_account TEXT,
        credit_account TEXT,
        amount DECIMAL(10,2),
        ai_categorized BOOLEAN DEFAULT FALSE
    )
    ''')
    conn.commit()
    conn.close()

# Initialize on startup
init_db()

# Common accounts for quick reference
COMMON_ACCOUNTS = {
    "income": ["Revenue:Sales", "Revenue:Services", "Revenue:Other"],
    "expenses": ["Expenses:Food", "Expenses:Transport", "Expenses:Office", "Expenses:Marketing"],
    "assets": ["Assets:Cash", "Assets:Bank", "Assets:Receivables"],
    "liabilities": ["Liabilities:CreditCard", "Liabilities:Loans"]
}

class AIAccountant:
    def __init__(self):
        # Get Anthropic key from environment
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            self.client = Anthropic(api_key=api_key)
        else:
            self.client = None
            print("Warning: No ANTHROPIC_API_KEY found. Running without AI features.")
        
    def process_natural_language(self, user_input: str) -> str:
        """Process natural language and convert to accounting action"""
        
        # Use Claude for smarter parsing if available
        if self.client:
            try:
                message = self.client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=150,
                    temperature=0,
                    system="You are an accounting assistant. Parse user input and respond with: EXPENSE, INCOME, or QUERY followed by relevant details.",
                    messages=[{"role": "user", "content": user_input}]
                )
                
                ai_response = message.content[0].text
                
                # Process based on AI classification
                if "EXPENSE" in ai_response:
                    return self.record_expense(user_input)
                elif "INCOME" in ai_response:
                    return self.record_income(user_input)
                else:
                    return self.handle_query(user_input)
                    
            except Exception as e:
                print(f"AI error: {e}")
                # Fall through to pattern matching
        
        # Fallback to simple pattern matching
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ['bought', 'paid', 'spent']):
            return self.record_expense(user_input)
        elif any(word in user_input_lower for word in ['received', 'earned', 'got paid']):
            return self.record_income(user_input)
        elif any(word in user_input_lower for word in ['show', 'what', 'how much', 'balance']):
            return self.handle_query(user_input)
        else:
            return "I can help you record transactions or check balances. Try saying 'I spent $X on Y' or 'Show me my expenses'"
    
    def record_expense(self, text: str) -> str:
        """Parse and record an expense"""
        # Extract amount (simple regex for now)
        import re
        amount_match = re.search(r'\$?(\d+\.?\d*)', text)
        if not amount_match:
            return "I couldn't find an amount. Please include a number like '$25' or '25.50'"
        
        amount = float(amount_match.group(1))
        
        # Simple categorization
        category = "Expenses:General"
        if any(word in text.lower() for word in ['food', 'lunch', 'dinner', 'coffee']):
            category = "Expenses:Food"
        elif any(word in text.lower() for word in ['gas', 'uber', 'taxi', 'parking']):
            category = "Expenses:Transport"
        
        # Record transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (date, description, debit_account, credit_account, amount, ai_categorized)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (datetime.now(), text, category, "Assets:Cash", amount, True))
        conn.commit()
        conn.close()
        
        return f"✓ Recorded: {category} ${amount:.2f}\nDescription: {text}"
    
    def record_income(self, text: str) -> str:
        """Parse and record income"""
        import re
        amount_match = re.search(r'\$?(\d+\.?\d*)', text)
        if not amount_match:
            return "I couldn't find an amount. Please include a number."
        
        amount = float(amount_match.group(1))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (date, description, debit_account, credit_account, amount, ai_categorized)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (datetime.now(), text, "Assets:Bank", "Revenue:Sales", amount, True))
        conn.commit()
        conn.close()
        
        return f"✓ Recorded income: ${amount:.2f}\nDescription: {text}"
    
    def handle_query(self, text: str) -> str:
        """Handle balance and report queries"""
        if 'balance' in text.lower():
            return self.get_balances()
        elif 'expense' in text.lower():
            return self.get_expenses_summary()
        else:
            return self.get_recent_transactions()
    
    def get_balances(self) -> str:
        """Calculate account balances"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                debit_account as account,
                SUM(amount) as total
            FROM transactions
            GROUP BY debit_account
            
            UNION ALL
            
            SELECT 
                credit_account as account,
                -SUM(amount) as total
            FROM transactions
            GROUP BY credit_account
        ''')
        
        balances = {}
        for row in cursor.fetchall():
            account, amount = row
            balances[account] = balances.get(account, 0) + float(amount)
        
        conn.close()
        
        result = "**Account Balances:**\n"
        for account, balance in sorted(balances.items()):
            if balance != 0:  # Only show non-zero balances
                result += f"{account}: ${abs(balance):.2f} {'DR' if balance > 0 else 'CR'}\n"
        
        return result
    
    def get_recent_transactions(self) -> str:
        """Get recent transactions"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT date, description, amount, debit_account, credit_account
            FROM transactions
            ORDER BY date DESC
            LIMIT 5
        ''')
        
        result = "**Recent Transactions:**\n"
        for row in cursor.fetchall():
            date, desc, amount, debit, credit = row
            date_str = date.strftime("%m/%d")
            result += f"{date_str}: {desc[:30]}... ${float(amount):.2f}\n"
        
        conn.close()
        return result
    
    def get_expenses_summary(self) -> str:
        """Get expense summary"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT debit_account, SUM(amount) as total
            FROM transactions
            WHERE debit_account LIKE 'Expenses:%'
            GROUP BY debit_account
            ORDER BY total DESC
        ''')
        
        result = "**Expense Summary:**\n"
        total = 0
        for row in cursor.fetchall():
            account, amount = row
            amount_float = float(amount)
            result += f"{account}: ${amount_float:.2f}\n"
            total += amount_float
        
        result += f"\n**Total Expenses: ${total:.2f}**"
        conn.close()
        return result

# Initialize AI Accountant
ai_accountant = AIAccountant()

# Create Gradio interface
def chat_with_accountant(message, history):
    """Process user message and return response"""
    response = ai_accountant.process_natural_language(message)
    return response

# Build the interface
demo = gr.ChatInterface(
    fn=chat_with_accountant,
    title="AI Accounting Assistant",
    description="Just tell me about your transactions in plain English!",
    examples=[
        "I spent $45 on groceries",
        "Got paid $5000 from client project",
        "Show me my balance",
        "What are my expenses?",
        "I bought coffee for $4.50"
    ],
    theme=gr.themes.Soft()
)

if __name__ == "__main__":
    print("Starting AI Accounting Assistant...")
    # Get port from environment or default to 7860
    port = int(os.getenv("PORT", 7860))
    # Launch with server_name 0.0.0.0 for Render
    demo.launch(server_name="0.0.0.0", server_port=port)