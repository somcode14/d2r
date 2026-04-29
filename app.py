# ============================================================
# D2R (Dispatch to Retail) Auto Distance Calculation System
# ============================================================
# This Flask app calculates distances between cities.
# It first checks the database (Distance Master table).
# If not found, it calculates using the Haversine formula.
# It also supports: manual override, bulk CSV upload, and audit log.
# ============================================================

from flask import Flask, render_template, request, flash, redirect, url_for
import sqlite3
import math
import csv
import os

app = Flask(__name__)

# Secret key is needed to use flash messages (temporary notifications)
app.secret_key = "d2r_secret_key_2024"

# Folder where uploaded CSV files will be saved
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ============================================================
# LOCATION MASTER — city name → (latitude, longitude)
# In a real system, this would also come from a database
# ============================================================
LOCATIONS = {
    "Patna":   (25.5941, 85.1376),
    "Delhi":   (28.7041, 77.1025),
    "Mumbai":  (19.0760, 72.8777),
    "Kolkata": (22.5726, 88.3639),
    "Chennai": (13.0827, 80.2707),
    "Lucknow": (26.8467, 80.9462),
}


# ============================================================
# DATABASE SETUP
# Creates tables if they don't already exist
# ============================================================
def init_db():
    conn = sqlite3.connect("distance.db")
    c = conn.cursor()

    # Distance Master table: stores known source-destination distances
    c.execute("""
        CREATE TABLE IF NOT EXISTS distance_master (
            source      TEXT,
            destination TEXT,
            distance    REAL,
            UNIQUE(source, destination)
        )
    """)

    # Audit Log table: records every manual override with reason
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source       TEXT,
            destination  TEXT,
            old_distance REAL,
            new_distance REAL,
            reason       TEXT,
            updated_at   TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# HELPER: Get a database connection
# Using a helper function keeps the code clean
# ============================================================
def get_db():
    return sqlite3.connect("distance.db")


# ============================================================
# HELPER: Haversine Formula
# Calculates straight-line distance between two lat/lon points
# Returns distance in kilometers
# ============================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth's radius in km

    # Convert degrees to radians
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    # Haversine formula
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)

    distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return distance


# ============================================================
# HELPER: Look up distance from DB, or calculate if not found
# This is the core BRD logic: DB first → Calculate if missing
# ============================================================
def get_distance(source, destination):
    conn = get_db()
    c = conn.cursor()

    # Step 1: Check if distance already exists in master DB
    c.execute(
        "SELECT distance FROM distance_master WHERE source=? AND destination=?",
        (source, destination)
    )
    row = c.fetchone()

    if row:
        # Found in DB — return it directly
        conn.close()
        return round(row[0], 2), "Fetched from Distance Master DB"

    # Step 2: Not in DB — calculate using Haversine
    if source not in LOCATIONS or destination not in LOCATIONS:
        conn.close()
        return None, "Location not found in system"

    lat1, lon1 = LOCATIONS[source]
    lat2, lon2 = LOCATIONS[destination]
    dist = haversine(lat1, lon1, lat2, lon2)

    # Step 3: Save the new result to DB for future use
    c.execute(
        "INSERT OR IGNORE INTO distance_master VALUES (?, ?, ?)",
        (source, destination, dist)
    )
    conn.commit()
    conn.close()

    return round(dist, 2), "Calculated using Haversine & Saved to DB"


# ============================================================
# ROUTE: Home Page
# ============================================================
@app.route("/")
def home():
    return render_template("index.html", locations=LOCATIONS.keys())


# ============================================================
# ROUTE: Calculate Distance
# Accepts source and destination from the form
# ============================================================
@app.route("/calculate", methods=["POST"])
def calculate():
    source = request.form.get("source", "").strip()
    destination = request.form.get("destination", "").strip()

    # Basic validation: source and destination must not be same
    if source == destination:
        flash("Source and destination cannot be the same!", "error")
        return redirect(url_for("home"))

    dist, msg = get_distance(source, destination)

    if dist is None:
        flash(f"Error: {msg}", "error")
        return redirect(url_for("home"))

    return render_template(
        "index.html",
        locations=LOCATIONS.keys(),
        distance=dist,
        msg=msg,
        source=source,
        destination=destination
    )


