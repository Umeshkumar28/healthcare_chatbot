import openai, os
from dotenv import load_dotenv
from datetime import datetime
from database import get_connection
import dateutil.parser

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def get_doctors():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM doctors")
    doctors = [row[0] for row in cursor.fetchall()]
    conn.close()
    return doctors

def normalize_doctor_name(name):
    name = name.lower().replace("dr.", "").replace("doctor", "").strip()
    return name

def find_matching_doctor(user_input_name, doctors):
    normalized_input = normalize_doctor_name(user_input_name)
    for doctor in doctors:
        if normalize_doctor_name(doctor) == normalized_input:
            return doctor
    return None

def get_availability(doctor_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT available_date, available_time 
        FROM availability
        JOIN doctors ON availability.doctor_id = doctors.id
        WHERE doctors.name = %s AND is_booked = 0
        ORDER BY available_date, available_time
    """, (doctor_name,))
    slots = cursor.fetchall()
    conn.close()
    return [{"date": str(row[0]), "time": str(row[1])} for row in slots]

def book_appointment(patient_name, doctor_name, date, time):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO appointments (patient_name, doctor_name, appointment_date, appointment_time)
        VALUES (%s, %s, %s, %s)
    """, (patient_name, doctor_name, date, time))
    cursor.execute("""
        UPDATE availability
        JOIN doctors ON availability.doctor_id = doctors.id
        SET is_booked = 1
        WHERE doctors.name = %s AND available_date = %s AND available_time = %s
    """, (doctor_name, date, time))
    conn.commit()
    conn.close()

def cancel_appointment(patient_name, doctor_name, date, time):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM appointments
        WHERE patient_name = %s AND doctor_name = %s AND appointment_date = %s AND appointment_time = %s
    """, (patient_name, doctor_name, date, time))
    cursor.execute("""
        UPDATE availability
        JOIN doctors ON availability.doctor_id = doctors.id
        SET is_booked = 0
        WHERE doctors.name = %s AND available_date = %s AND available_time = %s
    """, (doctor_name, date, time))
    conn.commit()
    conn.close()

def extract_information(text):
    try:
        fields = {"patient": None, "doctor": None, "date": None, "time": None}
        for line in text.split("\n"):
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if val.lower() == "not provided" or val == "":
                continue
            if key.startswith("patient"):
                fields["patient"] = val
            elif key.startswith("doctor"):
                fields["doctor"] = val
            elif key.startswith("date"):
                try:
                    parsed_date = dateutil.parser.parse(val, fuzzy=True)
                    fields["date"] = parsed_date.strftime("%Y-%m-%d")
                except:
                    fields["date"] = None
            elif key.startswith("time"):
                try:
                    parsed_time = dateutil.parser.parse(val, fuzzy=True)
                    fields["time"] = parsed_time.strftime("%H:%M:%S")
                except:
                    fields["time"] = None
        return fields
    except Exception as e:
        print("Error extracting info:", e)
        return {"patient": None, "doctor": None, "date": None, "time": None}

def main():
    print("Welcome to the Healthcare Chatbot!")
    info = {"patient": None, "doctor": None, "date": None, "time": None}
    doctors = get_doctors()

    messages = [
        {"role": "system", "content": (
                "You are a helpful healthcare assistant. Today is " + datetime.now().strftime("%Y-%m-%d") + ".\n"
                                                                                                            "You help users book and cancel appointments with doctors.\n"
                                                                                                            "You must extract or ask for: patient name, doctor name, date (YYYY-MM-DD), and time (HH:MM:SS).\n"
                                                                                                            "If a user wants to cancel, say 'Understood, I will cancel the appointment.'\n"
                                                                                                            "If a user wants to book, say 'I'm ready to book the appointment.'\n"
                                                                                                            "Always reply in this format:\nPatient: <...>\nDoctor: <...>\nDate: <...>\nTime: <...>"
        )}
    ]

    action = None

    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            break

        messages.append({"role": "user", "content": user_input})
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.2
        )
        assistant_reply = response["choices"][0]["message"]["content"]
        print(f"Assistant:\n{assistant_reply}")
        messages.append({"role": "assistant", "content": assistant_reply})

        if "cancel" in user_input.lower():
            action = "cancel"
        elif "book" in user_input.lower():
            action = "book"

        extracted = extract_information(assistant_reply)
        for key in info:
            if not info[key] and extracted[key]:
                info[key] = extracted[key]

        if all(info.values()) and action:
            matched_doctor = find_matching_doctor(info["doctor"], doctors)
            if not matched_doctor:
                print(f"⚠️ Doctor '{info['doctor']}' not found. Please try again with a valid name.")
                info["doctor"] = None
                continue

            info["doctor"] = matched_doctor

            if action == "book":
                available_slots = get_availability(info["doctor"])
                print(f"Available slots: {available_slots}")
                slot_match = next((slot for slot in available_slots if slot["date"] == info["date"] and slot["time"] == info["time"]), None)

                if not slot_match:
                    print(f"❌ No available slot for {info['doctor']} on {info['date']} at {info['time']}.")
                    info["date"] = info["time"] = None
                    continue

                book_appointment(info["patient"], info["doctor"], info["date"], info["time"])
                print(f"✅ Appointment booked for {info['patient']} with {info['doctor']} on {info['date']} at {info['time']}.")

            elif action == "cancel":
                cancel_appointment(info["patient"], info["doctor"], info["date"], info["time"])
                print(f"❌ Appointment canceled for {info['patient']} with {info['doctor']} on {info['date']} at {info['time']}.")

            info = {"patient": None, "doctor": None, "date": None, "time": None}
            messages = messages[:1]
            action = None

if __name__ == "__main__":
    main()
