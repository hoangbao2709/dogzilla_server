import whisper

model = whisper.load_model("tiny")

def speech_to_text(file_path):
    print("dang nhan dien giong noi...")
    result = model.transcribe(file_path)
    return result["text"]