# ============================================================
# ROUTE: Manual Override
# Allows updating the distance with a reason (logged to audit)
# ============================================================
@app.route("/override", methods=["POST"])
def override():
    source = request.form.get("source", "").strip()
    destination = request.form.get("destination", "").strip()
    reason = request.form.get("reason", "").strip()

    # Validate inputs
    try:
        new_distance = float(request.form.get("new_distance", ""))
        if new_distance <= 0:
            raise ValueError
    except ValueError:
        flash("Please enter a valid positive distance value.", "error")
        return redirect(url_for("home"))

    if not source or not destination:
        flash("Source and destination are required for override.", "error")
        return redirect(url_for("home"))

    if not reason:
        flash("Please provide a reason for the override.", "error")
        return redirect(url_for("home"))

    conn = get_db()
    c = conn.cursor()

    # Get current (old) distance before updating
    c.execute(
        "SELECT distance FROM distance_master WHERE source=? AND destination=?",
        (source, destination)
    )
    old_row = c.fetchone()
    old_distance = round(old_row[0], 2) if old_row else None

    # Update or insert the new distance
    if old_row:
        c.execute(
            "UPDATE distance_master SET distance=? WHERE source=? AND destination=?",
            (new_distance, source, destination)
        )
    else:
        c.execute(
            "INSERT INTO distance_master VALUES (?, ?, ?)",
            (source, destination, new_distance)
        )

    # Log the override in audit table
    c.execute(
        "INSERT INTO audit_log (source, destination, old_distance, new_distance, reason) VALUES (?, ?, ?, ?, ?)",
        (source, destination, old_distance, new_distance, reason)
    )

    conn.commit()
    conn.close()

    flash(f"Override applied for {source} → {destination}. New distance: {new_distance} km", "success")
    return render_template(
        "index.html",
        locations=LOCATIONS.keys(),
        distance=new_distance,
        msg="Manual Override Applied",
        source=source,
        destination=destination
    )


# ============================================================
# ROUTE: Bulk CSV Upload
# CSV must have columns: source, destination
# ============================================================
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")

    # Check if a file was actually uploaded
    if not file or file.filename == "":
        flash("Please select a CSV file to upload.", "error")
        return redirect(url_for("home"))

    # Only allow .csv files
    if not file.filename.endswith(".csv"):
        flash("Only CSV files are allowed.", "error")
        return redirect(url_for("home"))

    # Save file to uploads folder
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(filepath)

    results = []
    errors = []

    try:
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)

            # Check that required columns exist
            if "source" not in reader.fieldnames or "destination" not in reader.fieldnames:
                flash("CSV must have 'source' and 'destination' columns.", "error")
                return redirect(url_for("home"))

            for i, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                source = row.get("source", "").strip()
                destination = row.get("destination", "").strip()

                if not source or not destination:
                    errors.append(f"Row {i}: Empty source or destination — skipped")
                    continue

                if source == destination:
                    errors.append(f"Row {i}: Source and destination are same — skipped")
                    continue

                dist, status = get_distance(source, destination)

                if dist is None:
                    errors.append(f"Row {i}: {source} or {destination} not in system — skipped")
                else:
                    results.append({
                        "source": source,
                        "destination": destination,
                        "distance": dist,
                        "status": status
                    })

    except Exception as e:
        flash(f"Error reading CSV file: {str(e)}", "error")
        return redirect(url_for("home"))

    if errors:
        for err in errors:
            flash(err, "warning")

    return render_template(
        "index.html",
        locations=LOCATIONS.keys(),
        bulk=results
    )


# ============================================================
# ROUTE: Audit Log
# Shows all manual overrides with old/new values and reason
# ============================================================
@app.route("/history")
def history():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT source, destination, old_distance, new_distance, reason, updated_at FROM audit_log ORDER BY id DESC")
    logs = c.fetchall()
    conn.close()
    return render_template("index.html", locations=LOCATIONS.keys(), logs=logs)


# ============================================================
# APP ENTRY POINT
# ============================================================
if __name__ == "__main__":
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    init_db()
    app.run(debug=True)
