from ach.builder import File
import json

def nacha_to_json(nacha_path, json_path):
    # Parse NACHA file
    with open(nacha_path, "r") as f:
        nacha_text = f.read()

    ach_file = File.from_string(nacha_text)

    # Convert to Python dict
    data = ach_file.to_dict()

    # Write JSON
    with open(json_path, "w") as out:
        json.dump(data, out, indent=2)

    return data

# Example usage
data = nacha_to_json("sample.ach", "sample.json")
print("Converted NACHA → JSON")

from ach.builder import File
import json

def json_to_nacha(json_path, nacha_path):
    # Load JSON
    with open(json_path, "r") as f:
        data = json.load(f)

    # Build ACH file object
    ach_file = File.from_dict(data)

    # Convert back to NACHA text
    nacha_text = ach_file.to_string()

    # Write NACHA file
    with open(nacha_path, "w") as out:
        out.write(nacha_text)

    return nacha_text

# Example usage
nacha_text = json_to_nacha("sample.json", "roundtrip.ach")
print("Converted JSON → NACHA")

# Convert to JSON
data = nacha_to_json("sample.ach", "sample.json")

# Convert back to NACHA
roundtrip = json_to_nacha("sample.json", "roundtrip.ach")

print(roundtrip[:200])  # preview first 200 chars
