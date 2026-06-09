import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

# Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── Contract generation prompt ──────────────────────────────
def build_prompt(data):
    trade       = data.get("bizType", "Service Provider")
    contractor  = data.get("contractorName", "Contractor")
    client_name = data.get("clientName", "Client")
    state       = data.get("state", "California")
    job_desc    = data.get("jobDesc", "Professional services")
    price       = data.get("price", "0")
    currency    = data.get("currency", "$")
    pay_terms   = data.get("payTerms", "full")
    style       = data.get("style", "formal")
    start_date  = data.get("startDate", "")
    duration    = data.get("duration", "")
    special     = data.get("special", "")

    style_instruction = {
        "formal":   "Use formal legal language, third-person references, and professional tone.",
        "simple":   "Use plain English that anyone can understand. Keep sentences short and clear.",
        "detailed": "Use comprehensive legal language with maximum protection clauses, detailed conditions, and thorough coverage of all scenarios."
    }.get(style, "Use formal legal language.")

    pay_instruction = {
        "full":    "Full payment due upon completion of work.",
        "deposit": "50% deposit required before work begins. Remaining 50% due upon completion.",
        "net30":   "Full payment due within 30 days of invoice date.",
        "weekly":  "Weekly payments due every Friday during the project.",
        "monthly": "Monthly payments due on the 1st of each month."
    }.get(pay_terms, "Full payment due upon completion.")

    return f"""You are a professional contract attorney. Generate a complete, legally sound service agreement.

INSTRUCTIONS:
- {style_instruction}
- State: {state} (include state-specific legal clauses where relevant)
- Trade: {trade}
- Do NOT include any explanation or preamble — output ONLY the contract document itself
- Format with clear section headers (1. SCOPE OF WORK, 2. PAYMENT TERMS, etc.)
- Include signature lines at the end

CONTRACT DETAILS:
- Contractor: {contractor}
- Client: {client_name}
- State: {state}
- Service/Trade: {trade}
- Job Description: {job_desc}
- Total Price: {currency}{price}
- Payment Terms: {pay_instruction}
- Start Date: {start_date if start_date else "To be determined"}
- Duration: {duration if duration else "Until project completion"}
- Special Terms: {special if special else "None"}

Generate a complete professional service agreement with these sections:
1. PARTIES
2. SCOPE OF WORK
3. PAYMENT TERMS
4. TIMELINE & DURATION
5. CANCELLATION POLICY
6. LIABILITY LIMITATION
7. DISPUTE RESOLUTION ({state} law)
8. SPECIAL PROVISIONS (if any)
9. SIGNATURES

Make it specific to the {trade} trade and {state} state law."""


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Signra API is running", "version": "1.0"})


@app.route("/api/generate-contract", methods=["POST"])
def generate_contract():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        prompt = build_prompt(data)

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional contract attorney specializing in service agreements for small businesses. Generate complete, legally sound contracts."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        contract_text = completion.choices[0].message.content

        return jsonify({
            "success": True,
            "contract": contract_text,
            "model": "llama-3.3-70b-versatile",
            "trade": data.get("bizType", ""),
            "state": data.get("state", "")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "signra-backend"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
