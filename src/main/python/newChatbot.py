import openai
import os
from dotenv import load_dotenv
from datetime import datetime
import dateutil.parser
from database import get_connection

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Fetch available doctors and their slots from DB
def get_available_doctors_with_slots():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.name, a.available_date, a.available_time
        FROM doctors d
        JOIN availability a ON d.id = a.doctor_id
        WHERE a.is_booked = 0
        ORDER BY d.name, a.available_date, a.available_time
    """)
    rows = cursor.fetchall()
    conn.close()

    doctor_slots = {}
    for name, date, time in rows:
        formatted_name = f"{name.strip().title()}"
        slot = {"date": str(date), "time": str(time)}
        doctor_slots.setdefault(formatted_name, []).append(slot)
    return doctor_slots

# Create readable doctor availability info for prompt
def format_doctor_slots_for_prompt(available_doctors):
    lines = []
    for doctor, slots in available_doctors.items():
        slot_strs = [f"{slot['date']} at {slot['time']}" for slot in slots]
        lines.append(f"Dr. {doctor}: {', '.join(slot_strs)}")
    return "\n".join(lines)

# Extract information from assistant response
def extract_information(text):
    fields = {"patient": None, "doctor": None, "date": None, "time": None}
    for line in text.split("\n"):
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if not val or val.lower() == "not provided":
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
                pass
        elif key.startswith("time"):
            try:
                parsed_time = dateutil.parser.parse(val, fuzzy=True)
                fields["time"] = parsed_time.strftime("%H:%M:%S")
            except:
                pass
    return fields

def process_response(assistant_reply, available_doctors):
    extracted = extract_information(assistant_reply)

    # If not all fields are present, return None
    if not all(extracted.values()):
        return None

    doctor = extracted["doctor"]
    date = extracted["date"]
    time = extracted["time"]

    # Check if the doctor is in the list
    if doctor not in available_doctors:
        print(f"❌ Invalid doctor: {doctor}")
        return None

    # Check if that doctor has this exact date + time slot
    valid_slots = available_doctors[doctor]
    if not any(slot["date"] == date and slot["time"] == time for slot in valid_slots):
        print(f"❌ Invalid time slot for {doctor} on {date} at {time}")
        return None

    # ✅ Valid info
    print(f"✅ All necessary info provided and valid: {extracted}")
    return extracted



# Book appointment in DB
def book_appointment(patient_name, doctor_name, date, time):
    print("📅 Booking appointment...")
    print("Doctor name :"+doctor_name)
    print("Doctor name :"+date)
    print("Doctor name :"+time)
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

system_prompt_template = (
    "You are a helpful healthcare assistant. Today's date is {today}.\n"
    "You help users book appointments with doctors based on available slots.\n"
    "📋 Here are the current available appointment slots:\n{availability}\n\n"
    "⚠️ Only accept doctor names from this list: {doctor_list}.\n"
    "If a user enters a name not in the list, respond with an error and ask them to choose a valid doctor.\n\n"
    "🗓️ You must also verify that the doctor is available **exactly** on the requested date and time.\n"
    "If the requested slot does not appear in the availability list above, respond with:\n"
    "'❌ Sorry, Dr. <name> is not available on <date> at <time>. Please choose another available slot.'\n\n"
    "If the user provides all required fields (Patient's name, Doctor's name, Date, and Time) **and the slot is available**, respond with:\n"
    "Patient: <patient name>\nDoctor: Dr. <doctor name>\nDate: <appointment date>\nTime: <appointment time>\n"
    "If any information is missing, only ask for the missing fields, and do not repeat already provided ones."
)



# Main chatbot loop
def main():
    print("Welcome to the Healthcare Chatbot!")

    available_doctors = get_available_doctors_with_slots()
    availability_text = format_doctor_slots_for_prompt(available_doctors)
    # Set up the system prompt with current date and available slots
    doctor_list_str = ", ".join(f"{name}" for name in sorted(available_doctors.keys()))

    system_prompt = system_prompt_template.format(
        today=datetime.now().strftime('%Y-%m-%d'),
        availability=availability_text,
        doctor_list=doctor_list_str
    )

    messages = [{"role": "system", "content": system_prompt}]

    while True:
        # User inputs their query
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            break

        # Append the user message to the conversation history
        messages.append({"role": "user", "content": user_input})

        # Get the assistant's response from GPT-3.5-turbo
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.2
        )

        assistant_reply = response.choices[0].message.content
        print(f"Assistant:\n{assistant_reply}")
        messages.append({"role": "assistant", "content": assistant_reply})

        # Process the response to check if booking can proceed
        extracted_info = process_response(assistant_reply, available_doctors)

        if extracted_info:
            # If the response is complete, book the appointment
            patient_name = extracted_info["patient"]
            doctor_name = extracted_info["doctor"]
            date = extracted_info["date"]
            time = extracted_info["time"]

            book_appointment(patient_name, doctor_name, date, time)
            print(f"✅ Appointment booked for {patient_name} with {doctor_name} on {date} at {time}.")
    messages = [{"role": "system", "content": system_prompt}]




if __name__ == "__main__":
    main()
