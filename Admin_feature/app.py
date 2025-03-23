from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pandas as pd
import os
from werkzeug.exceptions import BadRequest
from datetime import datetime
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
CSV_FILE = "gst_faq_final.csv"
LOG_FILE = "change_logs.json"
ENTRIES_PER_PAGE = 10  # Limit entries shown per page

def load_kb():
    try:
        if os.path.exists(CSV_FILE):
            # Read CSV with proper encoding and handle any potential issues
            df = pd.read_csv(CSV_FILE, encoding='utf-8')
            
            # Ensure column names are correct
            if 'Question' not in df.columns or 'Answer' not in df.columns:
                raise ValueError("CSV file must contain 'Question' and 'Answer' columns")
            
            # Clean the data
            df['Question'] = df['Question'].str.strip()
            df['Answer'] = df['Answer'].str.strip()
            
            # Remove any empty rows
            df = df.dropna(subset=['Question', 'Answer'])
            
            # Remove duplicate questions (keeping the first occurrence)
            df = df.drop_duplicates(subset=['Question'], keep='first')
            
            # Sort by question for better organization
            df = df.sort_values('Question')
            
            # Reset index to ensure proper row numbering
            df = df.reset_index(drop=True)
            
            # Log the number of entries loaded
            app.logger.info(f"Successfully loaded {len(df)} entries from {CSV_FILE}")
            
            return df
        else:
            app.logger.error(f"CSV file {CSV_FILE} not found")
            return pd.DataFrame(columns=["Question", "Answer"])
    except Exception as e:
        app.logger.error(f"Error loading knowledge base: {str(e)}")
        return pd.DataFrame(columns=["Question", "Answer"])

def save_kb(df):
    try:
        # Ensure proper column order and clean data before saving
        df = df[['Question', 'Answer']]
        df['Question'] = df['Question'].str.strip()
        df['Answer'] = df['Answer'].str.strip()
        
        # Remove any empty rows
        df = df.dropna(subset=['Question', 'Answer'])
        
        # Remove duplicate questions (keeping the first occurrence)
        df = df.drop_duplicates(subset=['Question'], keep='first')
        
        # Sort by question for better organization
        df = df.sort_values('Question')
        
        df.to_csv(CSV_FILE, index=False, encoding='utf-8')
    except Exception as e:
        app.logger.error(f"Error saving knowledge base: {str(e)}")
        raise

def log_change(change_type, details):
    try:
        # Load existing logs
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
        
        # Add new log entry
        new_log = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": change_type,
            "details": details
        }
        
        logs.append(new_log)
        
        # Keep only last 30 days of logs
        thirty_days_ago = (datetime.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        logs = [log for log in logs if log["timestamp"].startswith(thirty_days_ago) or log["timestamp"] > thirty_days_ago]
        
        # Save updated logs
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        app.logger.error(f"Error logging change: {str(e)}")

@app.route('/')
def admin_panel():
    try:
        df = load_kb()
        
        # Log the number of entries loaded
        app.logger.info(f"Loaded {len(df)} entries from knowledge base")
        
        # Get only the first ENTRIES_PER_PAGE entries
        df_preview = df.head(ENTRIES_PER_PAGE)
        
        # Convert DataFrame to list of dictionaries with proper keys
        faqs = []
        for _, row in df_preview.iterrows():
            faqs.append({
                'Question': str(row['Question']).strip(),
                'Answer': str(row['Answer']).strip()
            })
        
        # Log the number of entries being sent to template
        app.logger.info(f"Sending {len(faqs)} entries to template")
        
        # Log the first entry to verify data structure
        if faqs:
            app.logger.info(f"First entry: {faqs[0]}")
            
        return render_template("admin.html", 
                             faqs=faqs,
                             total_entries=len(df))
    except Exception as e:
        app.logger.error(f"Error rendering admin panel: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/all-data')
def get_all_data():
    try:
        df = load_kb()
        return jsonify({"faqs": df.to_dict(orient='records')})
    except Exception as e:
        app.logger.error(f"Error getting all data: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/stats')
def get_stats():
    try:
        df = load_kb()
        stats = {
            "total_entries": len(df),
            "sample_entries": df.head(5).to_dict(orient='records'),
            "last_updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "unique_questions": len(df['Question'].unique())
        }
        return jsonify(stats)
    except Exception as e:
        app.logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/logs')
def get_logs():
    try:
        if not os.path.exists(LOG_FILE):
            return jsonify({"logs": []})
        
        with open(LOG_FILE, 'r') as f:
            logs = json.load(f)
        
        # Get logs from last 5 days
        five_days_ago = (datetime.now() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        recent_logs = [log for log in logs if log["timestamp"].startswith(five_days_ago) or log["timestamp"] > five_days_ago]
        
        return jsonify({"logs": recent_logs})
    except Exception as e:
        app.logger.error(f"Error getting logs: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/update', methods=['POST'])
def update_kb():
    try:
        data = request.get_json()
        if not data:
            raise BadRequest("No data provided")
        
        # Validate data structure
        if not isinstance(data, list):
            raise BadRequest("Data must be a list of FAQ entries")
        
        for entry in data:
            if not isinstance(entry, dict) or 'Question' not in entry or 'Answer' not in entry:
                raise BadRequest("Each entry must contain 'Question' and 'Answer' fields")
            # Clean the data
            entry['Question'] = entry['Question'].strip()
            entry['Answer'] = entry['Answer'].strip()
        
        # Load existing data
        existing_df = load_kb()
        
        # Create new DataFrame with updated entries
        new_df = pd.DataFrame(data)
        
        # If we're only showing a subset, merge with existing data
        if len(new_df) <= ENTRIES_PER_PAGE:
            # Keep existing entries beyond the preview limit
            remaining_entries = existing_df.iloc[ENTRIES_PER_PAGE:]
            # Combine new entries with remaining entries
            final_df = pd.concat([new_df, remaining_entries], ignore_index=True)
        else:
            final_df = new_df
        
        # Log changes
        changes = []
        for idx, row in new_df.iterrows():
            if idx < len(existing_df):
                old_row = existing_df.iloc[idx]
                if row['Question'] != old_row['Question'] or row['Answer'] != old_row['Answer']:
                    changes.append(f"Updated FAQ: {row['Question']}")
            else:
                changes.append(f"Added new FAQ: {row['Question']}")
        
        if changes:
            log_change("update", changes)
        
        save_kb(final_df)
        return jsonify({"message": "Knowledge Base Updated Successfully!"})
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error updating knowledge base: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(debug=True)
